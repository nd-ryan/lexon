"""Utility to filter out hidden properties from case data before sending to frontend."""

import re
from typing import Any, Dict, List, Optional
from app.lib.schema_runtime import load_schema_payload


def prepare_for_postgres_save(data: Dict[str, Any]) -> Dict[str, Any]:
    """Apply all cleanup rules for Postgres storage.
    
    Strips embeddings and catalog nodes before saving to ensure consistent
    storage rules. This is the single source of truth for what gets saved.
    
    Args:
        data: Case graph data with nodes and edges
        
    Returns:
        Cleaned data ready for Postgres storage
    """
    cleaned = strip_embeddings(data)
    cleaned = strip_catalog_nodes(cleaned)
    return cleaned


def _is_hidden_property(name: str, meta: Dict[str, Any]) -> bool:
    """Check if a property should be hidden from the frontend."""
    # Always preserve *_id fields for catalog referential integrity
    if name.endswith("_id"):
        return False
    
    ui = meta.get("ui", {}) or {}
    if ui.get("hidden") is True:
        return True
    
    # Also hide embedding fields
    if name.endswith("_embedding") or name.endswith("_embeddings") or "embedding" in name:
        return True
    
    return False


def _is_existing_node(node: Dict[str, Any]) -> bool:
    """Check if a node is an existing catalog node by looking for UUID properties.
    
    A node is considered existing if it has any property ending in '_id' 
    with a UUID value (contains hyphens).
    
    Args:
        node: Node dict with {temp_id, label, properties}
        
    Returns:
        True if node has a UUID property indicating it exists in Neo4j
    """
    if not isinstance(node, dict):
        return False
    
    properties = node.get("properties")
    if not isinstance(properties, dict):
        return False
    
    # Check all properties for UUID pattern
    for prop_name, prop_value in properties.items():
        # Look for properties ending in '_id' with UUID values
        if prop_name.endswith('_id') and isinstance(prop_value, str) and '-' in prop_value:
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
    """Filter hidden properties from a single node and order them by schema ui.order.
    
    Args:
        node: Node dict with {temp_id, label, properties}
        schema_payload: The schema array from schema.json
        
    Returns:
        Filtered node dict with properties ordered by schema
    """
    if not isinstance(node, dict):
        return node
    
    # Always preserve temp_id and label
    filtered = {
        "temp_id": node.get("temp_id"),
        "label": node.get("label")
    }
    
    # Mark if this is an existing catalog node (check BEFORE filtering removes UUID properties)
    # Preserve if already set by normalize step
    filtered["is_existing"] = node.get("is_existing", _is_existing_node(node))
    
    # Filter and order properties
    properties = node.get("properties")
    if isinstance(properties, dict):
        label = node.get("label")
        hidden_props = _get_hidden_properties_for_label(label, schema_payload) if label else set()
        schema_props = _get_all_schema_properties_for_label(label, schema_payload) if label else {}
        
        # Filter out hidden properties
        filtered_props = {}
        for prop_name, prop_value in properties.items():
            # Always preserve temp_id even if it appears in properties
            if prop_name == "temp_id" or prop_name not in hidden_props:
                filtered_props[prop_name] = prop_value
        
        # Order properties by schema ui.order
        # Properties with explicit order come first (sorted by order value),
        # then properties without order (sorted alphabetically)
        def get_sort_key(item):
            prop_name, prop_value = item
            meta = schema_props.get(prop_name, {})
            order = _get_property_order(prop_name, meta)
            # Return tuple: (order, prop_name) for stable sort
            return (order, prop_name)
        
        ordered_items = sorted(filtered_props.items(), key=get_sort_key)
        filtered["properties"] = dict(ordered_items)
    
    # Preserve any other top-level fields (like 'related' for catalog nodes)
    for key, value in node.items():
        if key not in ["temp_id", "label", "properties", "is_existing"]:
            filtered[key] = value
    
    return filtered


