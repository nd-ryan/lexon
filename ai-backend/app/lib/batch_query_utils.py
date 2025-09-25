"""
Utility functions for building batch queries for enriched node data retrieval.

Minimal strategy:
- Use id properties derived from schema.json (any property ending with "_id")
- Use only m.name for display title (no fallback chain)
"""
import json
import os
from typing import Dict, List

DISPLAY_OVERRIDES_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "display_overrides.json")

def _load_simple_mappings() -> Dict[str, List[str]]:
    from app.lib.schema_runtime import derive_simple_mappings_from_schema
    return derive_simple_mappings_from_schema()

def load_display_overrides() -> Dict[str, any]:
    """Derive display overrides from schema.json."""
    try:
        from app.lib.schema_runtime import derive_display_overrides_from_schema
        return derive_display_overrides_from_schema()
    except Exception as e:
        print(f"Warning: Could not derive display overrides from schema.json: {e}")
        return {}

def build_label_based_override_expression(node_alias: str, overrides_config: Dict[str, any]) -> str:
    """Build a Cypher CASE expression that picks a property based on the node label.

    If multiple properties are configured for a label, they are wrapped in coalesce(...).
    Returns 'NULL' if no overrides are configured.
    """
    label_map = (overrides_config or {}).get("label_display_properties", {}) or {}
    cases: List[str] = []
    for label, props in label_map.items():
        if isinstance(props, list):
            valid_props = [p for p in props if isinstance(p, str) and p]
            if not valid_props:
                continue
            prop_expr = "coalesce(" + ", ".join([f"{node_alias}.{p}" for p in valid_props]) + ")"
        elif isinstance(props, str) and props:
            prop_expr = f"{node_alias}.{props}"
        else:
            continue
        cases.append(f"WHEN '{label}' THEN {prop_expr}")
    if not cases:
        return "NULL"
    return f"CASE head(labels({node_alias})) " + " ".join(cases) + " ELSE NULL END"

def build_batch_query(label: str, id_field: str, id_values: list) -> str:
    """
    Build a batch query to get enriched data for nodes of a specific label.
    Uses static property mappings file to build coalesce expressions.
    
    Args:
        label: The Neo4j node label
        id_field: The field name used as the identifier
        id_values: List of identifier values to query for
        
    Returns:
        str: A Cypher query string for batch retrieval of enriched node data
    """
    # Load minimal mappings from schema.json
    mappings = _load_simple_mappings()
    id_properties = mappings.get("id_properties", [])
    
    # Convert id_values to a properly formatted Cypher list
    values_str = "[" + ", ".join([f"'{val}'" for val in id_values]) + "]"
    
    # Build expressions for neighbor node `m`
    id_coalesce_m = "coalesce(" + ", ".join([f"m.{prop}" for prop in id_properties]) + ")" if id_properties else "m.id"
    name_expr_m = "m.name"

    return f"""
    MATCH (n:{label})
    WHERE n.{id_field} IN {values_str}
    WITH n,
         [(n)-[r]-(m) | {{
           type: type(r),
           direction: CASE WHEN startNode(r) = n THEN 'out' ELSE 'in' END,
           target_label: head(labels(m)),
           target_id: {id_coalesce_m},
           target_name: {name_expr_m}
         }}] AS rels
    RETURN n {{ .*, node_label: head(labels(n)), relationships: rels }}
    """

def get_property_mappings_info() -> Dict[str, any]:
    """Get basic information about current property mappings derived from schema.json."""
    mappings = _load_simple_mappings()
    return {
        "id_properties_count": len(mappings.get("id_properties", [])),
        "name_properties_count": len(mappings.get("name_properties", [])),
        "schema_source": "schema.json",
    } 

def build_single_node_enrichment_query(label: str, id_value: str) -> str:
    """
    Build a query to retrieve a single node by trying the configured id properties
    against the provided id_value, and return enriched data with relationships.
    """
    mappings = _load_simple_mappings()
    id_properties = mappings.get("id_properties", [])

    safe_value = str(id_value).replace("'", "\\'")

    if id_properties:
        where_clause = " OR ".join([f"n.{prop} = '{safe_value}'" for prop in id_properties])
    else:
        where_clause = f"n.id = '{safe_value}'"

    id_coalesce_m = "coalesce(" + ", ".join([f"m.{prop}" for prop in id_properties]) + ")" if id_properties else "m.id"
    name_expr_m = "m.name"

    return f"""
    MATCH (n:{label})
    WHERE {where_clause}
    WITH n,
         [(n)-[r]-(m) | {{
           type: type(r),
           direction: CASE WHEN startNode(r) = n THEN 'out' ELSE 'in' END,
           target_label: head(labels(m)),
           target_id: {id_coalesce_m},
           target_name: {name_expr_m}
         }}] AS rels
    RETURN n {{ .*, node_label: head(labels(n)), relationships: rels }}
    """