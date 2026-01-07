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
import logging
import os
from typing import Any, Dict, List, Optional, Set, Tuple
from enum import Enum


logger = logging.getLogger(__name__)


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


def get_required_properties_config(schema: Optional[List[Dict[str, Any]]] = None) -> Dict[str, List[str]]:
    """Get which properties are required per label.
    
    Required properties are indicated by `"required": true` in the `ui` object.
    This is used to check if extracted data is complete (needs manual completion).
    
    Args:
        schema: Optional schema list. If not provided, loads from schema_v3.json.
        
    Returns:
        Dict of { label: [required_prop_names...] }
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
        
        required_props: List[str] = []
        for prop_name, meta in props.items():
            if not isinstance(prop_name, str):
                continue
            if not isinstance(meta, dict):
                continue
            # Skip hidden/internal fields
            if prop_name.endswith("_embedding") or prop_name.endswith("_id") or prop_name.endswith("_upload_code"):
                continue
            # Check if required in UI (use truthiness, not identity)
            ui = meta.get("ui") or {}
            if ui.get("required"):
                required_props.append(prop_name)
        
        if required_props:
            config[label] = sorted(required_props)
    
    return config


def check_missing_required_properties(
    nodes: List[Dict[str, Any]],
    schema: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Check which required properties are missing from nodes.
    
    This identifies nodes that uploaded successfully but are incomplete,
    requiring manual completion by an admin.
    
    Args:
        nodes: List of node dicts from the case (with label and properties)
        schema: Optional schema list
        
    Returns:
        Dict with:
        - total_expected: number of required property instances expected
        - total_present: number of required properties that have values
        - total_missing: number of required properties missing
        - all_present: True if no missing required properties
        - missing: list of {node_id, label, property} for missing required props
    """
    required_config = get_required_properties_config(schema)
    logger.debug(f"Required properties config: {required_config}")
    
    if not required_config:
        return {
            "total_expected": 0,
            "total_present": 0,
            "total_missing": 0,
            "all_present": True,
            "missing": []
        }
    
    missing_required: List[Dict[str, str]] = []
    total_expected = 0
    total_present = 0
    
    for node in nodes:
        label = node.get("label")
        if not label or label not in required_config:
            continue
        
        required_props = required_config.get(label, [])
        if not required_props:
            continue
        
        # Get node identifier for reporting
        props = node.get("properties", {})
        node_id = node.get("temp_id")
        if not node_id:
            for key, val in props.items():
                if key.endswith("_id") and val:
                    node_id = str(val)
                    break
        if not node_id:
            node_id = f"unknown-{label}"
        
        # Check each required property
        for prop in required_props:
            total_expected += 1
            value = props.get(prop)
            # Check if value is present and non-empty
            is_present = False
            if value is not None:
                if isinstance(value, str):
                    # String must be non-empty after stripping whitespace
                    is_present = bool(value.strip())
                else:
                    # Non-string values (int, bool, list, etc.) are present if not None
                    is_present = True
            
            if is_present:
                total_present += 1
            else:
                logger.debug(f"Missing required property: {label}.{prop} (node_id={node_id}, value={value!r})")
                missing_required.append({
                    "node_id": str(node_id),
                    "label": label,
                    "property": prop
                })
    
    logger.info(f"Required properties check: {total_expected} expected, {total_present} present, {len(missing_required)} missing")
    
    return {
        "total_expected": total_expected,
        "total_present": total_present,
        "total_missing": len(missing_required),
        "all_present": len(missing_required) == 0,
        "missing": missing_required
    }