def _get_property_order(prop_name: str, meta: Dict[str, Any]) -> int:
    """Get the display order for a property from its schema definition.
    
    Args:
        prop_name: The property name
        meta: The property's schema metadata
        
    Returns:
        Integer order value (defaults to 999 for unspecified)
    """
    if not isinstance(meta, dict):
        return 999
    
    ui = meta.get("ui", {}) or {}
    order = ui.get("order")
    
    if isinstance(order, (int, float)):
        return int(order)
    
    return 999


def _get_all_schema_properties_for_label(label: str, schema_payload: Any) -> Dict[str, Any]:
    """Get all non-hidden property definitions for a given node label.
    
    Args:
        label: The node label to check
        schema_payload: The schema array from schema.json
        
    Returns:
        Dict mapping property names to their schema definitions
    """
    if not isinstance(schema_payload, list):
        return {}
    
    # Find the schema definition for this label
    for node_def in schema_payload:
        if node_def.get("label") == label:
            props = node_def.get("properties") or {}
            if isinstance(props, dict):
                # Return only non-hidden properties
                result = {}
                for prop_name, meta in props.items():
                    if not isinstance(prop_name, str) or not isinstance(meta, dict):
                        continue
                    if not _is_hidden_property(prop_name, meta):
                        result[prop_name] = meta
                return result
            break
    
    return {}


def _get_all_relationship_properties(source_label: str, rel_label: str, schema_payload: Any) -> Dict[str, Any]:
    """Get all non-hidden relationship property definitions.
    
    Args:
        source_label: The source node label
        rel_label: The relationship label
        schema_payload: The schema array from schema.json
        
    Returns:
        Dict mapping property names to their schema definitions
    """
    if not isinstance(schema_payload, list):
        return {}
    
    # Find the schema definition for the source label
    for node_def in schema_payload:
        if node_def.get("label") == source_label:
            relationships = node_def.get("relationships") or {}
            if isinstance(relationships, dict):
                rel_def = relationships.get(rel_label)
                if isinstance(rel_def, dict):
                    rel_props = rel_def.get("properties") or {}
                    if isinstance(rel_props, dict):
                        # Return only non-hidden properties
                        result = {}
                        for prop_name, meta in rel_props.items():
                            if not isinstance(prop_name, str) or not isinstance(meta, dict):
                                continue
                            if not _is_hidden_property(prop_name, meta):
                                result[prop_name] = meta
                        return result
            break
    
    return {}


def normalize_node_with_schema(node: Dict[str, Any], schema_payload: Any) -> Dict[str, Any]:
    """Ensure node has all non-hidden schema properties, adding None for missing ones.
    
    Args:
        node: Node dict with {temp_id, label, properties}
        schema_payload: The schema array from schema.json
        
    Returns:
        Node with all schema properties present
    """
    if not isinstance(node, dict):
        return node
    
    label = node.get("label")
    if not label:
        return node
    
    # Get all non-hidden properties from schema for this label
    schema_props = _get_all_schema_properties_for_label(label, schema_payload)
    
    # Start with existing properties
    existing_props = node.get("properties") or {}
    normalized_props = dict(existing_props)
    
    # Add missing schema properties with None value
    for prop_name in schema_props.keys():
        if prop_name not in normalized_props:
            normalized_props[prop_name] = None
    
    # Create normalized node
    result = dict(node)
    result["properties"] = normalized_props
    
    # Mark if this is an existing catalog node (check BEFORE filtering removes UUID properties)
    # Preserve existing flag if already set, otherwise compute from UUID properties
    if "is_existing" in node and isinstance(node.get("is_existing"), bool):
        result["is_existing"] = node["is_existing"]
    else:
        result["is_existing"] = _is_existing_node(node)
    
    return result


