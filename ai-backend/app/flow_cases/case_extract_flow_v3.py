from crewai.flow.flow import Flow, listen, start
from crewai import Crew, Process
from pydantic import BaseModel, Field, create_model, field_validator
from typing import Dict, Any, List, Optional
from .crews.case_crew.case_crew_v3 import CaseCrew
from .tools.io_tools import read_document, fetch_schema_v3
from app.lib.schema_runtime import prune_ui_schema_for_llm, build_property_models, validate_case_graph, render_spec_text, build_relationship_property_models, get_relationship_label_for_edge, get_all_assigned_relationship_labels
from app.models.case_graph import CaseGraph
from app.lib.logging_config import setup_logger
from app.lib.neo4j_client import neo4j_client
import json
import yaml
import os
from datetime import datetime


logger = setup_logger("case-extract-flow-v3")

def _get_label_instructions_and_examples(label: str, node_instructions_by_label: Dict[str, Dict[str, Any]] | None) -> tuple[str, str]:
    """
    Extract instructions and examples for a given label from node_instructions_by_label.
    
    Args:
        label: The node label to look up (e.g., "Case", "Ruling", "Argument")
        node_instructions_by_label: Dictionary mapping label names to their instruction entries from flow_map_v3.yaml
    
    Returns:
        Tuple of (instructions, examples_json) where:
        - instructions: The instruction string for the label (empty if not found)
        - examples_json: JSON-serialized examples list (empty list if not found)
    """
    # O(1) dictionary lookup
    fm_entry = (node_instructions_by_label or {}).get(label)
    
    instructions = (fm_entry or {}).get("instructions") or ""
    examples_json = json.dumps((fm_entry or {}).get("examples") or [], ensure_ascii=False)
    
    return instructions, examples_json


# ==============================================================================
# INDEX-BASED CATALOG SELECTION HELPERS
# ==============================================================================
# These helpers prevent UUID hallucination by having the AI return simple indices
# instead of UUIDs. We then validate and map indices back to real IDs in code.

def build_indexed_catalog(
    catalog: List[Dict[str, Any]], 
    id_field: str,
    display_fields: Optional[List[str]] = None
) -> tuple[List[Dict[str, Any]], Dict[int, str]]:
    """
    Build an indexed version of a catalog for AI consumption.
    
    Instead of exposing UUIDs to the AI (which can be hallucinated), we add a simple
    integer index `_idx` to each entry. The AI returns indices, which we then map
    back to real IDs.
    
    Args:
        catalog: List of catalog entries (each a dict with properties)
        id_field: The name of the ID field (e.g., "doctrine_id", "forum_id")
        display_fields: Optional list of fields to include in indexed catalog.
                       If None, includes all fields except embeddings.
    
    Returns:
        Tuple of:
        - indexed_catalog: List of catalog entries with `_idx` field added
        - idx_to_id_map: Dict mapping index -> original ID value
    
    Example:
        indexed, idx_map = build_indexed_catalog(doctrine_catalog, "doctrine_id", ["name", "description"])
        # indexed: [{"_idx": 0, "name": "Rule of Reason", ...}, {"_idx": 1, ...}]
        # idx_map: {0: "abc-123-...", 1: "def-456-..."}
    """
    indexed_catalog = []
    idx_to_id_map: Dict[int, str] = {}
    
    for idx, entry in enumerate(catalog):
        if not isinstance(entry, dict):
            continue
        
        # Get the real ID
        real_id = entry.get(id_field)
        if real_id is None:
            continue
        
        # Build indexed entry
        indexed_entry: Dict[str, Any] = {"_idx": idx}
        
        # Add requested fields (or all non-embedding fields)
        for key, value in entry.items():
            # Skip embedding fields (they're large and not needed for selection)
            if isinstance(key, str) and key.endswith("_embedding"):
                continue
            # Skip the original ID field - we use _idx instead
            if key == id_field:
                continue
            # Include field if no display_fields specified, or if in display_fields
            if display_fields is None or key in display_fields:
                indexed_entry[key] = value
        
        indexed_catalog.append(indexed_entry)
        idx_to_id_map[idx] = str(real_id)
    
    return indexed_catalog, idx_to_id_map


def resolve_indices_to_ids(
    returned_values: List[Any],
    idx_to_id_map: Dict[int, str],
    label: str,
    phase: str
) -> List[str]:
    """
    Validate and convert AI-returned indices to real IDs.
    
    Handles three cases:
    1. Integer index -> map to real ID
    2. String that looks like an integer -> convert and map
    3. Invalid value -> log warning and skip
    
    Args:
        returned_values: List of values returned by AI (should be indices)
        idx_to_id_map: Mapping from index to real ID
        label: Node label for logging (e.g., "Doctrine")
        phase: Phase name for logging (e.g., "Phase 7")
    
    Returns:
        List of valid IDs (only those that successfully resolved)
    """
    valid_ids = []
    
    for val in returned_values:
        idx: Optional[int] = None
        
        # Try to get an integer index
        if isinstance(val, int):
            idx = val
        elif isinstance(val, str):
            # Check if it's a string representation of an integer
            try:
                idx = int(val)
            except ValueError:
                # Not an integer - might be a hallucinated UUID or name
                logger.warning(f"{phase}: {label} returned non-index value '{val}' - rejecting hallucinated ID")
                continue
        else:
            logger.warning(f"{phase}: {label} returned unexpected type {type(val).__name__}: '{val}'")
            continue
        
        # Validate index is in our map
        if idx in idx_to_id_map:
            valid_ids.append(idx_to_id_map[idx])
        else:
            logger.warning(f"{phase}: {label} index {idx} out of range (max={len(idx_to_id_map)-1}) - rejecting")
    
    return valid_ids


def validate_catalog_ids(
    returned_ids: List[str],
    catalog: List[Dict[str, Any]],
    id_field: str,
    label: str,
    phase: str
) -> List[str]:
    """
    Validate that returned IDs actually exist in the catalog.
    
    This is a fallback validator for cases where we still use UUID-based selection.
    It filters out any hallucinated IDs.
    
    Args:
        returned_ids: List of IDs returned by AI
        catalog: The catalog to validate against
        id_field: The ID field name (e.g., "doctrine_id")
        label: Node label for logging
        phase: Phase name for logging
    
    Returns:
        List of valid IDs (only those that exist in catalog)
    """
    # Build set of valid IDs from catalog
    valid_id_set = set()
    for entry in catalog:
        if isinstance(entry, dict):
            entry_id = entry.get(id_field)
            if entry_id is not None:
                valid_id_set.add(str(entry_id))
            # Also include temp_id if present (for newly created nodes)
            temp_id = entry.get("temp_id")
            if temp_id is not None:
                valid_id_set.add(str(temp_id))
    
    valid_ids = []
    for returned_id in returned_ids:
        if str(returned_id) in valid_id_set:
            valid_ids.append(str(returned_id))
        else:
            logger.warning(f"{phase}: {label} ID '{returned_id}' not found in catalog - rejecting hallucinated ID")
    
    return valid_ids


class CaseExtractState(BaseModel):
    file_path: str = ""
    filename: str = ""
    case_id: str = ""
    # Progress callback for job tracking
    progress_callback: Any = None  # Callable[[str, str, int], None] but Any for Pydantic
    # Runtime additions shared across flow steps
    schema_spec: Dict[str, Any] | None = None
    schema_spec_text: str = ""
    models_by_label: Dict[str, Any] | None = None
    rels_by_label: Dict[str, Dict[str, str]] | None = None
    props_meta_by_label: Dict[str, Dict[str, Dict[str, Any]]] | None = None
    label_flags_by_label: Dict[str, Dict[str, bool]] | None = None
    rel_cardinality_by_label: Dict[str, Dict[str, str]] | None = None
    # Relationship property validators keyed by (source_label, rel_label)
    rel_prop_models_by_key: Dict[tuple[str, str], Any] | None = None
    rel_prop_meta_by_key: Dict[tuple[str, str], Dict[str, Dict[str, Any]]] | None = None
    # Full schema payload (with relationship property schemas) if available
    schema_full: Any | None = None
    existing_catalog_by_label: Dict[str, List[Dict[str, Any]]] | None = None
    # Node-specific instructions and examples from flow_map_v3.yaml
    node_instructions: List[Dict[str, Any]] | None = None  # For phase filtering and ordering
    node_instructions_by_label: Dict[str, Dict[str, Any]] | None = None  # For O(1) label lookups
    # Flow configuration (batch sizes, model overrides, etc.)
    flow_config: Dict[str, Any] | None = None
    # Working context
    document_text: str = ""
    nodes_accumulated: List[Dict[str, Any]] | None = None
    edges_accumulated: List[Dict[str, Any]] | None = None


# Pydantic models for batch extraction responses

class ArgumentWithStatus(BaseModel):
    """Argument with its evaluation status in the ruling"""
    properties: Dict[str, Any]  # Argument node properties
    status: Optional[str] = None  # "Supported" or "Rejected" - status in EVALUATED_IN relationship

class RulingAndArgumentsResult(BaseModel):
    """Result for a single issue's ruling and arguments extraction"""
    issue_temp_id: str
    ruling: Optional[Dict[str, Any]] = None  # Ruling properties
    in_favor: Optional[str] = None  # "plaintiff", "defendant", etc - in_favor property for SETS relationship
    arguments: List[ArgumentWithStatus] = []  # List of Arguments with their evaluation status


class RulingAndArgumentsBatchResponse(BaseModel):
    """Response for Phase 5: Ruling and Arguments extraction from multiple issues"""
    results: List[RulingAndArgumentsResult]



class SelectionResponse(BaseModel):
    """Response for selection tasks (Forum, Domain, etc.) - now uses integer indices"""
    selected: Dict[str, List[Any]]  # Can be integers (indices) or strings


class DispositionTextEntry(BaseModel):
    """Single argument's disposition_text extraction result"""
    argument_temp_id: str
    disposition_text: str  # Required - Pydantic will error if missing or empty
    
    @field_validator('disposition_text')
    @classmethod
    def disposition_text_not_empty(cls, v: str) -> str:
        """Ensure disposition_text is not empty or whitespace-only."""
        if not v or not v.strip():
            raise ValueError('disposition_text cannot be empty')
        return v.strip()


class DispositionTextBatchResponse(BaseModel):
    """Response for Phase 5B: disposition_text extraction for arguments"""
    results: List[DispositionTextEntry]

