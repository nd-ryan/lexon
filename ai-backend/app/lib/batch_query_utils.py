"""
Utility functions for building batch queries for enriched node data retrieval.
Uses static property mappings file updated by document imports.
"""
import json
import os
from typing import Dict, List

# Path to static property mappings file
PROPERTY_MAPPINGS_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "property_mappings.json")

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
    id_properties = mappings.get("id_properties", [])
    name_properties = mappings.get("name_properties", [])
    
    # Convert id_values to a properly formatted Cypher list
    values_str = "[" + ", ".join([f"'{val}'" for val in id_values]) + "]"
    
    # Build coalesce expressions dynamically from static property lists
    if id_properties:
        id_coalesce = "coalesce(" + ", ".join([f"m1.{prop}" for prop in id_properties]) + ")"
        id_coalesce_incoming = "coalesce(" + ", ".join([f"m2.{prop}" for prop in id_properties]) + ")"
    else:
        id_coalesce = "m1.id"
        id_coalesce_incoming = "m2.id"
    
    if name_properties:
        name_coalesce = "coalesce(" + ", ".join([f"m1.{prop}" for prop in name_properties]) + ")"
        name_coalesce_incoming = "coalesce(" + ", ".join([f"m2.{prop}" for prop in name_properties]) + ")"
    else:
        name_coalesce = "m1.name"
        name_coalesce_incoming = "m2.name"
    
    return f"""
    MATCH (n:{label})
    WHERE n.{id_field} IN {values_str}
    OPTIONAL MATCH (n)-[r1]->(m1)
    WITH n, collect({{
      type: type(r1),
      target_label: labels(m1)[0],
      target_id: {id_coalesce},
      target_name: {name_coalesce}
    }}) AS outgoing
    OPTIONAL MATCH (m2)-[r2]->(n)
    WITH n, outgoing, collect({{
      type: type(r2),
      target_label: labels(m2)[0],
      target_id: {id_coalesce_incoming},
      target_name: {name_coalesce_incoming}
    }}) AS incoming
    RETURN n {{ .*, relationships: outgoing + incoming }}
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