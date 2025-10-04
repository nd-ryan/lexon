"""Utility to filter out hidden properties from case data before sending to frontend."""

from typing import Any, Dict, List, Optional
from app.lib.schema_runtime import load_schema_payload


def _is_hidden_property(name: str, meta: Dict[str, Any]) -> bool:
    """Check if a property should be hidden from the frontend."""
    ui = meta.get("ui", {}) or {}
    if ui.get("hidden") is True:
        return True
    # Also hide embedding fields
    if name.endswith("_embedding") or name.endswith("_embeddings") or "embedding" in name:
        return True
    return False


def _get_hidden_properties_for_label(label: str, schema_payload: Any) -> set[str]:
    """Get the set of hidden property names for a given node label.
    
    Args:
        label: The node label to check
        schema_payload: The schema array from schema.json
        
    Returns:
        Set of property names that should be hidden
    """
    hidden_props = set()
    
    if not isinstance(schema_payload, list):
        return hidden_props
    
    # Find the schema definition for this label
    for node_def in schema_payload:
        if node_def.get("label") == label:
            props = node_def.get("properties") or {}
            if isinstance(props, dict):
                for prop_name, meta in props.items():
                    if not isinstance(prop_name, str) or not isinstance(meta, dict):
                        continue
                    if _is_hidden_property(prop_name, meta):
                        hidden_props.add(prop_name)
            break
    
    return hidden_props


def filter_node_properties(node: Dict[str, Any], schema_payload: Any) -> Dict[str, Any]:
    """Filter hidden properties from a single node while preserving temp_id.
    
    Args:
        node: Node dict with {temp_id, label, properties}
        schema_payload: The schema array from schema.json
        
    Returns:
        Filtered node dict
    """
    if not isinstance(node, dict):
        return node
    
    # Always preserve temp_id and label
    filtered = {
        "temp_id": node.get("temp_id"),
        "label": node.get("label")
    }
    
    # Filter properties
    properties = node.get("properties")
    if isinstance(properties, dict):
        label = node.get("label")
        hidden_props = _get_hidden_properties_for_label(label, schema_payload) if label else set()
        
        # Filter out hidden properties
        filtered_props = {}
        for prop_name, prop_value in properties.items():
            # Always preserve temp_id even if it appears in properties
            if prop_name == "temp_id" or prop_name not in hidden_props:
                filtered_props[prop_name] = prop_value
        
        filtered["properties"] = filtered_props
    
    # Preserve any other top-level fields (like 'related' for catalog nodes)
    for key, value in node.items():
        if key not in ["temp_id", "label", "properties"]:
            filtered[key] = value
    
    return filtered


def filter_case_data(case_data: Dict[str, Any]) -> Dict[str, Any]:
    """Filter hidden properties from case data (nodes and edges).
    
    Args:
        case_data: Case data dict with {nodes: [...], edges: [...]}
        
    Returns:
        Filtered case data with hidden properties removed
    """
    schema_payload = load_schema_payload()
    
    filtered = {}
    
    # Filter nodes
    nodes = case_data.get("nodes")
    if isinstance(nodes, list):
        filtered["nodes"] = [
            filter_node_properties(node, schema_payload)
            for node in nodes
        ]
    
    # Edges don't contain properties that need filtering (just from/to/label)
    # but we'll copy them through for completeness
    edges = case_data.get("edges")
    if isinstance(edges, list):
        filtered["edges"] = edges
    
    # Preserve any other top-level fields
    for key, value in case_data.items():
        if key not in ["nodes", "edges"]:
            filtered[key] = value
    
    return filtered


def filter_display_data(display_data: Dict[str, Any]) -> Dict[str, Any]:
    """Filter hidden properties from structured display data.
    
    This recursively processes nested structures to remove hidden properties
    from all nodes while preserving the structure.
    
    Args:
        display_data: Structured display data from case_view_builder
        
    Returns:
        Filtered display data
    """
    schema_payload = load_schema_payload()
    
    def filter_recursive(obj: Any) -> Any:
        """Recursively filter nodes in nested structures."""
        if isinstance(obj, dict):
            # Check if this is a node (has temp_id and label)
            if "temp_id" in obj and "label" in obj:
                return filter_node_properties(obj, schema_payload)
            
            # Otherwise recursively process dict values
            return {key: filter_recursive(value) for key, value in obj.items()}
        
        elif isinstance(obj, list):
            return [filter_recursive(item) for item in obj]
        
        else:
            return obj
    
    return filter_recursive(display_data)

