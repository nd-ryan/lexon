from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Type
from pydantic import BaseModel, create_model
try:
    # Pydantic v2
    from pydantic import ConfigDict  # type: ignore
except Exception:  # pragma: no cover
    ConfigDict = None  # type: ignore
import re
import json
import os
from datetime import date as python_date


DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
def load_schema_payload() -> Any:
    """Load the static schema_v3.json payload from the project root ai-backend directory.

    Returns the parsed JSON content, or raises on failure.
    """
    import logging
    logger = logging.getLogger(__name__)
    base_dir = os.path.join(os.path.dirname(__file__), "..", "..")
    path = os.path.abspath(os.path.join(base_dir, "schema_v3.json"))
    logger.info(f"Loading schema from: {path}")
    with open(path, "r") as f:
        data = json.load(f)
    logger.info(f"Loaded schema with {len(data) if isinstance(data, list) else 0} node definitions")
    return data


def derive_all_vector_index_names_from_schema(
    preferred_labels: Optional[List[str]] = None,
) -> Dict[str, Dict[str, str]]:
    """Derive Neo4j vector index names for *all* embedding properties from schema_v3.json.

    The naming pattern follows the DDL in presets_vector_indices.txt:

      <label_lower>_<embedding_property_name>_index

    For each label, we:
      - Collect all properties whose name ends with "_embedding".
      - For each such property, emit a vector index name using the pattern above.

    Args:
        preferred_labels: Optional list of labels to restrict the labels considered.
                          If None, all labels present in the schema are considered.

    Returns:
        Dict[label, Dict[embedding_property_name, index_name]]
    """
    payload = load_schema_payload()
    result: Dict[str, Dict[str, str]] = {}

    if not isinstance(payload, list):
        return result

    for node_def in payload:
        label = node_def.get("label")
        if not isinstance(label, str) or label.strip() == "":
            continue
        if preferred_labels is not None and label not in preferred_labels:
            continue

        props = node_def.get("properties") or {}
        if not isinstance(props, dict):
            continue

        for prop_name, meta in props.items():
            if not isinstance(prop_name, str):
                continue
            if not isinstance(meta, dict):
                continue
            if not prop_name.endswith("_embedding"):
                continue
            
            # User requested to exclude indices for "name" or "label" properties
            # The property name is "name_embedding" or "label_embedding"
            text_prop = prop_name[:-10] # remove "_embedding"
            if text_prop in ("name", "label"):
                continue

            index_name = f"{label.lower()}_{prop_name}_index"
            if label not in result:
                result[label] = {}
            result[label][prop_name] = index_name

    return result


def derive_primary_vector_index_names_from_schema(
    preferred_labels: Optional[List[str]] = None,
) -> Dict[str, str]:
    """Derive a single "primary" vector index name per label from schema_v3.json.

    This is a convenience for components (like query flows) that only need one
    embedding index per label. It is built on top of
    derive_all_vector_index_names_from_schema and uses the following priority
    order when multiple embedding properties exist:

      1. summary_embedding
      2. description_embedding
      3. text_embedding
      4. name_embedding
      5. else: the first embedding property in sorted order.

    Returns:
        Dict[label, index_name]
    """
    all_indices = derive_all_vector_index_names_from_schema(preferred_labels)
    result: Dict[str, str] = {}

    priority_order = [
        "summary_embedding",
        "description_embedding",
        "text_embedding",
        "name_embedding",
    ]

    for label, prop_map in all_indices.items():
        chosen_prop: Optional[str] = None
        for candidate in priority_order:
            if candidate in prop_map:
                chosen_prop = candidate
                break
        if chosen_prop is None:
            # Fallback: deterministic but arbitrary choice
            chosen_prop = sorted(prop_map.keys())[0]

        result[label] = prop_map[chosen_prop]

    return result


def derive_simple_mappings_from_schema() -> Dict[str, List[str]]:
    """Return minimal mappings derived from schema_v3.json.

    - id_properties: union of all property names across labels that end with "_id"
    - name_properties: ["name"] only
    """
    payload = load_schema_payload()
    id_set: set[str] = set()

    if isinstance(payload, list):
        for node_def in payload:
            props = node_def.get("properties") or {}
            if isinstance(props, dict):
                for prop_name in props.keys():
                    if isinstance(prop_name, str) and prop_name.endswith("_id"):
                        id_set.add(prop_name)

    return {
        "id_properties": sorted(id_set),
        "name_properties": ["name"],
    }


