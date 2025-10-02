"""Helper utilities for writing data to Neo4j with proper type conversion."""

from typing import Dict, Any, List
from app.lib.schema_runtime import convert_properties_for_neo4j, build_property_models, prune_ui_schema_for_llm


def prepare_nodes_for_neo4j(nodes: List[Dict[str, Any]], schema_payload: Any) -> List[Dict[str, Any]]:
    """Convert a list of nodes to Neo4j-compatible format.
    
    Handles date conversion and other type transformations.
    
    Args:
        nodes: List of node dicts with {label, temp_id, properties}
        schema_payload: The full schema from fetch_neo4j_schema() or schema.json
        
    Returns:
        List of nodes with properties converted for Neo4j
    """
    # Build property metadata from schema
    spec = prune_ui_schema_for_llm(schema_payload) if schema_payload is not None else {"labels": []}
    _, _, props_meta_by_label, _ = build_property_models(spec)
    
    converted_nodes = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        
        label = node.get("label")
        properties = node.get("properties", {})
        
        if isinstance(label, str) and isinstance(properties, dict):
            # Convert properties (e.g., DATE strings to Neo4j Date objects)
            converted_props = convert_properties_for_neo4j(
                properties,
                label,
                props_meta_by_label
            )
            
            # Create new node dict with converted properties
            converted_node = dict(node)
            converted_node["properties"] = converted_props
            converted_nodes.append(converted_node)
        else:
            converted_nodes.append(node)
    
    return converted_nodes


def convert_node_properties(
    label: str,
    properties: Dict[str, Any],
    props_meta_by_label: Dict[str, Dict[str, Dict[str, Any]]]
) -> Dict[str, Any]:
    """Convenience wrapper for convert_properties_for_neo4j.
    
    Use this when you already have props_meta_by_label loaded.
    """
    return convert_properties_for_neo4j(properties, label, props_meta_by_label)