def normalize_edge_with_schema(edge: Dict[str, Any], nodes_by_id: Dict[str, str], schema_payload: Any) -> Dict[str, Any]:
    """Ensure edge has all non-hidden schema relationship properties, adding None for missing ones.
    
    Args:
        edge: Edge dict with {from, to, label, properties}
        nodes_by_id: Mapping of temp_id to node label
        schema_payload: The schema array from schema.json
        
    Returns:
        Edge with all schema properties present
    """
    if not isinstance(edge, dict):
        return edge
    
    source_id = edge.get("from")
    rel_label = edge.get("label")
    
    if not source_id or not rel_label:
        return edge
    
    # Get source node label
    source_label = nodes_by_id.get(source_id)
    if not source_label:
        return edge
    
    # Get all non-hidden relationship properties from schema
    schema_props = _get_all_relationship_properties(source_label, rel_label, schema_payload)
    
    if not schema_props:
        return edge
    
    # Start with existing properties
    existing_props = edge.get("properties") or {}
    normalized_props = dict(existing_props)
    
    # Add missing schema properties with None value
    for prop_name in schema_props.keys():
        if prop_name not in normalized_props:
            normalized_props[prop_name] = None
    
    # Create normalized edge
    result = dict(edge)
    result["properties"] = normalized_props
    
    return result


# Define catalog-only node types (immutable, Neo4j-only)
CATALOG_ONLY_NODES = {'ReliefType', 'Forum', 'Jurisdiction', 'Domain'}


def strip_embeddings(case_data: Dict[str, Any]) -> Dict[str, Any]:
    """Remove all embedding fields from case data before Postgres save.
    
    Args:
        case_data: Case data dict with {nodes: [...], edges: [...]}
        
    Returns:
        Case data with embeddings removed
    """
    if not isinstance(case_data, dict):
        return case_data
    
    result = {}
    nodes = case_data.get("nodes", [])
    if isinstance(nodes, list):
        result["nodes"] = [
            {
                **node,
                "properties": {
                    k: v for k, v in (node.get("properties") or {}).items()
                    if not (k.endswith("_embedding") or k.endswith("_embeddings") or "embedding" in k)
                }
            }
            for node in nodes
        ]
    
    # Copy edges and other fields as-is
    for key in case_data:
        if key != "nodes":
            result[key] = case_data[key]
    
    return result


def strip_catalog_nodes(case_data: Dict[str, Any]) -> Dict[str, Any]:
    """Remove catalog-only nodes from case data but preserve edges that reference them.
    
    Catalog nodes are immutable Neo4j entities that should not be stored in Postgres.
    Instead, edges point directly to their Neo4j IDs.
    
    Args:
        case_data: Case data dict with {nodes: [...], edges: [...]}
        
    Returns:
        Case data with catalog nodes removed but edges preserved
    """
    if not isinstance(case_data, dict):
        return case_data
    
    nodes = case_data.get("nodes", [])
    edges = case_data.get("edges", [])
    
    # Filter out catalog nodes
    filtered_nodes = [
        node for node in nodes 
        if node.get("label") not in CATALOG_ONLY_NODES
    ]
    
    # Keep all edges (they may reference catalog node IDs)
    result = {**case_data, "nodes": filtered_nodes, "edges": edges}
    
    return result


def add_temp_ids(case_data: Dict[str, Any]) -> Dict[str, Any]:
    """Add temp_id to nodes by copying from their *_id property.
    
    The temp_id is removed before Neo4j upload to keep the data clean,
    but is needed for Postgres storage and frontend consistency.
    
    Args:
        case_data: Case data dict with {nodes: [...], edges: [...]}
        
    Returns:
        Case data with temp_id added to all nodes
    """
    if not isinstance(case_data, dict):
        return case_data
    
    schema_payload = load_schema_payload()
    nodes = case_data.get("nodes", [])
    
    if not isinstance(nodes, list):
        return case_data
    
    # Add temp_id to each node by copying from its *_id property
    updated_nodes = []
    for node in nodes:
        if not isinstance(node, dict):
            updated_nodes.append(node)
            continue
        
        label = node.get("label")
        props = node.get("properties") or {}
        
        # Get the *_id property name for this label
        if isinstance(label, str) and isinstance(props, dict):
            id_prop = _get_id_prop_for_label(label, schema_payload)
            node_uuid = props.get(id_prop)
            
            # Copy *_id value to temp_id
            if node_uuid:
                node_with_temp_id = {**node, "temp_id": str(node_uuid)}
                updated_nodes.append(node_with_temp_id)
            else:
                updated_nodes.append(node)
        else:
            updated_nodes.append(node)
    
    result = {**case_data, "nodes": updated_nodes}
    return result


