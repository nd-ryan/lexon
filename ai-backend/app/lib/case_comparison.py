"""
Compare case data between Postgres and Neo4j.

This module provides reusable comparison logic that can be used:
1. On-demand via the admin Neo4j case view page
2. As a validation step during KG upload

Type handling:
- Neo4j stores dates as neo4j.time.Date objects, which get serialized with internal
  attributes (_Date__year, _Date__month, _Date__day) when converted to JSON/dict.
- Postgres stores dates as ISO strings (YYYY-MM-DD).
- This module normalizes both to ISO strings for fair comparison.

Catalog nodes:
- Certain node types (case_unique=false AND can_create_new=false) are "catalog" nodes.
- These are shared/immutable entries (Domain, Forum, Jurisdiction, ReliefType) that
  exist only in Neo4j - they're intentionally stripped from Postgres to avoid duplication.
- The comparison skips these nodes since the difference is by design, not an error.
"""

import json
import os
from typing import Any, Dict, List, Optional, Set, Tuple
from enum import Enum


def _load_schema() -> List[Dict[str, Any]]:
    """Load the schema from schema_v3.json."""
    schema_path = os.path.join(os.path.dirname(__file__), "..", "..", "schema_v3.json")
    with open(schema_path, "r") as f:
        return json.load(f)


def get_catalog_node_labels(schema: Optional[List[Dict[str, Any]]] = None) -> Set[str]:
    """Get node labels that are catalog-only (not stored in Postgres).
    
    Catalog nodes are defined by:
    - case_unique: false (shared across cases)
    - can_create_new: false (users select from existing, can't create new)
    
    These nodes exist only in Neo4j and are intentionally stripped from Postgres.
    
    Args:
        schema: Optional schema list. If not provided, loads from schema_v3.json.
        
    Returns:
        Set of label strings for catalog-only nodes.
    """
    if schema is None:
        schema = _load_schema()
    
    catalog_labels = set()
    for node_def in schema:
        if not isinstance(node_def, dict):
            continue
        label = node_def.get("label")
        case_unique = node_def.get("case_unique")
        can_create_new = node_def.get("can_create_new")
        
        # Catalog nodes: shared (case_unique=false) AND immutable (can_create_new=false)
        if label and case_unique is False and can_create_new is False:
            catalog_labels.add(label)
    
    return catalog_labels


def get_embedding_config(schema: Optional[List[Dict[str, Any]]] = None) -> Dict[str, List[str]]:
    """Get which properties should have embeddings per label.
    
    Uses the same logic as derive_embedding_config_from_schema() but works with
    a provided schema or loads from file.
    
    Rule: For each label, include property `p` if:
      - `p` exists with type STRING; and
      - a corresponding property named `p + "_embedding"` exists in the schema.
    
    Returns:
        Dict of { label: [prop_name, ...] }
    """
    if schema is None:
        schema = _load_schema()
    
    config: Dict[str, List[str]] = {}
    
    for node_def in schema:
        if not isinstance(node_def, dict):
            continue
        label = node_def.get("label")
        if not isinstance(label, str) or not label.strip():
            continue
        props = node_def.get("properties") or {}
        if not isinstance(props, dict):
            continue
        
        targets: List[str] = []
        for prop_name, meta in props.items():
            if not isinstance(prop_name, str):
                continue
            if not isinstance(meta, dict):
                continue
            if prop_name.endswith("_embedding"):
                continue
            ptype = str(meta.get("type", "STRING")).upper()
            if ptype != "STRING":
                continue
            emb_key = f"{prop_name}_embedding"
            if emb_key in props:
                targets.append(prop_name)
        
        if targets:
            config[label] = sorted(set(targets))
    
    return config


