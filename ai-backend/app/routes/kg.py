import os
import logging
import json
from typing import Dict, Set, List, Any, Tuple
import re
from fastapi import APIRouter, HTTPException, Request, Depends
from sqlalchemy.orm import Session

from app.lib.db import get_db
from app.lib.case_repo import case_repo
from app.lib.pending_deletions_repo import pending_deletions_repo
from app.lib.graph_events_repo import graph_events_repo
from app.flow_kg import create_flow
from app.lib.property_filter import filter_case_data
from app.lib.logging_config import setup_logger


logger = setup_logger("kg-route")
router = APIRouter(prefix="/kg")


def load_schema() -> List[Dict[str, Any]]:
    """Load the schema from schema_v3.json."""
    schema_path = os.path.join(os.path.dirname(__file__), "..", "..", "schema_v3.json")
    with open(schema_path, "r") as f:
        return json.load(f)


def get_case_unique_labels(schema: List[Dict[str, Any]]) -> Set[str]:
    """Get labels where case_unique=true."""
    return {
        node_def.get("label")
        for node_def in schema
        if isinstance(node_def, dict) and node_def.get("case_unique") is True
    }


def get_node_id_prop(label: str, schema: List[Dict[str, Any]]) -> str:
    """Get the *_id property name for a label."""
    import re
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", label).lower()
    return f"{snake}_id"


def find_deleted_nodes(
    old_nodes: List[Dict], 
    new_nodes: List[Dict]
) -> List[Dict]:
    """Find nodes that were in old_nodes but not in new_nodes."""
    # Build set of (label, *_id) for new nodes
    new_node_keys = set()
    for node in new_nodes:
        if not isinstance(node, dict):
            continue
        label = node.get("label")
        props = node.get("properties", {})
        # Find the *_id property
        for key, val in props.items():
            if key.endswith("_id") and val:
                new_node_keys.add((label, str(val)))
                break
    
    # Find old nodes that are not in new nodes
    deleted = []
    for node in old_nodes:
        if not isinstance(node, dict):
            continue
        label = node.get("label")
        props = node.get("properties", {})
        # Find the *_id property
        for key, val in props.items():
            if key.endswith("_id") and val:
                if (label, str(val)) not in new_node_keys:
                    deleted.append(node)
                break
    
    return deleted


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


def get_node_display_name(node: Dict) -> str:
    """Get a display name for a node."""
    props = node.get("properties", {})
    return props.get("name") or props.get("label") or props.get("text", "")[:50] or "Unknown"


def verify_bearer(request: Request):
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    token = auth.replace("Bearer ", "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    expected = os.getenv("API_TOKEN") or os.getenv("FASTAPI_API_KEY")
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="Invalid token")
    return True


def get_user_id_from_header(request: Request) -> str:
    """Extract user ID from X-User-Id header (set by Next.js API routes)."""
    return request.headers.get("X-User-Id", "unknown")