def _get_id_prop_for_label(label: str, schema_payload: Any) -> str:
    """Get the *_id property name for a label from schema.
    
    Args:
        label: The node label
        schema_payload: The schema array from schema.json
        
    Returns:
        The *_id property name (e.g., 'case_id', 'law_id', etc.)
    """
    # Convert label to snake_case for default
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", label).lower()
    preferred = f"{snake}_id"
    
    if isinstance(schema_payload, list):
        for node_def in schema_payload:
            if not isinstance(node_def, dict):
                continue
            if node_def.get("label") != label:
                continue
            props = node_def.get("properties") or {}
            if isinstance(props, dict):
                # exact preferred
                if preferred in props:
                    return preferred
                # any *_id
                for pname in props.keys():
                    if isinstance(pname, str) and pname.endswith("_id"):
                        return pname
    return preferred


def filter_case_data(case_data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize and filter case data: add missing schema properties and remove hidden ones.
    
    Args:
        case_data: Case data dict with {nodes: [...], edges: [...]}
        
    Returns:
        Normalized and filtered case data
    """
    schema_payload = load_schema_payload()
    
    filtered = {}
    
    # First, normalize and filter nodes
    nodes = case_data.get("nodes")
    if isinstance(nodes, list):
        # Normalize: add missing schema properties
        normalized_nodes = [
            normalize_node_with_schema(node, schema_payload)
            for node in nodes
        ]
        # Then filter: remove hidden properties
        filtered["nodes"] = [
            filter_node_properties(node, schema_payload)
            for node in normalized_nodes
        ]
    
    # Create mapping of node temp_id to label for edge processing
    nodes_by_id = {}
    if isinstance(nodes, list):
        for node in nodes:
            if isinstance(node, dict):
                temp_id = node.get("temp_id")
                label = node.get("label")
                if temp_id and label:
                    nodes_by_id[temp_id] = label
    
    # Normalize and filter edges
    edges = case_data.get("edges")
    if isinstance(edges, list):
        filtered["edges"] = [
            normalize_edge_with_schema(edge, nodes_by_id, schema_payload)
            for edge in edges
        ]
    
    # Preserve any other top-level fields
    for key, value in case_data.items():
        if key not in ["nodes", "edges"]:
            filtered[key] = value
    
    return filtered


def filter_display_data(display_data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize and filter structured display data.
    
    This recursively processes nested structures to add missing schema properties
    and remove hidden properties from all nodes while preserving the structure.
    
    Args:
        display_data: Structured display data from case_view_builder
        
    Returns:
        Normalized and filtered display data
    """
    schema_payload = load_schema_payload()
    
    def filter_recursive(obj: Any) -> Any:
        """Recursively normalize and filter nodes in nested structures."""
        if isinstance(obj, dict):
            # Check if this is a node (has temp_id and label)
            if "temp_id" in obj and "label" in obj:
                # First normalize (add missing schema properties)
                normalized = normalize_node_with_schema(obj, schema_payload)
                # Then filter (remove hidden properties)
                return filter_node_properties(normalized, schema_payload)
            
            # Otherwise recursively process dict values
            return {key: filter_recursive(value) for key, value in obj.items()}
        
        elif isinstance(obj, list):
            return [filter_recursive(item) for item in obj]
        
        else:
            return obj
    
    return filter_recursive(display_data)