def derive_relationship_constraints_from_schema() -> Dict[str, List[str]]:
    """Build a mapping of allowed relationship types between labels from schema.json.

    Returns a dict keyed by "SourceLabel->TargetLabel" with value = sorted list of
    relationship type strings (e.g., ["RELATES_TO", "HAS_PARTY"]).
    """
    payload = load_schema_payload()
    constraints: Dict[str, List[str]] = {}

    if not isinstance(payload, list):
        return constraints

    for node_def in payload:
        src_label = node_def.get("label")
        if not isinstance(src_label, str) or src_label.strip() == "":
            continue
        relationships_map = node_def.get("relationships", {}) or {}
        if not isinstance(relationships_map, dict):
            continue
        for rel_label, target_spec in relationships_map.items():
            if not isinstance(rel_label, str) or rel_label.strip() == "":
                continue
            # target can be a string label or an object like { "target": "Label", ... }
            if isinstance(target_spec, str):
                dst_label = target_spec
            elif isinstance(target_spec, dict):
                dst_label = target_spec.get("target")
            else:
                dst_label = None
            if not isinstance(dst_label, str) or dst_label.strip() == "":
                continue

            key = f"{src_label}->{dst_label}"
            existing = constraints.get(key) or []
            if rel_label not in existing:
                existing.append(rel_label)
            constraints[key] = existing

    # sort lists for stability
    for k, v in list(constraints.items()):
        constraints[k] = sorted(v)

    return constraints


def get_relationship_label_for_edge(source_label: str, target_label: str, relationships_by_label: Dict[str, Dict[str, str]]) -> Optional[str]:
    """Get the correct relationship label for a source->target edge from schema.
    
    Args:
        source_label: The label of the source node
        target_label: The label of the target node
        relationships_by_label: Mapping of label -> {rel_label: target_label}
    
    Returns:
        The relationship label if found, None otherwise
    """
    source_rels = relationships_by_label.get(source_label, {})
    for rel_label, tgt in source_rels.items():
        if tgt == target_label:
            return rel_label
    return None


def get_all_assigned_relationship_labels(relationships_by_label: Dict[str, Dict[str, str]], exclude_sources: Optional[List[str]] = None) -> set[str]:
    """Get all relationship labels that are explicitly assigned in earlier phases.
    
    This is used to build exclusion lists for Phase 4+ to avoid re-assigning
    relationships that were already created in earlier phases.
    
    Args:
        relationships_by_label: Mapping of label -> {rel_label: target_label}
        exclude_sources: Optional list of source labels to limit the search
    
    Returns:
        Set of relationship labels that are manually assigned in earlier phases
    """
    # These are assigned in specific phases with special logic:
    # Phase 2: RELIES_ON_FACT (Argument -> Fact)
    # Phase 3: SUPPORTED_BY_* (Fact -> Witness/Evidence/JudicialNotice)
    # Phase 6: RELIES_ON_LAW (Argument -> Law)
    assigned_rels: set[str] = set()
    
    # Get RELIES_ON_FACT from Argument
    arg_rels = relationships_by_label.get("Argument", {})
    for rel_label in arg_rels:
        if rel_label in {"RELIES_ON_FACT", "RELIES_ON_LAW"}:
            assigned_rels.add(rel_label)
    
    # Get SUPPORTED_BY_* from Fact
    fact_rels = relationships_by_label.get("Fact", {})
    for rel_label in fact_rels:
        if rel_label.startswith("SUPPORTED_BY_"):
            assigned_rels.add(rel_label)
    
    return assigned_rels


def derive_embedding_config_from_schema() -> Dict[str, List[str]]:
    """Derive which STRING properties should have embeddings per label from schema.json.

    Rule: For each label, include property `p` if:
      - `p` exists with type STRING; and
      - a corresponding property named `p + "_embedding"` exists in the schema (any type).

    Returns { label: [prop_name, ...] }
    """
    payload = load_schema_payload()
    config: Dict[str, List[str]] = {}
    if not isinstance(payload, list):
        return config

    for node_def in payload:
        label = node_def.get("label")
        if not isinstance(label, str) or label.strip() == "":
            continue
        props = node_def.get("properties") or {}
        if not isinstance(props, dict):
            continue
        props_lower = {str(k): v for k, v in props.items() if isinstance(k, str)}
        targets: List[str] = []
        for prop_name, meta in props_lower.items():
            if not isinstance(meta, dict):
                continue
            if prop_name.endswith("_embedding"):
                continue
            ptype = str(meta.get("type", "STRING")).upper()
            if ptype != "STRING":
                continue
            emb_key = f"{prop_name}_embedding"
            if emb_key in props_lower:
                targets.append(prop_name)
        if targets:
            config[label] = sorted(set(targets))

    return config