class CaseExtractFlow(Flow[CaseExtractState]):
    @start()
    def phase0_kickoff(self) -> Dict[str, Any]:
        # Log initial kickoff context
        try:
            logger.info(f"Kickoff: file_path='{self.state.file_path}', filename='{self.state.filename}', case_id='{self.state.case_id}'")
        except Exception:
            pass
        return {
            "file_path": self.state.file_path,
            "filename": self.state.filename,
            "case_id": self.state.case_id,
            "status": "initialized"
        }

    def build_catalog_for_labels(self, labels: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Build formatted catalog from raw data for specified labels.
        
        This method takes existing nodes from Neo4j (fetched in phase 0) and formats them
        for AI agent consumption by:
        1. Filtering properties to only those defined in the schema
        2. Converting values to appropriate JSON-serializable types
        3. Ensuring ID fields (properties ending in '_id') are included as a safety net
        
        Args:
            labels: List of node label names to build catalogs for (e.g., ["Forum", "Law"])
            
        Returns:
            Dictionary mapping label names to lists of formatted node properties.
            Example: {"Forum": [{"name": "Supreme Court", "forum_id": "123"}, ...]}
            
        Note:
            The '_id' field handling in step 3 is defensive - these fields are typically
            already in the schema definition, so they'd be included in step 1 anyway.
        """
        # Helper to ensure values are JSON-serializable (keep primitives, stringify everything else)
        def format_value(v: Any) -> Any:
            return v if isinstance(v, (int, float, bool)) else str(v)
        
        catalogs = {}
        for lbl in labels:
            # Get raw existing nodes for this label from state (fetched via Neo4j in phase 0)
            rows = (self.state.existing_catalog_by_label or {}).get(lbl) or []
            
            # Get schema metadata to know which properties are valid for this label
            props_meta = (self.state.props_meta_by_label or {}).get(lbl) or {}
            allowed_keys = [k for k in props_meta.keys() if isinstance(k, str)]
            
            # Build formatted entries by combining:
            # 1. Schema-defined properties (from allowed_keys)
            # 2. Any '_id' fields as a safety net (typically these are already in schema, but this ensures they're never missed)
            entries = [
                {k: format_value(r[k]) for k in allowed_keys if r.get(k) is not None} |
                {k: format_value(v) for k, v in r.items() if isinstance(k, str) and k.endswith("_id") and v is not None}
                for r in rows if isinstance(r, dict)
            ]
            # Filter out any empty entries
            catalogs[lbl] = [e for e in entries if e]
        
        return catalogs

    def find_first_temp_id(self, label: str) -> Optional[str]:
        """Find the first node with the given label and return its temp_id."""
        for n in (self.state.nodes_accumulated or []):
            if isinstance(n, dict) and n.get("label") == label and isinstance(n.get("temp_id"), str):
                return n.get("temp_id")
        return None

    def find_all_temp_ids(self, label: str) -> List[str]:
        """Find all nodes with the given label and return their temp_ids."""
        return [n.get("temp_id") for n in (self.state.nodes_accumulated or []) 
                if isinstance(n, dict) and n.get("label") == label and isinstance(n.get("temp_id"), str)]

    def get_existing_edges_set(self) -> set:
        """Build a set of existing edge tuples for deduplication."""
        return {(e.get("from"), e.get("to"), e.get("label")) 
                for e in (self.state.edges_accumulated or []) if isinstance(e, dict)}

    def parse_crew_result(self, result: Any) -> Dict[str, Any]:
        """Parse CrewAI result into a dictionary, handling both dict and JSON string formats."""
        try:
            return json.loads(str(result)) if not isinstance(result, dict) else result
        except Exception:
            return {}

    def validate_with_model(self, props: Dict[str, Any], model: Any) -> Dict[str, Any]:
        """
        Validate properties against a Pydantic model, with fallback to simple dict filtering.
        
        Args:
            props: Raw properties dictionary
            model: Pydantic model class (can be None)
            
        Returns:
            Validated/cleaned properties dictionary
        """
        try:
            if model is not None:
                inst = model(**props)
                return inst.model_dump(exclude_none=False)
            else:
                return {k: v for k, v in props.items() if isinstance(k, str)}
        except Exception:
            return {k: v for k, v in props.items() if isinstance(k, str)}

    def parse_selection_response(self, result: Any) -> Dict[str, List[str]]:
        """
        Parse SelectionResponse from crew result into a dict of label -> list of IDs.
        
        Args:
            result: CrewAI result containing selected items
            
        Returns:
            Dictionary mapping label names to lists of selected IDs
        """
        selected: Dict[str, List[str]] = {}
        try:
            # First check if result has pydantic attribute (CrewOutput with Pydantic model)
            if hasattr(result, 'pydantic'):
                pydantic_result = result.pydantic
                # Check if pydantic result has model_dump method
                if hasattr(pydantic_result, 'model_dump'):
                    data = pydantic_result.model_dump()
                elif hasattr(pydantic_result, 'dict'):
                    data = pydantic_result.dict()
                else:
                    # Try to access as dict directly
                    data = dict(pydantic_result) if hasattr(pydantic_result, '__dict__') else {}
            # Fall back to JSON parsing for string/dict results
            elif isinstance(result, str):
                data = json.loads(result)
            elif isinstance(result, dict):
                data = result
            else:
                # Try JSON parsing as last resort
                data = json.loads(str(result))
            
            # Extract selected field
            sel = data.get("selected") if isinstance(data, dict) else None
            if isinstance(sel, dict):
                for k, v in sel.items():
                    if isinstance(k, str) and isinstance(v, list):
                        selected[k] = [str(x) for x in v]
        except Exception as e:
            logger.warning(f"Failed to parse selection response: {e}")
        return selected

    def validate_relationship_properties(self, source_label: str, rel_label: str, props: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate relationship properties against schema models.
        
        Args:
            source_label: Source node label
            rel_label: Relationship label
            props: Raw relationship properties
            
        Returns:
            Validated and cleaned relationship properties
        """
        # Get the relationship property model for this source/rel combination
        model = (self.state.rel_prop_models_by_key or {}).get((source_label, rel_label))
        
        if model is None:
            # No property schema defined for this relationship - return as-is
            return {k: v for k, v in props.items() if isinstance(k, str) and v is not None}
        
        try:
            # Validate using Pydantic model
            inst = model(**props)
            return inst.model_dump(exclude_none=False)
        except Exception as e:
            logger.warning(f"Failed to validate relationship properties for {source_label}-[{rel_label}]: {e}")
            # Fallback: return simple filtered dict
            return {k: v for k, v in props.items() if isinstance(k, str) and v is not None}

    @listen(phase0_kickoff)
    def phase0_prepare_schema(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("prepare_schema: starting")
        print("[prepare_schema] starting")
        # Build pruned spec and models up front so we can pass spec to the crew
        try:
            schema_res = fetch_schema_v3()
            schema_payload = schema_res.get('schema') if isinstance(schema_res, dict) else None
        except Exception:
            schema_payload = None

        spec = prune_ui_schema_for_llm(schema_payload) if schema_payload is not None else {"labels": []}
        models_by_label, rels_by_label, props_meta_by_label, label_flags_by_label, rel_cardinality_by_label = build_property_models(spec)
        spec_text = render_spec_text(spec)
        # Persist on state for later listeners
        self.state.schema_spec = spec
        self.state.schema_spec_text = spec_text
        self.state.models_by_label = models_by_label
        self.state.rels_by_label = rels_by_label
        # ui
        self.state.props_meta_by_label = props_meta_by_label
        self.state.label_flags_by_label = label_flags_by_label
        self.state.rel_cardinality_by_label = rel_cardinality_by_label
        # Relationship property models from full schema when available
        try:
            rel_models, rel_meta = build_relationship_property_models(schema_payload)
            self.state.rel_prop_models_by_key = rel_models  # type: ignore[assignment]
            self.state.rel_prop_meta_by_key = rel_meta  # type: ignore[assignment]
        except Exception:
            self.state.rel_prop_models_by_key = {}
            self.state.rel_prop_meta_by_key = {}
        self.state.schema_full = schema_payload

        # Load node instructions (flow_map_v3.yaml) for label-specific prompts and index by label
        try:
            flow_map_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "flow_map_v3.yaml"))
            with open(flow_map_path, "r") as f:
                flow_map_data = yaml.safe_load(f)
            # Store list for phase filtering/ordering
            self.state.node_instructions = flow_map_data
            # Build dictionary index for O(1) lookups
            self.state.node_instructions_by_label = {
                e.get("label"): e 
                for e in flow_map_data 
                if isinstance(e, dict) and isinstance(e.get("label"), str)
            }
            logger.info(f"Loaded node instructions for {len(self.state.node_instructions_by_label)} labels")
        except Exception as e:
            logger.warning(f"Failed to load flow_map_v3.yaml: {e}")
            self.state.node_instructions = []
            self.state.node_instructions_by_label = {}

        # Load flow configuration (flow_config_v3.json) for batch sizes and model overrides
        try:
            # Navigate up to ai-backend directory from flow_cases
            config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "flow_config_v3.json"))
            with open(config_path, "r") as f:
                self.state.flow_config = json.load(f)
            logger.info(f"Loaded flow configuration from {config_path}")
        except Exception as e:
            logger.warning(f"Failed to load flow_config_v3.json: {e}; using defaults")
            self.state.flow_config = {"batch_sizes": {}}

        # Read document once and store text
        try:
            logger.info(f"Reading document: file_path='{self.state.file_path}', filename='{self.state.filename}'")
            
            # Add file existence check with detailed logging
            if not os.path.exists(self.state.file_path):
                error_msg = f"File not found: {self.state.file_path}"
                logger.error(error_msg)
                logger.error(f"Current working directory: {os.getcwd()}")
                logger.error(f"Directory contents: {os.listdir(os.path.dirname(self.state.file_path) if os.path.dirname(self.state.file_path) else '.')}")
                self.state.document_text = ""
                return ctx
            
            file_size = os.path.getsize(self.state.file_path)
            logger.info(f"File exists, size: {file_size} bytes")
            
            doc_res = read_document(self.state.file_path, self.state.filename)
            logger.info(f"Document read result type: {type(doc_res)}, is_dict: {isinstance(doc_res, dict)}")
            if isinstance(doc_res, dict):
                logger.info(f"Document read result keys: {list(doc_res.keys())}, ok={doc_res.get('ok')}")
                if doc_res.get("ok"):
                    text_content = doc_res.get("text") or ""
                    self.state.document_text = str(text_content)
                    logger.info(f"Document text loaded successfully, length: {len(self.state.document_text)}")
                else:
                    error_msg = doc_res.get("error", "Unknown error")
                    logger.error(f"Document read failed: {error_msg}")
                    self.state.document_text = ""
            else:
                logger.warning(f"Document read returned unexpected type: {type(doc_res)}")
                self.state.document_text = ""
        except Exception as e:
            logger.error(f"Exception while reading document: {e}", exc_info=True)
            self.state.document_text = ""

        # Build existing catalogs for:
        # - labels where can_create_new is False 
        # - labels where case_unique is False and can_create_new is True
        try:
            existing_catalog_by_label: Dict[str, List[Dict[str, Any]]] = {}
            for ldef in (spec.get("labels") if isinstance(spec, dict) else []) or []:
                if not isinstance(ldef, dict):
                    continue
                lbl = ldef.get("label")
                if not isinstance(lbl, str):
                    continue
                flags = (label_flags_by_label or {}).get(lbl, {})
                if flags.get("ai_ignore"):
                    continue
                # Skip preloading Party catalog; phase 8 performs on-demand fuzzy lookup
                if lbl == "Party":
                    continue
                should_fetch = False
                try:
                    is_creatable = flags.get("can_create_new") is True
                    is_non_creatable = flags.get("can_create_new") is False
                    is_case_unique = flags.get("case_unique") is True

                    if is_non_creatable:
                        should_fetch = True
                    elif (not is_case_unique) and is_creatable:
                        should_fetch = True
                except Exception:
                    should_fetch = False

                if should_fetch:
                    # Project common identifier props
                    props = [p.get("name") for p in (ldef.get("properties") or []) if isinstance(p, dict) and isinstance(p.get("name"), str)]
                    projection = "properties(n) AS props" if not props else "properties(n) AS props"
                    query = f"MATCH (n:`{lbl}`) RETURN {projection} LIMIT 1000"
                    try:
                        rows = neo4j_client.execute_query(query)
                        cleaned: List[Dict[str, Any]] = []
                        for r in rows:
                            props_map = r.get("props") if isinstance(r.get("props"), dict) else None
                            if props_map is None:
                                # If direct properties were returned
                                props_map = {k: v for k, v in r.items() if k != "props"}
                            if isinstance(props_map, dict):
                                cleaned.append(props_map)
                        existing_catalog_by_label[lbl] = cleaned
                    except Exception as e:
                        logger.error(f"Failed to fetch existing catalog for {lbl}: {e}")
                        existing_catalog_by_label[lbl] = []
            self.state.existing_catalog_by_label = existing_catalog_by_label
        except Exception as e:
            logger.warning(f"existing catalog fetch failed: {e}")
            self.state.existing_catalog_by_label = {}

        # Init accumulators
        self.state.nodes_accumulated = []
        self.state.edges_accumulated = []
        try:
            labels_cnt = len((self.state.schema_spec or {}).get("labels", [])) if isinstance(self.state.schema_spec, dict) else 0
            doc_len = len(self.state.document_text or "")
            catalog_cnt = len(self.state.existing_catalog_by_label or {}) if isinstance(self.state.existing_catalog_by_label, dict) else 0
            logger.info(f"prepare_schema: completed (labels={labels_cnt}, doc_len={doc_len}, catalogs={catalog_cnt})")
        except Exception:
            logger.info("prepare_schema: completed")
        print("[prepare_schema] completed")
        return ctx

    @listen(phase0_prepare_schema)
    def phase1_extract_foundation(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 1: extract Case, Proceeding, Issue nodes and create edges between them
        logger.info(f"Phase 1 (foundation): starting for file {self.state.filename}")
        if self.state.progress_callback:
            try:
                self.state.progress_callback("Phase 1 in progress: Extracting foundation nodes", "phase1", 10)
            except Exception as e:
                logger.warning(f"Failed to publish progress: {e}")
        tools = []

        # Phase 1: Extract Case, Proceeding, Issue (hardcoded order)
        labels_src = (self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else []
        def_map = {ld.get("label"): ld for ld in labels_src if isinstance(ld, dict) and isinstance(ld.get("label"), str)}

        # Hardcoded Phase 1 labels in order
        ordered_labels: List[str] = []
        for lbl in ["Case", "Proceeding", "Issue"]:
            # Check ai_ignore from schema
            flags = (self.state.label_flags_by_label or {}).get(lbl, {})
            if flags.get("ai_ignore"):
                continue
            if lbl in def_map:
                ordered_labels.append(lbl)

        # Iterate per label and create crew instances with label-specific replacements
        next_idx = 1 + len(self.state.nodes_accumulated or [])
        produced_labels: List[str] = []

        # Log target labels for Phase 1
        try:
            preview = ", ".join(ordered_labels[:10]) + ("..." if len(ordered_labels) > 10 else "")
            logger.info(f"Phase 1: target labels count={len(ordered_labels)} [{preview}]")
        except Exception:
            pass

        nodes_before_p1 = len(self.state.nodes_accumulated or [])

        # Phase 1: Extract Case (single)
        if "Case" in ordered_labels:
            try:
                ldef = def_map.get("Case")
                if isinstance(ldef, dict):
                    ldef_props_only = {
                        "label": ldef.get("label"),
                        "properties": ldef.get("properties", []),
                    }
                    props_spec_text = render_spec_text({"labels": [ldef_props_only]})
                    instructions, examples_json = _get_label_instructions_and_examples("Case", self.state.node_instructions_by_label)
                    props_model = (self.state.models_by_label or {}).get("Case")
                    
                    if props_model is not None:
                        logger.info("Phase 1: extracting Case")
                        replacements = {
                            "INSTRUCTIONS": instructions,
                            "PROPS_SPEC_TEXT": props_spec_text,
                            "EXAMPLES_JSON": examples_json,
                            "CASE_TEXT": self.state.document_text or "",
                        }
                        crew = CaseCrew(
                            file_path=self.state.file_path,
                            filename=self.state.filename,
                            case_id=self.state.case_id,
                            tools=tools,
                            replacements=replacements,
                        )
                        dyn_task = crew.phase1_extract_case_task(props_model)
                        single_crew = Crew(
                            agents=[crew.phase1_extract_agent()],
                            tasks=[dyn_task],
                            process=Process.sequential,
                        )
                        result = single_crew.kickoff()
                        
                        actual_result = None
                        if hasattr(result, 'pydantic'):
                            actual_result = result.pydantic
                        elif hasattr(result, 'model_dump'):
                            actual_result = result
                        else:
                            actual_result = result
                        
                        if hasattr(actual_result, 'model_dump'):
                            properties = actual_result.model_dump(exclude_none=False)
                        elif isinstance(actual_result, dict):
                            properties = actual_result
                        else:
                            properties = json.loads(str(actual_result))
                        
                        node = {"temp_id": f"n{next_idx}", "label": "Case", "properties": properties}
                        next_idx += 1
                        self.state.nodes_accumulated.append(node)
                        produced_labels.append("Case")
                        logger.info("Phase 1: Case extraction completed")
            except Exception as e:
                logger.warning(f"Phase 1: Case extraction failed: {e}")

        # Phase 1: Extract Proceeding (single)
        if "Proceeding" in ordered_labels:
            try:
                ldef = def_map.get("Proceeding")
                if isinstance(ldef, dict):
                    ldef_props_only = {
                        "label": ldef.get("label"),
                        "properties": ldef.get("properties", []),
                    }
                    props_spec_text = render_spec_text({"labels": [ldef_props_only]})
                    instructions, examples_json = _get_label_instructions_and_examples("Proceeding", self.state.node_instructions_by_label)
                    props_model = (self.state.models_by_label or {}).get("Proceeding")
                    
                    if props_model is not None:
                        logger.info("Phase 1: extracting Proceeding")
                        replacements = {
                            "INSTRUCTIONS": instructions,
                            "PROPS_SPEC_TEXT": props_spec_text,
                            "EXAMPLES_JSON": examples_json,
                            "CASE_TEXT": self.state.document_text or "",
                        }
                        crew = CaseCrew(
                            file_path=self.state.file_path,
                            filename=self.state.filename,
                            case_id=self.state.case_id,
                            tools=tools,
                            replacements=replacements,
                        )
                        dyn_task = crew.phase1_extract_proceeding_task(props_model)
                        single_crew = Crew(
                            agents=[crew.phase1_extract_agent()],
                            tasks=[dyn_task],
                            process=Process.sequential,
                        )
                        result = single_crew.kickoff()
                        
                        actual_result = None
                        if hasattr(result, 'pydantic'):
                            actual_result = result.pydantic
                        elif hasattr(result, 'model_dump'):
                            actual_result = result
                        else:
                            actual_result = result
                        
                        if hasattr(actual_result, 'model_dump'):
                            properties = actual_result.model_dump(exclude_none=False)    
                        elif isinstance(actual_result, dict):
                            properties = actual_result
                        else:
                            properties = json.loads(str(actual_result))
                        
                        node = {"temp_id": f"n{next_idx}", "label": "Proceeding", "properties": properties}
                        next_idx += 1
                        self.state.nodes_accumulated.append(node)
                        produced_labels.append("Proceeding")
                        logger.info("Phase 1: Proceeding extraction completed")
            except Exception as e:
                logger.warning(f"Phase 1: Proceeding extraction failed: {e}")

        # Phase 1: Extract Issue (multiple)
        if "Issue" in ordered_labels:
            try:
                ldef = def_map.get("Issue")
                if isinstance(ldef, dict):
                    ldef_props_only = {
                        "label": ldef.get("label"),
                        "properties": ldef.get("properties", []),
                    }
                    props_spec_text = render_spec_text({"labels": [ldef_props_only]})
                    instructions, examples_json = _get_label_instructions_and_examples("Issue", self.state.node_instructions_by_label)
                    props_model = (self.state.models_by_label or {}).get("Issue")
                    
                    if props_model is not None:
                        logger.info("Phase 1: extracting Issue")
                        list_model = create_model(
                            'IssueList',
                            items=(List[props_model], ...)  # type: ignore
                        )
                        replacements = {
                            "INSTRUCTIONS": instructions,
                            "PROPS_SPEC_TEXT": props_spec_text,
                            "EXAMPLES_JSON": examples_json,
                            "CASE_TEXT": self.state.document_text or "",
                        }
                        crew = CaseCrew(
                            file_path=self.state.file_path,
                            filename=self.state.filename,
                            case_id=self.state.case_id,
                            tools=tools,
                            replacements=replacements,
                        )
                        dyn_task = crew.phase1_extract_issue_task(list_model)
                        single_crew = Crew(
                            agents=[crew.phase1_extract_agent()],
                            tasks=[dyn_task],
                            process=Process.sequential,
                        )
                        result = single_crew.kickoff()
                        
                        actual_result = None
                        if hasattr(result, 'pydantic'):
                            actual_result = result.pydantic
                        elif hasattr(result, 'raw'):
                            actual_result = result.raw
                        else:
                            actual_result = result
                        
                        if not hasattr(actual_result, 'items'):
                            logger.warning(f"Phase 1: Issue result has no 'items' attribute")
                            items = []
                        elif not isinstance(actual_result.items, list):
                            logger.warning(f"Phase 1: Issue result.items is not a list")
                            items = []
                        else:
                            items = actual_result.items
                            logger.info(f"Phase 1: Issue returned {len(items)} items")
                        
                        nodes_added_count = 0
                        for idx, item in enumerate(items):
                            try:
                                properties = item.model_dump(exclude_none=False)
                                node = {"temp_id": f"n{next_idx}", "label": "Issue", "properties": properties}
                                next_idx += 1
                                self.state.nodes_accumulated.append(node)
                                nodes_added_count += 1
                            except Exception as e:
                                logger.warning(f"Phase 1: Failed to process Issue {idx}: {e}")
                                continue
                        
                        logger.info(f"Phase 1: Issue added {nodes_added_count} nodes")
                        if nodes_added_count > 0:
                            produced_labels.append("Issue")
            except Exception as e:
                logger.error(f"Phase 1: Issue extraction failed: {e}", exc_info=True)

        # Fail fast if Case wasn't produced
        if "Case" in ordered_labels and ("Case" not in produced_labels):
            raise RuntimeError("Phase 1: Case extraction produced no Case node; aborting")

        # Create edges: Case → Proceeding and Proceeding → Issue
        try:
            case_id = self.find_first_temp_id("Case")
            proceeding_id = self.find_first_temp_id("Proceeding")
            issue_ids = self.find_all_temp_ids("Issue")
            
            edges_before = len(self.state.edges_accumulated or [])
            
            # Case → Proceeding (HAS_PROCEEDING)
            if case_id and proceeding_id:
                rel_label = get_relationship_label_for_edge("Case", "Proceeding", self.state.rels_by_label or {})
                if rel_label:
                    self.state.edges_accumulated.append({
                        "from": case_id, 
                        "to": proceeding_id, 
                        "label": rel_label, 
                        "properties": {}
                    })
                    logger.info(f"Phase 1: Created edge Case → Proceeding ({rel_label})")
            
            # Proceeding → Issue (ADDRESSES) for each Issue
            if proceeding_id and issue_ids:
                rel_label = get_relationship_label_for_edge("Proceeding", "Issue", self.state.rels_by_label or {})
                if rel_label:
                    for issue_id in issue_ids:
                        self.state.edges_accumulated.append({
                            "from": proceeding_id, 
                            "to": issue_id, 
                            "label": rel_label, 
                            "properties": {}
                        })
                    logger.info(f"Phase 1: Created {len(issue_ids)} edges Proceeding → Issue ({rel_label})")
            
            edges_after = len(self.state.edges_accumulated or [])
            edges_added = max(0, edges_after - edges_before)
        except Exception as e:
            logger.warning(f"Phase 1: Failed to create edges: {e}")
            edges_added = 0

        try:
            nodes_after_p1 = len(self.state.nodes_accumulated or [])
            added = max(0, nodes_after_p1 - nodes_before_p1)
            preview_prod = ", ".join(produced_labels[:10]) + ("..." if len(produced_labels) > 10 else "")
            logger.info(f"Phase 1: completed (nodes_added={added}, edges_added={edges_added}, produced_labels={len(produced_labels)} [{preview_prod}])")
        except Exception:
            logger.info("Phase 1 (foundation): completed")
        
        # No end-of-phase progress callback; start-of-phase now announces in-progress
        
        return {"status": "phase1_done"}


    @listen(phase1_extract_foundation)
    def phase2_assign_forum_jurisdiction(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 2: select Forum and programmatically fetch Jurisdiction; create edges to Proceeding
        logger.info("Phase 2: assigning Forum and Jurisdiction")
        if self.state.progress_callback:
            try:
                self.state.progress_callback("Phase 2 in progress: Assigning forum and jurisdiction", "phase2", 20)
            except Exception as e:
                logger.warning(f"Failed to publish progress: {e}")
        try:
            from .crews.case_crew.case_crew_v3 import CaseCrew as _CaseCrew
            # Build catalog for Forum only
            catalogs = self.build_catalog_for_labels(["Forum"])
            
            # Build indexed catalog to prevent UUID hallucination
            forum_catalog = catalogs.get("Forum", [])
            indexed_forum_catalog, forum_idx_to_id = build_indexed_catalog(
                forum_catalog, 
                "forum_id",
                display_fields=["name", "type"]  # Only show fields needed for selection
            )
            indexed_catalogs = {"Forum": indexed_forum_catalog}
            
            # Get Forum instructions and examples from flow_map
            forum_instructions, forum_examples_json = _get_label_instructions_and_examples("Forum", self.state.node_instructions_by_label)

            # Select Forum based on case text (using indexed catalog)
            crew_sel = _CaseCrew(
                self.state.file_path,
                self.state.filename,
                self.state.case_id,
                tools=[],
                replacements={
                    "FORUM_INSTRUCTIONS": forum_instructions,
                    "FORUM_EXAMPLES_JSON": forum_examples_json,
                    "CASE_TEXT": self.state.document_text or "",
                    "CATALOGS_JSON": json.dumps(indexed_catalogs, ensure_ascii=False),
                },
            )
            task_sel = crew_sel.phase2_select_forum_task(SelectionResponse)
            single_crew_sel = Crew(
                agents=[crew_sel.phase2_select_forum_agent()],
                tasks=[task_sel],
                process=Process.sequential,
            )
            edges_before = len(self.state.edges_accumulated or [])
            nodes_before = len(self.state.nodes_accumulated or [])
            result_sel = single_crew_sel.kickoff()
            
            # Debug logging - show raw AI output before parsing
            logger.info(f"Phase 2: Raw AI result type: {type(result_sel)}")
            if hasattr(result_sel, 'pydantic'):
                logger.info(f"Phase 2: Has pydantic attribute, value: {result_sel.pydantic}")
            if hasattr(result_sel, 'raw'):
                logger.info(f"Phase 2: Has raw attribute, value: {result_sel.raw}")
            logger.info(f"Phase 2: String representation: {str(result_sel)}")
            
            selected = self.parse_selection_response(result_sel)
            
            # Debug logging for forum selection
            logger.info(f"Phase 2: AI returned indices: {selected}")
            logger.info(f"Phase 2: Forum catalog size: {len(forum_catalog)}")

            # Convert returned indices to validated forum_ids
            returned_forum_indices = selected.get("Forum") or []
            forum_ids = resolve_indices_to_ids(returned_forum_indices, forum_idx_to_id, "Forum", "Phase 2")
            logger.info(f"Phase 2: Resolved forum_ids: {forum_ids}")

            # Create selected Forum nodes by ID lookup
            next_idx = 1 + len(self.state.nodes_accumulated or [])
            props_meta = (self.state.props_meta_by_label or {}).get("Forum", {})
            allowed_keys = [k for k in (props_meta.keys() if isinstance(props_meta, dict) else []) if isinstance(k, str)]
            
            # Lookup catalog entry by forum_id
            def find_catalog_by_id(forum_id: str) -> Dict[str, Any] | None:
                for row in forum_catalog:
                    if isinstance(row, dict) and str(row.get("forum_id")) == str(forum_id):
                        return row
                return None
            
            for forum_id in forum_ids:
                entry = find_catalog_by_id(forum_id)
                if not entry:
                    # This shouldn't happen since we validated indices, but keep as safety
                    logger.warning(f"Phase 2: Forum ID '{forum_id}' not found in catalog; skipping")
                    continue
                    
                    # Use all properties from catalog entry
                    props: Dict[str, Any] = {}
                    for k in allowed_keys:
                        if entry.get(k) is not None:
                            props[k] = entry.get(k)
                    # Ensure ID fields are included
                    for k, v in entry.items():
                        if isinstance(k, str) and k.endswith("_id") and v is not None:
                            props[k] = str(v) if not isinstance(v, (int, float, bool)) else v
                    
                    node = {"temp_id": f"n{next_idx}", "label": lbl, "properties": props}
                    next_idx += 1
                    self.state.nodes_accumulated.append(node)

            # Create edges: Proceeding → Forum (using Neo4j ID instead of temp_id)
            try:
                p_id = self.find_first_temp_id("Proceeding")
                
                # Get Forum node and extract its Neo4j ID
                forum_nodes = [n for n in (self.state.nodes_accumulated or []) if isinstance(n, dict) and n.get("label") == "Forum"]
                if p_id and forum_nodes:
                    forum_node = forum_nodes[0]
                    forum_props = forum_node.get("properties") or {}
                    forum_neo4j_id = forum_props.get("forum_id")
                    
                    if forum_neo4j_id:
                        rel_proceeding_forum = get_relationship_label_for_edge("Proceeding", "Forum", self.state.rels_by_label or {})
                        if rel_proceeding_forum:
                            # Use Neo4j ID instead of temp_id for catalog node reference
                            self.state.edges_accumulated.append({
                                "from": p_id, 
                                "to": str(forum_neo4j_id), 
                                "label": rel_proceeding_forum, 
                                "properties": {}
                            })
                            logger.info(f"Phase 2: Created edge Proceeding → Forum ({rel_proceeding_forum}) using Neo4j ID")

                        # Programmatically fetch Jurisdiction for selected Forum
                        forum_name = forum_props.get("name") or forum_props.get("text") or forum_props.get("description")
                        if isinstance(forum_name, str) and forum_name.strip():
                            rel_forum_jurisdiction = get_relationship_label_for_edge("Forum", "Jurisdiction", self.state.rels_by_label or {})
                            
                            if rel_forum_jurisdiction:
                                query = f"MATCH (f:Forum {{name: $name}})-[:{rel_forum_jurisdiction}]->(j:Jurisdiction) RETURN properties(j) AS props LIMIT 1"
                                rows = neo4j_client.execute_query(query, parameters={"name": forum_name})
                                if rows:
                                    j_props = rows[0].get("props") if isinstance(rows[0], dict) else None
                                    if isinstance(j_props, dict):
                                        # Add Jurisdiction node to accumulator (will be stripped later)
                                        j_temp_id = f"n{next_idx}"
                                        next_idx += 1
                                        self.state.nodes_accumulated.append({"temp_id": j_temp_id, "label": "Jurisdiction", "properties": j_props})
                                        
                                        # Get Jurisdiction Neo4j ID for edge
                                        jurisdiction_neo4j_id = j_props.get("jurisdiction_id")
                                        if jurisdiction_neo4j_id:
                                            # Use Neo4j IDs for both Forum and Jurisdiction in edge
                                            self.state.edges_accumulated.append({
                                                "from": str(forum_neo4j_id), 
                                                "to": str(jurisdiction_neo4j_id), 
                                                "label": rel_forum_jurisdiction, 
                                                "properties": {}
                                            })
                                            logger.info(f"Phase 2: Created edge Forum → Jurisdiction ({rel_forum_jurisdiction}) using Neo4j IDs")
            except Exception as e:
                logger.warning(f"Phase 2: Failed to create edges: {e}")

            try:
                nodes_after = len(self.state.nodes_accumulated or [])
                edges_after = len(self.state.edges_accumulated or [])
                logger.info(f"Phase 2: completed (nodes_added={max(0, nodes_after - nodes_before)}, edges_added={max(0, edges_after - edges_before)})")
            except Exception:
                logger.info("Phase 2: Forum and Jurisdiction completed")
            
            # No end-of-phase progress callback; start-of-phase announces in-progress
            
            return {"status": "phase2_done"}
        except Exception as e:
            logger.warning(f"Phase 2: Forum/Jurisdiction assignment failed: {e}")
            return {"status": "phase2_skipped"}

    @listen(phase2_assign_forum_jurisdiction)
    def phase3_extract_parties(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 3: extract/dedupe Parties and create Proceeding->Party edges with roles
        logger.info("Phase 3: extracting and deduplicating Parties; assigning roles")
        if self.state.progress_callback:
            try:
                self.state.progress_callback("Phase 3 in progress: Extracting parties and assigning roles", "phase3", 30)
            except Exception as e:
                logger.warning(f"Failed to publish progress: {e}")
        try:
            from .crews.case_crew.case_crew_v3 import CaseCrew as _CaseCrew
            # Party catalog can be extremely large; skip preloading and use fuzzy lookup per generated name
            catalogs: Dict[str, List[Dict[str, Any]]] = {"Party": []}

            # Get Party instructions and examples from flow_map
            party_instructions, party_examples_json = _get_label_instructions_and_examples("Party", self.state.node_instructions_by_label)

            crew = _CaseCrew(
                self.state.file_path,
                self.state.filename,
                self.state.case_id,
                tools=[],
                replacements={
                    "PARTY_INSTRUCTIONS": party_instructions,
                    "PARTY_EXAMPLES_JSON": party_examples_json,
                    "CASE_TEXT": self.state.document_text or "",
                    "CATALOGS_JSON": json.dumps(catalogs, ensure_ascii=False),
                },
            )
            task = crew.phase9_party_task()
            single_crew = Crew(
                agents=[crew.phase9_party_agent()],
                tasks=[task],
                process=Process.sequential,
            )
            edges_before = len(self.state.edges_accumulated or [])
            nodes_before = len(self.state.nodes_accumulated or [])
            result = single_crew.kickoff()
            data = self.parse_crew_result(result)
            parties = data.get("parties") if isinstance(data, dict) else None
            roles = data.get("case_roles") if isinstance(data, dict) else None
            if not isinstance(parties, list):
                parties = []
            if not isinstance(roles, list):
                roles = []

            # Validate/dedup parties by name
            party_model = (self.state.models_by_label or {}).get("Party")
            existing_names = set()
            for n in (self.state.nodes_accumulated or []):
                if isinstance(n, dict) and n.get("label") == "Party":
                    nm = ((n.get("properties") or {}).get("name") or "").strip()
                    if nm:
                        existing_names.add(nm)

            # Fuzzy lookup using Neo4j for each generated party name
            def _lookup_existing_party(raw_name: str) -> tuple[str, Optional[str]]:
                try:
                    q = (raw_name or "").strip()
                    if not q:
                        return raw_name, None
                    query = (
                        "MATCH (p:Party) "
                        "WHERE p.name IS NOT NULL AND (toLower(p.name) CONTAINS toLower($q) OR toLower($q) CONTAINS toLower(p.name)) "
                        "RETURN properties(p) AS props LIMIT 25"
                    )
                    rows = neo4j_client.execute_query(query, {"q": q})
                    candidates: List[Dict[str, Any]] = []
                    for r in rows:
                        props = r.get("props") if isinstance(r.get("props"), dict) else None
                        if isinstance(props, dict):
                            nm = props.get("name")
                            if isinstance(nm, str) and nm.strip():
                                candidates.append(props)
                    if not candidates:
                        return raw_name, None
                    # Prefer case-insensitive exact
                    for props in candidates:
                        n = str(props.get("name") or "")
                        if n.lower() == q.lower():
                            pid = props.get("party_id")
                            return n, (str(pid) if isinstance(pid, (str, int)) else None)
                    # TODO: Replace string-based fuzzy matching with embedding-based similarity search for better party matching
                    # Heuristic: choose the closest by containment and length similarity
                    def score(candidate_name: str) -> float:
                        c = candidate_name.lower()
                        qq = q.lower()
                        contain = (1.0 if (c in qq or qq in c) else 0.0)
                        len_ratio = min(len(c), len(qq)) / max(len(c), len(qq)) if max(len(c), len(qq)) > 0 else 0.0
                        return contain * 0.7 + len_ratio * 0.3
                    best_props = max(candidates, key=lambda p: score(str(p.get("name") or "")))
                    best_name = str(best_props.get("name") or "")
                    if score(best_name) >= 0.75:
                        pid = best_props.get("party_id")
                        return best_name, (str(pid) if isinstance(pid, (str, int)) else None)
                    return raw_name, None
                except Exception:
                    return raw_name, None

            next_idx = 1 + len(self.state.nodes_accumulated or [])
            created_ids_by_index: Dict[int, str] = {}
            for idx, p in enumerate(parties):
                if not isinstance(p, dict):
                    continue
                clean = self.validate_with_model(p, party_model)
                nm = (clean.get("name") or "").strip()
                if nm:
                    standardized_name, matched_party_id = _lookup_existing_party(nm)
                    if standardized_name and standardized_name != nm:
                        clean["name"] = standardized_name
                        nm = standardized_name
                    if matched_party_id:
                        clean["party_id"] = matched_party_id
                if nm and nm in existing_names:
                    # find existing temp_id
                    tid = None
                    for n in (self.state.nodes_accumulated or []):
                        if isinstance(n, dict) and n.get("label") == "Party":
                            if ((n.get("properties") or {}).get("name") or "").strip() == nm and isinstance(n.get("temp_id"), str):
                                tid = n.get("temp_id")
                                break
                    if isinstance(tid, str):
                        created_ids_by_index[idx] = tid
                        continue
                # create new party
                tid = f"n{next_idx}"
                next_idx += 1
                (self.state.nodes_accumulated or []).append({"temp_id": tid, "label": "Party", "properties": clean})
                created_ids_by_index[idx] = tid
                if nm:
                    existing_names.add(nm)

            # Create Proceeding → Party edges (with role properties validated against schema)
            try:
                rel_proceeding_party = get_relationship_label_for_edge("Proceeding", "Party", self.state.rels_by_label or {})
                
                if not rel_proceeding_party:
                    logger.warning("Phase 3: No relationship found in schema for Proceeding -> Party")
                    return {"status": "phase3_skipped"}
                
                pr_id = None
                for n in (self.state.nodes_accumulated or []):
                    if isinstance(n, dict) and n.get("label") == "Proceeding" and isinstance(n.get("temp_id"), str):
                        pr_id = n.get("temp_id")
                        break
                if isinstance(pr_id, str):
                    existing_edges = self.get_existing_edges_set()
                    for r in roles:
                        if not isinstance(r, dict):
                            continue
                        p_idx = r.get("party_index")
                        role = r.get("role")
                        if not (isinstance(p_idx, int) and isinstance(role, str)):
                            continue
                        p_id = created_ids_by_index.get(p_idx)
                        if not isinstance(p_id, str):
                            continue
                        key = (pr_id, p_id, rel_proceeding_party)
                        if key not in existing_edges:
                            # Validate role property against schema
                            raw_props = {"role": role}
                            validated_props = self.validate_relationship_properties("Proceeding", rel_proceeding_party, raw_props)
                            self.state.edges_accumulated.append({"from": pr_id, "to": p_id, "label": rel_proceeding_party, "properties": validated_props})
                            existing_edges.add(key)
                    logger.info(f"Phase 3: Created {len(roles)} edges Proceeding → Party ({rel_proceeding_party})")
            except Exception as e:
                logger.warning(f"Phase 3: Failed to create edges: {e}")

            try:
                nodes_after = len(self.state.nodes_accumulated or [])
                edges_after = len(self.state.edges_accumulated or [])
                logger.info(f"Phase 3: completed (nodes_added={max(0, nodes_after - nodes_before)}, edges_added={max(0, edges_after - edges_before)})")
            except Exception:
                logger.info("Phase 3: party extraction/dedup and relationships completed")
            
            # No end-of-phase progress callback; start-of-phase announces in-progress
            
            return {"status": "phase3_done"}
        except Exception as e:
            logger.warning(f"Phase 3: party extraction failed: {e}")
            return {"status": "phase3_skipped"}

    @listen(phase3_extract_parties)
    def phase4_extract_ruling_per_issue(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 4: extract one Ruling per Issue (batched with AI-driven deduplication); create Proceeding→Ruling and Ruling→Issue edges
        logger.info("Phase 4: extracting Ruling per Issue (batched with AI deduplication)")
        if self.state.progress_callback:
            try:
                self.state.progress_callback("Phase 4 in progress: Extracting rulings", "phase4", 40)
            except Exception as e:
                logger.warning(f"Failed to publish progress: {e}")
        try:
            from .crews.case_crew.case_crew_v3 import CaseCrew as _CaseCrew
            from typing import Union
            
            # Collect all Issues
            issues = [
                {"temp_id": n.get("temp_id"), "properties": n.get("properties") or {}}
                for n in (self.state.nodes_accumulated or [])
                if isinstance(n, dict) and n.get("label") == "Issue" and isinstance(n.get("temp_id"), str)
            ]
            if not issues:
                logger.info("Phase 4: no Issue nodes present; skipping Ruling extraction")
                return {"status": "phase4_skipped"}
            
            # Get batch size from config (default: 1 issue per batch)
            batch_size = (self.state.flow_config or {}).get("batch_sizes", {}).get("phase4_issues", 1)
            
            # Get cached node instructions for Ruling (O(1) lookup)
            ruling_instructions, ruling_examples_json = _get_label_instructions_and_examples("Ruling", self.state.node_instructions_by_label)
            
            # Get Ruling schema
            labels_src = (self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else []
            ruling_def = next((ld for ld in labels_src if isinstance(ld, dict) and ld.get("label") == "Ruling"), None)
            
            ruling_spec_text = ""
            if isinstance(ruling_def, dict):
                ruling_def_props_only = {"label": ruling_def.get("label"), "properties": ruling_def.get("properties", [])}
                ruling_spec_text = render_spec_text({"labels": [ruling_def_props_only]})
            
            ruling_model = (self.state.models_by_label or {}).get("Ruling")
            if ruling_model is None:
                raise ValueError("Phase 4: Ruling model not found in state; schema must be available for phase4")
            
            # Split issues into batches
            total_issues = len(issues)
            num_batches = (total_issues + batch_size - 1) // batch_size  # Ceiling division
            logger.info(f"Phase 4: Processing {total_issues} issues in {num_batches} batch(es) of size {batch_size}")
            
            proceeding_temp_id = self.find_first_temp_id("Proceeding")
            next_idx = 1 + len(self.state.nodes_accumulated or [])
            nodes_before = len(self.state.nodes_accumulated or [])
            edges_before = len(self.state.edges_accumulated or [])
            
            # Process issues in batches
            for batch_num in range(num_batches):
                start_idx = batch_num * batch_size
                end_idx = min(start_idx + batch_size, total_issues)
                batch_issues = issues[start_idx:end_idx]
                
                logger.info(f"Phase 4: Processing batch {batch_num + 1}/{num_batches} ({len(batch_issues)} issues)")
                
                # Build replacements for YAML task template
                replacements = {
                    "CASE_TEXT": self.state.document_text or "",
                    "ISSUES_JSON": json.dumps({"issues": batch_issues}, ensure_ascii=False),
                    "RULING_INSTRUCTIONS": ruling_instructions,
                    "RULING_EXAMPLES_JSON": ruling_examples_json,
                    "RULING_SPEC_TEXT": ruling_spec_text,
                }
                
                # Create crew with replacements
                crew = _CaseCrew(
                    self.state.file_path,
                    self.state.filename,
                    self.state.case_id,
                    tools=[],
                    replacements=replacements,
                )
                
                # Create Pydantic output model - each issue gets its own unique ruling (one-to-one)
                ruling_per_issue_result = create_model(
                    'RulingPerIssueResult',
                    issue_temp_id=(str, ...),
                    ruling=(ruling_model, ...),  # Required - each issue must have its own ruling
                    in_favor=(Optional[str], None),
                )
                ruling_batch_response = create_model(
                    'RulingPerIssueBatchResponse',
                    rulings=(List[ruling_per_issue_result], ...),
                )
                
                task = crew.phase4_ruling_per_issue_task(ruling_batch_response)
                single_crew = Crew(
                    agents=[crew.phase1_extract_agent()],
                    tasks=[task],
                    process=Process.sequential,
                )
                
                result = single_crew.kickoff()
                
                # Parse result from Pydantic model
                if hasattr(result, 'pydantic'):
                    data = result.pydantic.model_dump() if hasattr(result.pydantic, 'model_dump') else result.pydantic
                elif hasattr(result, 'model_dump'):
                    data = result.model_dump()
                else:
                    data = self.parse_crew_result(result)
                rulings_list = data.get("rulings") if isinstance(data, dict) else None
                if not isinstance(rulings_list, list):
                    rulings_list = []
                
                # Process each ruling result - enforce ONE ruling per issue (one-to-one)
                rel_label_sets = get_relationship_label_for_edge("Ruling", "Issue", self.state.rels_by_label or {})
                
                for entry in rulings_list:
                    if not isinstance(entry, dict):
                        continue
                    
                    issue_temp_id = entry.get("issue_temp_id")
                    ruling_props = entry.get("ruling")
                    in_favor = entry.get("in_favor")
                    
                    # Skip if no valid ruling data
                    if not isinstance(ruling_props, dict):
                        logger.warning(f"Phase 4 batch {batch_num + 1}: No valid ruling data for issue {issue_temp_id}")
                        continue
                    
                    # Enforce one-to-one: Check if this issue already has a ruling
                    if rel_label_sets:
                        existing_sets_to_issue = any(
                            e.get("to") == issue_temp_id and e.get("label") == rel_label_sets
                            for e in (self.state.edges_accumulated or []) if isinstance(e, dict)
                        )
                        if existing_sets_to_issue:
                            logger.warning(f"Phase 4 batch {batch_num + 1}: Issue {issue_temp_id} already has a ruling, skipping duplicate")
                            continue
                    
                    # Validate Ruling properties
                    ruling_properties = self.validate_with_model(ruling_props, ruling_model)
                    
                    # Create new Ruling (always unique per issue)
                    ruling_temp_id = f"n{next_idx}"
                    next_idx += 1
                    ruling_node = {"temp_id": ruling_temp_id, "label": "Ruling", "properties": ruling_properties}
                    self.state.nodes_accumulated.append(ruling_node)
                    logger.debug(f"Phase 4 batch {batch_num + 1}: Created Ruling ({ruling_temp_id}) for issue {issue_temp_id}")
                    
                    # Create edge: Proceeding → Ruling (RESULTS_IN)
                    if proceeding_temp_id:
                        rel_label_results_in = get_relationship_label_for_edge("Proceeding", "Ruling", self.state.rels_by_label or {})
                        if rel_label_results_in:
                            self.state.edges_accumulated.append({
                                "from": proceeding_temp_id,
                                "to": ruling_temp_id,
                                "label": rel_label_results_in,
                                "properties": {}
                            })
                    
                    # Create edge: Ruling → Issue (SETS) with in_favor property
                    if rel_label_sets and isinstance(issue_temp_id, str) and issue_temp_id:
                        raw_sets_props = {"in_favor": in_favor} if isinstance(in_favor, str) else {}
                        validated_sets_props = self.validate_relationship_properties("Ruling", rel_label_sets, raw_sets_props)
                        self.state.edges_accumulated.append({
                            "from": ruling_temp_id,
                            "to": issue_temp_id,
                            "label": rel_label_sets,
                            "properties": validated_sets_props
                        })
            
            try:
                nodes_after = len(self.state.nodes_accumulated or [])
                edges_after = len(self.state.edges_accumulated or [])
                logger.info(f"Phase 4: completed (rulings_created={max(0, nodes_after - nodes_before)}, edges_created={max(0, edges_after - edges_before)})")
            except Exception:
                logger.info("Phase 4: Ruling extraction completed")
            
            return {"status": "phase4_done"}
        except Exception as e:
            logger.warning(f"Phase 4: Ruling extraction failed: {e}")
            return {"status": "phase4_skipped"}

    @listen(phase4_extract_ruling_per_issue)
    def phase5_extract_arguments_per_ruling(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 5: extract Arguments per Ruling (batched with AI-driven deduplication); create Argument nodes and edges
        logger.info("Phase 5: extracting Arguments per Ruling (batched with AI deduplication)")
        if self.state.progress_callback:
            try:
                self.state.progress_callback("Phase 5 in progress: Extracting arguments per ruling", "phase5", 50)
            except Exception as e:
                logger.warning(f"Failed to publish progress: {e}")
        try:
            from .crews.case_crew.case_crew_v3 import CaseCrew as _CaseCrew
            from typing import Union
            
            # Collect all Rulings
            rulings = [
                {"temp_id": n.get("temp_id"), "properties": n.get("properties") or {}}
                for n in (self.state.nodes_accumulated or [])
                if isinstance(n, dict) and n.get("label") == "Ruling" and isinstance(n.get("temp_id"), str)
            ]
            if not rulings:
                logger.info("Phase 5: no Ruling nodes present; skipping Arguments extraction")
                return {"status": "phase5_skipped"}
            
            # Get batch size from config (default: 1 ruling per batch)
            batch_size = (self.state.flow_config or {}).get("batch_sizes", {}).get("phase5_rulings", 1)
            
            # Get cached node instructions for Argument (O(1) lookup)
            argument_instructions, argument_examples_json_raw = _get_label_instructions_and_examples("Argument", self.state.node_instructions_by_label)
            
            # Filter out disposition_text from examples for Phase 5 (will be added in Phase 5B)
            try:
                examples_list = json.loads(argument_examples_json_raw) if isinstance(argument_examples_json_raw, str) else argument_examples_json_raw
                if isinstance(examples_list, list):
                    filtered_examples = []
                    for ex in examples_list:
                        if isinstance(ex, dict):
                            # Remove disposition_text from each example
                            filtered_ex = {k: v for k, v in ex.items() if k != "disposition_text"}
                            # If it has nested arguments, filter those too
                            if "arguments" in filtered_ex and isinstance(filtered_ex["arguments"], list):
                                filtered_ex["arguments"] = [
                                    {k: v for k, v in arg.items() if k != "disposition_text"}
                                    for arg in filtered_ex["arguments"]
                                    if isinstance(arg, dict)
                                ]
                            filtered_examples.append(filtered_ex)
                    argument_examples_json = json.dumps(filtered_examples, ensure_ascii=False)
                else:
                    argument_examples_json = argument_examples_json_raw
            except Exception:
                argument_examples_json = argument_examples_json_raw
            
            # Get Argument schema
            labels_src = (self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else []
            argument_def = next((ld for ld in labels_src if isinstance(ld, dict) and ld.get("label") == "Argument"), None)
            
            # Filter disposition_text from schema for Phase 5
            argument_spec_text = ""
            if isinstance(argument_def, dict):
                # Filter out disposition_text property
                filtered_props = [p for p in (argument_def.get("properties", []) or []) 
                                  if isinstance(p, dict) and p.get("name") != "disposition_text"]
                argument_def_props_only = {"label": argument_def.get("label"), "properties": filtered_props}
                argument_spec_text = render_spec_text({"labels": [argument_def_props_only]})
            
            # Create filtered Argument model without disposition_text for Phase 5
            base_argument_model = (self.state.models_by_label or {}).get("Argument")
            if base_argument_model is None:
                raise ValueError("Phase 5: Argument model not found in state; schema must be available for phase5")
            
            # Build a new model excluding disposition_text
            try:
                from typing import get_type_hints
                fields_dict = {}
                for field_name, field_info in base_argument_model.model_fields.items():
                    if field_name != "disposition_text":
                        fields_dict[field_name] = (field_info.annotation, field_info.default if field_info.default is not None else ...)
                argument_model = create_model('ArgumentPhase5Model', **fields_dict)
            except Exception as e:
                logger.warning(f"Phase 5: Failed to create filtered Argument model: {e}; using base model")
                argument_model = base_argument_model
            
            # Split rulings into batches
            total_rulings = len(rulings)
            num_batches = (total_rulings + batch_size - 1) // batch_size  # Ceiling division
            logger.info(f"Phase 5: Processing {total_rulings} rulings in {num_batches} batch(es) of size {batch_size}")
            
            next_idx = 1 + len(self.state.nodes_accumulated or [])
            nodes_before = len(self.state.nodes_accumulated or [])
            edges_before = len(self.state.edges_accumulated or [])
            arguments_created = 0
            edges_created = 0
            
            # Process rulings in batches
            for batch_num in range(num_batches):
                start_idx = batch_num * batch_size
                end_idx = min(start_idx + batch_size, total_rulings)
                batch_rulings = rulings[start_idx:end_idx]
                
                logger.info(f"Phase 5: Processing batch {batch_num + 1}/{num_batches} ({len(batch_rulings)} rulings)")
                
                # Build context of already-created Arguments for AI deduplication
                existing_arguments = [
                    {"temp_id": n.get("temp_id"), "properties": n.get("properties") or {}}
                    for n in (self.state.nodes_accumulated or [])
                    if isinstance(n, dict) and n.get("label") == "Argument" and isinstance(n.get("temp_id"), str)
                ]
                
                # Build replacements for YAML task template
                replacements = {
                    "CASE_TEXT": self.state.document_text or "",
                    "RULINGS_JSON": json.dumps({"rulings": batch_rulings}, ensure_ascii=False),
                    "EXISTING_ARGUMENTS_JSON": json.dumps({"arguments": existing_arguments}, ensure_ascii=False),
                    "ARGUMENT_INSTRUCTIONS": argument_instructions,
                    "ARGUMENT_EXAMPLES_JSON": argument_examples_json,
                    "ARGUMENT_SPEC_TEXT": argument_spec_text,
                }
                
                # Create crew with replacements
                crew = _CaseCrew(
                    self.state.file_path,
                    self.state.filename,
                    self.state.case_id,
                    tools=[],
                    replacements=replacements,
                )
                
                # Create Pydantic output model that accepts either temp_id OR argument properties
                # For reuse: {"temp_id": "n123", "status": "Accepted"|"Rejected"}
                # For new: {"properties": {...}, "status": "Accepted"|"Rejected"}
                argument_with_status = create_model(
                    'ArgumentWithStatus',
                    temp_id=(Optional[str], None),
                    properties=(Optional[argument_model], None),
                    status=(Optional[str], None),
                )
                ruling_arguments_result = create_model(
                    'RulingArgumentsResult',
                    ruling_temp_id=(str, ...),
                    arguments=(List[argument_with_status], ...),
                )
                arguments_batch_response = create_model(
                    'ArgumentsPerRulingBatchResponse',
                    results=(List[ruling_arguments_result], ...),
                )
                
                task = crew.phase5_arguments_per_ruling_task(arguments_batch_response)
                single_crew = Crew(
                    agents=[crew.phase1_extract_agent()],
                    tasks=[task],
                    process=Process.sequential,
                )
                
                result = single_crew.kickoff()
                
                # Parse result from Pydantic model
                if hasattr(result, 'pydantic'):
                    data = result.pydantic.model_dump() if hasattr(result.pydantic, 'model_dump') else result.pydantic
                elif hasattr(result, 'model_dump'):
                    data = result.model_dump()
                else:
                    data = self.parse_crew_result(result)
                results_list = data.get("results") if isinstance(data, dict) else None
                if not isinstance(results_list, list):
                    results_list = []
                
                # Process each ruling's arguments
                for entry in results_list:
                    if not isinstance(entry, dict):
                        continue
                    
                    ruling_temp_id = entry.get("ruling_temp_id")
                    arguments_list = entry.get("arguments") or []
                    
                    if not isinstance(ruling_temp_id, str):
                        logger.warning(f"Phase 5 batch {batch_num + 1}: ruling_temp_id is not a string")
                        continue
                    
                    # Get relationship label
                    rel_label_eval = get_relationship_label_for_edge("Argument", "Ruling", self.state.rels_by_label or {})
                    
                    # Process each argument
                    for arg_item in arguments_list:
                        if not isinstance(arg_item, dict):
                            continue
                        
                        reuse_temp_id = arg_item.get("temp_id")
                        arg_props = arg_item.get("properties")
                        arg_status = arg_item.get("status")
                        
                        arg_temp_id = None
                        
                        # Check if AI is reusing an existing argument
                        if isinstance(reuse_temp_id, str) and reuse_temp_id:
                            # Verify the temp_id exists in our accumulated nodes
                            if any(n.get("temp_id") == reuse_temp_id and n.get("label") == "Argument" 
                                   for n in (self.state.nodes_accumulated or []) if isinstance(n, dict)):
                                arg_temp_id = reuse_temp_id
                                logger.debug(f"Phase 5 batch {batch_num + 1}: Reusing existing Argument ({arg_temp_id}) for ruling {ruling_temp_id}")
                            else:
                                logger.warning(f"Phase 5 batch {batch_num + 1}: AI returned invalid temp_id {reuse_temp_id}; will try to create new argument")
                        
                        # If not reusing, create new argument
                        if arg_temp_id is None:
                            if not isinstance(arg_props, dict):
                                logger.warning(f"Phase 5 batch {batch_num + 1}: No valid argument data for ruling {ruling_temp_id}")
                                continue
                            
                            # Validate Argument properties
                            arg_properties = self.validate_with_model(arg_props, argument_model)
                            
                            # Create new Argument
                            arg_temp_id = f"n{next_idx}"
                            next_idx += 1
                            arg_node = {"temp_id": arg_temp_id, "label": "Argument", "properties": arg_properties}
                            self.state.nodes_accumulated.append(arg_node)
                            arguments_created += 1
                            logger.debug(f"Phase 5 batch {batch_num + 1}: Created new Argument ({arg_temp_id}) for ruling {ruling_temp_id}")
                        
                        # Create edge: Argument → Ruling (EVALUATED_IN) with status property (for both new and reused arguments)
                        if rel_label_eval and isinstance(arg_temp_id, str):
                            # Check if edge already exists
                            existing = any(
                                e.get("from") == arg_temp_id and e.get("to") == ruling_temp_id and e.get("label") == rel_label_eval
                                for e in (self.state.edges_accumulated or []) if isinstance(e, dict)
                            )
                            if not existing:
                                # Validate status property against schema
                                raw_eval_props = {"status": arg_status} if isinstance(arg_status, str) else {}
                                validated_eval_props = self.validate_relationship_properties("Argument", rel_label_eval, raw_eval_props)
                                self.state.edges_accumulated.append({
                                    "from": arg_temp_id,
                                    "to": ruling_temp_id,
                                    "label": rel_label_eval,
                                    "properties": validated_eval_props
                                })
                                edges_created += 1
            
            try:
                nodes_after = len(self.state.nodes_accumulated or [])
                edges_after = len(self.state.edges_accumulated or [])
                logger.info(f"Phase 5: completed (arguments_created={arguments_created}, edges_created={edges_created})")
            except Exception:
                logger.info("Phase 5: Arguments extraction completed")
            
            return {"status": "phase5_done"}
        except Exception as e:
            logger.warning(f"Phase 5: Arguments extraction failed: {e}")
            return {"status": "phase5_skipped"}

    @listen(phase5_extract_arguments_per_ruling)
    def phase5b_extract_disposition(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 5B: extract disposition_text for newly created arguments (those missing it)
        logger.info("Phase 5B: extracting disposition_text for arguments")
        if self.state.progress_callback:
            try:
                self.state.progress_callback("Phase 5B in progress: Extracting disposition text", "phase5b", 52)
            except Exception as e:
                logger.warning(f"Failed to publish progress: {e}")
        try:
            from .crews.case_crew.case_crew_v3 import CaseCrew as _CaseCrew
            
            # Filter arguments that need disposition_text (those without it)
            arguments_needing_disposition = [
                {"temp_id": n.get("temp_id"), "properties": n.get("properties") or {}}
                for n in (self.state.nodes_accumulated or [])
                if isinstance(n, dict) 
                and n.get("label") == "Argument" 
                and isinstance(n.get("temp_id"), str)
                and not ((n.get("properties") or {}).get("disposition_text"))
            ]
            
            if not arguments_needing_disposition:
                logger.info("Phase 5B: all arguments already have disposition_text; skipping")
                return {"status": "phase5b_skipped"}
            
            # Get batch size from config (default: 3)
            batch_size = (self.state.flow_config or {}).get("batch_sizes", {}).get("phase5b_arguments", 3)
            
            total_args = len(arguments_needing_disposition)
            num_batches = (total_args + batch_size - 1) // batch_size  # Ceiling division
            logger.info(f"Phase 5B: Processing {total_args} arguments in {num_batches} batch(es) of size {batch_size}")
            
            # Get Argument examples and filter to show only argument fields (no ruling context)
            argument_instructions, argument_examples_json_raw = _get_label_instructions_and_examples("Argument", self.state.node_instructions_by_label)
            
            # Extract just the argument objects from examples (strip ruling context)
            try:
                examples_list = json.loads(argument_examples_json_raw) if isinstance(argument_examples_json_raw, str) else argument_examples_json_raw
                filtered_examples = []
                if isinstance(examples_list, list):
                    for ex in examples_list:
                        if isinstance(ex, dict) and "arguments" in ex and isinstance(ex["arguments"], list):
                            # Extract just the argument objects, keeping only relevant fields
                            for arg in ex["arguments"]:
                                if isinstance(arg, dict):
                                    # Keep only: label, text, raised_by, status, disposition_text
                                    filtered_arg = {
                                        k: v for k, v in arg.items() 
                                        if k in ["label", "text", "raised_by", "status", "disposition_text"]
                                    }
                                    if filtered_arg:  # Only add if it has any fields
                                        filtered_examples.append(filtered_arg)
                argument_examples_json = json.dumps(filtered_examples, ensure_ascii=False)
            except Exception as e:
                logger.warning(f"Phase 5B: Failed to filter argument examples: {e}")
                argument_examples_json = "[]"
            
            dispositions_added = 0
            
            # Process arguments in batches
            for batch_num in range(num_batches):
                start_idx = batch_num * batch_size
                end_idx = min(start_idx + batch_size, total_args)
                batch_arguments = arguments_needing_disposition[start_idx:end_idx]
                
                logger.info(f"Phase 5B: Processing batch {batch_num + 1}/{num_batches} ({len(batch_arguments)} arguments)")
                
                # Build replacements for YAML task template
                replacements = {
                    "CASE_TEXT": self.state.document_text or "",
                    "ARGUMENTS_JSON": json.dumps({"arguments": batch_arguments}, ensure_ascii=False),
                    "ARGUMENT_EXAMPLES_JSON": argument_examples_json,
                }
                
                # Create crew with replacements
                crew = _CaseCrew(
                    self.state.file_path,
                    self.state.filename,
                    self.state.case_id,
                    tools=[],
                    replacements=replacements,
                )
                
                # Pass the Pydantic model for validation - disposition_text is required
                task = crew.phase5b_disposition_task(DispositionTextBatchResponse)
                single_crew = Crew(
                    agents=[crew.phase1_extract_agent()],
                    tasks=[task],
                    process=Process.sequential,
                )
                
                result = single_crew.kickoff()
                
                # Extract validated Pydantic result
                results_list: List[DispositionTextEntry] = []
                if hasattr(result, 'pydantic') and result.pydantic is not None:
                    # Pydantic validation succeeded - use validated model
                    pydantic_result = result.pydantic
                    if hasattr(pydantic_result, 'results'):
                        results_list = pydantic_result.results
                    logger.debug(f"Phase 5B batch {batch_num + 1}: Pydantic validation succeeded, {len(results_list)} entries")
                else:
                    # Pydantic validation failed - try to parse manually but log error
                    logger.error(f"Phase 5B batch {batch_num + 1}: Pydantic validation failed! disposition_text may be missing.")
                    data = self.parse_crew_result(result)
                    raw_results = data.get("results") if isinstance(data, dict) else None
                    if isinstance(raw_results, list):
                        for entry in raw_results:
                            if isinstance(entry, dict):
                                arg_id = entry.get("argument_temp_id")
                                disp_text = entry.get("disposition_text")
                                if isinstance(arg_id, str) and isinstance(disp_text, str) and disp_text.strip():
                                    results_list.append(DispositionTextEntry(
                                        argument_temp_id=arg_id,
                                        disposition_text=disp_text
                                    ))
                                else:
                                    logger.error(f"Phase 5B batch {batch_num + 1}: Missing/invalid disposition_text for argument {arg_id}")
                
                # Update existing argument nodes with disposition_text
                for entry in results_list:
                    arg_temp_id = entry.argument_temp_id
                    disposition_text = entry.disposition_text
                    
                    # Find and update the argument node
                    for n in (self.state.nodes_accumulated or []):
                        if isinstance(n, dict) and n.get("temp_id") == arg_temp_id and n.get("label") == "Argument":
                            props = n.get("properties") or {}
                            if isinstance(props, dict):
                                props["disposition_text"] = disposition_text
                                dispositions_added += 1
                                logger.debug(f"Phase 5B batch {batch_num + 1}: Added disposition_text to {arg_temp_id}")
                            break
            
            # Validate: check for any arguments still missing disposition_text
            arguments_missing_disposition = [
                n.get("temp_id")
                for n in (self.state.nodes_accumulated or [])
                if isinstance(n, dict) 
                and n.get("label") == "Argument" 
                and not ((n.get("properties") or {}).get("disposition_text"))
            ]
            
            if arguments_missing_disposition:
                logger.error(
                    f"Phase 5B: CRITICAL - {len(arguments_missing_disposition)} arguments still missing disposition_text: "
                    f"{arguments_missing_disposition}. These will be uploaded to KG without embeddings!"
                )
            
            logger.info(f"Phase 5B: completed (dispositions_added={dispositions_added}, missing={len(arguments_missing_disposition)})")
            return {"status": "phase5b_done", "missing_count": len(arguments_missing_disposition)}
        except Exception as e:
            logger.error(f"Phase 5B: Disposition extraction failed: {e}")
            return {"status": "phase5b_skipped"}

    @listen(phase5b_extract_disposition)
    def phase6_select_laws_per_ruling(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 6: select Laws per Ruling from catalog; create Law nodes and edges
        logger.info("Phase 6: selecting Laws per Ruling")
        if self.state.progress_callback:
            try:
                self.state.progress_callback("Phase 6 in progress: Selecting laws per ruling", "phase6", 55)
            except Exception as e:
                logger.warning(f"Failed to publish progress: {e}")
        try:
            from .crews.case_crew.case_crew_v3 import CaseCrew as _CaseCrew
            
            # Collect all Rulings
            rulings = [
                {"temp_id": n.get("temp_id"), "properties": n.get("properties") or {}}
                for n in (self.state.nodes_accumulated or [])
                if isinstance(n, dict) and n.get("label") == "Ruling" and isinstance(n.get("temp_id"), str)
            ]
            if not rulings:
                logger.info("Phase 6: no Ruling nodes present; skipping Laws selection")
                return {"status": "phase6_skipped"}
            
            # Get Law schema
            labels_src = (self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else []
            law_def = next((ld for ld in labels_src if isinstance(ld, dict) and ld.get("label") == "Law"), None)
            
            law_spec_text = ""
            if isinstance(law_def, dict):
                law_def_props_only = {"label": law_def.get("label"), "properties": law_def.get("properties", [])}
                law_spec_text = render_spec_text({"labels": [law_def_props_only]})
            
            # Build Law catalog
            catalogs = self.build_catalog_for_labels(["Law"])
            law_catalog = catalogs.get("Law", [])
            
            # Build indexed catalog to prevent UUID hallucination
            indexed_law_catalog, law_idx_to_id = build_indexed_catalog(
                law_catalog,
                "law_id",
                display_fields=["name", "citation", "type"]  # Only show fields needed for selection
            )
            indexed_catalogs = {"Law": indexed_law_catalog}
            
            # Build rulings payload
            rulings_payload = {"rulings": rulings}
            
            # Build replacements for YAML task template
            replacements = {
                "CASE_TEXT": self.state.document_text or "",
                "RULINGS_JSON": json.dumps(rulings_payload, ensure_ascii=False),
                "LAW_SPEC_TEXT": law_spec_text,
                "CATALOGS_JSON": json.dumps(indexed_catalogs, ensure_ascii=False),
            }
            
            # Create crew with replacements
            crew = _CaseCrew(
                self.state.file_path,
                self.state.filename,
                self.state.case_id,
                tools=[],
                replacements=replacements,
            )
            
            task = crew.phase6_laws_per_ruling_task()
            single_crew = Crew(
                agents=[crew.phase1_extract_agent()],
                tasks=[task],
                process=Process.sequential,
            )
            
            nodes_before = len(self.state.nodes_accumulated or [])
            result = single_crew.kickoff()
            
            # Parse result
            data = self.parse_crew_result(result)
            results_list = data.get("results") if isinstance(data, dict) else None
            if not isinstance(results_list, list):
                results_list = []
            
            next_idx = 1 + len(self.state.nodes_accumulated or [])
            edges_created = 0
            
            # Process each ruling's laws
            for entry in results_list:
                if not isinstance(entry, dict):
                    continue
                
                ruling_temp_id = entry.get("ruling_temp_id")
                raw_law_indices = entry.get("law_ids") or []
                
                if not isinstance(ruling_temp_id, str):
                    logger.warning(f"Phase 6: ruling_temp_id is not a string")
                    continue
                
                # Convert returned indices to validated law_ids
                law_ids = resolve_indices_to_ids(raw_law_indices, law_idx_to_id, "Law", "Phase 6")
                
                # Create Ruling → Law edges (RELIES_ON_LAW)
                if law_ids:
                    rel_label_law = get_relationship_label_for_edge("Ruling", "Law", self.state.rels_by_label or {})
                    if rel_label_law:
                        existing_edges = self.get_existing_edges_set()
                        
                        for law_id in law_ids:
                            # Find Law in catalog by ID
                            law_entry = None
                            for row in law_catalog:
                                if isinstance(row, dict) and str(row.get("law_id")) == str(law_id):
                                    law_entry = row
                                    break
                            
                            if not law_entry:
                                # This shouldn't happen since we validated indices, but keep as safety
                                logger.warning(f"Phase 6: Law ID '{law_id}' not found in catalog; skipping")
                                continue
                            
                            # Check if Law node already exists in accumulated nodes
                            law_temp_id = None
                            for n in (self.state.nodes_accumulated or []):
                                if isinstance(n, dict) and n.get("label") == "Law":
                                    props = n.get("properties") or {}
                                    if str(props.get("law_id")) == str(law_id):
                                        law_temp_id = n.get("temp_id")
                                        break
                            
                            # Create Law node if it doesn't exist
                            if not law_temp_id:
                                law_temp_id = f"n{next_idx}"
                                next_idx += 1
                                props_meta = (self.state.props_meta_by_label or {}).get("Law", {})
                                allowed_keys = [k for k in props_meta.keys() if isinstance(k, str)]
                                law_props: Dict[str, Any] = {}
                                for k in allowed_keys:
                                    if law_entry.get(k) is not None:
                                        law_props[k] = law_entry.get(k)
                                # Ensure ID fields are included
                                for k, v in law_entry.items():
                                    if isinstance(k, str) and k.endswith("_id") and v is not None:
                                        law_props[k] = str(v) if not isinstance(v, (int, float, bool)) else v
                                
                                self.state.nodes_accumulated.append({"temp_id": law_temp_id, "label": "Law", "properties": law_props})
                            
                            # Create edge: Ruling → Law
                            key = (ruling_temp_id, law_temp_id, rel_label_law)
                            if key not in existing_edges:
                                self.state.edges_accumulated.append({
                                    "from": ruling_temp_id,
                                    "to": law_temp_id,
                                    "label": rel_label_law,
                                    "properties": {}
                                })
                                existing_edges.add(key)
                                edges_created += 1
            
            try:
                nodes_after = len(self.state.nodes_accumulated or [])
                logger.info(f"Phase 6: completed (edges_created={edges_created})")
            except Exception:
                logger.info("Phase 6: Laws selection completed")
            
            return {"status": "phase6_done"}
        except Exception as e:
            logger.warning(f"Phase 6: Laws selection failed: {e}")
            return {"status": "phase6_skipped"}

    @listen(phase6_select_laws_per_ruling)
    def phase7_assign_concepts_to_arguments(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 7: select or create Doctrine/Policy/FactPattern per Argument (batched) + propagate to Issue
        logger.info("Phase 7: assigning Doctrine/Policy/FactPattern to Arguments (batched with creation)")
        if self.state.progress_callback:
            try:
                self.state.progress_callback("Phase 7 in progress: Assigning concepts to arguments", "phase7", 60)
            except Exception as e:
                logger.warning(f"Failed to publish progress: {e}")
        try:
            from .crews.case_crew.case_crew_v3 import CaseCrew as _CaseCrew
            
            # Collect Arguments
            arguments = [
                {"temp_id": n.get("temp_id"), "properties": n.get("properties") or {}}
                for n in (self.state.nodes_accumulated or [])
                if isinstance(n, dict) and n.get("label") == "Argument" and isinstance(n.get("temp_id"), str)
            ]
            if not arguments:
                logger.info("Phase 7: no Argument nodes present; skipping concept assignment")
                return {"status": "phase7_skipped"}

            # Get batch size from config (default: 3)
            batch_size = (self.state.flow_config or {}).get("batch_sizes", {}).get("phase7_arguments", 3)
            
            # Build catalogs for Doctrine, Policy, FactPattern - will be updated after each batch
            catalogs = self.build_catalog_for_labels(["Doctrine", "Policy", "FactPattern"])

            # Get cached node instructions for Doctrine, Policy, FactPattern (O(1) lookups)
            doctrine_instructions, doctrine_examples_json = _get_label_instructions_and_examples("Doctrine", self.state.node_instructions_by_label)
            policy_instructions, policy_examples_json = _get_label_instructions_and_examples("Policy", self.state.node_instructions_by_label)
            factpattern_instructions, factpattern_examples_json = _get_label_instructions_and_examples("FactPattern", self.state.node_instructions_by_label)

            # Build schema spec text
            labels_src = (self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else []
            defs_props_only: List[Dict[str, Any]] = []
            for lbl in ["Doctrine", "Policy", "FactPattern"]:
                d = next((ld for ld in labels_src if isinstance(ld, dict) and ld.get("label") == lbl), None)
                if isinstance(d, dict):
                    defs_props_only.append({"label": d.get("label"), "properties": d.get("properties", [])})
            spec_text = render_spec_text({"labels": defs_props_only})

            # Get relationship labels
            rel_label_doctrine = get_relationship_label_for_edge("Argument", "Doctrine", self.state.rels_by_label or {})
            rel_label_policy = get_relationship_label_for_edge("Argument", "Policy", self.state.rels_by_label or {})
            rel_label_factpattern = get_relationship_label_for_edge("Argument", "FactPattern", self.state.rels_by_label or {})
            
            # Issue relationship labels for propagation
            issue_rel_doctrine = get_relationship_label_for_edge("Issue", "Doctrine", self.state.rels_by_label or {})
            issue_rel_policy = get_relationship_label_for_edge("Issue", "Policy", self.state.rels_by_label or {})
            issue_rel_factpattern = get_relationship_label_for_edge("Issue", "FactPattern", self.state.rels_by_label or {})
            
            existing_edges = self.get_existing_edges_set()
            next_idx = 1 + len(self.state.nodes_accumulated or [])
            nodes_before = len(self.state.nodes_accumulated or [])
            edges_before = len(self.state.edges_accumulated or [])
            
            # Track concept IDs to propagate to Issues (across all batches)
            concepts_to_propagate: Dict[str, set[str]] = {
                "Doctrine": set(),
                "Policy": set(),
                "FactPattern": set()
            }
            
            # Split arguments into batches
            total_args = len(arguments)
            num_batches = (total_args + batch_size - 1) // batch_size  # Ceiling division
            logger.info(f"Phase 7: Processing {total_args} arguments in {num_batches} batch(es) of size {batch_size}")
            
            # Helper function to find catalog node by ID or temp_id and instantiate if from catalog
            def find_catalog_node_temp_id(label: str, node_id: str, catalog: List[Dict[str, Any]]) -> Optional[str]:
                """
                Find a node in catalog by node_id or temp_id.
                If found in catalog but not in nodes_accumulated, create it.
                Returns temp_id if found/created, None if not in catalog.
                """
                nonlocal next_idx
                
                # Map label names to their ID property names (for compound names)
                ID_PROPERTY_MAP = {
                    'ReliefType': 'relief_type_id',
                    'FactPattern': 'fact_pattern_id',
                }
                id_field = ID_PROPERTY_MAP.get(label, f"{label.lower()}_id")
                
                # First, try to match by node_id in catalog
                catalog_entry = None
                for row in catalog:
                    if isinstance(row, dict) and str(row.get(id_field)) == str(node_id):
                        catalog_entry = row
                        break
                
                # If not found by node_id, try to match by temp_id (for newly created nodes in previous batches)
                if not catalog_entry:
                    for row in catalog:
                        if isinstance(row, dict) and str(row.get("temp_id")) == str(node_id):
                            catalog_entry = row
                            break
                
                if not catalog_entry:
                    logger.warning(f"Phase 7: {label} ID '{node_id}' not found in catalog by {id_field} or temp_id")
                    return None
                
                # Check if node already exists in accumulated nodes (by node_id or temp_id)
                existing_temp_id = None
                for n in (self.state.nodes_accumulated or []):
                    if isinstance(n, dict) and n.get("label") == label:
                        # Match by node_id
                        props = n.get("properties") or {}
                        if str(props.get(id_field)) == str(node_id):
                            existing_temp_id = n.get("temp_id")
                            break
                        # Match by temp_id
                        if str(n.get("temp_id")) == str(node_id):
                            existing_temp_id = n.get("temp_id")
                            break
                
                if existing_temp_id:
                    return existing_temp_id
                
                # Create new node from catalog entry
                temp_id = f"n{next_idx}"
                next_idx += 1
                props_meta = (self.state.props_meta_by_label or {}).get(label, {})
                allowed_keys = [k for k in props_meta.keys() if isinstance(k, str)]
                node_props: Dict[str, Any] = {}
                for k in allowed_keys:
                    if catalog_entry.get(k) is not None:
                        node_props[k] = catalog_entry.get(k)
                # Ensure ID fields are included
                for k, v in catalog_entry.items():
                    if isinstance(k, str) and k.endswith("_id") and v is not None:
                        node_props[k] = str(v) if not isinstance(v, (int, float, bool)) else v
                
                self.state.nodes_accumulated.append({"temp_id": temp_id, "label": label, "properties": node_props})
                return temp_id
            
            # Process arguments in batches
            for batch_num in range(num_batches):
                start_idx = batch_num * batch_size
                end_idx = min(start_idx + batch_size, total_args)
                batch_arguments = arguments[start_idx:end_idx]
                
                logger.info(f"Phase 7: Processing batch {batch_num + 1}/{num_batches} ({len(batch_arguments)} arguments)")
                
                # Build indexed catalogs for this batch to prevent UUID hallucination
                # Rebuild each batch since new concepts may have been added
                indexed_doctrine_catalog, doctrine_idx_to_id = build_indexed_catalog(
                    catalogs.get("Doctrine", []), "doctrine_id", display_fields=["name", "description", "temp_id"]
                )
                indexed_policy_catalog, policy_idx_to_id = build_indexed_catalog(
                    catalogs.get("Policy", []), "policy_id", display_fields=["name", "description", "temp_id"]
                )
                indexed_factpattern_catalog, factpattern_idx_to_id = build_indexed_catalog(
                    catalogs.get("FactPattern", []), "fact_pattern_id", display_fields=["name", "description", "temp_id"]
                )
                indexed_catalogs = {
                    "Doctrine": indexed_doctrine_catalog,
                    "Policy": indexed_policy_catalog,
                    "FactPattern": indexed_factpattern_catalog
                }
                
                # Create crew for this batch with indexed catalogs
                crew = _CaseCrew(
                    self.state.file_path,
                    self.state.filename,
                    self.state.case_id,
                    tools=[],
                    replacements={
                        "ARGUMENTS_JSON": json.dumps({"arguments": batch_arguments}, ensure_ascii=False),
                        "CATALOGS_JSON": json.dumps(indexed_catalogs, ensure_ascii=False),
                        "SCHEMA_SPEC_TEXT": spec_text,
                        "DOCTRINE_INSTRUCTIONS": doctrine_instructions,
                        "DOCTRINE_EXAMPLES_JSON": doctrine_examples_json,
                        "POLICY_INSTRUCTIONS": policy_instructions,
                        "POLICY_EXAMPLES_JSON": policy_examples_json,
                        "FACTPATTERN_INSTRUCTIONS": factpattern_instructions,
                        "FACTPATTERN_EXAMPLES_JSON": factpattern_examples_json,
                    },
                )
                
                # Create Pydantic output model for type safety
                new_concept_node = create_model(
                    'NewConceptNode',
                    properties=(Dict[str, Any], ...)
                )
                argument_concept_assignment = create_model(
                    'ArgumentConceptAssignment',
                    argument_temp_id=(str, ...),
                    doctrine_ids=(List[Any], []),  # Now accepts integer indices
                    policy_ids=(List[Any], []),    # Now accepts integer indices
                    factpattern_ids=(List[Any], []),  # Now accepts integer indices
                    new_doctrines=(List[new_concept_node], []),
                    new_policies=(List[new_concept_node], []),
                    new_factpatterns=(List[new_concept_node], [])
                )
                argument_concept_response = create_model(
                    'ArgumentConceptResponse',
                    argument_map=(List[argument_concept_assignment], ...)
                )
                
                task = crew.phase7_argument_concepts_task(argument_concept_response)
                single_crew = Crew(
                    agents=[crew.phase1_extract_agent()],
                    tasks=[task],
                    process=Process.sequential,
                )
                
                result = single_crew.kickoff()
                
                # Parse output from Pydantic model
                if hasattr(result, 'pydantic'):
                    data = result.pydantic.model_dump() if hasattr(result.pydantic, 'model_dump') else result.pydantic
                elif hasattr(result, 'model_dump'):
                    data = result.model_dump()
                else:
                    data = self.parse_crew_result(result)
                argument_map = data.get("argument_map") if isinstance(data, dict) else None
                if not isinstance(argument_map, list):
                    argument_map = []
                
                # Process each argument's concept assignments in this batch
                for entry in argument_map:
                    if not isinstance(entry, dict):
                        continue
                    
                    arg_temp_id = entry.get("argument_temp_id")
                    raw_doctrine_indices = entry.get("doctrine_ids") or []
                    raw_policy_indices = entry.get("policy_ids") or []
                    raw_factpattern_indices = entry.get("factpattern_ids") or []
                    new_doctrines = entry.get("new_doctrines") or []
                    new_policies = entry.get("new_policies") or []
                    new_factpatterns = entry.get("new_factpatterns") or []
                    
                    if not isinstance(arg_temp_id, str):
                        continue
                    
                    # Convert returned indices to validated IDs
                    doctrine_ids = resolve_indices_to_ids(raw_doctrine_indices, doctrine_idx_to_id, "Doctrine", "Phase 7")
                    policy_ids = resolve_indices_to_ids(raw_policy_indices, policy_idx_to_id, "Policy", "Phase 7")
                    factpattern_ids = resolve_indices_to_ids(raw_factpattern_indices, factpattern_idx_to_id, "FactPattern", "Phase 7")
                    
                    # Handle newly created Doctrines
                    if isinstance(new_doctrines, list):
                        for new_node in new_doctrines:
                            if not isinstance(new_node, dict):
                                continue
                            new_props = new_node.get("properties") or {}
                            if not isinstance(new_props, dict):
                                continue
                            
                            # Assign temp_id and add to nodes_accumulated
                            temp_id = f"n{next_idx}"
                            next_idx += 1
                            
                            # Validate and filter properties against schema
                            props_meta = (self.state.props_meta_by_label or {}).get("Doctrine", {})
                            allowed_keys = [k for k in props_meta.keys() if isinstance(k, str)]
                            validated_props: Dict[str, Any] = {k: new_props[k] for k in allowed_keys if k in new_props}
                            
                            self.state.nodes_accumulated.append({
                                "temp_id": temp_id,
                                "label": "Doctrine",
                                "properties": validated_props
                            })
                            
                            # Add to catalog with temp_id for future batch matching
                            catalogs["Doctrine"].append({
                                "temp_id": temp_id,
                                **validated_props
                            })
                            
                            # Create edge Argument → Doctrine
                            if rel_label_doctrine:
                                key = (arg_temp_id, temp_id, rel_label_doctrine)
                                if key not in existing_edges:
                                    self.state.edges_accumulated.append({
                                        "from": arg_temp_id,
                                        "to": temp_id,
                                        "label": rel_label_doctrine,
                                        "properties": {}
                                    })
                                    existing_edges.add(key)
                                    concepts_to_propagate["Doctrine"].add(temp_id)
                    
                    # Handle newly created Policies
                    if isinstance(new_policies, list):
                        for new_node in new_policies:
                            if not isinstance(new_node, dict):
                                continue
                            new_props = new_node.get("properties") or {}
                            if not isinstance(new_props, dict):
                                continue
                            
                            temp_id = f"n{next_idx}"
                            next_idx += 1
                            
                            props_meta = (self.state.props_meta_by_label or {}).get("Policy", {})
                            allowed_keys = [k for k in props_meta.keys() if isinstance(k, str)]
                            validated_props: Dict[str, Any] = {k: new_props[k] for k in allowed_keys if k in new_props}
                            
                            self.state.nodes_accumulated.append({
                                "temp_id": temp_id,
                                "label": "Policy",
                                "properties": validated_props
                            })
                            
                            catalogs["Policy"].append({
                                "temp_id": temp_id,
                                **validated_props
                            })
                            
                            if rel_label_policy:
                                key = (arg_temp_id, temp_id, rel_label_policy)
                                if key not in existing_edges:
                                    self.state.edges_accumulated.append({
                                        "from": arg_temp_id,
                                        "to": temp_id,
                                        "label": rel_label_policy,
                                        "properties": {}
                                    })
                                    existing_edges.add(key)
                                    concepts_to_propagate["Policy"].add(temp_id)
                    
                    # Handle newly created FactPatterns
                    if isinstance(new_factpatterns, list):
                        for new_node in new_factpatterns:
                            if not isinstance(new_node, dict):
                                continue
                            new_props = new_node.get("properties") or {}
                            if not isinstance(new_props, dict):
                                continue
                            
                            temp_id = f"n{next_idx}"
                            next_idx += 1
                            
                            props_meta = (self.state.props_meta_by_label or {}).get("FactPattern", {})
                            allowed_keys = [k for k in props_meta.keys() if isinstance(k, str)]
                            validated_props: Dict[str, Any] = {k: new_props[k] for k in allowed_keys if k in new_props}
                            
                            self.state.nodes_accumulated.append({
                                "temp_id": temp_id,
                                "label": "FactPattern",
                                "properties": validated_props
                            })
                            
                            catalogs["FactPattern"].append({
                                "temp_id": temp_id,
                                **validated_props
                            })
                            
                            if rel_label_factpattern:
                                key = (arg_temp_id, temp_id, rel_label_factpattern)
                                if key not in existing_edges:
                                    self.state.edges_accumulated.append({
                                        "from": arg_temp_id,
                                        "to": temp_id,
                                        "label": rel_label_factpattern,
                                        "properties": {}
                                    })
                                    existing_edges.add(key)
                                    concepts_to_propagate["FactPattern"].add(temp_id)
                    
                    # Create Argument → Doctrine edges (for selected IDs - already validated)
                    if doctrine_ids and rel_label_doctrine:
                        for doctrine_id in doctrine_ids:
                            doctrine_temp_id = find_catalog_node_temp_id("Doctrine", doctrine_id, catalogs.get("Doctrine", []))
                            if doctrine_temp_id:
                                key = (arg_temp_id, doctrine_temp_id, rel_label_doctrine)
                                if key not in existing_edges:
                                    self.state.edges_accumulated.append({
                                        "from": arg_temp_id,
                                        "to": doctrine_temp_id,
                                        "label": rel_label_doctrine,
                                        "properties": {}
                                    })
                                    existing_edges.add(key)
                                    concepts_to_propagate["Doctrine"].add(doctrine_temp_id)
                    
                    # Create Argument → Policy edges (for selected IDs - already validated)
                    if policy_ids and rel_label_policy:
                        for policy_id in policy_ids:
                            policy_temp_id = find_catalog_node_temp_id("Policy", policy_id, catalogs.get("Policy", []))
                            if policy_temp_id:
                                key = (arg_temp_id, policy_temp_id, rel_label_policy)
                                if key not in existing_edges:
                                    self.state.edges_accumulated.append({
                                        "from": arg_temp_id,
                                        "to": policy_temp_id,
                                        "label": rel_label_policy,
                                        "properties": {}
                                    })
                                    existing_edges.add(key)
                                    concepts_to_propagate["Policy"].add(policy_temp_id)
                    
                    # Create Argument → FactPattern edges (for selected IDs - already validated)
                    if factpattern_ids and rel_label_factpattern:
                        for factpattern_id in factpattern_ids:
                            fp_temp_id = find_catalog_node_temp_id("FactPattern", factpattern_id, catalogs.get("FactPattern", []))
                            if fp_temp_id:
                                key = (arg_temp_id, fp_temp_id, rel_label_factpattern)
                                if key not in existing_edges:
                                    self.state.edges_accumulated.append({
                                        "from": arg_temp_id,
                                        "to": fp_temp_id,
                                        "label": rel_label_factpattern,
                                        "properties": {}
                                    })
                                    existing_edges.add(key)
                                    concepts_to_propagate["FactPattern"].add(fp_temp_id)
            
            # Propagate concept relationships to Issues
            # Find Issues via: Argument → Ruling → Issue path
            issue_temp_ids = set()
            rel_label_eval = get_relationship_label_for_edge("Argument", "Ruling", self.state.rels_by_label or {})
            
            for arg in arguments:
                arg_id = arg.get("temp_id")
                if not isinstance(arg_id, str):
                    continue
                
                # Find Ruling(s) connected to this Argument
                ruling_ids = set()
                for e in (self.state.edges_accumulated or []):
                    if isinstance(e, dict) and e.get("from") == arg_id and e.get("label") == rel_label_eval:
                        ruling_id = e.get("to")
                        if isinstance(ruling_id, str):
                            ruling_ids.add(ruling_id)
                
                # Find Issue(s) connected to these Ruling(s)
                for ruling_id in ruling_ids:
                    for e in (self.state.edges_accumulated or []):
                        if isinstance(e, dict) and e.get("from") == ruling_id:
                            # Check if it's a SETS relationship
                            rel_label_sets = get_relationship_label_for_edge("Ruling", "Issue", self.state.rels_by_label or {})
                            if e.get("label") == rel_label_sets:
                                issue_id = e.get("to")
                                if isinstance(issue_id, str):
                                    issue_temp_ids.add(issue_id)
            
            # Create Issue → Doctrine/Policy/FactPattern edges
            for issue_id in issue_temp_ids:
                # Issue → Doctrine
                if issue_rel_doctrine:
                    for doctrine_id in concepts_to_propagate["Doctrine"]:
                        key = (issue_id, doctrine_id, issue_rel_doctrine)
                        if key not in existing_edges:
                            self.state.edges_accumulated.append({
                                "from": issue_id,
                                "to": doctrine_id,
                                "label": issue_rel_doctrine,
                                "properties": {}
                            })
                            existing_edges.add(key)
                
                # Issue → Policy
                if issue_rel_policy:
                    for policy_id in concepts_to_propagate["Policy"]:
                        key = (issue_id, policy_id, issue_rel_policy)
                        if key not in existing_edges:
                            self.state.edges_accumulated.append({
                                "from": issue_id,
                                "to": policy_id,
                                "label": issue_rel_policy,
                                "properties": {}
                            })
                            existing_edges.add(key)
                
                # Issue → FactPattern
                if issue_rel_factpattern:
                    for fp_id in concepts_to_propagate["FactPattern"]:
                        key = (issue_id, fp_id, issue_rel_factpattern)
                        if key not in existing_edges:
                            self.state.edges_accumulated.append({
                                "from": issue_id,
                                "to": fp_id,
                                "label": issue_rel_factpattern,
                                "properties": {}
                            })
                            existing_edges.add(key)
            
            try:
                nodes_after = len(self.state.nodes_accumulated or [])
                edges_after = len(self.state.edges_accumulated or [])
                logger.info(f"Phase 7: completed (nodes_added={max(0, nodes_after - nodes_before)}, edges_added={max(0, edges_after - edges_before)})")
            except Exception:
                logger.info("Phase 7: concept assignment completed")
            
            return {"status": "phase7_done"}
        except Exception as e:
            logger.warning(f"Phase 7: concept assignment failed: {e}")
            return {"status": "phase7_skipped"}

    @listen(phase7_assign_concepts_to_arguments)
    def phase8_generate_relief_and_assign_types(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 8: generate Relief nodes per Ruling + assign ReliefType; create Ruling→Relief and Relief→ReliefType edges
        logger.info("Phase 8: generating Relief nodes and assigning ReliefTypes per Ruling")
        if self.state.progress_callback:
            try:
                self.state.progress_callback("Phase 8 in progress: Generating relief and assigning types", "phase8", 70)
            except Exception as e:
                logger.warning(f"Failed to publish progress: {e}")
        try:
            from .crews.case_crew.case_crew_v3 import CaseCrew as _CaseCrew
            
            # Collect all Rulings
            rulings = [
                {"temp_id": n.get("temp_id"), "properties": n.get("properties") or {}}
                for n in (self.state.nodes_accumulated or [])
                if isinstance(n, dict) and n.get("label") == "Ruling" and isinstance(n.get("temp_id"), str)
            ]
            if not rulings:
                logger.info("Phase 8: no Ruling nodes present; skipping Relief generation")
                return {"status": "phase8_skipped"}

            # Build ReliefType catalog
            catalogs = self.build_catalog_for_labels(["ReliefType"])
            relief_type_catalog = catalogs.get("ReliefType", [])
            
            # Build indexed catalog to prevent UUID hallucination
            indexed_relief_type_catalog, relief_type_idx_to_id = build_indexed_catalog(
                relief_type_catalog,
                "relief_type_id",
                display_fields=["type", "description"]  # Only show fields needed for selection
            )
            indexed_catalogs = {"ReliefType": indexed_relief_type_catalog}

            # Get cached node instructions for Relief and ReliefType (O(1) lookups)
            relief_instructions, relief_examples_json = _get_label_instructions_and_examples("Relief", self.state.node_instructions_by_label)
            relieftype_instructions, relieftype_examples_json = _get_label_instructions_and_examples("ReliefType", self.state.node_instructions_by_label)

            # Get Relief schema
            labels_src = (self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else []
            relief_def = next((ld for ld in labels_src if isinstance(ld, dict) and ld.get("label") == "Relief"), None)
            
            relief_spec_text = ""
            if isinstance(relief_def, dict):
                relief_def_props_only = {"label": relief_def.get("label"), "properties": relief_def.get("properties", [])}
                relief_spec_text = render_spec_text({"labels": [relief_def_props_only]})
            
            relief_model = (self.state.models_by_label or {}).get("Relief")
            
            # Build rulings payload
            rulings_payload = {"rulings": rulings}
            
            # Build replacements for YAML task template (using indexed catalog)
            replacements = {
                "CASE_TEXT": self.state.document_text or "",
                "RULINGS_JSON": json.dumps(rulings_payload, ensure_ascii=False),
                "RELIEF_SPEC_TEXT": relief_spec_text,
                "RELIEF_INSTRUCTIONS": relief_instructions,
                "RELIEF_EXAMPLES_JSON": relief_examples_json,
                "RELIEFTYPE_INSTRUCTIONS": relieftype_instructions,
                "RELIEFTYPE_EXAMPLES_JSON": relieftype_examples_json,
                "CATALOGS_JSON": json.dumps(indexed_catalogs, ensure_ascii=False),
            }
            
            # Create crew with replacements
            crew = _CaseCrew(
                self.state.file_path,
                self.state.filename,
                self.state.case_id,
                tools=[],
                replacements=replacements,
            )
            
            # TODO: Create appropriate task in case_crew_v3.py for phase8_relief_and_type
            # Expected response format: { "results": [{"ruling_temp_id": str, "relief": {properties}, "relief_status": str, "relief_type_id": str}] }
            task = crew.phase8_relief_and_type_task()
            single_crew = Crew(
                agents=[crew.phase1_extract_agent()],
                tasks=[task],
                process=Process.sequential,
            )
            
            edges_before = len(self.state.edges_accumulated or [])
            nodes_before = len(self.state.nodes_accumulated or [])
            result = single_crew.kickoff()

            # Parse result
            data = self.parse_crew_result(result)
            results_list = data.get("results") if isinstance(data, dict) else None
            if not isinstance(results_list, list):
                results_list = []

            next_idx = 1 + len(self.state.nodes_accumulated or [])
            reliefs_created = 0
            edges_created = 0
            
            # Process each ruling's relief
            for entry in results_list:
                if not isinstance(entry, dict):
                    continue
                
                ruling_temp_id = entry.get("ruling_temp_id")
                relief_props = entry.get("relief")
                relief_status = entry.get("relief_status")  # For RESULTS_IN relationship property
                raw_relief_type_idx = entry.get("relief_type_id")
                
                if not isinstance(ruling_temp_id, str):
                    logger.warning(f"Phase 8: ruling_temp_id is not a string")
                    continue
                
                if not isinstance(relief_props, dict):
                    logger.warning(f"Phase 8: Relief properties for ruling {ruling_temp_id} is not a dict")
                    continue
                
                # Convert returned index to validated relief_type_id
                relief_type_ids = resolve_indices_to_ids(
                    [raw_relief_type_idx] if raw_relief_type_idx is not None else [],
                    relief_type_idx_to_id,
                    "ReliefType",
                    "Phase 8"
                )
                relief_type_id = relief_type_ids[0] if relief_type_ids else None
                
                # Validate Relief properties
                relief_properties = self.validate_with_model(relief_props, relief_model)
                
                # Create Relief node
                relief_temp_id = f"n{next_idx}"
                next_idx += 1
                relief_node = {"temp_id": relief_temp_id, "label": "Relief", "properties": relief_properties}
                self.state.nodes_accumulated.append(relief_node)
                reliefs_created += 1
                
                # Create edge: Ruling → Relief (RESULTS_IN) with relief_status property
                rel_label_results_in = get_relationship_label_for_edge("Ruling", "Relief", self.state.rels_by_label or {})
                if rel_label_results_in:
                    # Validate relief_status property against schema
                    raw_props = {"relief_status": relief_status} if isinstance(relief_status, str) else {}
                    validated_props = self.validate_relationship_properties("Ruling", rel_label_results_in, raw_props)
                    self.state.edges_accumulated.append({
                        "from": ruling_temp_id,
                        "to": relief_temp_id,
                        "label": rel_label_results_in,
                        "properties": validated_props
                    })
                    edges_created += 1
                
                # Find or create ReliefType node from catalog
                if isinstance(relief_type_id, str) and relief_type_id:
                    relief_type_catalog = catalogs.get("ReliefType", [])
                    
                    # Find ReliefType in catalog
                    relief_type_entry = None
                    for row in relief_type_catalog:
                        if isinstance(row, dict) and str(row.get("relief_type_id")) == str(relief_type_id):
                            relief_type_entry = row
                            break
                    
                    if not relief_type_entry:
                        logger.warning(f"Phase 7: ReliefType ID '{relief_type_id}' not found in catalog; skipping")
                        continue
                    
                    # Check if ReliefType node already exists in accumulated nodes
                    relief_type_temp_id = None
                    for n in (self.state.nodes_accumulated or []):
                        if isinstance(n, dict) and n.get("label") == "ReliefType":
                            props = n.get("properties") or {}
                            if str(props.get("relief_type_id")) == str(relief_type_id):
                                relief_type_temp_id = n.get("temp_id")
                                break
                    
                    # Create ReliefType node if it doesn't exist (will be stripped later)
                    if not relief_type_temp_id:
                        relief_type_temp_id = f"n{next_idx}"
                        next_idx += 1
                        props_meta = (self.state.props_meta_by_label or {}).get("ReliefType", {})
                        allowed_keys = [k for k in props_meta.keys() if isinstance(k, str)]
                        rt_props: Dict[str, Any] = {}
                        for k in allowed_keys:
                            if relief_type_entry.get(k) is not None:
                                rt_props[k] = relief_type_entry.get(k)
                        # Ensure ID fields are included
                        for k, v in relief_type_entry.items():
                            if isinstance(k, str) and k.endswith("_id") and v is not None:
                                rt_props[k] = str(v) if not isinstance(v, (int, float, bool)) else v
                        
                        self.state.nodes_accumulated.append({"temp_id": relief_type_temp_id, "label": "ReliefType", "properties": rt_props})
                    
                    # Create edge: Relief → ReliefType (IS_TYPE) using Neo4j ID
                    rel_label_is_type = get_relationship_label_for_edge("Relief", "ReliefType", self.state.rels_by_label or {})
                    if rel_label_is_type:
                        # Use Neo4j ID (relief_type_id) instead of temp_id for catalog node reference
                        relief_type_neo4j_id = str(relief_type_id)
                        # Check if edge already exists
                        existing = any(
                            e.get("from") == relief_temp_id and e.get("to") == relief_type_neo4j_id and e.get("label") == rel_label_is_type
                            for e in (self.state.edges_accumulated or []) if isinstance(e, dict)
                        )
                        if not existing:
                            self.state.edges_accumulated.append({
                                "from": relief_temp_id,
                                "to": relief_type_neo4j_id,
                                "label": rel_label_is_type,
                                "properties": {}
                            })
                            edges_created += 1

            try:
                nodes_after = len(self.state.nodes_accumulated or [])
                edges_after = len(self.state.edges_accumulated or [])
                logger.info(f"Phase 8: completed (reliefs_created={reliefs_created}, edges_created={edges_created})")
            except Exception:
                logger.info("Phase 8: Relief generation and ReliefType assignment completed")
            
            return {"status": "phase8_done"}
        except Exception as e:
            logger.warning(f"Phase 8: Relief generation failed: {e}")
            return {"status": "phase8_skipped"}

    @listen(phase8_generate_relief_and_assign_types)
    def phase9_select_domain(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 9: select Domain from Neo4j catalog; create Domain node and edge to Case
        logger.info("Phase 9: selecting Domain")
        if self.state.progress_callback:
            try:
                self.state.progress_callback("Phase 9 in progress: Selecting domain", "phase9", 75)
            except Exception as e:
                logger.warning(f"Failed to publish progress: {e}")
        try:
            from .crews.case_crew.case_crew_v3 import CaseCrew as _CaseCrew
            
            # Build catalog for Domain from Neo4j
            catalogs = self.build_catalog_for_labels(["Domain"])
            domain_catalog = catalogs.get("Domain", [])
            
            if not domain_catalog:
                logger.warning("Phase 9: No Domain catalog available; skipping domain assignment")
                return {"status": "phase9_skipped"}
            
            logger.info(f"Phase 9: Using catalog with {len(domain_catalog)} domains")
            
            # Build indexed catalog to prevent UUID hallucination
            indexed_domain_catalog, domain_idx_to_id = build_indexed_catalog(
                domain_catalog,
                "domain_id",
                display_fields=["name", "description"]  # Only show fields needed for selection
            )
            indexed_catalogs = {"Domain": indexed_domain_catalog}
            
            # Get Domain instructions and examples from flow_map
            domain_instructions, domain_examples_json = _get_label_instructions_and_examples("Domain", self.state.node_instructions_by_label)
            
            # Create crew with indexed catalog
            crew = _CaseCrew(
                self.state.file_path,
                self.state.filename,
                self.state.case_id,
                tools=[],
                replacements={
                    "DOMAIN_INSTRUCTIONS": domain_instructions,
                    "DOMAIN_EXAMPLES_JSON": domain_examples_json,
                    "CASE_TEXT": self.state.document_text or "",
                    "CATALOGS_JSON": json.dumps(indexed_catalogs, ensure_ascii=False),
                },
            )
            
            task = crew.phase9_select_domain_task(SelectionResponse)
            single_crew = Crew(
                agents=[crew.phase9_domain_agent()],
                tasks=[task],
                process=Process.sequential,
            )
            
            nodes_before = len(self.state.nodes_accumulated or [])
            edges_before = len(self.state.edges_accumulated or [])
            result = single_crew.kickoff()
            
            # Parse result as SelectionResponse
            selected = self.parse_selection_response(result)
            raw_domain_indices = selected.get("Domain") or []
            
            # Convert returned indices to validated domain_ids
            domain_ids = resolve_indices_to_ids(raw_domain_indices, domain_idx_to_id, "Domain", "Phase 9")
            
            if not domain_ids:
                logger.warning("Phase 9: No valid domain selected by AI; skipping")
                return {"status": "phase9_skipped"}
            
            selected_domain_id = domain_ids[0]
            logger.info(f"Phase 9: AI selected domain_id: {selected_domain_id}")
            
            # Find domain in catalog by ID
            domain_entry = None
            for row in domain_catalog:
                if isinstance(row, dict) and str(row.get("domain_id")) == str(selected_domain_id):
                    domain_entry = row
                    break
            
            if not domain_entry:
                logger.warning(f"Phase 9: Domain ID '{selected_domain_id}' not found in catalog; skipping")
                return {"status": "phase9_skipped"}
            
            # Create Domain node with all catalog properties
            next_idx = 1 + len(self.state.nodes_accumulated or [])
            domain_temp_id = f"n{next_idx}"
            
            props_meta = (self.state.props_meta_by_label or {}).get("Domain", {})
            allowed_keys = [k for k in props_meta.keys() if isinstance(k, str)]
            domain_props: Dict[str, Any] = {}
            for k in allowed_keys:
                if domain_entry.get(k) is not None:
                    domain_props[k] = domain_entry.get(k)
            # Ensure ID fields are included
            for k, v in domain_entry.items():
                if isinstance(k, str) and k.endswith("_id") and v is not None:
                    domain_props[k] = str(v) if not isinstance(v, (int, float, bool)) else v
            
            # Add Domain node
            domain_node = {"temp_id": domain_temp_id, "label": "Domain", "properties": domain_props}
            self.state.nodes_accumulated.append(domain_node)
            logger.info(f"Phase 9: Created Domain node {domain_temp_id} with properties: {domain_props}")
            
            # Find Case node to create edge
            case_temp_id = self.find_first_temp_id("Case")
            if case_temp_id:
                # Create edge: Domain → Case (CONTAINS) using Neo4j ID
                rel_label = get_relationship_label_for_edge("Domain", "Case", self.state.rels_by_label or {})
                if rel_label:
                    # Use Neo4j ID (domain_id) instead of temp_id for catalog node reference
                    domain_neo4j_id = domain_props.get("domain_id")
                    if domain_neo4j_id:
                        self.state.edges_accumulated.append({
                            "from": str(domain_neo4j_id),
                            "to": case_temp_id,
                            "label": rel_label,
                            "properties": {}
                        })
                        logger.info(f"Phase 9: Created edge Domain → Case ({rel_label}) using Neo4j ID")
                    else:
                        logger.warning("Phase 9: Domain node missing domain_id; cannot create edge (catalog-only node)")
                else:
                    logger.warning("Phase 9: No relationship label found for Domain → Case")
            else:
                logger.warning("Phase 9: No Case node found; cannot create Domain → Case edge")
            
            try:
                nodes_after = len(self.state.nodes_accumulated or [])
                edges_after = len(self.state.edges_accumulated or [])
                logger.info(f"Phase 9: completed (nodes_added={max(0, nodes_after - nodes_before)}, edges_added={max(0, edges_after - edges_before)})")
            except Exception:
                logger.info("Phase 9: Domain selection completed")
            
            return {"status": "phase9_done"}
        except Exception as e:
            logger.warning(f"Phase 9: Domain selection failed: {e}")
            return {"status": "phase9_skipped"}

    @listen(phase9_select_domain)
    def phase10_validate_and_repair(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 10: Quick validation mode: just return the data without deep validation
        # The flow phases already enforce schema rules, so validation is mainly for catching edge cases
        import os
        skip_validation = os.getenv("SKIP_CASE_VALIDATION", "false").lower() in ("true", "1", "yes")
        
        if skip_validation:
            logger.info("Phase 10 (Validation): skipped (SKIP_CASE_VALIDATION=true)")
            return {
                "case_name": self.state.filename,
                "nodes": self.state.nodes_accumulated or [],
                "edges": self.state.edges_accumulated or []
            }
        
        # Pull validators from state prepared in prepare_schema
        models_by_label = self.state.models_by_label
        rels_by_label = self.state.rels_by_label
        props_meta_by_label = self.state.props_meta_by_label
        label_flags_by_label = self.state.label_flags_by_label
        rel_cardinality_by_label = self.state.rel_cardinality_by_label

        # Fallback if state doesn't expose mapping (Flow state is BaseModel; use previous ctx return pattern)
        if not models_by_label or not rels_by_label or not props_meta_by_label:
            return {"case_name": self.state.filename, "nodes": self.state.nodes_accumulated or [], "edges": self.state.edges_accumulated or []}

        logger.info("Phase 10 (Validation): starting")
        
        # Unwrap 'raw' field if present (CrewAI sometimes wraps structured output)
        nodes = self.state.nodes_accumulated or []
        unwrapped_nodes = []
        unwrap_count = 0
        for node in nodes:
            if isinstance(node, dict):
                props = node.get("properties") or {}
                # Check if properties are wrapped in 'raw' field with JSON string
                if isinstance(props, dict) and len(props) == 1 and "raw" in props:
                    try:
                        raw_val = props.get("raw")
                        if isinstance(raw_val, str):
                            unwrapped_props = json.loads(raw_val)
                            # Create new node dict with unwrapped properties
                            node = dict(node)  # shallow copy to preserve other fields
                            node["properties"] = unwrapped_props
                            unwrap_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to unwrap 'raw' field for {node.get('temp_id')}: {e}")
                unwrapped_nodes.append(node)
        
        if unwrap_count > 0:
            logger.info(f"Unwrapped 'raw' field from {unwrap_count} nodes")
        
        edges = self.state.edges_accumulated or []
        logger.info(f"Validation: input has {len(unwrapped_nodes)} nodes, {len(edges)} edges")
        
        payload = {
            "case_name": self.state.filename,
            "nodes": unwrapped_nodes,
            "edges": edges,
        }
        cleaned, errors = validate_case_graph(
            payload,
            models_by_label,
            rels_by_label,
            props_meta_by_label,
            label_flags_by_label=label_flags_by_label,
            existing_catalog_by_label=self.state.existing_catalog_by_label if isinstance(self.state.existing_catalog_by_label, dict) else None,
            relationship_cardinality_by_label=rel_cardinality_by_label,
        )
        
        # Log validation results
        if errors:
            logger.warning(f"Phase 10 (Validation): found {len(errors)} errors")
            logger.warning(f"Phase 10 (Validation): first 5 errors: {errors[:5]}")
            logger.info(f"Validation: cleaned output has {len(cleaned.get('nodes', []))} nodes, {len(cleaned.get('edges', []))} edges")
        
        if not errors:
            try:
                logger.info(f"Validation: passed (nodes={len(cleaned.get('nodes', []))}, edges={len(cleaned.get('edges', []))})")
            except Exception:
                logger.info("Phase 10 (Validation): passed with no errors")
            return cleaned

        # Return cleaned output with validation errors logged
        # Note: LLM repair was removed because it was slow (~5min) and removed all edges
        logger.warning(f"Phase 10 (Validation): returning cleaned output with {len(errors)} errors, {len(cleaned.get('edges', []))} edges retained")
        return cleaned
