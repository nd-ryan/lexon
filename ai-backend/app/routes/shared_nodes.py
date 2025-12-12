"""API routes for managing shared (non-case-unique) nodes in the Knowledge Graph."""

import json
import logging
from typing import Any, Dict, List, Optional, Set
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.lib.security import get_api_key
from app.lib.neo4j_client import neo4j_client
from app.lib.logging_config import setup_logger
from app.lib.db import get_db
from app.lib.graph_events_repo import graph_events_repo, compute_content_hash


logger = setup_logger("shared-nodes")
router = APIRouter(prefix="/shared-nodes", dependencies=[Depends(get_api_key)])


def get_user_id(request: Request) -> str:
    """Extract user ID from X-User-Id header (set by Next.js API routes)."""
    return request.headers.get("X-User-Id", "admin")


def load_schema() -> List[Dict[str, Any]]:
    """Load the schema from file."""
    import os
    schema_path = os.path.join(os.path.dirname(__file__), "..", "..", "schema_v3.json")
    with open(schema_path, "r") as f:
        return json.load(f)


def get_shared_labels(schema: List[Dict[str, Any]]) -> List[str]:
    """Get labels where case_unique=false."""
    return [
        node_def.get("label")
        for node_def in schema
        if isinstance(node_def, dict) and node_def.get("case_unique") is False
    ]


def get_min_per_case(schema: List[Dict[str, Any]], label: str) -> int:
    """Get min_per_case value for a label (default 0)."""
    for node_def in schema:
        if isinstance(node_def, dict) and node_def.get("label") == label:
            return node_def.get("min_per_case", 0)
    return 0


def get_id_property(label: str) -> str:
    """Get the *_id property name for a label."""
    # Convert label to snake_case and add _id
    # e.g., "ReliefType" -> "relief_type_id", "Party" -> "party_id"
    import re
    snake = re.sub(r'(?<!^)(?=[A-Z])', '_', label).lower()
    return f"{snake}_id"


def get_node_display_name(node: Dict[str, Any]) -> str:
    """Get a display name for a node."""
    props = node.get("properties", {})
    # Try common name properties
    for key in ["name", "label", "type", "text", "description"]:
        if key in props and props[key]:
            val = props[key]
            if isinstance(val, str) and len(val) > 100:
                return val[:100] + "..."
            return str(val)
    return f"{node.get('label', 'Unknown')}"


def find_cases_containing_node(db: Session, node_id: str, node_label: str) -> List[Dict[str, Any]]:
    """Find all cases that contain a reference to this node (from Postgres extracted data)."""
    from sqlalchemy import text
    
    # Query cases where extracted.nodes contains this node_id
    # Note: cases table has id, filename, extracted - NOT name or citation columns
    # The case name and citation are stored in extracted.nodes where label="Case"
    id_prop = get_id_property(node_label)
    query = text("""
        SELECT id, filename, extracted
        FROM cases
        WHERE extracted IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM jsonb_array_elements(extracted->'nodes') AS node
            WHERE node->>'label' = :label
              AND node->'properties'->>:id_prop = :node_id
          )
    """)
    
    result = db.execute(query, {"label": node_label, "id_prop": id_prop, "node_id": node_id})
    
    cases = []
    for row in result:
        extracted = row.extracted or {}
        nodes = extracted.get("nodes", [])
        
        # Find the Case node to get case_name and citation
        case_node = next((n for n in nodes if n.get("label") == "Case"), None)
        case_props = case_node.get("properties", {}) if case_node else {}
        case_name = case_props.get("name") or row.filename
        citation = case_props.get("citation")
        
        # Count how many nodes of this label are in this case
        label_count = sum(1 for n in nodes if n.get("label") == node_label)
        
        cases.append({
            "case_id": str(row.id),
            "case_name": case_name,
            "citation": citation,
            "labelCount": label_count,
            "extracted": extracted,  # Keep for later use in detachment
        })
    
    return cases


def get_case_node_ids(nodes: List[Dict]) -> Set[str]:
    """Get all *_id values from nodes."""
    ids = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        props = node.get("properties", {})
        for key, val in props.items():
            if key.endswith("_id") and val:
                ids.add(str(val))
    return ids


