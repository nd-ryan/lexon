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


DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
def load_schema_payload() -> Any:
    """Load the static schema.json payload from the project root ai-backend directory.

    Returns the parsed JSON content, or raises on failure.
    """
    base_dir = os.path.join(os.path.dirname(__file__), "..", "..")
    path = os.path.abspath(os.path.join(base_dir, "schema.json"))
    with open(path, "r") as f:
        return json.load(f)


def derive_simple_mappings_from_schema() -> Dict[str, List[str]]:
    """Return minimal mappings derived from schema.json.

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
                allowed_types = {"STRING", "INTEGER", "BOOLEAN", "LIST"}
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
        rels: Dict[str, str] = {}
        if isinstance(relationships_map, dict):
            for rel_label, target_label in relationships_map.items():
                if isinstance(rel_label, str) and isinstance(target_label, str):
                    rels[rel_label] = target_label

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

            ptype = str(p.get("type", "STRING")).upper()
            required = bool(p.get("required", False))
            options = p.get("options")
            fmt = p.get("format")

            # Base type mapping
            py_type: Any
            if ptype == "INTEGER":
                py_type = int
            elif ptype == "BOOLEAN":
                py_type = bool
            elif ptype == "LIST":
                py_type = List[str]
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
        relationships_by_label[label] = label_def.get("relationships", {}) or {}
        properties_meta_by_label[label] = properties_meta
        # Capture flags; defaults if not present
        label_flags_by_label[label] = {
            "case_unique": bool(label_def.get("case_unique", False)),
            "can_create_new": bool(label_def.get("can_create_new", True)),
            "ai_ignore": bool(label_def.get("ai_ignore", False)),
        }

    return models_by_label, relationships_by_label, properties_meta_by_label, label_flags_by_label


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

    cleaned_edges: List[Dict[str, Any]] = []
    for idx, edge in enumerate(edges):
        if not isinstance(edge, dict):
            errors.append(f"edge[{idx}] is not an object")
            continue
        src = edge.get("from") or edge.get("from_")
        dst = edge.get("to")
        elabel = edge.get("label")
        eprops = edge.get("properties") or {}

        if not isinstance(src, str) or src not in id_to_label:
            errors.append(f"edge[{idx}] from references unknown node '{src}'")
            continue
        if not isinstance(dst, str) or dst not in id_to_label:
            errors.append(f"edge[{idx}] to references unknown node '{dst}'")
            continue
        if not isinstance(elabel, str):
            errors.append(f"edge[{idx}] label must be a string")
            continue

        src_label = id_to_label[src]
        dst_label = id_to_label[dst]
        allowed = relationships_by_label.get(src_label, {})
        expected_target = allowed.get(elabel)
        if expected_target is None:
            errors.append(f"edge[{idx}] label '{elabel}' not allowed for source label '{src_label}'")
            continue
        if expected_target != dst_label:
            errors.append(
                f"edge[{idx}] label '{elabel}' expects target '{expected_target}', got '{dst_label}'"
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
    """Render a compact, LLM-friendly text for inclusion in prompts."""
    parts: List[str] = []
    for label_def in spec.get("labels", []):
        label = label_def.get("label")
        parts.append(f"Label: {label}")
        props_lines: List[str] = []
        for p in label_def.get("properties", []):
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
        if rels:
            rel_lines = [f"  - {k} -> {v}" for k, v in rels.items()]
            parts.append(" Relationships:\n" + "\n".join(rel_lines))
        parts.append("")
    return "\n".join(parts).strip()


