"""
Utility functions for building batch queries for enriched node data retrieval.
Uses static property mappings file updated by document imports.

Display strategy for relationship target text:
- Prefer name_properties (from property_mappings.json)
- Fallback to per-label overrides (from display_overrides.json)
- Finally fallback to id_properties
"""
import json
import os
from typing import Dict, List

# Path to static files
PROPERTY_MAPPINGS_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "property_mappings.json")
DISPLAY_OVERRIDES_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "display_overrides.json")

def load_property_mappings() -> Dict[str, List[str]]:
    """
    Load property mappings from static file.
    
    Returns:
        Dict with 'id_properties' and 'name_properties' lists
    """
    try:
        if os.path.exists(PROPERTY_MAPPINGS_FILE):
            with open(PROPERTY_MAPPINGS_FILE, 'r') as f:
                mappings = json.load(f)
                return mappings
    except Exception as e:
        print(f"Warning: Could not load property mappings from {PROPERTY_MAPPINGS_FILE}: {e}")
    
    # Return default mappings if file doesn't exist or loading fails
    return {
        "id_properties": ["id", "case_id", "party_id", "law_id", "citation", "forum_id", 
                         "document_id", "doctrine_id", "relief_id", "issue_id", "fact_id", 
                         "fact_pattern_id", "jurisdiction_id"],
        "name_properties": ["name", "case_name", "party_name", "law_name", "forum_name", 
                           "fact_pattern_name", "doctrine_name", "relief_description", 
                           "issue_text", "description", "fact_description", "argument_text"]
    }

def load_display_overrides() -> Dict[str, any]:
    """Load display overrides configuration from static file.

    Expected structure:
    {
      "label_display_properties": { "Label": "propName" | ["p1", "p2"] }
    }
    """
    try:
        if os.path.exists(DISPLAY_OVERRIDES_FILE):
            with open(DISPLAY_OVERRIDES_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Warning: Could not load display overrides from {DISPLAY_OVERRIDES_FILE}: {e}")
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
    # Load property mappings from static file
    mappings = load_property_mappings()
    overrides = load_display_overrides()
    id_properties = mappings.get("id_properties", [])
    name_properties = mappings.get("name_properties", [])
    
    # Convert id_values to a properly formatted Cypher list
    values_str = "[" + ", ".join([f"'{val}'" for val in id_values]) + "]"
    
    # Build coalesce expressions dynamically from static property lists for neighbor node `m`
    if id_properties:
        id_coalesce_m = "coalesce(" + ", ".join([f"m.{prop}" for prop in id_properties]) + ")"
    else:
        id_coalesce_m = "m.id"

    if name_properties:
        name_coalesce_m = "coalesce(" + ", ".join([f"m.{prop}" for prop in name_properties]) + ")"
    else:
        name_coalesce_m = "m.name"

    # Build per-label override expression and incorporate into fallback chain
    override_expr_m = build_label_based_override_expression("m", overrides)

    return f"""
    MATCH (n:{label})
    WHERE n.{id_field} IN {values_str}
    WITH n,
         [(n)-[r]-(m) | {{
           type: type(r),
           direction: CASE WHEN startNode(r) = n THEN 'out' ELSE 'in' END,
           target_label: head(labels(m)),
           target_id: {id_coalesce_m},
           target_name: coalesce({name_coalesce_m}, {override_expr_m}, {id_coalesce_m})
         }}] AS rels
    RETURN n {{ .*, node_label: head(labels(n)), relationships: rels }}
    """

def get_property_mappings_info() -> Dict[str, any]:
    """Get information about current property mappings from static file."""
    mappings = load_property_mappings()
    return {
        "id_properties_count": len(mappings.get("id_properties", [])),
        "name_properties_count": len(mappings.get("name_properties", [])),
        "last_updated": mappings.get("last_updated", "unknown"),
        "total_properties": mappings.get("total_properties", 0),
        "schema_source": mappings.get("schema_source", "unknown"),
        "file_exists": os.path.exists(PROPERTY_MAPPINGS_FILE),
        "file_path": PROPERTY_MAPPINGS_FILE
    } 

def build_single_node_enrichment_query(label: str, id_value: str) -> str:
    """
    Build a query to retrieve a single node by trying the configured id properties
    against the provided id_value, and return enriched data with relationships.
    """
    mappings = load_property_mappings()
    overrides = load_display_overrides()
    id_properties = mappings.get("id_properties", [])
    name_properties = mappings.get("name_properties", [])

    safe_value = str(id_value).replace("'", "\\'")

    if id_properties:
        where_clause = " OR ".join([f"n.{prop} = '{safe_value}'" for prop in id_properties])
    else:
        where_clause = f"n.id = '{safe_value}'"

    if id_properties:
        id_coalesce_m = "coalesce(" + ", ".join([f"m.{prop}" for prop in id_properties]) + ")"
    else:
        id_coalesce_m = "m.id"

    if name_properties:
        name_coalesce_m = "coalesce(" + ", ".join([f"m.{prop}" for prop in name_properties]) + ")"
    else:
        name_coalesce_m = "m.name"

    override_expr_m = build_label_based_override_expression("m", overrides)

    return f"""
    MATCH (n:{label})
    WHERE {where_clause}
    WITH n,
         [(n)-[r]-(m) | {{
           type: type(r),
           direction: CASE WHEN startNode(r) = n THEN 'out' ELSE 'in' END,
           target_label: head(labels(m)),
           target_id: {id_coalesce_m},
           target_name: coalesce({name_coalesce_m}, {override_expr_m}, {id_coalesce_m})
         }}] AS rels
    RETURN n {{ .*, node_label: head(labels(n)), relationships: rels }}
    """