@router.get("")
def list_shared_nodes(
    label: Optional[str] = Query(None, description="Filter by node label"),
    orphaned_only: bool = Query(False, description="Only show nodes with no connections"),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
):
    """List shared nodes from the Knowledge Graph."""
    schema = load_schema()
    shared_labels = get_shared_labels(schema)
    
    if label and label not in shared_labels:
        raise HTTPException(400, f"Label '{label}' is not a shared node type")
    
    labels_to_query = [label] if label else shared_labels
    
    nodes = []
    
    for lbl in labels_to_query:
        id_prop = get_id_property(lbl)
        
        # Query nodes with connection count
        query = f"""
            MATCH (n:{lbl})
            OPTIONAL MATCH (n)-[r]-()
            WITH n, count(r) as connectionCount
            {"WHERE connectionCount = 0" if orphaned_only else ""}
            RETURN n, connectionCount
            ORDER BY n.name, n.{id_prop}
            SKIP $offset LIMIT $limit
        """
        
        results = neo4j_client.execute_query(query, {"offset": offset, "limit": limit})
        
        for record in results:
            node = record["n"]
            conn_count = record["connectionCount"]
            
            node_data = {
                "label": lbl,
                "id": node.get(id_prop, ""),
                "name": get_node_display_name({"label": lbl, "properties": node}),
                "properties": node,
                "connectionCount": conn_count,
                "isOrphaned": conn_count == 0,
            }
            nodes.append(node_data)
    
    return {
        "success": True,
        "nodes": nodes,
        "labels": shared_labels,
    }


@router.get("/{label}/{node_id}")
def get_shared_node(label: str, node_id: str, db: Session = Depends(get_db)):
    """Get a single shared node with its connected cases."""
    schema = load_schema()
    shared_labels = get_shared_labels(schema)
    
    if label not in shared_labels:
        raise HTTPException(400, f"Label '{label}' is not a shared node type")
    
    id_prop = get_id_property(label)
    
    # Get the node from Neo4j
    query = f"""
        MATCH (n:{label} {{{id_prop}: $node_id}})
        OPTIONAL MATCH (n)-[r]-()
        RETURN n, count(r) as connectionCount
    """
    results = neo4j_client.execute_query(query, {"node_id": node_id})
    
    if not results:
        raise HTTPException(404, "Node not found")
    
    record = results[0]
    node = record["n"]
    conn_count = record["connectionCount"]
    
    # Get connected cases from Postgres (authoritative source)
    cases_data = find_cases_containing_node(db, node_id, label)
    connected_cases = [
        {"case_id": c["case_id"], "case_name": c["case_name"], "citation": c["citation"]}
        for c in cases_data
    ]
    
    return {
        "success": True,
        "node": {
            "label": label,
            "id": node_id,
            "name": get_node_display_name({"label": label, "properties": node}),
            "properties": node,
            "connectionCount": conn_count,
            "isOrphaned": conn_count == 0,
        },
        "connectedCases": connected_cases,
        "minPerCase": get_min_per_case(schema, label),
    }


class UpdateNodeRequest(BaseModel):
    properties: Dict[str, Any]