def derive_display_overrides_from_schema() -> Dict[str, Any]:
    """Derive a lightweight display overrides structure from schema.json.

    Shape matches what the frontend expects minimally:
    {
      "node_card": {
        "Label": {
          "properties": ["prop1", ...],    # non-hidden, non-embedding properties
          "relationships": ["REL", ...]     # outgoing relationship labels from schema
        }
      }
    }
    """
    payload = load_schema_payload()
    node_card: Dict[str, Dict[str, List[str]]] = {}

    if not isinstance(payload, list):
        return {"node_card": node_card}

    for node_def in payload:
        label = node_def.get("label")
        if not isinstance(label, str) or label.strip() == "":
            continue
        props = node_def.get("properties") or {}
        relationships_map = node_def.get("relationships", {}) or {}

        # properties: include those not hidden and not *_embedding
        prop_list: List[str] = []
        if isinstance(props, dict):
            for prop_name, meta in props.items():
                if not isinstance(prop_name, str):
                    continue
                if not isinstance(meta, dict):
                    continue
                if _is_hidden_property(prop_name, meta):
                    continue
                prop_list.append(prop_name)

        # relationships: keys of the relationships map (outgoing rel types)
        rel_list: List[str] = []
        if isinstance(relationships_map, dict):
            for rel_label, target in relationships_map.items():
                if isinstance(rel_label, str) and rel_label.strip():
                    rel_list.append(rel_label)

        node_card[label] = {
            "properties": prop_list,
            "relationships": rel_list,
        }

    return {"node_card": node_card}


def _is_hidden_property(name: str, meta: Dict[str, Any]) -> bool:
    ui = meta.get("ui", {}) or {}
    if ui.get("hidden") is True:
        return True
    # Heuristic: drop embedding fields from LLM spec
    if name.endswith("_embedding") or name.endswith("_embeddings") or "embedding" in name:
        return True
    return False


def prune_ui_schema_for_llm(schema_payload: Any) -> Dict[str, Any]:
    """Prune rich UI schema into a compact LLM extraction spec.

    Input is expected to be a list of node definitions with keys:
      - label: str
      - properties: dict[str, { type: STRING|INTEGER|BOOLEAN|LIST, ui?: {...} }]
      - relationships: dict[str, str]  # relationship -> target_label

    Returns a dict with per-label property constraints and relationships.
    """
    labels: List[Dict[str, Any]] = []
    if not isinstance(schema_payload, list):
        return {"labels": []}

    for node_def in schema_payload:
        label = node_def.get("label")
        if not isinstance(label, str) or label.strip() == "":
            continue
        # Flags from source schema
        case_unique = bool(node_def.get("case_unique", False))
        can_create_new = bool(node_def.get("can_create_new", True))
        ai_ignore = bool(node_def.get("ai_ignore", False))

        properties_spec: List[Dict[str, Any]] = []
        props = node_def.get("properties", {}) or {}
        if isinstance(props, dict):
            for prop_name, meta in props.items():
                if not isinstance(prop_name, str):
                    continue
                if not isinstance(meta, dict):
                    continue
                # Skip AI-ignored properties entirely
                if bool(meta.get("ai_ignore", False)):
                    continue
                if _is_hidden_property(prop_name, meta):
                    continue

                ui = meta.get("ui", {}) or {}
                prop_type = str(meta.get("type", "STRING")).upper()
                allowed_types = {"STRING", "INTEGER", "BOOLEAN", "LIST", "DATE"}
                if prop_type not in allowed_types:
                    prop_type = "STRING"

                entry: Dict[str, Any] = {
                    "name": prop_name,
                    "type": prop_type,
                    "required": bool(ui.get("required", False)),
                }

                options = ui.get("options")
                if isinstance(options, list) and len(options) > 0:
                    entry["options"] = options

                ui_input = ui.get("input")
                if ui_input == "date":
                    entry["format"] = "YYYY-MM-DD"

                properties_spec.append(entry)

        relationships_map = node_def.get("relationships", {}) or {}
        rels: Dict[str, Any] = {}
        if isinstance(relationships_map, dict):
            for rel_label, rel_def in relationships_map.items():
                if not isinstance(rel_label, str):
                    continue
                # Handle both string format and object format with properties
                if isinstance(rel_def, str):
                    # Simple format: "INVOLVES": "Party"
                    rels[rel_label] = rel_def
                elif isinstance(rel_def, dict):
                    # Object format: "INVOLVES": {"target": "Party", "properties": {...}}
                    target = rel_def.get("target")
                    if isinstance(target, str):
                        # Preserve the full object format including properties schema
                        rels[rel_label] = rel_def

        entry = {
            "label": label,
            "properties": properties_spec,
            "relationships": rels,
            # Propagate flags for downstream logic
            "case_unique": case_unique,
            "can_create_new": can_create_new,
            "ai_ignore": ai_ignore,
        }
        labels.append(entry)

    return {"labels": labels}


