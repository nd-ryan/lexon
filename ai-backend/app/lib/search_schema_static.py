"""
Helpers for deriving a Neo4j schema description from the static schema_v3.json
in the same shape as the schema returned by the Neo4j MCP server.

This is used by the SearchFlow so it can operate without depending on MCP
for schema loading, while preserving the structure the search agents expect:

[
  {
    "label": "Case",
    "attributes": {
      "name": "STRING",
      "citation": "STRING",
      ...
    },
    "relationships": {
      "HAS_PROCEEDING": "Proceeding",
      ...
    }
  },
  ...
]
"""

from typing import Any, Dict, List

from app.lib.schema_runtime import load_schema_payload


def derive_mcp_style_schema_from_static() -> List[Dict[str, Any]]:
    """
    Build an MCP-style schema list from the local schema_v3.json file.

    Shape:
      [
        {
          "label": str,
          "attributes": { prop_name: TYPE_STRING },
          "relationships": { rel_label: target_label }
        },
        ...
      ]

    Notes:
    - Includes *all* properties defined in schema_v3.json, including hidden,
      *_id, *_upload_code, and embedding fields. This mirrors the MCP schema,
      which exposes raw database properties without UI pruning.
    - Relationship targets are normalized so both simple string and
      object-with-target formats are supported.
    """
    payload = load_schema_payload()
    result: List[Dict[str, Any]] = []

    if not isinstance(payload, list):
        return result

    for node_def in payload:
        if not isinstance(node_def, dict):
            continue

        label = node_def.get("label")
        if not isinstance(label, str) or not label.strip():
            continue

        # Attributes: prop_name -> TYPE (STRING/INTEGER/BOOLEAN/LIST/DATE/...)
        attributes: Dict[str, str] = {}
        props = node_def.get("properties") or {}
        if isinstance(props, dict):
            for prop_name, meta in props.items():
                if not isinstance(prop_name, str):
                    continue
                if isinstance(meta, dict):
                    ptype = str(meta.get("type", "STRING")).upper()
                else:
                    ptype = "STRING"
                attributes[prop_name] = ptype

        # Relationships: rel_label -> target_label
        relationships: Dict[str, str] = {}
        rels_map = node_def.get("relationships") or {}
        if isinstance(rels_map, dict):
            for rel_label, target_spec in rels_map.items():
                if not isinstance(rel_label, str) or not rel_label.strip():
                    continue

                if isinstance(target_spec, str):
                    target_label = target_spec
                elif isinstance(target_spec, dict):
                    target_label = target_spec.get("target")
                else:
                    target_label = None

                if isinstance(target_label, str) and target_label.strip():
                    relationships[rel_label] = target_label

        result.append(
            {
                "label": label,
                "attributes": attributes,
                "relationships": relationships,
            }
        )

    return result