@router.post("/submit")
async def submit_to_kg(payload: dict, request: Request, db: Session = Depends(get_db), _: bool = Depends(verify_bearer)):
    try:
        case_id = payload.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            logger.error("KG submit: missing case_id in request body")
            return {"success": False}

        user_id = get_user_id_from_header(request)

        rec = case_repo.get_case(db.connection(), case_id)
        if not rec:
            logger.error(f"KG submit: case not found: {case_id}")
            return {"success": False}

        data = rec.get("extracted") or {}
        old_nodes = data.get("nodes", [])
        
        # Ensure we don't pass hidden props if filter is used elsewhere
        try:
            data = filter_case_data(data)
        except Exception:
            pass

        # Run KG Flow transformation
        flow = create_flow()
        flow.state.payload = data
        # Use kickoff_async() since we're already in an async context (FastAPI event loop)
        result = await flow.kickoff_async()
        
        # Upload transformed data to Neo4j
        try:
            from app.lib.neo4j_uploader import Neo4jUploader
            from app.lib.neo4j_client import neo4j_client
            from app.lib.property_filter import prepare_for_postgres_save, add_temp_ids
            
            logger.info(f"Uploading case {case_id} to Neo4j by user {user_id}")
            
            # Load schema to check case_unique property
            schema = load_schema()
            case_unique_labels = get_case_unique_labels(schema)
            
            uploader = Neo4jUploader(flow.state.schema_payload, neo4j_client)
            
            # Find nodes that were deleted (in old but not in new)
            new_nodes = result.get("nodes", [])
            deleted_nodes = find_deleted_nodes(old_nodes, new_nodes)
            
            if deleted_nodes:
                logger.info(f"Found {len(deleted_nodes)} deleted nodes to process")
                case_node_ids = get_case_node_ids(new_nodes)
                
                for node in deleted_nodes:
                    label = node.get("label")
                    props = node.get("properties", {})
                    node_id = None
                    
                    # Find the *_id property
                    for key, val in props.items():
                        if key.endswith("_id") and val:
                            node_id = str(val)
                            break
                    
                    if not label or not node_id:
                        continue
                    
                    if label in case_unique_labels:
                        # Case-unique node: check isolation and delete if safe
                        is_isolated = uploader.check_node_isolation(label, node_id, case_node_ids)
                        if is_isolated:
                            uploader.delete_node(label, node_id)
                            logger.info(f"Deleted case-unique node {label}:{node_id}")
                        else:
                            # Has external connections - detach from this case first, then queue for admin
                            logger.warning(f"Case-unique node {label}:{node_id} has external connections")
                            old_case_node_ids = get_case_node_ids(old_nodes)
                            detached_count = uploader.detach_node_from_case(label, node_id, old_case_node_ids)
                            logger.info(f"Detached case-unique node {label}:{node_id} from case ({detached_count} relationships)")
                            
                            # Queue for admin to decide on graph-wide deletion
                            pending_deletions_repo.create_deletion_request(
                                conn=db.connection(),
                                case_id=case_id,
                                node_label=label,
                                node_id=node_id,
                                node_name=get_node_display_name(node),
                                requested_by=user_id,
                            )
                            logger.info(f"Queued case-unique node {label}:{node_id} for admin deletion approval")
                    else:
                        # Non-case-unique node: first detach from this case, then queue for admin approval
                        # This reflects the edit in the KG while protecting shared nodes
                        
                        # Detach from this case's nodes in Neo4j
                        # We need the old case node IDs to know what to detach from
                        old_case_node_ids = get_case_node_ids(old_nodes)
                        detached_count = uploader.detach_node_from_case(label, node_id, old_case_node_ids)
                        logger.info(f"Detached non-case-unique node {label}:{node_id} from case ({detached_count} relationships)")
                        
                        # Check if node is now orphaned (no remaining connections)
                        has_connections = uploader.check_node_has_connections(label, node_id)
                        
                        if not has_connections:
                            # Node is orphaned - queue for admin to confirm deletion
                            existing = pending_deletions_repo.check_existing_request(
                                conn=db.connection(),
                                node_label=label,
                                node_id=node_id,
                            )
                            if not existing:
                                pending_deletions_repo.create_deletion_request(
                                    conn=db.connection(),
                                    case_id=case_id,
                                    node_label=label,
                                    node_id=node_id,
                                    node_name=get_node_display_name(node),
                                    requested_by=user_id,
                                )
                                logger.info(f"Queued orphaned non-case-unique node {label}:{node_id} for admin deletion approval")
                        else:
                            logger.info(f"Non-case-unique node {label}:{node_id} still has connections to other cases, not queuing for deletion")
            
            # Capture original temp_ids BEFORE the nodes go through the flow/upload
            # Build a map: temp_id -> (label, index within that label)
            # This preserves position for matching after upload
            
            # Pattern for AI-generated temp_ids: n0, n1, n42, etc.
            ai_temp_id_pattern = re.compile(r'^n\d+$')
            
            old_temp_id_info: Dict[str, Tuple[str, int]] = {}  # temp_id -> (label, index)
            label_counts: Dict[str, int] = {}
            
            for node in old_nodes:
                label = node.get("label")
                temp_id = node.get("temp_id")
                if label and temp_id and ai_temp_id_pattern.match(temp_id):
                    # Only track AI-generated temp_ids (not UUIDs from previous submits)
                    idx = label_counts.get(label, 0)
                    old_temp_id_info[temp_id] = (label, idx)
                    label_counts[label] = idx + 1
            
            logger.debug(f"Captured {len(old_temp_id_info)} AI temp_ids to map: {list(old_temp_id_info.keys())}")
            
            # Upload nodes and edges to Neo4j
            uploaded_data = uploader.upload_graph_data(
                new_nodes,
                result.get("edges", [])
            )
            
            # Build mapping from old temp_ids to new UUIDs
            id_mapping: Dict[str, str] = {}
            uploaded_nodes = uploaded_data.get("nodes", [])
            
            # Group uploaded nodes by label with their indices
            uploaded_by_label_idx: Dict[str, Dict[int, Dict]] = {}  # label -> {idx -> node}
            uploaded_label_counts: Dict[str, int] = {}
            
            for node in uploaded_nodes:
                label = node.get("label")
                if label:
                    idx = uploaded_label_counts.get(label, 0)
                    if label not in uploaded_by_label_idx:
                        uploaded_by_label_idx[label] = {}
                    uploaded_by_label_idx[label][idx] = node
                    uploaded_label_counts[label] = idx + 1
            
            # Match old temp_ids to new UUIDs by label + index position
            for old_temp_id, (label, idx) in old_temp_id_info.items():
                uploaded_node = uploaded_by_label_idx.get(label, {}).get(idx)
                if uploaded_node:
                    props = uploaded_node.get("properties", {})
                    # Find the *_id property
                    for key, val in props.items():
                        if key.endswith("_id") and val:
                            new_uuid = str(val)
                            if old_temp_id != new_uuid:
                                id_mapping[old_temp_id] = new_uuid
                                logger.debug(f"Mapping {label} temp_id {old_temp_id} -> {new_uuid}")
                            break
            
            logger.info(f"Built id_mapping with {len(id_mapping)} entries for case {case_id}")
            
            # Add temp_id back to nodes (copies *_id to temp_id for Postgres consistency)
            updated_data = add_temp_ids(uploaded_data)
            
            # Check if this is the first KG submission
            is_first_submit = rec.get("kg_submitted_at") is None
            
            if is_first_submit:
                # First KG submit: log 'create' events for all new nodes and edges
                # Use the UUIDs from uploaded_data (now in temp_id after add_temp_ids)
                created_event_count = 0
                
                for node in updated_data.get("nodes", []):
                    # Skip pre-existing nodes (already in KG from other cases)
                    if node.get("is_existing"):
                        continue
                    
                    node_id = node.get("temp_id", "")  # Now contains the UUID
                    if node_id:
                        graph_events_repo.log_node_event(
                            conn=db.connection(),
                            case_id=case_id,
                            node_temp_id=node_id,
                            node_label=node.get("label", ""),
                            action="create",
                            user_id=user_id,
                            properties=node.get("properties", {}),
                        )
                        created_event_count += 1
                
                for edge in updated_data.get("edges", []):
                    # Map edge from/to to UUIDs if they were temp_ids
                    from_id = edge.get("from", "")
                    to_id = edge.get("to", "")
                    # Apply id_mapping if these were temp_ids
                    from_id = id_mapping.get(from_id, from_id)
                    to_id = id_mapping.get(to_id, to_id)
                    
                    if from_id and to_id:
                        graph_events_repo.log_edge_event(
                            conn=db.connection(),
                            case_id=case_id,
                            from_id=from_id,
                            to_id=to_id,
                            edge_label=edge.get("label", ""),
                            action="create",
                            user_id=user_id,
                            properties=edge.get("properties", {}),
                        )
                        created_event_count += 1
                
                logger.info(f"Logged {created_event_count} create events for first KG submit of case {case_id}")
            
            # Always update entity_ids for any events that used temp_ids
            # This handles both first submit (edge events) and subsequent submits (new node events)
            if id_mapping:
                events_updated = graph_events_repo.update_entity_ids_for_case(
                    conn=db.connection(),
                    case_id=case_id,
                    id_mapping=id_mapping,
                )
                if events_updated > 0:
                    logger.info(f"Updated {events_updated} graph events with new UUIDs for case {case_id}")
            
            # Save updated data back to Postgres with Neo4j-generated _ids
            cleaned = prepare_for_postgres_save(updated_data)
            case_repo.update_case(db.connection(), case_id, cleaned, user_id)
            
            # Record KG submission metadata
            case_repo.set_kg_submitted(db.connection(), case_id, user_id)
            db.commit()
            
            nodes = len(updated_data.get("nodes", []))
            edges = len(updated_data.get("edges", []))
            logger.info(f"KG submit complete for case {case_id}: {nodes} nodes, {edges} edges uploaded to Neo4j and saved to Postgres")
            return {"success": True, "nodes": nodes, "edges": edges}
            
        except Exception as neo4j_error:
            logger.exception(f"Neo4j upload failed for case {case_id}")
            # Don't save to Postgres if Neo4j upload failed
            db.rollback()
            return {"success": False, "error": "Neo4j upload failed"}
            
    except Exception as e:
        logger.exception("KG submit failed")
        db.rollback()
        # Don't leak details to frontend; return generic 200 with success false
        return {"success": False}