def build_property_models(spec: Dict[str, Any]) -> Tuple[Dict[str, Type[BaseModel]], Dict[str, Dict[str, str]], Dict[str, Dict[str, Dict[str, Any]]], Dict[str, Dict[str, bool]]]:
    """Create Pydantic models per label for node.properties and return:
    - models_by_label: { label: PydanticModel }
    - relationships_by_label: { label: { rel_label: target_label } }
    - properties_meta_by_label: { label: { prop_name: {required, type, options, format?} } }
    """
    models_by_label: Dict[str, Type[BaseModel]] = {}
    relationships_by_label: Dict[str, Dict[str, str]] = {}
    properties_meta_by_label: Dict[str, Dict[str, Dict[str, Any]]] = {}
    label_flags_by_label: Dict[str, Dict[str, bool]] = {}

    labels = spec.get("labels", []) if isinstance(spec, dict) else []
    for label_def in labels:
        label = label_def.get("label")
        if not isinstance(label, str):
            continue

        fields: Dict[str, Tuple[Any, Any]] = {}
        properties_meta: Dict[str, Dict[str, Any]] = {}

        for p in label_def.get("properties", []) or []:
            if not isinstance(p, dict):
                continue
            name = p.get("name")
            if not isinstance(name, str):
                continue
            
            # Skip hidden properties - they're system-generated and shouldn't be in AI prompts
            ui_meta = p.get("ui")
            if isinstance(ui_meta, dict) and ui_meta.get("hidden") is True:
                continue

            ptype = str(p.get("type", "STRING")).upper()
            required = bool(p.get("required", False))
            options = p.get("options")
            fmt = p.get("format")

            # Base type mapping
            py_type: Any
            if ptype == "INTEGER":
                py_type = int
            elif ptype == "FLOAT":
                py_type = float
            elif ptype == "BOOLEAN":
                py_type = bool
            elif ptype == "LIST":
                py_type = List[str]
            elif ptype == "DATE":
                # Date stored as YYYY-MM-DD string in Python/Pydantic
                # Will be converted to Neo4j Date when writing to database
                py_type = str
            else:
                py_type = str

            # Enum constraint if options provided
            if isinstance(options, list) and len(options) > 0:
                try:
                    from typing import Literal  # type: ignore
                    # type: ignore[misc]
                    py_type = Literal[tuple(options)]  # noqa: F821
                except Exception:
                    pass  # fallback to base type

            default = ... if required else None
            if not required:
                from typing import Optional as TypingOptional
                py_type = TypingOptional[py_type]

            fields[name] = (py_type, default)
            properties_meta[name] = {
                "required": required,
                "type": ptype,
                "options": options,
                "format": fmt,
            }

        # Create the model; ignore unknown properties so we can drop them
        if ConfigDict is not None:
            # Pydantic v2: use model_config via base class
            class _IgnoreExtraBase(BaseModel):  # type: ignore[misc,valid-type]
                model_config = ConfigDict(extra="ignore")  # type: ignore[assignment]

            model = create_model(  # type: ignore[call-arg]
                f"{label}PropertiesModel",
                __base__=_IgnoreExtraBase,
                **fields,
            )
        else:
            # Pydantic v1 fallback: keep old style
            model = create_model(  # type: ignore[call-arg]
                f"{label}PropertiesModel",
                __base__=BaseModel,
                __config__=type("Config", (), {"extra": "ignore"}),
                **fields,
            )

        models_by_label[label] = model
        
        # Extract relationship targets (handle both string and object formats)
        rels_raw = label_def.get("relationships", {}) or {}
        rels_mapped: Dict[str, str] = {}
        for rel_label, rel_def in rels_raw.items():
            if isinstance(rel_def, str):
                # Old format: "INVOLVES": "Party"
                rels_mapped[rel_label] = rel_def
            elif isinstance(rel_def, dict):
                # New format: "INVOLVES": {"target": "Party", "properties": {...}}
                target = rel_def.get("target")
                if isinstance(target, str):
                    rels_mapped[rel_label] = target
        relationships_by_label[label] = rels_mapped
        
        properties_meta_by_label[label] = properties_meta
        # Capture flags; defaults if not present
        label_flags_by_label[label] = {
            "case_unique": bool(label_def.get("case_unique", False)),
            "can_create_new": bool(label_def.get("can_create_new", True)),
            "ai_ignore": bool(label_def.get("ai_ignore", False)),
        }

    return models_by_label, relationships_by_label, properties_meta_by_label, label_flags_by_label


