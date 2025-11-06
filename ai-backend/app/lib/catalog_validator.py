"""Validation for catalog node IDs to prevent tampering."""

from typing import Dict, Any, List, Tuple
from app.lib.neo4j_client import neo4j_client
from app.lib.logging_config import setup_logger

logger = setup_logger("catalog-validator")

# Labels where can_create_new=false (must reference catalog)
CATALOG_ONLY_LABELS = {"Forum", "Jurisdiction", "ReliefType", "Domain"}

# Map label names to their ID property names (for compound names)
ID_PROPERTY_MAP = {
    'ReliefType': 'relief_type_id',
    'FactPattern': 'fact_pattern_id',
}


def validate_catalog_ids(nodes: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    """
    Validate that catalog node IDs exist in Neo4j and match expected labels.
    
    Args:
        nodes: List of node dictionaries with {temp_id, label, properties}
        
    Returns:
        Tuple of (is_valid, error_messages)
    """
    errors = []
    
    for node in nodes:
        if not isinstance(node, dict):
            continue
            
        label = node.get("label")
        if not label or label not in CATALOG_ONLY_LABELS:
            continue
        
        properties = node.get("properties") or {}
        # Handle compound label names (ReliefType → relief_type_id)
        id_field = ID_PROPERTY_MAP.get(label, f"{label.lower()}_id")
        node_id = properties.get(id_field)
        
        if not node_id:
            errors.append(f"{label} node missing required {id_field}")
            continue
        
        # Verify ID exists in Neo4j with matching label
        try:
            query = f"MATCH (n:`{label}` {{{id_field}: $id}}) RETURN count(n) as cnt"
            result = neo4j_client.execute_query(query, {"id": node_id})
            count = result[0].get("cnt", 0) if result else 0
            
            if count == 0:
                errors.append(f"Invalid {id_field}='{node_id}' - not found in catalog")
        except Exception as e:
            logger.warning(f"Failed to validate {label} ID {node_id}: {e}")
            errors.append(f"Could not validate {label} catalog reference")
    
    return len(errors) == 0, errors