def check_neo4j_embeddings(
    neo4j_client: Any,
    case_nodes: List[Dict[str, Any]],
    schema: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Check which embedding properties are missing in Neo4j for specific case nodes.
    
    Uses Cypher to check for NULL or missing embedding properties without
    returning the actual embedding values (which are very large).
    
    Args:
        neo4j_client: Neo4j client instance with execute_query method
        case_nodes: List of node dicts from the case (with label and properties)
        schema: Optional schema list
        
    Returns:
        Dict with:
        - total_expected: number of embedding fields expected
        - total_present: number of embedding fields that have values
        - missing: list of {node_id, label, property} for missing embeddings
    """
    embedding_config = get_embedding_config(schema)
    
    if not embedding_config:
        return {
            "total_expected": 0,
            "total_present": 0,
            "total_missing": 0,
            "missing": []
        }
    
    # Group nodes by label and collect their IDs
    nodes_by_label: Dict[str, List[str]] = {}
    for node in case_nodes:
        label = node.get("label")
        if not label or label not in embedding_config:
            continue
        
        # Find the node's *_id property
        props = node.get("properties", {})
        node_id = None
        for key, val in props.items():
            if key.endswith("_id") and val:
                node_id = str(val)
                break
        
        if node_id:
            if label not in nodes_by_label:
                nodes_by_label[label] = []
            nodes_by_label[label].append(node_id)
    
    missing_embeddings: List[Dict[str, str]] = []
    total_expected = 0
    total_present = 0
    
    # Check embeddings only for the specific nodes in this case
    for label, node_ids in nodes_by_label.items():
        if not node_ids:
            continue
        
        props_to_check = embedding_config.get(label, [])
        if not props_to_check:
            continue
        
        # Get the ID property name for this label
        id_prop = f"{label.lower()}_id"
        
        # Build Cypher to check each embedding property for these specific nodes
        for prop in props_to_check:
            emb_prop = f"{prop}_embedding"
            
            query = f"""
            MATCH (n:{label})
            WHERE n.{id_prop} IN $nodeIds
            RETURN 
                n.{id_prop} AS node_id,
                n.{emb_prop} IS NOT NULL AS has_embedding
            """
            
            try:
                results = neo4j_client.execute_query(query, {"nodeIds": node_ids})
                for row in results:
                    node_id = row.get("node_id")
                    if node_id is None:
                        continue
                    total_expected += 1
                    if row.get("has_embedding"):
                        total_present += 1
                    else:
                        missing_embeddings.append({
                            "node_id": str(node_id),
                            "label": label,
                            "property": prop
                        })
            except Exception as e:
                # Log but don't fail the comparison
                import logging
                logging.getLogger(__name__).warning(f"Failed to check embeddings for {label}.{prop}: {e}")
    
    return {
        "total_expected": total_expected,
        "total_present": total_present,
        "total_missing": len(missing_embeddings),
        "all_present": len(missing_embeddings) == 0,
        "missing": missing_embeddings
    }


class ComparisonStatus(str, Enum):
    MATCH = "match"
    DIFFER = "differ"
    ONLY_POSTGRES = "only_postgres"
    ONLY_NEO4J = "only_neo4j"


def _is_neo4j_date_dict(value: Any) -> bool:
    """Check if a value is a serialized Neo4j Date object."""
    if not isinstance(value, dict):
        return False
    # Neo4j Date objects serialize with these internal Python attributes
    return "_Date__year" in value and "_Date__month" in value and "_Date__day" in value


def _neo4j_date_dict_to_iso(value: Dict[str, Any]) -> str:
    """Convert a serialized Neo4j Date dict to ISO string (YYYY-MM-DD)."""
    year = value.get("_Date__year", 0)
    month = value.get("_Date__month", 0)
    day = value.get("_Date__day", 0)
    
    # Handle negative day values (Neo4j internal representation quirk)
    # The ordinal is the authoritative value; reconstruct date from it if available
    ordinal = value.get("_Date__ordinal")
    if ordinal is not None:
        try:
            from datetime import date
            d = date.fromordinal(ordinal)
            return d.isoformat()
        except (ValueError, OverflowError):
            pass
    
    # Fallback to direct year/month/day (may be incorrect if day is negative)
    # Clamp day to valid range as a safety measure
    if day < 1:
        day = 1
    if day > 31:
        day = 31
    if month < 1:
        month = 1
    if month > 12:
        month = 12
    
    return f"{year:04d}-{month:02d}-{day:02d}"


def _is_neo4j_time_dict(value: Any) -> bool:
    """Check if a value is a serialized Neo4j Time/DateTime object."""
    if not isinstance(value, dict):
        return False
    # Check for Time attributes
    return "_Time__hour" in value or "_DateTime__year" in value


def _neo4j_time_dict_to_iso(value: Dict[str, Any]) -> str:
    """Convert a serialized Neo4j Time/DateTime dict to ISO string."""
    # DateTime
    if "_DateTime__year" in value:
        year = value.get("_DateTime__year", 0)
        month = value.get("_DateTime__month", 1)
        day = value.get("_DateTime__day", 1)
        hour = value.get("_DateTime__hour", 0)
        minute = value.get("_DateTime__minute", 0)
        second = value.get("_DateTime__second", 0)
        return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}"
    
    # Time only
    if "_Time__hour" in value:
        hour = value.get("_Time__hour", 0)
        minute = value.get("_Time__minute", 0)
        second = value.get("_Time__second", 0)
        return f"{hour:02d}:{minute:02d}:{second:02d}"
    
    return str(value)


def _normalize_value(value: Any) -> Any:
    """Normalize a value for comparison.
    
    Handles:
    - None and empty strings -> None
    - Neo4j Date dicts -> ISO date strings
    - Neo4j Time/DateTime dicts -> ISO time strings
    - Embedding arrays -> placeholder
    - Nested dicts/lists -> recursive normalization
    """
    if value is None:
        return None
    
    if isinstance(value, str):
        # Treat empty strings as None for comparison
        stripped = value.strip()
        return stripped if stripped else None
    
    if isinstance(value, dict):
        # Check for Neo4j Date serialization
        if _is_neo4j_date_dict(value):
            return _neo4j_date_dict_to_iso(value)
        
        # Check for Neo4j Time/DateTime serialization
        if _is_neo4j_time_dict(value):
            return _neo4j_time_dict_to_iso(value)
        
        # Regular dict - normalize recursively
        return {k: _normalize_value(v) for k, v in value.items()}
    
    if isinstance(value, list):
        # Skip embedding arrays (they're large and not meaningful to compare)
        if len(value) > 10 and all(isinstance(x, (int, float)) for x in value[:10]):
            return "[embedding]"
        return [_normalize_value(v) for v in value]
    
    # Handle actual Neo4j time types (if passed directly instead of serialized)
    try:
        obj_type = type(value)
        if obj_type.__module__ == 'neo4j.time':
            if hasattr(value, 'iso_format'):
                return value.iso_format()
            elif hasattr(value, 'year') and hasattr(value, 'month') and hasattr(value, 'day'):
                return f"{value.year:04d}-{value.month:02d}-{value.day:02d}"
    except (AttributeError, TypeError):
        pass
    
    return value


def _get_node_key(node: Dict[str, Any]) -> Optional[str]:
    """Get a unique key for a node (temp_id or *_id property)."""
    # Prefer temp_id (which should match *_id after KG submission)
    temp_id = node.get("temp_id")
    if temp_id:
        return str(temp_id)
    
    # Fallback to any *_id property
    props = node.get("properties", {})
    for key, value in props.items():
        if key.endswith("_id") and value:
            return str(value)
    
    return None


def _get_edge_key(edge: Dict[str, Any]) -> str:
    """Get a unique key for an edge (from-to-label)."""
    return f"{edge.get('from', '')}:{edge.get('to', '')}:{edge.get('label', '')}"


def _compare_properties(
    postgres_props: Dict[str, Any],
    neo4j_props: Dict[str, Any],
    skip_fields: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """Compare properties between Postgres and Neo4j, returning differences."""
    differences = []
    skip_fields = skip_fields or []
    
    # Fields to always skip (internal/auto-generated)
    always_skip = {"temp_id", "is_existing", "status", "source"}
    skip_set = set(skip_fields) | always_skip
    
    # Also skip embedding fields
    all_keys = set(postgres_props.keys()) | set(neo4j_props.keys())
    for key in all_keys:
        if key in skip_set:
            continue
        if key.endswith("_embedding"):
            continue
        
        pg_value = _normalize_value(postgres_props.get(key))
        neo_value = _normalize_value(neo4j_props.get(key))
        
        if pg_value != neo_value:
            differences.append({
                "field": key,
                "postgres_value": pg_value,
                "neo4j_value": neo_value
            })
    
    return differences


def _compare_nodes(
    postgres_nodes: List[Dict[str, Any]],
    neo4j_nodes: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Compare nodes between Postgres and Neo4j."""
    comparisons = []
    stats = {
        "total_postgres": len(postgres_nodes),
        "total_neo4j": len(neo4j_nodes),
        "match": 0,
        "differ": 0,
        "only_postgres": 0,
        "only_neo4j": 0
    }
    
    # Build lookup maps
    pg_by_key: Dict[str, Dict[str, Any]] = {}
    for node in postgres_nodes:
        key = _get_node_key(node)
        if key:
            pg_by_key[key] = node
    
    neo_by_key: Dict[str, Dict[str, Any]] = {}
    for node in neo4j_nodes:
        key = _get_node_key(node)
        if key:
            neo_by_key[key] = node
    
    all_keys = set(pg_by_key.keys()) | set(neo_by_key.keys())
    
    for key in sorted(all_keys):
        pg_node = pg_by_key.get(key)
        neo_node = neo_by_key.get(key)
        
        if pg_node and neo_node:
            # Both exist - compare properties
            pg_props = pg_node.get("properties", {})
            neo_props = neo_node.get("properties", {})
            differences = _compare_properties(pg_props, neo_props)
            
            if differences:
                status = ComparisonStatus.DIFFER
                stats["differ"] += 1
            else:
                status = ComparisonStatus.MATCH
                stats["match"] += 1
            
            comparisons.append({
                "node_id": key,
                "label": pg_node.get("label") or neo_node.get("label"),
                "status": status.value,
                "differences": differences
            })
        elif pg_node:
            # Only in Postgres
            stats["only_postgres"] += 1
            comparisons.append({
                "node_id": key,
                "label": pg_node.get("label"),
                "status": ComparisonStatus.ONLY_POSTGRES.value,
                "postgres_properties": pg_node.get("properties", {}),
                "differences": []
            })
        else:
            # Only in Neo4j
            stats["only_neo4j"] += 1
            comparisons.append({
                "node_id": key,
                "label": neo_node.get("label"),
                "status": ComparisonStatus.ONLY_NEO4J.value,
                "neo4j_properties": neo_node.get("properties", {}),
                "differences": []
            })
    
    return comparisons, stats


def _compare_edges(
    postgres_edges: List[Dict[str, Any]],
    neo4j_edges: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Compare edges between Postgres and Neo4j."""
    comparisons = []
    stats = {
        "total_postgres": len(postgres_edges),
        "total_neo4j": len(neo4j_edges),
        "match": 0,
        "differ": 0,
        "only_postgres": 0,
        "only_neo4j": 0
    }
    
    # Build lookup maps
    pg_by_key: Dict[str, Dict[str, Any]] = {}
    for edge in postgres_edges:
        key = _get_edge_key(edge)
        pg_by_key[key] = edge
    
    neo_by_key: Dict[str, Dict[str, Any]] = {}
    for edge in neo4j_edges:
        key = _get_edge_key(edge)
        neo_by_key[key] = edge
    
    all_keys = set(pg_by_key.keys()) | set(neo_by_key.keys())
    
    for key in sorted(all_keys):
        pg_edge = pg_by_key.get(key)
        neo_edge = neo_by_key.get(key)
        
        if pg_edge and neo_edge:
            # Both exist - compare properties
            pg_props = pg_edge.get("properties", {})
            neo_props = neo_edge.get("properties", {})
            differences = _compare_properties(pg_props, neo_props)
            
            if differences:
                status = ComparisonStatus.DIFFER
                stats["differ"] += 1
            else:
                status = ComparisonStatus.MATCH
                stats["match"] += 1
            
            comparisons.append({
                "edge_id": key,
                "label": pg_edge.get("label") or neo_edge.get("label"),
                "from": pg_edge.get("from"),
                "to": pg_edge.get("to"),
                "status": status.value,
                "differences": differences
            })
        elif pg_edge:
            # Only in Postgres
            stats["only_postgres"] += 1
            comparisons.append({
                "edge_id": key,
                "label": pg_edge.get("label"),
                "from": pg_edge.get("from"),
                "to": pg_edge.get("to"),
                "status": ComparisonStatus.ONLY_POSTGRES.value,
                "postgres_properties": pg_edge.get("properties", {}),
                "differences": []
            })
        else:
            # Only in Neo4j
            stats["only_neo4j"] += 1
            comparisons.append({
                "edge_id": key,
                "label": neo_edge.get("label"),
                "from": neo_edge.get("from"),
                "to": neo_edge.get("to"),
                "status": ComparisonStatus.ONLY_NEO4J.value,
                "neo4j_properties": neo_edge.get("properties", {}),
                "differences": []
            })
    
    return comparisons, stats


def compare_case_data(
    postgres_data: Dict[str, Any],
    neo4j_data: Dict[str, Any],
    schema: Optional[List[Dict[str, Any]]] = None,
    neo4j_client: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Compare case data between Postgres and Neo4j.
    
    Args:
        postgres_data: Case data from Postgres (extracted format with nodes/edges)
        neo4j_data: Case data from Neo4j (extracted format with nodes/edges)
        schema: Optional schema list. If not provided, loads from schema_v3.json.
        neo4j_client: Optional Neo4j client for embedding validation
    
    Returns:
        Comparison result with summary stats and detailed comparisons
    """
    pg_nodes = postgres_data.get("nodes", [])
    pg_edges = postgres_data.get("edges", [])
    neo_nodes = neo4j_data.get("nodes", [])
    neo_edges = neo4j_data.get("edges", [])
    
    # Get catalog node labels (these are intentionally not stored in Postgres)
    catalog_labels = get_catalog_node_labels(schema)
    
    # Filter out catalog nodes from Neo4j data (they're expected to be missing from Postgres)
    neo_nodes_filtered = [n for n in neo_nodes if n.get("label") not in catalog_labels]
    catalog_nodes_skipped = [n for n in neo_nodes if n.get("label") in catalog_labels]
    
    node_comparisons, node_stats = _compare_nodes(pg_nodes, neo_nodes_filtered)
    edge_comparisons, edge_stats = _compare_edges(pg_edges, neo_edges)
    
    # Check embedding presence if Neo4j client provided
    # Use neo_nodes_filtered (the case's actual nodes, excluding catalog nodes)
    embeddings_result = None
    if neo4j_client is not None:
        embeddings_result = check_neo4j_embeddings(neo4j_client, neo_nodes_filtered, schema)
    
    # Overall status (includes embedding check if performed)
    all_match = (
        node_stats["differ"] == 0 and
        node_stats["only_postgres"] == 0 and
        node_stats["only_neo4j"] == 0 and
        edge_stats["differ"] == 0 and
        edge_stats["only_postgres"] == 0 and
        edge_stats["only_neo4j"] == 0 and
        (embeddings_result is None or embeddings_result.get("all_present", True))
    )
    
    # Build catalog nodes summary by label
    catalog_summary: Dict[str, int] = {}
    for node in catalog_nodes_skipped:
        label = node.get("label", "Unknown")
        catalog_summary[label] = catalog_summary.get(label, 0) + 1
    
    result: Dict[str, Any] = {
        "all_match": all_match,
        "summary": {
            "nodes": node_stats,
            "edges": edge_stats,
            "catalog_nodes_skipped": {
                "total": len(catalog_nodes_skipped),
                "by_label": catalog_summary,
                "labels": sorted(catalog_labels)
            }
        },
        "node_comparisons": node_comparisons,
        "edge_comparisons": edge_comparisons
    }
    
    # Add embeddings result if check was performed
    if embeddings_result is not None:
        result["summary"]["embeddings"] = embeddings_result
    
    return result