def get_required_relationships_config(schema: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Extract required relationship constraints from schema.
    
    Parses the schema to find:
    - Outgoing required relationships (required: true on relationship definition)
    - Incoming required relationships (inverse_required: true on relationship definition)
    
    Args:
        schema: Optional schema list. If not provided, loads from schema_v3.json.
        
    Returns:
        Dict with:
        - outgoing: { "SourceLabel": [{"rel": "REL_NAME", "target": "TargetLabel", "min": 1}, ...] }
        - incoming: { "TargetLabel": [{"rel": "REL_NAME", "source": "SourceLabel", "min": 1}, ...] }
    """
    if schema is None:
        schema = _load_schema()
    
    outgoing: Dict[str, List[Dict[str, Any]]] = {}
    incoming: Dict[str, List[Dict[str, Any]]] = {}
    
    for node_def in schema:
        if not isinstance(node_def, dict):
            continue
        source_label = node_def.get("label")
        if not isinstance(source_label, str) or not source_label.strip():
            continue
        
        relationships = node_def.get("relationships") or {}
        if not isinstance(relationships, dict):
            continue
        
        for rel_name, rel_def in relationships.items():
            if not isinstance(rel_def, dict):
                continue
            
            target_label = rel_def.get("target")
            if not isinstance(target_label, str):
                continue
            
            # Check outgoing required
            if rel_def.get("required"):
                min_count = rel_def.get("min", 1)
                if source_label not in outgoing:
                    outgoing[source_label] = []
                outgoing[source_label].append({
                    "rel": rel_name,
                    "target": target_label,
                    "min": min_count
                })
            
            # Check inverse required (target must have incoming)
            if rel_def.get("inverse_required"):
                inverse_min = rel_def.get("inverse_min", 1)
                if target_label not in incoming:
                    incoming[target_label] = []
                incoming[target_label].append({
                    "rel": rel_name,
                    "source": source_label,
                    "min": inverse_min
                })
    
    return {
        "outgoing": outgoing,
        "incoming": incoming
    }


def check_missing_required_relationships(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    schema: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Check for missing required relationships.
    
    This identifies nodes that are missing required outgoing or incoming relationships,
    requiring manual completion by an admin.
    
    Args:
        nodes: List of node dicts from the case (with label, temp_id, properties)
        edges: List of edge dicts from the case (with from, to, label)
        schema: Optional schema list
        
    Returns:
        Dict with:
        - total_expected: number of required relationship instances expected
        - total_present: number of required relationships that exist
        - total_missing: number of required relationships missing
        - all_present: True if no missing required relationships
        - missing: list of {node_id, label, relationship, direction, expected_min, actual_count}
    """
    config = get_required_relationships_config(schema)
    outgoing_reqs = config.get("outgoing", {})
    incoming_reqs = config.get("incoming", {})
    
    if not outgoing_reqs and not incoming_reqs:
        return {
            "total_expected": 0,
            "total_present": 0,
            "total_missing": 0,
            "all_present": True,
            "missing": []
        }
    
    # Build node lookup by temp_id and by label
    nodes_by_id: Dict[str, Dict[str, Any]] = {}
    nodes_by_label: Dict[str, List[str]] = {}  # label -> list of node_ids
    
    for node in nodes:
        temp_id = node.get("temp_id")
        label = node.get("label")
        if not temp_id or not label:
            # Try to get ID from properties
            props = node.get("properties", {})
            for key, val in props.items():
                if key.endswith("_id") and val:
                    temp_id = str(val)
                    break
        if temp_id and label:
            nodes_by_id[temp_id] = node
            if label not in nodes_by_label:
                nodes_by_label[label] = []
            nodes_by_label[label].append(temp_id)
    
    # Count outgoing edges per node per relationship type
    outgoing_edges: Dict[str, Dict[str, int]] = {}  # node_id -> {rel_label: count}
    incoming_edges: Dict[str, Dict[str, int]] = {}  # node_id -> {rel_label: count}
    
    for edge in edges:
        from_id = edge.get("from")
        to_id = edge.get("to")
        rel_label = edge.get("label")
        
        if from_id and rel_label:
            if from_id not in outgoing_edges:
                outgoing_edges[from_id] = {}
            outgoing_edges[from_id][rel_label] = outgoing_edges[from_id].get(rel_label, 0) + 1
        
        if to_id and rel_label:
            if to_id not in incoming_edges:
                incoming_edges[to_id] = {}
            incoming_edges[to_id][rel_label] = incoming_edges[to_id].get(rel_label, 0) + 1
    
    missing_required: List[Dict[str, Any]] = []
    total_expected = 0
    total_present = 0
    
    # Check outgoing requirements
    for source_label, reqs in outgoing_reqs.items():
        node_ids = nodes_by_label.get(source_label, [])
        for node_id in node_ids:
            for req in reqs:
                rel_name = req["rel"]
                min_count = req["min"]
                total_expected += 1
                
                actual_count = outgoing_edges.get(node_id, {}).get(rel_name, 0)
                if actual_count >= min_count:
                    total_present += 1
                else:
                    missing_required.append({
                        "node_id": node_id,
                        "label": source_label,
                        "relationship": rel_name,
                        "direction": "outgoing",
                        "expected_min": min_count,
                        "actual_count": actual_count
                    })
    
    # Check incoming requirements
    for target_label, reqs in incoming_reqs.items():
        node_ids = nodes_by_label.get(target_label, [])
        for node_id in node_ids:
            for req in reqs:
                rel_name = req["rel"]
                min_count = req["min"]
                total_expected += 1
                
                actual_count = incoming_edges.get(node_id, {}).get(rel_name, 0)
                if actual_count >= min_count:
                    total_present += 1
                else:
                    missing_required.append({
                        "node_id": node_id,
                        "label": target_label,
                        "relationship": rel_name,
                        "direction": "incoming",
                        "expected_min": min_count,
                        "actual_count": actual_count
                    })
    
    logger.info(f"Required relationships check: {total_expected} expected, {total_present} present, {len(missing_required)} missing")
    
    return {
        "total_expected": total_expected,
        "total_present": total_present,
        "total_missing": len(missing_required),
        "all_present": len(missing_required) == 0,
        "missing": missing_required
    }


def get_required_relationship_properties_config(schema: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Dict[str, List[str]]]:
    """Extract required relationship properties from schema.
    
    Args:
        schema: Optional schema list. If not provided, loads from schema_v3.json.
        
    Returns:
        Dict of { "SourceLabel": { "REL_NAME": ["prop1", "prop2", ...] } }
    """
    if schema is None:
        schema = _load_schema()
    
    config: Dict[str, Dict[str, List[str]]] = {}
    
    for node_def in schema:
        if not isinstance(node_def, dict):
            continue
        source_label = node_def.get("label")
        if not isinstance(source_label, str) or not source_label.strip():
            continue
        
        relationships = node_def.get("relationships") or {}
        if not isinstance(relationships, dict):
            continue
        
        for rel_name, rel_def in relationships.items():
            if not isinstance(rel_def, dict):
                continue
            
            rel_properties = rel_def.get("properties") or {}
            if not isinstance(rel_properties, dict):
                continue
            
            required_props: List[str] = []
            for prop_name, prop_def in rel_properties.items():
                if not isinstance(prop_def, dict):
                    continue
                ui = prop_def.get("ui") or {}
                if ui.get("required"):
                    required_props.append(prop_name)
            
            if required_props:
                if source_label not in config:
                    config[source_label] = {}
                config[source_label][rel_name] = sorted(required_props)
    
    return config


def check_relationship_properties(
    edges: List[Dict[str, Any]],
    nodes: List[Dict[str, Any]],
    schema: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Check for missing required properties on relationships.
    
    Args:
        edges: List of edge dicts from the case (with from, to, label, properties)
        nodes: List of node dicts to determine source labels
        schema: Optional schema list
        
    Returns:
        Dict with:
        - total_expected: number of required property instances expected
        - total_present: number of required properties that have values
        - total_missing: number of required properties missing
        - all_present: True if no missing required relationship properties
        - missing: list of {edge_id, relationship, property, from_id, to_id}
    """
    config = get_required_relationship_properties_config(schema)
    
    if not config:
        return {
            "total_expected": 0,
            "total_present": 0,
            "total_missing": 0,
            "all_present": True,
            "missing": []
        }
    
    # Build node lookup to get source labels
    node_labels: Dict[str, str] = {}
    for node in nodes:
        temp_id = node.get("temp_id")
        label = node.get("label")
        if temp_id and label:
            node_labels[temp_id] = label
        # Also try properties for ID
        props = node.get("properties", {})
        for key, val in props.items():
            if key.endswith("_id") and val and label:
                node_labels[str(val)] = label
    
    missing_required: List[Dict[str, Any]] = []
    total_expected = 0
    total_present = 0
    
    for edge in edges:
        from_id = edge.get("from")
        to_id = edge.get("to")
        rel_label = edge.get("label")
        edge_props = edge.get("properties") or {}
        
        if not from_id or not rel_label:
            continue
        
        # Get source label
        source_label = node_labels.get(from_id)
        if not source_label:
            continue
        
        # Check if this relationship type has required properties
        rel_config = config.get(source_label, {}).get(rel_label, [])
        if not rel_config:
            continue
        
        edge_id = f"{from_id}:{to_id}:{rel_label}"
        
        for prop_name in rel_config:
            total_expected += 1
            value = edge_props.get(prop_name)
            
            # Check if value is present and non-empty
            is_present = False
            if value is not None:
                if isinstance(value, str):
                    is_present = bool(value.strip())
                else:
                    is_present = True
            
            if is_present:
                total_present += 1
            else:
                missing_required.append({
                    "edge_id": edge_id,
                    "relationship": rel_label,
                    "property": prop_name,
                    "from_id": from_id,
                    "to_id": to_id
                })
    
    logger.info(f"Relationship properties check: {total_expected} expected, {total_present} present, {len(missing_required)} missing")
    
    return {
        "total_expected": total_expected,
        "total_present": total_present,
        "total_missing": len(missing_required),
        "all_present": len(missing_required) == 0,
        "missing": missing_required
    }


def get_cardinality_config(schema: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Dict[str, str]]:
    """Extract cardinality constraints from schema.
    
    Args:
        schema: Optional schema list. If not provided, loads from schema_v3.json.
        
    Returns:
        Dict of { "SourceLabel": { "REL_NAME": "cardinality" } }
    """
    if schema is None:
        schema = _load_schema()
    
    config: Dict[str, Dict[str, str]] = {}
    
    for node_def in schema:
        if not isinstance(node_def, dict):
            continue
        source_label = node_def.get("label")
        if not isinstance(source_label, str) or not source_label.strip():
            continue
        
        relationships = node_def.get("relationships") or {}
        if not isinstance(relationships, dict):
            continue
        
        for rel_name, rel_def in relationships.items():
            if not isinstance(rel_def, dict):
                continue
            
            cardinality = rel_def.get("cardinality", "many-to-many")
            if isinstance(cardinality, str):
                if source_label not in config:
                    config[source_label] = {}
                config[source_label][rel_name] = cardinality
    
    return config


def check_cardinality_violations(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    schema: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Check for cardinality violations in relationships.
    
    Cardinality types:
    - one-to-one: Each source has at most ONE edge, each target referenced at most once
    - one-to-many: Each source can have MANY edges, each target referenced at most once
    - many-to-one: Each source has at most ONE edge, targets can be referenced many times
    - many-to-many: No restrictions
    
    Args:
        nodes: List of node dicts from the case
        edges: List of edge dicts from the case
        schema: Optional schema list
        
    Returns:
        Dict with:
        - total_violations: number of cardinality violations found
        - all_valid: True if no violations
        - violations: list of {source_id, source_label, relationship, issue, details}
    """
    cardinality_config = get_cardinality_config(schema)
    
    if not cardinality_config:
        return {
            "total_violations": 0,
            "all_valid": True,
            "violations": []
        }
    
    # Build node lookup to get source labels
    node_labels: Dict[str, str] = {}
    for node in nodes:
        temp_id = node.get("temp_id")
        label = node.get("label")
        if temp_id and label:
            node_labels[temp_id] = label
        props = node.get("properties", {})
        for key, val in props.items():
            if key.endswith("_id") and val and label:
                node_labels[str(val)] = label
    
    # Group edges by (source_label, rel_label)
    edges_by_type: Dict[Tuple[str, str], List[Tuple[str, str]]] = {}
    
    for edge in edges:
        from_id = edge.get("from")
        to_id = edge.get("to")
        rel_label = edge.get("label")
        
        if not from_id or not to_id or not rel_label:
            continue
        
        source_label = node_labels.get(from_id)
        if not source_label:
            continue
        
        key = (source_label, rel_label)
        if key not in edges_by_type:
            edges_by_type[key] = []
        edges_by_type[key].append((from_id, to_id))
    
    violations: List[Dict[str, Any]] = []
    
    # Check cardinality for each relationship type
    for (source_label, rel_label), edge_list in edges_by_type.items():
        cardinality = cardinality_config.get(source_label, {}).get(rel_label, "many-to-many")
        
        # Count edges per source and per target
        edges_per_source: Dict[str, List[str]] = {}
        edges_per_target: Dict[str, List[str]] = {}
        
        for from_id, to_id in edge_list:
            if from_id not in edges_per_source:
                edges_per_source[from_id] = []
            edges_per_source[from_id].append(to_id)
            
            if to_id not in edges_per_target:
                edges_per_target[to_id] = []
            edges_per_target[to_id].append(from_id)
        
        if cardinality == "one-to-one":
            # Each source can have at most ONE edge, AND each target can only be referenced once
            for src_id, targets in edges_per_source.items():
                if len(targets) > 1:
                    violations.append({
                        "source_id": src_id,
                        "source_label": source_label,
                        "relationship": rel_label,
                        "issue": "source_multiple",
                        "details": f"Source has {len(targets)} edges (should be 1)"
                    })
            for tgt_id, sources in edges_per_target.items():
                if len(sources) > 1:
                    violations.append({
                        "source_id": tgt_id,
                        "source_label": source_label,
                        "relationship": rel_label,
                        "issue": "target_multiple",
                        "details": f"Target referenced by {len(sources)} sources (should be 1)"
                    })
        
        elif cardinality == "one-to-many":
            # Each source can have many, but each target can only be referenced once
            for tgt_id, sources in edges_per_target.items():
                if len(sources) > 1:
                    violations.append({
                        "source_id": tgt_id,
                        "source_label": source_label,
                        "relationship": rel_label,
                        "issue": "target_multiple",
                        "details": f"Target referenced by {len(sources)} sources (should be 1)"
                    })
        
        elif cardinality == "many-to-one":
            # Each source can have at most ONE edge of this type
            for src_id, targets in edges_per_source.items():
                if len(targets) > 1:
                    violations.append({
                        "source_id": src_id,
                        "source_label": source_label,
                        "relationship": rel_label,
                        "issue": "source_multiple",
                        "details": f"Source has {len(targets)} edges (should be 1)"
                    })
        
        # many-to-many: no restrictions
    
    logger.info(f"Cardinality check: {len(violations)} violations found")
    
    return {
        "total_violations": len(violations),
        "all_valid": len(violations) == 0,
        "violations": violations
    }


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
    
    # Fields to always skip (internal/auto-generated or Neo4j-only)
    # - temp_id, is_existing, status, source: internal tracking fields
    # - preset: Neo4j-only flag for canonical nodes (not stored in Postgres)
    always_skip = {"temp_id", "is_existing", "status", "source", "preset"}
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
    
    # ==========================================================================
    # POSTGRES INTEGRITY CHECKS
    # Validates the source data (what admin can edit in the case editor)
    # ==========================================================================
    pg_required_props = check_missing_required_properties(pg_nodes, schema)
    pg_required_rels = check_missing_required_relationships(pg_nodes, pg_edges, schema)
    pg_rel_props = check_relationship_properties(pg_edges, pg_nodes, schema)
    pg_cardinality = check_cardinality_violations(pg_nodes, pg_edges, schema)
    
    pg_integrity_valid = (
        pg_required_props.get("all_present", True) and
        pg_required_rels.get("all_present", True) and
        pg_rel_props.get("all_present", True) and
        pg_cardinality.get("all_valid", True)
    )
    
    # ==========================================================================
    # NEO4J INTEGRITY CHECKS
    # Validates the knowledge graph directly (guards against sync issues, partial updates, etc.)
    # ==========================================================================
    neo4j_required_props = check_missing_required_properties(neo_nodes_filtered, schema)
    neo4j_required_rels = check_missing_required_relationships(neo_nodes_filtered, neo_edges, schema)
    neo4j_rel_props = check_relationship_properties(neo_edges, neo_nodes_filtered, schema)
    neo4j_cardinality = check_cardinality_violations(neo_nodes_filtered, neo_edges, schema)
    
    neo4j_integrity_valid = (
        neo4j_required_props.get("all_present", True) and
        neo4j_required_rels.get("all_present", True) and
        neo4j_rel_props.get("all_present", True) and
        neo4j_cardinality.get("all_valid", True) and
        (embeddings_result is None or embeddings_result.get("all_present", True))
    )
    
    # ==========================================================================
    # SYNC CHECK
    # Validates that Neo4j mirrors Postgres correctly
    # ==========================================================================
    data_synced = (
        node_stats["differ"] == 0 and
        node_stats["only_postgres"] == 0 and
        node_stats["only_neo4j"] == 0 and
        edge_stats["differ"] == 0 and
        edge_stats["only_postgres"] == 0 and
        edge_stats["only_neo4j"] == 0
    )
    
    # Overall status: everything is good
    all_match = data_synced and pg_integrity_valid and neo4j_integrity_valid
    
    # Separate flag for "needs completion" - synced correctly but Neo4j has missing required items
    # Admin needs to fix in Postgres and re-submit
    needs_completion = data_synced and not neo4j_integrity_valid
    
    # Build catalog nodes summary by label
    catalog_summary: Dict[str, int] = {}
    for node in catalog_nodes_skipped:
        label = node.get("label", "Unknown")
        catalog_summary[label] = catalog_summary.get(label, 0) + 1
    
    result: Dict[str, Any] = {
        "all_match": all_match,
        "needs_completion": needs_completion,
        "summary": {
            # Sync status (Postgres ↔ Neo4j)
            "sync": {
                "all_synced": data_synced,
                "nodes": node_stats,
                "edges": edge_stats,
                "catalog_nodes_skipped": {
                    "total": len(catalog_nodes_skipped),
                    "by_label": catalog_summary,
                    "labels": sorted(catalog_labels)
                }
            },
            # Postgres integrity (source data - what admin edits)
            "postgres_integrity": {
                "all_valid": pg_integrity_valid,
                "required_properties": pg_required_props,
                "required_relationships": pg_required_rels,
                "relationship_properties": pg_rel_props,
                "cardinality": pg_cardinality
            },
            # Neo4j integrity (knowledge graph - the goal)
            "neo4j_integrity": {
                "all_valid": neo4j_integrity_valid,
                "required_properties": neo4j_required_props,
                "required_relationships": neo4j_required_rels,
                "relationship_properties": neo4j_rel_props,
                "cardinality": neo4j_cardinality,
                "embeddings": embeddings_result
            }
        },
        "node_comparisons": node_comparisons,
        "edge_comparisons": edge_comparisons
    }
    
    return result

