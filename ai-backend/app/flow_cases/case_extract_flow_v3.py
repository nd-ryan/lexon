from crewai.flow.flow import Flow, listen, start
from crewai import Crew, Process
from pydantic import BaseModel, Field, create_model
from typing import Dict, Any, List, Optional
from .crews.case_crew.case_crew_v3 import CaseCrew
from .tools.io_tools import read_document, fetch_neo4j_schema
from app.lib.schema_runtime import prune_ui_schema_for_llm, build_property_models, validate_case_graph, render_spec_text, build_relationship_property_models, get_relationship_label_for_edge, get_all_assigned_relationship_labels
from app.models.case_graph import CaseGraph
from app.lib.logging_config import setup_logger
from app.lib.neo4j_client import neo4j_client
import json
import os
from datetime import datetime


logger = setup_logger("case-extract-flow-v3")


def _load_flow_config() -> Dict[str, Any]:
    """Load flow runtime configuration from flow_config_v3.json"""
    try:
        config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "flow_config_v3.json"))
        with open(config_path, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load flow_config_v3.json: {e}; using fallback defaults")
        return {
            "batch_sizes": {
                "phase9_arguments": 999,
                "phase10_facts": 10
            }
        }


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
    # Relationship property validators keyed by (source_label, rel_label)
    rel_prop_models_by_key: Dict[tuple[str, str], Any] | None = None
    rel_prop_meta_by_key: Dict[tuple[str, str], Dict[str, Dict[str, Any]]] | None = None
    # Full schema payload (with relationship property schemas) if available
    schema_full: Any | None = None
    existing_catalog_by_label: Dict[str, List[Dict[str, Any]]] | None = None
    # Working context
    document_text: str = ""
    nodes_accumulated: List[Dict[str, Any]] | None = None
    edges_accumulated: List[Dict[str, Any]] | None = None


# Pydantic models for batch extraction responses
class RulingAndArgumentsResult(BaseModel):
    """Result for a single issue's ruling and arguments extraction"""
    issue_temp_id: str
    ruling: Optional[Dict[str, Any]] = None  # Ruling properties
    arguments: List[Dict[str, Any]] = []  # List of Argument properties


class RulingAndArgumentsBatchResponse(BaseModel):
    """Response for Phase 5: Ruling and Arguments extraction from multiple issues"""
    results: List[RulingAndArgumentsResult]


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

    @listen(phase0_kickoff)
    def phase0_prepare_schema(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("prepare_schema: starting")
        print("[prepare_schema] starting")
        # Build pruned spec and models up front so we can pass spec to the crew
        try:
            schema_res = fetch_neo4j_schema()
            schema_payload = schema_res.get('schema') if isinstance(schema_res, dict) else None
        except Exception:
            schema_payload = None

        spec = prune_ui_schema_for_llm(schema_payload) if schema_payload is not None else {"labels": []}
        models_by_label, rels_by_label, props_meta_by_label, label_flags_by_label = build_property_models(spec)
        spec_text = render_spec_text(spec)
        # Persist on state for later listeners
        self.state.schema_spec = spec
        self.state.schema_spec_text = spec_text
        self.state.models_by_label = models_by_label
        self.state.rels_by_label = rels_by_label
        self.state.props_meta_by_label = props_meta_by_label
        self.state.label_flags_by_label = label_flags_by_label
        # Relationship property models from full schema when available
        try:
            rel_models, rel_meta = build_relationship_property_models(schema_payload)
            self.state.rel_prop_models_by_key = rel_models  # type: ignore[assignment]
            self.state.rel_prop_meta_by_key = rel_meta  # type: ignore[assignment]
        except Exception:
            self.state.rel_prop_models_by_key = {}
            self.state.rel_prop_meta_by_key = {}
        self.state.schema_full = schema_payload

        # Read document once and store text
        try:
            logger.info(f"Reading document: file_path='{self.state.file_path}', filename='{self.state.filename}'")
            
            # Add file existence check with detailed logging
            import os
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

        # Load flow_map to determine phase ordering and get instructions/examples for LLM prompts
        # NOTE: Structural attributes (label, case_unique, can_create_new, ai_ignore) are sourced
        # from schema_v3.json via label_flags_by_label. flow_map_v3.json only provides:
        # - phase: determines extraction order
        # - instructions: LLM guidance for extracting each label
        # - examples: sample data for few-shot prompting
        try:
            import os
            flow_map_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "flow_map_v3.json"))
            with open(flow_map_path, "r") as f:
                flow_map = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load flow_map_v3.json; falling back to schema order: {e}")
            flow_map = []

        # Build list of Phase 1 labels: only Case, Proceeding, Issue
        labels_src = (self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else []
        def_map = {ld.get("label"): ld for ld in labels_src if isinstance(ld, dict) and isinstance(ld.get("label"), str)}

        # Phase 1: Case, Proceeding, Issue only
        # Filter flow_map by phase, then check ai_ignore from schema (not flow_map)
        fm_phase1 = [e for e in (flow_map or []) if isinstance(e, dict) and e.get("phase") == 1]
        
        # Filter to only Case, Proceeding, Issue and check ai_ignore from schema
        phase1_target_labels = {"Case", "Proceeding", "Issue"}
        ordered_labels: List[str] = []
        fm_labels = [e.get("label") for e in fm_phase1 if isinstance(e.get("label"), str)]
        for lbl in fm_labels:
            # Check ai_ignore from schema, not flow_map
            flags = (self.state.label_flags_by_label or {}).get(lbl, {})
            if flags.get("ai_ignore"):
                continue
            if lbl in phase1_target_labels and lbl in def_map and lbl not in ordered_labels:
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

        for label in ordered_labels:
            try:
                # Build single-label spec for properties rendering
                ldef = def_map.get(label)
                if not isinstance(ldef, dict):
                    continue
                # Build properties-only spec for Phase 1 (omit relationships)
                ldef_props_only = {
                    "label": ldef.get("label"),
                    "properties": ldef.get("properties", []),
                }
                props_spec_text = render_spec_text({"labels": [ldef_props_only]})

                # Pull instructions/examples from flow_map entry
                fm_entry = None
                for e in (flow_map or []):
                    if isinstance(e, dict) and e.get("label") == label:
                        fm_entry = e
                        break
                instructions = (fm_entry or {}).get("instructions") or ""
                examples_json = json.dumps((fm_entry or {}).get("examples") or [], ensure_ascii=False)

                # Model for properties
                props_model = (self.state.models_by_label or {}).get(label)
                if props_model is None:
                    continue

                # Build replacements for YAML task template
                replacements = {
                    "INSTRUCTIONS": instructions,
                    "LABEL": label,
                    "PROPS_SPEC_TEXT": props_spec_text,
                    "EXAMPLES_JSON": examples_json,
                    "CASE_TEXT": self.state.document_text or "",
                }

                # Decide single vs multi extraction
                # In Phase 1: Issue can have multiple instances; Proceeding typically single but allow multi for edge cases
                allow_multiple = label in {"Issue", "Proceeding"}
                if allow_multiple:
                    try:
                        # Create a dynamic Pydantic model for the list of items
                        list_model = create_model(
                            f'{label}List',
                            items=(List[props_model], ...)  # type: ignore
                        )
                        logger.info(f"Phase 1: extracting multi-node label '{label}'")
                        
                        # Create crew with replacements
                        crew_multi = CaseCrew(
                            file_path=self.state.file_path,
                            filename=self.state.filename,
                            case_id=self.state.case_id,
                            tools=tools,
                            replacements=replacements,
                        )
                        dyn_task = crew_multi.phase1_extract_multi_nodes_task(list_model)
                        single_crew = Crew(
                            agents=[crew_multi.phase1_extract_agent()],
                            tasks=[dyn_task],
                            process=Process.sequential,
                        )
                        result = single_crew.kickoff()
                        logger.info(f"Phase 1: '{label}' extraction completed, result type: {type(result).__name__}")
                        
                        # CrewAI returns a CrewOutput that wraps the Pydantic result
                        # Access the actual Pydantic model via .pydantic or .raw
                        actual_result = None
                        if hasattr(result, 'pydantic'):
                            actual_result = result.pydantic
                        elif hasattr(result, 'raw'):
                            actual_result = result.raw
                        else:
                            actual_result = result
                        
                        logger.info(f"Phase 1: '{label}' unwrapped result type: {type(actual_result).__name__}, has items: {hasattr(actual_result, 'items')}")
                        
                        # Now extract items from the Pydantic model
                        if not hasattr(actual_result, 'items'):
                            logger.warning(f"Phase 1: '{label}' result has no 'items' attribute. Result: {actual_result}")
                            items = []
                        elif not isinstance(actual_result.items, list):
                            logger.warning(f"Phase 1: '{label}' result.items is not a list. Type: {type(actual_result.items).__name__}")
                            items = []
                        else:
                            items = actual_result.items
                            logger.info(f"Phase 1: '{label}' returned {len(items)} items")

                        nodes_added_count = 0
                        for idx, item in enumerate(items):
                            try:
                                # Each item is already a validated Pydantic model instance
                                properties = item.model_dump(exclude_none=True)
                                node = {"temp_id": f"n{next_idx}", "label": label, "properties": properties}
                                next_idx += 1
                                self.state.nodes_accumulated.append(node)
                                nodes_added_count += 1
                            except Exception as e:
                                logger.warning(f"Phase 1: Failed to process item {idx} for '{label}': {e}")
                                continue
                        
                        logger.info(f"Phase 1: '{label}' added {nodes_added_count} nodes")
                        if nodes_added_count > 0:
                            produced_labels.append(label)
                    except Exception as e:
                        logger.error(f"Phase 1: Multi-node extraction for '{label}' failed with error: {e}", exc_info=True)
                        continue
                else:
                    # Single-instance labels
                    # Create crew with replacements
                    crew_single = CaseCrew(
                        file_path=self.state.file_path,
                        filename=self.state.filename,
                        case_id=self.state.case_id,
                        tools=tools,
                        replacements=replacements,
                    )
                    dyn_task = crew_single.phase1_extract_single_node_task(props_model)  # type: ignore[arg-type]
                    single_crew = Crew(
                        agents=[crew_single.phase1_extract_agent()],
                        tasks=[dyn_task],
                        process=Process.sequential,
                    )
                    result = single_crew.kickoff()

                    # Unwrap CrewOutput to get the actual Pydantic model
                    actual_result = None
                    if hasattr(result, 'pydantic'):
                        actual_result = result.pydantic
                    elif hasattr(result, 'model_dump'):
                        actual_result = result
                    else:
                        actual_result = result

                    # Parse pydantic output into properties dict
                    if hasattr(actual_result, 'model_dump'):
                        properties = actual_result.model_dump(exclude_none=True)  # type: ignore[attr-defined]
                    elif isinstance(actual_result, dict):
                        properties = actual_result
                    else:
                        properties = json.loads(str(actual_result))

                    node = {"temp_id": f"n{next_idx}", "label": label, "properties": properties}
                    next_idx += 1
                    self.state.nodes_accumulated.append(node)
                    produced_labels.append(label)
            except Exception as e:
                logger.warning(f"Phase 1 per-node task for {label} failed: {e}")
                continue

        # Fail fast if Case wasn't produced
        if "Case" in ordered_labels and ("Case" not in produced_labels):
            raise RuntimeError("Phase 1: Case extraction produced no Case node; aborting")

        # Create edges: Case → Proceeding and Proceeding → Issue
        try:
            # Helper to find temp_id by label
            def find_first_temp_id(label: str) -> Optional[str]:
                for n in (self.state.nodes_accumulated or []):
                    if isinstance(n, dict) and n.get("label") == label and isinstance(n.get("temp_id"), str):
                        return n.get("temp_id")
                return None
            
            def find_all_temp_ids(label: str) -> List[str]:
                return [n.get("temp_id") for n in (self.state.nodes_accumulated or []) 
                        if isinstance(n, dict) and n.get("label") == label and isinstance(n.get("temp_id"), str)]
            
            case_id = find_first_temp_id("Case")
            proceeding_id = find_first_temp_id("Proceeding")
            issue_ids = find_all_temp_ids("Issue")
            
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
            # Build catalog for Forum only (no ReliefType in this phase)
            catalogs: Dict[str, List[Dict[str, Any]]] = {}
            for lbl in ["Forum"]:
                rows = (self.state.existing_catalog_by_label or {}).get(lbl) or []
                entries: List[Dict[str, Any]] = []
                props_meta = (self.state.props_meta_by_label or {}).get(lbl) or {}
                allowed_keys = [k for k in props_meta.keys() if isinstance(k, str)]
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    entry: Dict[str, Any] = {}
                    for k in allowed_keys:
                        if r.get(k) is not None:
                            v = r.get(k)
                            try:
                                entry[k] = v if isinstance(v, (int, float, bool)) else str(v)
                            except Exception:
                                entry[k] = str(v)
                    for k, v in r.items():
                        if isinstance(k, str) and k.endswith("_id") and v is not None:
                            try:
                                entry[k] = v if isinstance(v, (int, float, bool)) else str(v)
                            except Exception:
                                entry[k] = str(v)
                    if entry:
                        entries.append(entry)
                catalogs[lbl] = entries

            # Select Forum based on case text
            crew_sel = _CaseCrew(
                self.state.file_path,
                self.state.filename,
                self.state.case_id,
                tools=[],
                replacements={
                    "CASE_TEXT": self.state.document_text or "",
                    "CATALOGS_JSON": json.dumps(catalogs, ensure_ascii=False),
                },
            )
            task_sel = crew_sel.phase5_select_existing_task()
            single_crew_sel = Crew(
                agents=[crew_sel.phase5_select_existing_agent()],
                tasks=[task_sel],
                process=Process.sequential,
            )
            edges_before = len(self.state.edges_accumulated or [])
            nodes_before = len(self.state.nodes_accumulated or [])
            result_sel = single_crew_sel.kickoff()
            selected: Dict[str, List[str]] = {}
            try:
                text = str(result_sel)
                data = json.loads(text) if isinstance(result_sel, str) else (result_sel if isinstance(result_sel, dict) else json.loads(str(result_sel)))
                sel = data.get("selected") if isinstance(data, dict) else None
                if isinstance(sel, dict):
                    for k, v in sel.items():
                        if isinstance(k, str) and isinstance(v, list):
                            selected[k] = [str(x) for x in v]
            except Exception:
                selected = {}

            # Create selected Forum nodes by ID lookup
            next_idx = 1 + len(self.state.nodes_accumulated or [])
            for lbl in ["Forum"]:
                forum_ids = selected.get(lbl) or []
                props_meta = (self.state.props_meta_by_label or {}).get(lbl, {})
                allowed_keys = [k for k in (props_meta.keys() if isinstance(props_meta, dict) else []) if isinstance(k, str)]
                catalog_rows = catalogs.get(lbl, [])
                
                # Lookup catalog entry by forum_id
                def find_catalog_by_id(forum_id: str) -> Dict[str, Any] | None:
                    for row in catalog_rows:
                        if isinstance(row, dict) and str(row.get("forum_id")) == str(forum_id):
                            return row
                    return None
                
                for forum_id in forum_ids:
                    entry = find_catalog_by_id(forum_id)
                    if not entry:
                        logger.warning(f"Phase 2: Forum ID '{forum_id}' not found in catalog; skipping (can_create_new=false)")
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

            # Create edges: Proceeding → Forum
            try:
                def find_first_temp_id(label: str) -> Optional[str]:
                    for n in (self.state.nodes_accumulated or []):
                        if isinstance(n, dict) and n.get("label") == label and isinstance(n.get("temp_id"), str):
                            return n.get("temp_id")
                    return None

                p_id = find_first_temp_id("Proceeding")
                f_id = find_first_temp_id("Forum")

                if p_id and f_id:
                    rel_proceeding_forum = get_relationship_label_for_edge("Proceeding", "Forum", self.state.rels_by_label or {})
                    if rel_proceeding_forum:
                        self.state.edges_accumulated.append({"from": p_id, "to": f_id, "label": rel_proceeding_forum, "properties": {}})
                        logger.info(f"Phase 2: Created edge Proceeding → Forum ({rel_proceeding_forum})")

                # Programmatically fetch Jurisdiction for selected Forum
                if f_id:
                    forum_nodes = [n for n in (self.state.nodes_accumulated or []) if isinstance(n, dict) and n.get("temp_id") == f_id]
                    forum_name = None
                    if forum_nodes:
                        props = forum_nodes[0].get("properties") or {}
                        forum_name = props.get("name") or props.get("text") or props.get("description")
                    if isinstance(forum_name, str) and forum_name.strip():
                        rel_forum_jurisdiction = get_relationship_label_for_edge("Forum", "Jurisdiction", self.state.rels_by_label or {})
                        
                        if rel_forum_jurisdiction:
                            query = f"MATCH (f:Forum {{name: $name}})-[:{rel_forum_jurisdiction}]->(j:Jurisdiction) RETURN properties(j) AS props LIMIT 1"
                            rows = neo4j_client.execute_query(query, parameters={"name": forum_name})
                            if rows:
                                j_props = rows[0].get("props") if isinstance(rows[0], dict) else None
                                if isinstance(j_props, dict):
                                    j_node_id = find_first_temp_id("Jurisdiction")
                                    if not j_node_id:
                                        j_node_id = f"n{next_idx}"
                                        next_idx += 1
                                        self.state.nodes_accumulated.append({"temp_id": j_node_id, "label": "Jurisdiction", "properties": j_props})
                                    # Forum → Jurisdiction
                                    self.state.edges_accumulated.append({"from": f_id, "to": j_node_id, "label": rel_forum_jurisdiction, "properties": {}})
                                    logger.info(f"Phase 2: Created edge Forum → Jurisdiction ({rel_forum_jurisdiction})")
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

            crew = _CaseCrew(
                self.state.file_path,
                self.state.filename,
                self.state.case_id,
                tools=[],
                replacements={
                    "CASE_TEXT": self.state.document_text or "",
                    "CATALOGS_JSON": json.dumps(catalogs, ensure_ascii=False),
                },
            )
            task = crew.phase8_party_task()
            single_crew = Crew(
                agents=[crew.phase8_party_agent()],
                tasks=[task],
                process=Process.sequential,
            )
            edges_before = len(self.state.edges_accumulated or [])
            nodes_before = len(self.state.nodes_accumulated or [])
            result = single_crew.kickoff()

            try:
                data = json.loads(str(result)) if not isinstance(result, dict) else result
            except Exception:
                data = {}
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
                try:
                    if party_model is not None:
                        inst = party_model(**p)
                        clean = inst.model_dump(exclude_none=True)
                    else:
                        clean = {k: v for k, v in p.items() if isinstance(k, str)}
                except Exception:
                    clean = {k: v for k, v in p.items() if isinstance(k, str)}
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

            # Create Proceeding → Party edges (with role properties)
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
                    existing_edges = {(e.get("from"), e.get("to"), e.get("label")) for e in (self.state.edges_accumulated or []) if isinstance(e, dict)}
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
                            props = {"role": role}
                            self.state.edges_accumulated.append({"from": pr_id, "to": p_id, "label": rel_proceeding_party, "properties": props})
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
    def phase4_assign_issue_concepts(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 4: per Issue, select/generate Doctrine, Policy, FactPattern with dedup and create edges
        logger.info("Phase 4: assigning Doctrine/Policy/FactPattern per Issue with catalog dedup")
        if self.state.progress_callback:
            try:
                self.state.progress_callback("Phase 4 in progress: Assigning issue concepts", "phase4", 40)
            except Exception as e:
                logger.warning(f"Failed to publish progress: {e}")
        try:
            from .crews.case_crew.case_crew_v3 import CaseCrew as _CaseCrew
            issues = [
                {"temp_id": n.get("temp_id"), "properties": n.get("properties") or {}}
                for n in (self.state.nodes_accumulated or [])
                if isinstance(n, dict) and n.get("label") == "Issue" and isinstance(n.get("temp_id"), str)
            ]
            if not issues:
                logger.info("Phase 4: no Issue nodes present; skipping")
                return {"status": "phase4_skipped"}

            # Build catalogs using schema-defined properties
            catalogs: Dict[str, List[Dict[str, Any]]] = {"Doctrine": [], "Policy": [], "FactPattern": []}
            try:
                for lbl in list(catalogs.keys()):
                    rows = (self.state.existing_catalog_by_label or {}).get(lbl) or []
                    entries: List[Dict[str, Any]] = []
                    props_meta = (self.state.props_meta_by_label or {}).get(lbl) or {}
                    allowed_keys = [k for k in props_meta.keys() if isinstance(k, str)]
                    for r in rows:
                        if not isinstance(r, dict):
                            continue
                        entry: Dict[str, Any] = {}
                        for k in allowed_keys:
                            if r.get(k) is not None:
                                v = r.get(k)
                                try:
                                    entry[k] = v if isinstance(v, (int, float, bool)) else str(v)
                                except Exception:
                                    entry[k] = str(v)
                        for k, v in r.items():
                            if isinstance(k, str) and k.endswith("_id") and v is not None:
                                try:
                                    entry[k] = v if isinstance(v, (int, float, bool)) else str(v)
                                except Exception:
                                    entry[k] = str(v)
                        if entry:
                            entries.append(entry)
                    catalogs[lbl] = entries
            except Exception:
                pass

            # Build schema spec snippets
            labels_src = (self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else []
            def get_def(lbl: str) -> Dict[str, Any] | None:
                return next((ld for ld in labels_src if isinstance(ld, dict) and ld.get("label") == lbl), None)
            defs_props_only: List[Dict[str, Any]] = []
            for lbl in ["Doctrine", "Policy", "FactPattern"]:
                d = get_def(lbl)
                if isinstance(d, dict):
                    defs_props_only.append({"label": d.get("label"), "properties": d.get("properties", [])})
            spec_text = render_spec_text({"labels": defs_props_only})

            crew = _CaseCrew(
                self.state.file_path,
                self.state.filename,
                self.state.case_id,
                tools=[],
                replacements={
                    "ISSUES_JSON": json.dumps({"issues": issues}, ensure_ascii=False),
                    "CATALOGS_JSON": json.dumps(catalogs, ensure_ascii=False),
                    "SCHEMA_SPEC_TEXT": spec_text,
                },
            )
            task = crew.phase7_issue_related_task()
            single_crew = Crew(
                agents=[crew.phase7_issue_related_agent()],
                tasks=[task],
                process=Process.sequential,
            )
            edges_before = len(self.state.edges_accumulated or [])
            nodes_before = len(self.state.nodes_accumulated or [])
            result = single_crew.kickoff()

            # Parse
            try:
                data = json.loads(str(result)) if not isinstance(result, dict) else result
            except Exception:
                data = {}
            doctrines = data.get("doctrines") if isinstance(data, dict) else None
            policies = data.get("policies") if isinstance(data, dict) else None
            factpatterns = data.get("factpatterns") if isinstance(data, dict) else None
            issue_map = data.get("issue_map") if isinstance(data, dict) else None
            if not isinstance(doctrines, list):
                doctrines = []
            if not isinstance(policies, list):
                policies = []
            if not isinstance(factpatterns, list):
                factpatterns = []
            if not isinstance(issue_map, list):
                issue_map = []

            # Models
            doctrine_model = (self.state.models_by_label or {}).get("Doctrine")
            policy_model = (self.state.models_by_label or {}).get("Policy")
            fp_model = (self.state.models_by_label or {}).get("FactPattern")

            # Dedup signatures and add nodes
            def build_signature(lbl: str, props: Dict[str, Any]) -> str:
                if lbl == "Doctrine":
                    return f"{props.get('name','')}//{props.get('category','')}".strip()
                if lbl == "Policy":
                    return f"{props.get('name','')}//{props.get('discipline','')}".strip()
                return f"{props.get('name','')}".strip()

            existing_sig: Dict[str, set[str]] = {"Doctrine": set(), "Policy": set(), "FactPattern": set()}
            for n in (self.state.nodes_accumulated or []):
                if not isinstance(n, dict):
                    continue
                lbl = n.get("label")
                if lbl not in existing_sig:
                    continue
                props = n.get("properties") or {}
                sig = build_signature(lbl, props)
                if sig:
                    existing_sig[lbl].add(sig)

            created_ids: Dict[str, Dict[int, str]] = {"Doctrine": {}, "Policy": {}, "FactPattern": {}}
            next_idx = 1 + len(self.state.nodes_accumulated or [])
            def add_items(lbl: str, items: List[Dict[str, Any]], model) -> None:
                nonlocal next_idx
                for idx, iprops in enumerate(items):
                    if not isinstance(iprops, dict):
                        continue
                    try:
                        if model is not None:
                            inst = model(**iprops)
                            clean = inst.model_dump(exclude_none=True)
                        else:
                            clean = {k: v for k, v in iprops.items() if isinstance(k, str)}
                    except Exception:
                        clean = {k: v for k, v in iprops.items() if isinstance(k, str)}
                    sig = build_signature(lbl, clean)
                    if sig and sig in existing_sig[lbl]:
                        # find existing temp_id
                        tid = None
                        for n in (self.state.nodes_accumulated or []):
                            if isinstance(n, dict) and n.get("label") == lbl:
                                props = n.get("properties") or {}
                                if build_signature(lbl, props) == sig and isinstance(n.get("temp_id"), str):
                                    tid = n.get("temp_id")
                                    break
                        if isinstance(tid, str):
                            created_ids[lbl][idx] = tid
                            continue
                    tid = f"n{next_idx}"
                    next_idx += 1
                    self.state.nodes_accumulated.append({"temp_id": tid, "label": lbl, "properties": clean})
                    created_ids[lbl][idx] = tid
                    if sig:
                        existing_sig[lbl].add(sig)

            add_items("Doctrine", doctrines, doctrine_model)
            add_items("Policy", policies, policy_model)
            add_items("FactPattern", factpatterns, fp_model)

            # Create Issue relationships (get labels from schema)
            rel_label_doctrine = get_relationship_label_for_edge("Issue", "Doctrine", self.state.rels_by_label or {})
            rel_label_policy = get_relationship_label_for_edge("Issue", "Policy", self.state.rels_by_label or {})
            rel_label_factpattern = get_relationship_label_for_edge("Issue", "FactPattern", self.state.rels_by_label or {})
            
            existing_edges = {(e.get("from"), e.get("to"), e.get("label")) for e in (self.state.edges_accumulated or []) if isinstance(e, dict)}
            for m in issue_map:
                if not isinstance(m, dict):
                    continue
                i_id = m.get("issue_temp_id")
                di = m.get("doctrine_index")
                pi = m.get("policy_index")
                fi = m.get("factpattern_index")
                if isinstance(i_id, str) and isinstance(di, int) and rel_label_doctrine:
                    d_id = created_ids["Doctrine"].get(di)
                    if isinstance(d_id, str):
                        key = (i_id, d_id, rel_label_doctrine)
                        if key not in existing_edges:
                            self.state.edges_accumulated.append({"from": i_id, "to": d_id, "label": rel_label_doctrine, "properties": {}})
                            existing_edges.add(key)
                if isinstance(i_id, str) and isinstance(pi, int) and rel_label_policy:
                    p_id = created_ids["Policy"].get(pi)
                    if isinstance(p_id, str):
                        key = (i_id, p_id, rel_label_policy)
                        if key not in existing_edges:
                            self.state.edges_accumulated.append({"from": i_id, "to": p_id, "label": rel_label_policy, "properties": {}})
                            existing_edges.add(key)
                if isinstance(i_id, str) and isinstance(fi, int) and rel_label_factpattern:
                    f_id = created_ids["FactPattern"].get(fi)
                    if isinstance(f_id, str):
                        key = (i_id, f_id, rel_label_factpattern)
                        if key not in existing_edges:
                            self.state.edges_accumulated.append({"from": i_id, "to": f_id, "label": rel_label_factpattern, "properties": {}})
                            existing_edges.add(key)

            try:
                nodes_after = len(self.state.nodes_accumulated or [])
                edges_after = len(self.state.edges_accumulated or [])
                logger.info(f"Phase 4: completed (nodes_added={max(0, nodes_after - nodes_before)}, edges_added={max(0, edges_after - edges_before)})")
            except Exception:
                logger.info("Phase 4: issue-related assignment completed")
            
            # No end-of-phase progress callback; start-of-phase announces in-progress
            
            return {"status": "phase4_done"}
        except Exception as e:
            logger.warning(f"Phase 4: issue-related assignment failed: {e}")
            return {"status": "phase4_skipped"}

    @listen(phase4_assign_issue_concepts)
    def phase5_extract_ruling_and_arguments(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 5: for each Issue batch, create Ruling and extract Arguments; create edges
        logger.info("Phase 5: extracting Ruling and Arguments per Issue (batched)")
        if self.state.progress_callback:
            try:
                self.state.progress_callback("Phase 5 in progress: Creating rulings and arguments", "phase5", 45)
            except Exception as e:
                logger.warning(f"Failed to publish progress: {e}")
        try:
            from .crews.case_crew.case_crew_v3 import CaseCrew as _CaseCrew
            
            # Load config and apply batch size
            flow_config = _load_flow_config()
            batch_size = flow_config.get("batch_sizes", {}).get("phase5_issues", 999)
            # Allow env override
            batch_size = int(os.getenv("PHASE5_ISSUE_BATCH_SIZE", str(batch_size)))
            
            # Load flow_map for Ruling and Argument instructions
            try:
                flow_map_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "flow_map_v3.json"))
                with open(flow_map_path, "r") as f:
                    flow_map = json.load(f)
            except Exception:
                flow_map = []
            
            fm_ruling = None
            fm_argument = None
            for e in (flow_map or []):
                if isinstance(e, dict):
                    if e.get("label") == "Ruling":
                        fm_ruling = e
                    if e.get("label") == "Argument":
                        fm_argument = e
            
            ruling_instructions = (fm_ruling or {}).get("instructions") or ""
            ruling_examples_json = json.dumps((fm_ruling or {}).get("examples") or [], ensure_ascii=False)
            argument_instructions = (fm_argument or {}).get("instructions") or ""
            argument_examples_json = json.dumps((fm_argument or {}).get("examples") or [], ensure_ascii=False)
            
            # Get schemas
            labels_src = (self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else []
            ruling_def = next((ld for ld in labels_src if isinstance(ld, dict) and ld.get("label") == "Ruling"), None)
            argument_def = next((ld for ld in labels_src if isinstance(ld, dict) and ld.get("label") == "Argument"), None)
            
            ruling_spec_text = ""
            if isinstance(ruling_def, dict):
                ruling_def_props_only = {"label": ruling_def.get("label"), "properties": ruling_def.get("properties", [])}
                ruling_spec_text = render_spec_text({"labels": [ruling_def_props_only]})
            
            argument_spec_text = ""
            if isinstance(argument_def, dict):
                argument_def_props_only = {"label": argument_def.get("label"), "properties": argument_def.get("properties", [])}
                argument_spec_text = render_spec_text({"labels": [argument_def_props_only]})
            
            ruling_model = (self.state.models_by_label or {}).get("Ruling")
            argument_model = (self.state.models_by_label or {}).get("Argument")
            
            # Collect all Issues
            issues = [n for n in (self.state.nodes_accumulated or []) if isinstance(n, dict) and n.get("label") == "Issue"]
            if not issues:
                logger.info("Phase 5: no Issue nodes present; skipping Ruling/Arguments")
                return {"status": "phase5_skipped"}
            
            logger.info(f"Phase 5: processing {len(issues)} issues in batches of {batch_size}")
            
            # Helper function to find first node by label
            def find_first_temp_id(label: str) -> Optional[str]:
                for n in (self.state.nodes_accumulated or []):
                    if isinstance(n, dict) and n.get("label") == label and isinstance(n.get("temp_id"), str):
                        return n.get("temp_id")
                return None
            
            next_idx = 1 + len(self.state.nodes_accumulated or [])
            rulings_created = 0
            arguments_created = 0
            edges_created = 0
            
            # Track created Rulings for deduplication (same Ruling can apply to multiple Issues)
            ruling_signatures: Dict[str, str] = {}  # signature -> temp_id
            
            # Process issues in batches
            for batch_start in range(0, len(issues), batch_size):
                batch_end = min(batch_start + batch_size, len(issues))
                batch = issues[batch_start:batch_end]
                
                try:
                    logger.info(f"Phase 5: processing issue batch {batch_start // batch_size + 1} (issues {batch_start + 1}-{batch_end} of {len(issues)})")
                    
                    # Build issues payload for this batch
                    issues_payload = {
                        "issues": [
                            {"temp_id": n.get("temp_id"), "properties": n.get("properties") or {}}
                            for n in batch if isinstance(n, dict)
                        ]
                    }
                    
                    # Build replacements for YAML task template
                    replacements = {
                        "CASE_TEXT": self.state.document_text or "",
                        "ISSUES_JSON": json.dumps(issues_payload, ensure_ascii=False),
                        "RULING_INSTRUCTIONS": ruling_instructions,
                        "RULING_EXAMPLES_JSON": ruling_examples_json,
                        "RULING_SPEC_TEXT": ruling_spec_text,
                        "ARGUMENT_INSTRUCTIONS": argument_instructions,
                        "ARGUMENT_EXAMPLES_JSON": argument_examples_json,
                        "ARGUMENT_SPEC_TEXT": argument_spec_text,
                    }
                    
                    # Create crew with replacements
                    crew_batch = _CaseCrew(
                        self.state.file_path,
                        self.state.filename,
                        self.state.case_id,
                        tools=[],
                        replacements=replacements,
                    )
                    
                    task = crew_batch.phase5_batch_ruling_arguments_task(RulingAndArgumentsBatchResponse)
                    single_crew = Crew(
                        agents=[crew_batch.phase1_extract_agent()],
                        tasks=[task],
                        process=Process.sequential,
                    )
                    result = single_crew.kickoff()
                    
                    # Extract Pydantic model from CrewOutput
                    batch_response: RulingAndArgumentsBatchResponse
                    if hasattr(result, 'pydantic') and result.pydantic:
                        batch_response = result.pydantic
                    elif isinstance(result, RulingAndArgumentsBatchResponse):
                        batch_response = result
                    else:
                        logger.warning(f"Phase 5: Unexpected result type: {type(result)}")
                        batch_response = RulingAndArgumentsBatchResponse(results=[])
                    
                    results = batch_response.results
                    proceeding_temp_id = find_first_temp_id("Proceeding")
                    
                    # Process each result entry (one per issue in batch)
                    for entry in results:
                        issue_temp_id = entry.issue_temp_id
                        ruling_props = entry.ruling
                        arguments_list = entry.arguments or []
                        
                        if not isinstance(ruling_props, dict):
                            logger.warning(f"Phase 5: Ruling for issue {issue_temp_id} is not a dict")
                            continue
                        
                        # Validate Ruling
                        try:
                            if ruling_model is not None:
                                inst = ruling_model(**ruling_props)
                                ruling_properties = inst.model_dump(exclude_none=True)
                            else:
                                ruling_properties = ruling_props
                        except Exception:
                            ruling_properties = {k: v for k, v in ruling_props.items() if isinstance(k, str)}
                        
                        # Dedup Ruling by signature (label + type)
                        ruling_sig = f"{ruling_properties.get('label', '')}|{ruling_properties.get('type', '')}".strip()
                        if ruling_sig and ruling_sig in ruling_signatures:
                            # Reuse existing Ruling
                            ruling_temp_id = ruling_signatures[ruling_sig]
                            logger.debug(f"Phase 5: Reusing existing Ruling ({ruling_temp_id})")
                        else:
                            # Create new Ruling
                            ruling_temp_id = f"n{next_idx}"
                            next_idx += 1
                            ruling_node = {"temp_id": ruling_temp_id, "label": "Ruling", "properties": ruling_properties}
                            self.state.nodes_accumulated.append(ruling_node)
                            rulings_created += 1
                            if ruling_sig:
                                ruling_signatures[ruling_sig] = ruling_temp_id
                        
                        # Create edges for Ruling
                        if isinstance(issue_temp_id, str) and issue_temp_id:
                            # Edge: Ruling → Issue (SETS)
                            rel_label_sets = get_relationship_label_for_edge("Ruling", "Issue", self.state.rels_by_label or {})
                            if rel_label_sets:
                                # Check if edge already exists
                                existing = any(
                                    e.get("from") == ruling_temp_id and e.get("to") == issue_temp_id and e.get("label") == rel_label_sets
                                    for e in (self.state.edges_accumulated or []) if isinstance(e, dict)
                                )
                                if not existing:
                                    self.state.edges_accumulated.append({
                                        "from": ruling_temp_id,
                                        "to": issue_temp_id,
                                        "label": rel_label_sets,
                                        "properties": {}
                                    })
                                    edges_created += 1
                            
                            # Edge: Proceeding → Ruling (RESULTS_IN) - only create once per Ruling
                            if ruling_sig not in ruling_signatures or ruling_signatures.get(ruling_sig) == ruling_temp_id:
                                rel_label_results_in = get_relationship_label_for_edge("Proceeding", "Ruling", self.state.rels_by_label or {})
                                if rel_label_results_in and proceeding_temp_id:
                                    # Check if edge already exists
                                    existing = any(
                                        e.get("from") == proceeding_temp_id and e.get("to") == ruling_temp_id and e.get("label") == rel_label_results_in
                                        for e in (self.state.edges_accumulated or []) if isinstance(e, dict)
                                    )
                                    if not existing:
                                        self.state.edges_accumulated.append({
                                            "from": proceeding_temp_id,
                                            "to": ruling_temp_id,
                                            "label": rel_label_results_in,
                                            "properties": {}
                                        })
                                        edges_created += 1
                        
                        # Process Arguments
                        if not isinstance(arguments_list, list):
                            arguments_list = []
                        
                        rel_label_eval = get_relationship_label_for_edge("Argument", "Ruling", self.state.rels_by_label or {})
                        for arg_props in arguments_list:
                            if not isinstance(arg_props, dict):
                                continue
                            
                            try:
                                # Validate Argument
                                if argument_model is not None:
                                    inst = argument_model(**arg_props)
                                    arg_properties = inst.model_dump(exclude_none=True)
                                else:
                                    arg_properties = arg_props
                            except Exception:
                                arg_properties = {k: v for k, v in arg_props.items() if isinstance(k, str)}
                            
                            arg_temp_id = f"n{next_idx}"
                            next_idx += 1
                            arg_node = {"temp_id": arg_temp_id, "label": "Argument", "properties": arg_properties}
                            self.state.nodes_accumulated.append(arg_node)
                            arguments_created += 1
                            
                            # Create edge: Argument → Ruling (EVALUATED_IN)
                            if rel_label_eval and isinstance(ruling_temp_id, str):
                                self.state.edges_accumulated.append({
                                    "from": arg_temp_id,
                                    "to": ruling_temp_id,
                                    "label": rel_label_eval,
                                    "properties": {}
                                })
                                edges_created += 1
                
                except Exception as e:
                    logger.warning(f"Phase 5: Failed to process issues batch: {e}")
                    continue
            
            logger.info(f"Phase 5: completed (rulings_created={rulings_created}, arguments_created={arguments_created}, edges_created={edges_created})")
            
            return {"status": "phase5_done"}
        except Exception as e:
            logger.warning(f"Phase 5: Ruling/Arguments extraction failed: {e}")
            return {"status": "phase5_skipped"}

    @listen(phase5_extract_ruling_and_arguments)
    def phase6_assign_laws(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 6: for each Argument, select or create Law(s) with dedup and add Argument->Law edges
        logger.info("Phase 6: assigning Laws to Arguments with catalog dedup")
        if self.state.progress_callback:
            try:
                self.state.progress_callback("Phase 6 in progress: Assigning laws", "phase6", 60)
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
                logger.info("Phase 6: no Argument nodes present; skipping law assignment")
                return {"status": "phase6_skipped"}

            # Build Law catalog using schema-defined properties
            catalogs: Dict[str, List[Dict[str, Any]]] = {"Law": []}
            try:
                rows = (self.state.existing_catalog_by_label or {}).get("Law") or []
                entries: List[Dict[str, Any]] = []
                law_props_meta = (self.state.props_meta_by_label or {}).get("Law") or {}
                allowed_keys = [k for k in law_props_meta.keys() if isinstance(k, str)]
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    entry: Dict[str, Any] = {}
                    for k in allowed_keys:
                        if r.get(k) is not None:
                            v = r.get(k)
                            try:
                                entry[k] = v if isinstance(v, (int, float, bool)) else str(v)
                            except Exception:
                                entry[k] = str(v)
                    for k, v in r.items():
                        if isinstance(k, str) and k.endswith("_id") and v is not None:
                            try:
                                entry[k] = v if isinstance(v, (int, float, bool)) else str(v)
                            except Exception:
                                entry[k] = str(v)
                    if entry:
                        entries.append(entry)
                catalogs["Law"] = entries
            except Exception:
                catalogs = {"Law": []}

            # Law schema spec text for validation context
            labels_src = (self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else []
            law_def = next((ld for ld in labels_src if isinstance(ld, dict) and ld.get("label") == "Law"), None)
            law_spec_text = ""
            if isinstance(law_def, dict):
                law_def_props_only = {"label": law_def.get("label"), "properties": law_def.get("properties", [])}
                law_spec_text = render_spec_text({"labels": [law_def_props_only]})

            crew = _CaseCrew(
                self.state.file_path,
                self.state.filename,
                self.state.case_id,
                tools=[],
                replacements={
                    "ARGUMENTS_JSON": json.dumps({"arguments": arguments}, ensure_ascii=False),
                    "CATALOGS_JSON": json.dumps(catalogs, ensure_ascii=False),
                    "SCHEMA_SPEC_TEXT": law_spec_text,
                },
            )
            task = crew.phase6_law_task()
            single_crew = Crew(
                agents=[crew.phase6_law_agent()],
                tasks=[task],
                process=Process.sequential,
            )
            edges_before = len(self.state.edges_accumulated or [])
            nodes_before = len(self.state.nodes_accumulated or [])
            result = single_crew.kickoff()

            # Parse output
            try:
                data = json.loads(str(result)) if not isinstance(result, dict) else result
            except Exception:
                data = {}
            laws_list = data.get("laws") if isinstance(data, dict) else None
            arg_map_list = data.get("argument_to_law") if isinstance(data, dict) else None
            if not isinstance(laws_list, list):
                laws_list = []
            if not isinstance(arg_map_list, list):
                arg_map_list = []

            # Validate/dedup laws and add nodes
            law_model = (self.state.models_by_label or {}).get("Law")
            existing_signatures: set[str] = set()
            for n in (self.state.nodes_accumulated or []):
                if isinstance(n, dict) and n.get("label") == "Law":
                    props = n.get("properties") or {}
                    sig = (props.get("citation") or props.get("name") or "").strip()
                    if sig:
                        existing_signatures.add(sig)

            created_ids_by_index: Dict[int, str] = {}
            next_idx = 1 + len(self.state.nodes_accumulated or [])
            for idx, lprops in enumerate(laws_list):
                if not isinstance(lprops, dict):
                    continue
                try:
                    if law_model is not None:
                        inst = law_model(**lprops)
                        clean_props = inst.model_dump(exclude_none=True)
                    else:
                        clean_props = {k: v for k, v in lprops.items() if isinstance(k, str)}
                except Exception:
                    clean_props = {k: v for k, v in lprops.items() if isinstance(k, str)}

                sig = (clean_props.get("citation") or clean_props.get("name") or "").strip()
                if sig and sig in existing_signatures:
                    temp_id = None
                    for n in (self.state.nodes_accumulated or []):
                        if isinstance(n, dict) and n.get("label") == "Law":
                            props = n.get("properties") or {}
                            s = (props.get("citation") or props.get("name") or "").strip()
                            if s == sig and isinstance(n.get("temp_id"), str):
                                temp_id = n.get("temp_id")
                                break
                    if isinstance(temp_id, str):
                        created_ids_by_index[idx] = temp_id
                        continue
                temp_id = f"n{next_idx}"
                next_idx += 1
                self.state.nodes_accumulated.append({"temp_id": temp_id, "label": "Law", "properties": clean_props})
                created_ids_by_index[idx] = temp_id
                if sig:
                    existing_signatures.add(sig)

            # Create Argument -> Law edges
            rel_label_arg_law = get_relationship_label_for_edge("Argument", "Law", self.state.rels_by_label or {})
            if not rel_label_arg_law:
                logger.warning("Phase 6: No relationship found in schema for Argument -> Law")
                return {"status": "phase6_skipped"}
            
            existing_edges = {(e.get("from"), e.get("to"), e.get("label")) for e in (self.state.edges_accumulated or []) if isinstance(e, dict)}
            for m in arg_map_list:
                if not isinstance(m, dict):
                    continue
                a_id = m.get("argument_temp_id")
                l_index = m.get("law_index")
                if not (isinstance(a_id, str) and isinstance(l_index, int)):
                    continue
                l_id = created_ids_by_index.get(l_index)
                if not isinstance(l_id, str):
                    continue
                key = (a_id, l_id, rel_label_arg_law)
                if key not in existing_edges:
                    self.state.edges_accumulated.append({"from": a_id, "to": l_id, "label": rel_label_arg_law, "properties": {}})
                    existing_edges.add(key)

            try:
                nodes_after = len(self.state.nodes_accumulated or [])
                edges_after = len(self.state.edges_accumulated or [])
                logger.info(f"Phase 6: completed (nodes_added={max(0, nodes_after - nodes_before)}, edges_added={max(0, edges_after - edges_before)})")
            except Exception:
                logger.info("Phase 6: law assignment completed")
            
            # No end-of-phase progress callback; start-of-phase announces in-progress
            
            return {"status": "phase6_done"}
        except Exception as e:
            logger.warning(f"Phase 6: law assignment failed: {e}")
            return {"status": "phase6_skipped"}

    @listen(phase6_assign_laws)
    def phase7_assign_relief_types(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 7: select ReliefType(s) based on Ruling and create Ruling->ReliefType edges
        logger.info("Phase 7: assigning ReliefTypes per Ruling")
        if self.state.progress_callback:
            try:
                self.state.progress_callback("Phase 7 in progress: Assigning relief types", "phase7", 70)
            except Exception as e:
                logger.warning(f"Failed to publish progress: {e}")
        try:
            from .crews.case_crew.case_crew_v3 import CaseCrew as _CaseCrew
            # Build catalog for ReliefType
            catalogs: Dict[str, List[Dict[str, Any]]] = {}
            for lbl in ["ReliefType"]:
                rows = (self.state.existing_catalog_by_label or {}).get(lbl) or []
                entries: List[Dict[str, Any]] = []
                props_meta = (self.state.props_meta_by_label or {}).get(lbl) or {}
                allowed_keys = [k for k in props_meta.keys() if isinstance(k, str)]
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    entry: Dict[str, Any] = {}
                    for k in allowed_keys:
                        if r.get(k) is not None:
                            v = r.get(k)
                            try:
                                entry[k] = v if isinstance(v, (int, float, bool)) else str(v)
                            except Exception:
                                entry[k] = str(v)
                    for k, v in r.items():
                        if isinstance(k, str) and k.endswith("_id") and v is not None:
                            try:
                                entry[k] = v if isinstance(v, (int, float, bool)) else str(v)
                            except Exception:
                                entry[k] = str(v)
                    if entry:
                        entries.append(entry)
                catalogs[lbl] = entries

            # Extract Ruling properties
            rulings = [n for n in (self.state.nodes_accumulated or []) if isinstance(n, dict) and n.get("label") == "Ruling"]
            ruling_props = (rulings[0].get("properties") if rulings and isinstance(rulings[0].get("properties"), dict) else {})

            crew_sel = _CaseCrew(
                self.state.file_path,
                self.state.filename,
                self.state.case_id,
                tools=[],
                replacements={
                    "RULING_JSON": json.dumps(ruling_props, ensure_ascii=False),
                    "CASE_TEXT": self.state.document_text or "",
                    "CATALOGS_JSON": json.dumps(catalogs, ensure_ascii=False),
                },
            )
            task_sel = crew_sel.phase5_select_existing_task()
            single_crew_sel = Crew(
                agents=[crew_sel.phase5_select_existing_agent()],
                tasks=[task_sel],
                process=Process.sequential,
            )
            edges_before = len(self.state.edges_accumulated or [])
            nodes_before = len(self.state.nodes_accumulated or [])
            result_sel = single_crew_sel.kickoff()
            selected: Dict[str, List[str]] = {}
            try:
                text = str(result_sel)
                data = json.loads(text) if isinstance(result_sel, str) else (result_sel if isinstance(result_sel, dict) else json.loads(str(result_sel)))
                sel = data.get("selected") if isinstance(data, dict) else None
                if isinstance(sel, dict):
                    for k, v in sel.items():
                        if isinstance(k, str) and isinstance(v, list):
                            selected[k] = [str(x) for x in v]
            except Exception:
                selected = {}

            # Create selected ReliefType nodes by ID lookup
            next_idx = 1 + len(self.state.nodes_accumulated or [])
            for lbl in ["ReliefType"]:
                relief_type_ids = selected.get(lbl) or []
                props_meta = (self.state.props_meta_by_label or {}).get(lbl, {})
                allowed_keys = [k for k in (props_meta.keys() if isinstance(props_meta, dict) else []) if isinstance(k, str)]
                catalog_rows = catalogs.get(lbl, [])
                
                # Lookup catalog entry by relief_type_id
                def find_catalog_by_id(relief_type_id: str) -> Dict[str, Any] | None:
                    for row in catalog_rows:
                        if isinstance(row, dict) and str(row.get("relief_type_id")) == str(relief_type_id):
                            return row
                    return None
                
                for relief_type_id in relief_type_ids:
                    entry = find_catalog_by_id(relief_type_id)
                    if not entry:
                        logger.warning(f"Phase 7: ReliefType ID '{relief_type_id}' not found in catalog; skipping (can_create_new=false)")
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

            # Create edges: Ruling → ReliefType
            try:
                def find_first_temp_id(label: str) -> Optional[str]:
                    for n in (self.state.nodes_accumulated or []):
                        if isinstance(n, dict) and n.get("label") == label and isinstance(n.get("temp_id"), str):
                            return n.get("temp_id")
                    return None
                
                def find_all_temp_ids(label: str) -> List[str]:
                    return [n.get("temp_id") for n in (self.state.nodes_accumulated or []) 
                            if isinstance(n, dict) and n.get("label") == label and isinstance(n.get("temp_id"), str)]

                ruling_ids = find_all_temp_ids("Ruling")
                relief_type_ids = find_all_temp_ids("ReliefType")

                rel_ruling_relief = get_relationship_label_for_edge("Ruling", "ReliefType", self.state.rels_by_label or {})
                
                if rel_ruling_relief and ruling_ids and relief_type_ids:
                    existing_edges = {(e.get("from"), e.get("to"), e.get("label")) for e in (self.state.edges_accumulated or []) if isinstance(e, dict)}
                    # Create edges from each Ruling to each selected ReliefType
                    for r_id in ruling_ids:
                        for rt_id in relief_type_ids:
                            key = (r_id, rt_id, rel_ruling_relief)
                            if key not in existing_edges:
                                self.state.edges_accumulated.append({"from": r_id, "to": rt_id, "label": rel_ruling_relief, "properties": {}})
                                existing_edges.add(key)
                    logger.info(f"Phase 7: Created edges Ruling → ReliefType ({rel_ruling_relief})")
            except Exception as e:
                logger.warning(f"Phase 7: Failed to create edges: {e}")

            try:
                nodes_after = len(self.state.nodes_accumulated or [])
                edges_after = len(self.state.edges_accumulated or [])
                logger.info(f"Phase 7: completed (nodes_added={max(0, nodes_after - nodes_before)}, edges_added={max(0, edges_after - edges_before)})")
            except Exception:
                logger.info("Phase 7: ReliefType assignment completed")
            
            return {"status": "phase7_done"}
        except Exception as e:
            logger.warning(f"Phase 7: ReliefType assignment failed: {e}")
            return {"status": "phase7_skipped"}

    @listen(phase7_assign_relief_types)
    def phase8_validate_and_repair(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 8: Quick validation mode: just return the data without deep validation
        # The flow phases already enforce schema rules, so validation is mainly for catching edge cases
        import os
        skip_validation = os.getenv("SKIP_CASE_VALIDATION", "false").lower() in ("true", "1", "yes")
        
        if skip_validation:
            logger.info("Phase 8 (Validation): skipped (SKIP_CASE_VALIDATION=true)")
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

        # Fallback if state doesn't expose mapping (Flow state is BaseModel; use previous ctx return pattern)
        if not models_by_label or not rels_by_label or not props_meta_by_label:
            return {"case_name": self.state.filename, "nodes": self.state.nodes_accumulated or [], "edges": self.state.edges_accumulated or []}

        logger.info("Phase 8 (Validation): starting")
        
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
        )
        
        # Log validation results
        if errors:
            logger.warning(f"Phase 8 (Validation): found {len(errors)} errors")
            logger.warning(f"Phase 8 (Validation): first 5 errors: {errors[:5]}")
            logger.info(f"Validation: cleaned output has {len(cleaned.get('nodes', []))} nodes, {len(cleaned.get('edges', []))} edges")
        
        if not errors:
            try:
                logger.info(f"Validation: passed (nodes={len(cleaned.get('nodes', []))}, edges={len(cleaned.get('edges', []))})")
            except Exception:
                logger.info("Phase 8 (Validation): passed with no errors")
            return cleaned

        # Return cleaned output with validation errors logged
        # Note: LLM repair was removed because it was slow (~5min) and removed all edges
        logger.warning(f"Phase 8 (Validation): returning cleaned output with {len(errors)} errors, {len(cleaned.get('edges', []))} edges retained")
        return cleaned