def convert_properties_for_neo4j(
    properties: Dict[str, Any],
    label: str,
    properties_meta_by_label: Dict[str, Dict[str, Dict[str, Any]]]
) -> Dict[str, Any]:
    """Convert property values to Neo4j-compatible types.
    
    Specifically handles:
    - DATE type: converts "YYYY-MM-DD" strings to neo4j.time.Date objects
    
    Args:
        properties: Dictionary of property key-value pairs
        label: Node label to determine which properties to convert
        properties_meta_by_label: Metadata about properties including types
        
    Returns:
        Dictionary with converted values ready for Neo4j
    """
    try:
        from neo4j.time import Date as Neo4jDate
    except ImportError:
        # If neo4j driver not available, return as-is
        return properties
    
    meta = properties_meta_by_label.get(label, {})
    converted = dict(properties)  # shallow copy
    
    for prop_name, value in properties.items():
        prop_meta = meta.get(prop_name, {})
        prop_type = prop_meta.get("type", "").upper()
        
        # Convert DATE type strings to Neo4j Date objects
        if prop_type == "DATE" and isinstance(value, str):
            # Validate format YYYY-MM-DD
            if DATE_REGEX.match(value):
                try:
                    # Parse string and create Neo4j Date
                    year, month, day = value.split("-")
                    converted[prop_name] = Neo4jDate(int(year), int(month), int(day))
                except Exception:
                    # Keep as string if conversion fails
                    pass
    
    return converted