@router.put("/{label}/{node_id}")
def update_shared_node(
    label: str, 
    node_id: str, 
    body: UpdateNodeRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update a shared node's properties."""
    schema = load_schema()
    shared_labels = get_shared_labels(schema)
    
    if label not in shared_labels:
        raise HTTPException(400, f"Label '{label}' is not a shared node type")
    
    id_prop = get_id_property(label)
    user_id = get_user_id(request)
    
    # Get current node properties for change tracking
    get_query = f"""
        MATCH (n:{label} {{{id_prop}: $node_id}})
        RETURN n
    """
    current_result = neo4j_client.execute_query(get_query, {"node_id": node_id})
    if not current_result:
        raise HTTPException(404, "Node not found")
    
    old_props = dict(current_result[0]["n"])
    
    # Filter out protected properties
    protected_props = {id_prop, f"{label.lower()}_upload_code"}
    props_to_update = {
        k: v for k, v in body.properties.items() 
        if k not in protected_props and not k.endswith("_embedding")
    }
    
    if not props_to_update:
        raise HTTPException(400, "No properties to update")
    
    # Build SET clause
    set_clauses = ", ".join([f"n.{k} = ${k}" for k in props_to_update.keys()])
    
    query = f"""
        MATCH (n:{label} {{{id_prop}: $node_id}})
        SET {set_clauses}
        RETURN n
    """
    
    params = {"node_id": node_id, **props_to_update}
    results = neo4j_client.execute_query(query, params)
    
    if not results:
        raise HTTPException(404, "Node not found")
    
    new_props = dict(results[0]["n"])
    
    # Compute property changes
    property_changes = {}
    for key in props_to_update:
        if old_props.get(key) != new_props.get(key):
            property_changes[key] = {"old": old_props.get(key), "new": new_props.get(key)}
    
    # Log update events for each connected case
    cases_data = find_cases_containing_node(db, node_id, label)
    events_logged = 0
    
    with db.connection() as conn:
        for case in cases_data:
            try:
                graph_events_repo.log_node_event(
                    conn=conn,
                    case_id=case["case_id"],
                    node_temp_id=node_id,
                    node_label=label,
                    action="update",
                    user_id=user_id,
                    properties=new_props,
                    property_changes=property_changes if property_changes else None,
                )
                events_logged += 1
            except Exception as e:
                logger.error(f"Failed to log update event for case {case['case_id']}: {e}")
        conn.commit()
    
    logger.info(f"Updated shared node {label}:{node_id} by {user_id} ({events_logged} events logged)")
    
    return {
        "success": True,
        "node": {
            "label": label,
            "id": node_id,
            "properties": new_props,
        }
    }


class DeleteNodeRequest(BaseModel):
    force_partial: bool = False  # If true, delete from cases where min_per_case allows


@router.delete("/{label}/{node_id}")
def delete_shared_node(
    label: str, 
    node_id: str, 
    request: Request,
    force_partial: bool = Query(False), 
    db: Session = Depends(get_db),
):
    """Delete a shared node from the Knowledge Graph.
    
    This will:
    1. Check min_per_case constraints for connected cases (via Postgres)
    2. If constraints violated and force_partial=False, return error with details
    3. If force_partial=True, delete only from cases where constraint allows
    4. If node becomes orphaned or constraints allow, delete the node
    """
    schema = load_schema()
    shared_labels = get_shared_labels(schema)
    
    if label not in shared_labels:
        raise HTTPException(400, f"Label '{label}' is not a shared node type")
    
    id_prop = get_id_property(label)
    min_per_case = get_min_per_case(schema, label)
    user_id = get_user_id(request)
    
    # Check if node exists in Neo4j and get its properties for logging
    check_query = f"""
        MATCH (n:{label} {{{id_prop}: $node_id}})
        RETURN n
    """
    check_result = neo4j_client.execute_query(check_query, {"node_id": node_id})
    if not check_result:
        raise HTTPException(404, "Node not found")
    
    node_props = dict(check_result[0]["n"])
    
    # Get connected cases from Postgres (authoritative source for case membership)
    cases_data = find_cases_containing_node(db, node_id, label)
    
    blocked_cases = []
    deletable_cases = []
    
    for case in cases_data:
        case_info = {
            "case_id": case["case_id"],
            "case_name": case["case_name"],
            "currentCount": case["labelCount"],
            "extracted": case["extracted"],  # Keep for detachment
        }
        
        # If deleting this node would leave fewer than min_per_case
        if min_per_case > 0 and case["labelCount"] <= min_per_case:
            blocked_cases.append(case_info)
        else:
            deletable_cases.append(case_info)
    
    # If there are blocked cases and not forcing partial deletion
    if blocked_cases and not force_partial:
        return {
            "success": False,
            "error": "min_per_case_violation",
            "message": f"Cannot delete: {len(blocked_cases)} case(s) would have fewer than {min_per_case} {label} node(s)",
            "blockedCases": [{"case_id": c["case_id"], "case_name": c["case_name"], "currentCount": c["currentCount"]} for c in blocked_cases],
            "deletableCases": [{"case_id": c["case_id"], "case_name": c["case_name"], "currentCount": c["currentCount"]} for c in deletable_cases],
            "minPerCase": min_per_case,
        }
    
    # Perform deletion
    deleted_from_cases = []
    events_logged = 0
    
    if force_partial and blocked_cases:
        # Only detach from deletable cases, leave node connected to blocked cases
        with db.connection() as conn:
            for case in deletable_cases:
                try:
                    # Get node IDs from Postgres extracted data (no graph traversal!)
                    case_node_ids = list(get_case_node_ids(case["extracted"].get("nodes", [])))
                    
                    # Delete relationships between the shared node and case nodes
                    detach_query = f"""
                        MATCH (n:{label} {{{id_prop}: $node_id}})-[r]-(connected)
                        WHERE any(key IN keys(connected) WHERE key ENDS WITH '_id' AND connected[key] IN $case_node_ids)
                        DELETE r
                        RETURN count(r) as deleted
                    """
                    results = neo4j_client.execute_query(detach_query, {"node_id": node_id, "case_node_ids": case_node_ids})
                    deleted_count = results[0]["deleted"] if results else 0
                    
                    # Log delete event for this case (node detached from case)
                    try:
                        graph_events_repo.log_node_event(
                            conn=conn,
                            case_id=case["case_id"],
                            node_temp_id=node_id,
                            node_label=label,
                            action="delete",
                            user_id=user_id,
                            properties=node_props,
                        )
                        events_logged += 1
                    except Exception as e:
                        logger.error(f"Failed to log delete event for case {case['case_id']}: {e}")
                    
                    deleted_from_cases.append({
                        "case_id": case["case_id"],
                        "case_name": case["case_name"],
                        "status": "deleted",
                        "relationshipsRemoved": deleted_count,
                    })
                    logger.info(f"Detached {label}:{node_id} from case {case['case_id']} ({deleted_count} relationships)")
                except Exception as e:
                    logger.error(f"Failed to detach {label}:{node_id} from case {case['case_id']}: {e}")
                    deleted_from_cases.append({
                        "case_id": case["case_id"],
                        "case_name": case["case_name"],
                        "status": "failed",
                        "error": str(e),
                    })
            conn.commit()
        
        logger.info(f"Partial delete of {label}:{node_id} by {user_id} ({events_logged} events logged)")
        
        return {
            "success": True,
            "partial": True,
            "message": f"Node remains connected to {len(blocked_cases)} case(s) due to min_per_case constraint",
            "deletedFromCases": deleted_from_cases,
            "remainingCases": [{"case_id": c["case_id"], "case_name": c["case_name"]} for c in blocked_cases],
        }
    
    # Full deletion - delete the node and all its relationships
    delete_query = f"""
        MATCH (n:{label} {{{id_prop}: $node_id}})
        DETACH DELETE n
        RETURN count(*) as deleted
    """
    neo4j_client.execute_query(delete_query, {"node_id": node_id})
    
    all_cases = blocked_cases + deletable_cases
    
    # Log delete events for all affected cases
    with db.connection() as conn:
        for case in all_cases:
            try:
                graph_events_repo.log_node_event(
                    conn=conn,
                    case_id=case["case_id"],
                    node_temp_id=node_id,
                    node_label=label,
                    action="delete",
                    user_id=user_id,
                    properties=node_props,
                )
                events_logged += 1
            except Exception as e:
                logger.error(f"Failed to log delete event for case {case['case_id']}: {e}")
        conn.commit()
    
    logger.info(f"Deleted shared node {label}:{node_id} by {user_id} (was connected to {len(all_cases)} cases, {events_logged} events logged)")
    
    return {
        "success": True,
        "partial": False,
        "message": f"Node deleted successfully",
        "deletedFromCases": [
            {"case_id": c["case_id"], "case_name": c["case_name"], "status": "deleted"}
            for c in all_cases
        ],
    }