def validate_case_graph(
    payload: Dict[str, Any],
    models_by_label: Dict[str, Type[BaseModel]],
    relationships_by_label: Dict[str, Dict[str, str]],
    properties_meta_by_label: Dict[str, Dict[str, Dict[str, Any]]],
    label_flags_by_label: Optional[Dict[str, Dict[str, bool]]] = None,
    existing_catalog_by_label: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """Validate and coerce a CaseGraph-like payload.

    - Validates node properties per label model (drops unknowns, enforces required and type)
    - Enforces date format YYYY-MM-DD where specified
    - Enforces enums where configured (via model type)
    - Validates edges: label allowed for source label and target label matches expected
    Returns (cleaned_payload, errors)
    """
    errors: List[str] = []

    case_name = payload.get("case_name")
    if not isinstance(case_name, str) or case_name.strip() == "":
        errors.append("case_name must be a non-empty string")

    nodes = payload.get("nodes") or []
    edges = payload.get("edges") or []
    if not isinstance(nodes, list):
        errors.append("nodes must be a list")
        nodes = []
    if not isinstance(edges, list):
        errors.append("edges must be a list")
        edges = []

    cleaned_nodes: List[Dict[str, Any]] = []
    id_to_label: Dict[str, str] = {}

    for idx, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"node[{idx}] is not an object")
            continue
        temp_id = node.get("temp_id")
        label = node.get("label")
        props = node.get("properties") or {}

        if not isinstance(temp_id, str) or temp_id.strip() == "":
            errors.append(f"node[{idx}] temp_id missing or not a string")
            continue
        if not isinstance(label, str) or label not in models_by_label:
            errors.append(f"node[{idx}] label '{label}' is not recognized")
            continue
        # Enforce ai_ignore at label level: drop and record error
        flags = (label_flags_by_label or {}).get(label, {})
        if bool(flags.get("ai_ignore", False)):
            errors.append(f"node[{idx}] label '{label}' is ai_ignore and must not be created")
            continue
        if not isinstance(props, dict):
            errors.append(f"node[{idx}] properties must be an object")
            props = {}
        
        # Unwrap 'raw' field if present (CrewAI sometimes wraps structured output)
        if isinstance(props, dict) and len(props) == 1 and "raw" in props:
            try:
                raw_val = props.get("raw")
                if isinstance(raw_val, str):
                    props = json.loads(raw_val)
                    errors.append(f"node[{idx}] properties were wrapped in 'raw' field (unwrapped)")
            except Exception as e:
                errors.append(f"node[{idx}] failed to unwrap 'raw' field: {e}")

        model = models_by_label[label]
        try:
            model_instance = model(**props)
            coerced = model_instance.model_dump(exclude_none=True)
        except Exception as e:  # pydantic ValidationError
            errors.append(f"node[{idx}] properties validation error: {e}")
            # Attempt best-effort: drop invalid by using only fields present and correct type where possible
            coerced = {}
            for field_name, field_meta in properties_meta_by_label.get(label, {}).items():
                if field_name in props:
                    coerced[field_name] = props[field_name]

        # Preserve hidden identifier fields like *_id if present in original props
        try:
            for original_key, original_val in (props or {}).items():
                if isinstance(original_key, str) and original_key.endswith("_id") and original_val is not None:
                    # Cast to string for stability
                    try:
                        coerced[original_key] = str(original_val)
                    except Exception:
                        coerced[original_key] = original_val
        except Exception:
            pass

        # Additional format checks (e.g., date)
        for pname, pmeta in properties_meta_by_label.get(label, {}).items():
            if pmeta.get("format") == "YYYY-MM-DD" and pname in coerced:
                val = coerced.get(pname)
                if not (isinstance(val, str) and DATE_REGEX.match(val)):
                    errors.append(f"node[{idx}].properties.{pname} must match YYYY-MM-DD")

        # Enforce can_create_new=False labels must match an existing catalog when provided
        if flags.get("can_create_new") is False and existing_catalog_by_label:
            catalog = existing_catalog_by_label.get(label) or []
            if catalog:
                # Identifier selection heuristic: prefer 'name', else 'label', else any required string field present
                name_val = coerced.get("name")
                if name_val is None:
                    # try another required field for id
                    for pname, pmeta in properties_meta_by_label.get(label, {}).items():
                        if pmeta.get("type") == "STRING" and pmeta.get("required") and pname in coerced:
                            name_val = coerced.get(pname)
                            break
                catalog_names = set()
                for entry in catalog:
                    if isinstance(entry, dict):
                        if entry.get("name") is not None:
                            catalog_names.add(str(entry.get("name")))
                        # also include any required string field value for robustness
                        for pname, pmeta in properties_meta_by_label.get(label, {}).items():
                            if pmeta.get("type") == "STRING" and pmeta.get("required") and entry.get(pname) is not None:
                                catalog_names.add(str(entry.get(pname)))
                if not (isinstance(name_val, str) and str(name_val) in catalog_names):
                    errors.append(f"node[{idx}] label '{label}' must reference an existing node; got '{name_val}'.")

        cleaned_nodes.append({
            "temp_id": temp_id,
            "label": label,
            "properties": coerced,
        })
        id_to_label[temp_id] = label

    # Helper to check if an ID is a catalog node ID (UUID format)
    def is_catalog_node_id(node_id: str) -> bool:
        """Check if the ID looks like a Neo4j catalog node ID (contains hyphens like a UUID)."""
        return isinstance(node_id, str) and '-' in node_id and len(node_id) >= 32
    
    cleaned_edges: List[Dict[str, Any]] = []
    for idx, edge in enumerate(edges):
        if not isinstance(edge, dict):
            errors.append(f"edge[{idx}] is not an object")
            continue
        src = edge.get("from") or edge.get("from_")
        dst = edge.get("to")
        elabel = edge.get("label")
        eprops = edge.get("properties") or {}

        # Validate source: must be either in nodes array OR a catalog node ID
        if not isinstance(src, str):
            errors.append(f"edge[{idx}] from must be a string")
            continue
        src_is_catalog = is_catalog_node_id(src)
        if not src_is_catalog and src not in id_to_label:
            errors.append(f"edge[{idx}] from references unknown node '{src}'")
            continue
            
        # Validate destination: must be either in nodes array OR a catalog node ID
        if not isinstance(dst, str):
            errors.append(f"edge[{idx}] to must be a string")
            continue
        dst_is_catalog = is_catalog_node_id(dst)
        if not dst_is_catalog and dst not in id_to_label:
            errors.append(f"edge[{idx}] to references unknown node '{dst}'")
            continue
            
        if not isinstance(elabel, str):
            errors.append(f"edge[{idx}] label must be a string")
            continue

        # Get source label (skip validation if it's a catalog node ID)
        src_label = id_to_label.get(src) if not src_is_catalog else None
        dst_label = id_to_label.get(dst) if not dst_is_catalog else None
        
        # Only validate relationship if source is not a catalog node
        if src_label:
            allowed = relationships_by_label.get(src_label, {})
            expected_target = allowed.get(elabel)
            if expected_target is None:
                # Log available relationships for debugging
                available_rels = list(allowed.keys()) if allowed else []
                errors.append(f"edge[{idx}] label '{elabel}' not allowed for source label '{src_label}' (available: {available_rels[:5]})")
                continue
            
            # Handle both string and dict format for expected_target
            expected_target_label = expected_target
            if isinstance(expected_target, dict):
                expected_target_label = expected_target.get("target")
            
            # Only check target label match if destination is not a catalog node
            if dst_label and expected_target_label != dst_label:
                errors.append(
                    f"edge[{idx}] label '{elabel}' expects target '{expected_target_label}', got '{dst_label}'"
                )
                continue

        if not isinstance(eprops, dict):
            eprops = {}

        cleaned_edges.append({
            "from": src,
            "to": dst,
            "label": elabel,
            "properties": eprops,
        })

    cleaned = {
        "case_name": case_name if isinstance(case_name, str) else "",
        "nodes": cleaned_nodes,
        "edges": cleaned_edges,
    }
    return cleaned, errors


def render_spec_text(spec: Dict[str, Any]) -> str:
    """Render a compact, LLM-friendly text for inclusion in prompts.

    Supports relationship entries as either a simple target string or an object
    with "target" and optional "properties" schema.
    """
    parts: List[str] = []
    for label_def in spec.get("labels", []):
        if not isinstance(label_def, dict):
            continue
        label = label_def.get("label")
        parts.append(f"Label: {label}")
        props_lines: List[str] = []
        for p in label_def.get("properties", []):
            if not isinstance(p, dict):
                continue
            if not isinstance(p.get("name"), str) or not isinstance(p.get("type"), str):
                continue
            line = f"  - {p['name']}: {p['type']}"
            if p.get("required"):
                line += " (required)"
            if p.get("format"):
                line += f" [format: {p['format']}]"
            if p.get("options"):
                line += f" [one of: {', '.join(map(str, p['options']))}]"
            props_lines.append(line)
        if props_lines:
            parts.append(" Properties:\n" + "\n".join(props_lines))
        rels = label_def.get("relationships", {}) or {}
        if isinstance(rels, dict) and rels:
            rel_section: List[str] = []
            for rel_label, target in rels.items():
                if isinstance(target, dict):
                    tgt = target.get("target")
                    rel_section.append(f"  - {rel_label} -> {tgt}")
                    rprops = target.get("properties") or {}
                    if isinstance(rprops, dict) and rprops:
                        for rp_name, rp_meta in rprops.items():
                            if not isinstance(rp_name, str) or not isinstance(rp_meta, dict):
                                continue
                            # Skip AI-ignored or hidden relationship properties
                            if bool(rp_meta.get("ai_ignore", False)):
                                continue
                            if bool((rp_meta.get("ui", {}) or {}).get("hidden", False)):
                                continue
                            rtype = str(rp_meta.get("type", "STRING")).upper()
                            rreq = bool((rp_meta.get("ui", {}) or {}).get("required", False))
                            line = f"      * {rp_name}: {rtype}"
                            if rreq:
                                line += " (required)"
                            ropts = (rp_meta.get("ui", {}) or {}).get("options")
                            if isinstance(ropts, list) and ropts:
                                line += f" [one of: {', '.join(map(str, ropts))}]"
                            if (rp_meta.get("ui", {}) or {}).get("input") == "date":
                                line += " [format: YYYY-MM-DD]"
                            rel_section.append(line)
                else:
                    rel_section.append(f"  - {rel_label} -> {target}")
            if rel_section:
                parts.append(" Relationships:\n" + "\n".join(rel_section))
        parts.append("")
    return "\n".join(parts).strip()


def build_relationship_property_models(schema_payload: Any) -> Tuple[Dict[Tuple[str, str], Type[BaseModel]], Dict[Tuple[str, str], Dict[str, Dict[str, Any]]]]:
    """Create Pydantic models for relationship properties using full schema payload.

    Returns:
      - models_by_src_rel: { (source_label, rel_label): PydanticModel }
      - meta_by_src_rel:   { (source_label, rel_label): { prop_name: meta } }
    Only relationships with a properties map are included.
    """
    models_by_src_rel: Dict[Tuple[str, str], Type[BaseModel]] = {}
    meta_by_src_rel: Dict[Tuple[str, str], Dict[str, Dict[str, Any]]] = {}

    if not isinstance(schema_payload, list):
        return models_by_src_rel, meta_by_src_rel

    for node_def in schema_payload:
        src_label = node_def.get("label")
        if not isinstance(src_label, str) or not src_label:
            continue
        rels_map = node_def.get("relationships") or {}
        if not isinstance(rels_map, dict):
            continue
        for rel_label, target_spec in rels_map.items():
            if not isinstance(rel_label, str):
                continue
            # Only relationships with explicit properties
            if not isinstance(target_spec, dict):
                continue
            rprops = target_spec.get("properties") or {}
            if not isinstance(rprops, dict) or not rprops:
                continue

            fields: Dict[str, Tuple[Any, Any]] = {}
            meta: Dict[str, Dict[str, Any]] = {}
            for rp_name, rp_meta in rprops.items():
                if not isinstance(rp_name, str) or not isinstance(rp_meta, dict):
                    continue
                # Skip AI-ignored or hidden relationship properties
                if bool(rp_meta.get("ai_ignore", False)):
                    continue
                if bool((rp_meta.get("ui", {}) or {}).get("hidden", False)):
                    continue
                ui = (rp_meta.get("ui", {}) or {})
                rtype = str(rp_meta.get("type", "STRING")).upper()
                required = bool(ui.get("required", False))
                options = ui.get("options")
                # Base type mapping
                py_type: Any
                if rtype == "INTEGER":
                    py_type = int
                elif rtype == "FLOAT":
                    py_type = float
                elif rtype == "BOOLEAN":
                    py_type = bool
                elif rtype == "LIST":
                    py_type = List[str]
                else:
                    py_type = str
                if isinstance(options, list) and options:
                    try:
                        from typing import Literal  # type: ignore
                        py_type = Literal[tuple(options)]  # type: ignore[misc]
                    except Exception:
                        pass
                default = ... if required else None
                if not required:
                    from typing import Optional as TypingOptional
                    py_type = TypingOptional[py_type]
                fields[rp_name] = (py_type, default)
                meta[rp_name] = {"required": required, "type": rtype, "options": options}

            if ConfigDict is not None:
                class _IgnoreExtraBase(BaseModel):  # type: ignore[misc,valid-type]
                    model_config = ConfigDict(extra="ignore")  # type: ignore[assignment]
                model = create_model(  # type: ignore[call-arg]
                    f"{src_label}_{rel_label}_PropertiesModel",
                    __base__=_IgnoreExtraBase,
                    **fields,
                )
            else:
                model = create_model(  # type: ignore[call-arg]
                    f"{src_label}_{rel_label}_PropertiesModel",
                    __base__=BaseModel,
                    __config__=type("Config", (), {"extra": "ignore"}),
                    **fields,
                )
            key = (src_label, rel_label)
            models_by_src_rel[key] = model
            meta_by_src_rel[key] = meta

    return models_by_src_rel, meta_by_src_rel


