import os
import logging
import json
import time
from typing import Dict, Set, List, Any, Tuple, Callable, TypeVar
import re
from fastapi import APIRouter, HTTPException, Request, Depends
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, DBAPIError
from sqlalchemy import text

from app.lib.db import get_db
from app.lib.case_repo import case_repo
from app.lib.graph_events_repo import graph_events_repo, compute_content_hash, make_edge_id
from app.flow_kg import create_flow
from app.lib.property_filter import filter_case_data
from app.lib.logging_config import setup_logger


logger = setup_logger("kg-route")
router = APIRouter(prefix="/kg")

T = TypeVar("T")


def retry_postgres_operation(
    operation: Callable[[], T],
    operation_name: str,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
) -> T:
    """Execute a Postgres operation with exponential backoff retry on connection errors.
    
    Args:
        operation: Callable that performs the Postgres operation
        operation_name: Human-readable name for logging
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries (seconds)
        max_delay: Maximum delay between retries (seconds)
        
    Returns:
        The result of the operation
        
    Raises:
        The last exception if all retries fail
    """
    last_error = None
    
    for attempt in range(max_retries + 1):
        try:
            return operation()
        except (OperationalError, DBAPIError) as e:
            last_error = e
            error_msg = str(e).lower()
            
            # Check if this is a retryable error (connection timeout, connection reset, etc.)
            retryable_errors = [
                "could not receive data from server",
                "connection timed out",
                "connection reset",
                "server closed the connection",
                "connection refused",
                "broken pipe",
                "ssl connection has been closed unexpectedly",
            ]
            
            is_retryable = any(err in error_msg for err in retryable_errors)
            
            if not is_retryable or attempt >= max_retries:
                logger.error(f"Postgres {operation_name} failed after {attempt + 1} attempts: {e}")
                raise
            
            # Calculate delay with exponential backoff
            delay = min(base_delay * (2 ** attempt), max_delay)
            logger.warning(
                f"Postgres {operation_name} failed (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                f"Retrying in {delay:.1f}s..."
            )
            time.sleep(delay)
    
    # Should never reach here, but just in case
    raise last_error if last_error else RuntimeError(f"Postgres {operation_name} failed unexpectedly")


def ensure_postgres_connection(db: Session) -> bool:
    """Check and refresh Postgres connection if needed.
    
    Returns True if connection is healthy, raises exception otherwise.
    """
    try:
        # Execute a simple query to check connection health
        db.execute(text("SELECT 1"))
        return True
    except (OperationalError, DBAPIError) as e:
        logger.warning(f"Postgres connection check failed, attempting to refresh: {e}")
        try:
            # Try to rollback any pending transaction and get a fresh connection
            db.rollback()
            db.execute(text("SELECT 1"))
            logger.info("Postgres connection refreshed successfully")
            return True
        except Exception as refresh_error:
            logger.error(f"Failed to refresh Postgres connection: {refresh_error}")
            raise


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


def diff_published_graph(
    old_data: Dict[str, Any],
    new_data: Dict[str, Any],
) -> Tuple[List[Dict], List[Dict], List[Dict], List[Dict], List[Dict], List[Dict]]:
    """Diff two *published* case graphs (UUID temp_ids), returning created/updated/deleted nodes/edges."""
    old_nodes = {
        n.get("temp_id"): n
        for n in (old_data.get("nodes", []) or [])
        if isinstance(n, dict) and n.get("temp_id")
    }
    new_nodes = {
        n.get("temp_id"): n
        for n in (new_data.get("nodes", []) or [])
        if isinstance(n, dict) and n.get("temp_id")
    }

    old_node_ids = set(old_nodes.keys())
    new_node_ids = set(new_nodes.keys())

    created_nodes = [new_nodes[nid] for nid in (new_node_ids - old_node_ids)]
    deleted_nodes = [old_nodes[nid] for nid in (old_node_ids - new_node_ids)]

    updated_nodes: List[Dict] = []
    for nid in (old_node_ids & new_node_ids):
        old_hash = compute_content_hash(old_nodes[nid].get("properties", {}) or {})
        new_hash = compute_content_hash(new_nodes[nid].get("properties", {}) or {})
        if old_hash != new_hash:
            updated_nodes.append(new_nodes[nid])

    def edge_key(e: Dict) -> str:
        return make_edge_id(e.get("from", ""), e.get("to", ""), e.get("label", ""))

    old_edges = {edge_key(e): e for e in (old_data.get("edges", []) or []) if isinstance(e, dict)}
    new_edges = {edge_key(e): e for e in (new_data.get("edges", []) or []) if isinstance(e, dict)}

    old_edge_ids = set(old_edges.keys())
    new_edge_ids = set(new_edges.keys())

    created_edges = [new_edges[eid] for eid in (new_edge_ids - old_edge_ids)]
    deleted_edges = [old_edges[eid] for eid in (old_edge_ids - new_edge_ids)]

    updated_edges: List[Dict] = []
    for eid in (old_edge_ids & new_edge_ids):
        old_hash = compute_content_hash(old_edges[eid].get("properties", {}) or {})
        new_hash = compute_content_hash(new_edges[eid].get("properties", {}) or {})
        if old_hash != new_hash:
            updated_edges.append(new_edges[eid])

    return created_nodes, updated_nodes, deleted_nodes, created_edges, updated_edges, deleted_edges


def log_published_graph_events(
    conn,
    case_id: str,
    user_id: str,
    created_nodes: List[Dict],
    updated_nodes: List[Dict],
    deleted_nodes: List[Dict],
    created_edges: List[Dict],
    updated_edges: List[Dict],
    deleted_edges: List[Dict],
) -> int:
    """Log graph_events for a publish operation (KG submit)."""
    count = 0

    for node in created_nodes:
        # Do not log create for pre-existing/shared nodes (created elsewhere); edges carry attribution.
        if node.get("is_existing"):
            continue
        node_id = node.get("temp_id", "")
        if node_id:
            graph_events_repo.log_node_event(
                conn=conn,
                case_id=case_id,
                node_temp_id=node_id,
                node_label=node.get("label", ""),
                action="create",
                user_id=user_id,
                properties=node.get("properties", {}),
            )
            count += 1

    for node in updated_nodes:
        node_id = node.get("temp_id", "")
        if node_id:
            graph_events_repo.log_node_event(
                conn=conn,
                case_id=case_id,
                node_temp_id=node_id,
                node_label=node.get("label", ""),
                action="update",
                user_id=user_id,
                properties=node.get("properties", {}),
            )
            count += 1

    for node in deleted_nodes:
        # Skip node-level delete events for pre-existing nodes; edge deletes represent unlinking.
        if node.get("is_existing"):
            continue
        node_id = node.get("temp_id", "")
        if node_id:
            graph_events_repo.log_node_event(
                conn=conn,
                case_id=case_id,
                node_temp_id=node_id,
                node_label=node.get("label", ""),
                action="delete",
                user_id=user_id,
                properties=node.get("properties", {}),
            )
            count += 1

    for edge in created_edges:
        graph_events_repo.log_edge_event(
            conn=conn,
            case_id=case_id,
            from_id=edge.get("from", ""),
            to_id=edge.get("to", ""),
            edge_label=edge.get("label", ""),
            action="create",
            user_id=user_id,
            properties=edge.get("properties", {}),
        )
        count += 1

    for edge in updated_edges:
        graph_events_repo.log_edge_event(
            conn=conn,
            case_id=case_id,
            from_id=edge.get("from", ""),
            to_id=edge.get("to", ""),
            edge_label=edge.get("label", ""),
            action="update",
            user_id=user_id,
            properties=edge.get("properties", {}),
        )
        count += 1

    for edge in deleted_edges:
        graph_events_repo.log_edge_event(
            conn=conn,
            case_id=case_id,
            from_id=edge.get("from", ""),
            to_id=edge.get("to", ""),
            edge_label=edge.get("label", ""),
            action="delete",
            user_id=user_id,
            properties=edge.get("properties", {}),
        )
        count += 1

    return count


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
    case_id = None
    neo4j_committed = False  # Track whether Neo4j transaction was committed
    uploaded_data = None  # Store uploaded data for Postgres save after Neo4j success
    
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

        # Draft payload (used as the input to the KG flow)
        data = rec.get("extracted") or {}

        # Published payload baseline (used for delete processing + audit diffs).
        # If kg_extracted is missing (legacy rows), fall back to extracted to preserve prior behavior.
        published_data = rec.get("kg_extracted") or rec.get("extracted") or {}
        old_nodes = (published_data.get("nodes", []) or [])
        
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
        
        # ============================================================
        # PHASE 1: Neo4j Upload (separate error handling)
        # ============================================================
        try:
            from app.lib.neo4j_uploader import Neo4jUploader
            from app.lib.neo4j_client import neo4j_client
            from app.lib.property_filter import prepare_for_postgres_save, add_temp_ids
            
            logger.info(f"Uploading case {case_id} to Neo4j by user {user_id}")
            
            # Load schema to check case_unique property
            schema = load_schema()
            case_unique_labels = get_case_unique_labels(schema)
            
            uploader = Neo4jUploader(flow.state.schema_payload, neo4j_client)
            
            # Find nodes that were deleted (in last-published but not in new)
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
                            # Has external connections - just detach from this case
                            # (unexpected for case-unique, but handle gracefully)
                            logger.warning(f"Case-unique node {label}:{node_id} has external connections, detaching only")
                            old_case_node_ids = get_case_node_ids(old_nodes)
                            detached_count = uploader.detach_node_from_case(label, node_id, old_case_node_ids)
                            logger.info(f"Detached case-unique node {label}:{node_id} from case ({detached_count} relationships)")
                    else:
                        # Non-case-unique (shared) node: detach from this case
                        old_case_node_ids = get_case_node_ids(old_nodes)
                        detached_count = uploader.detach_node_from_case(label, node_id, old_case_node_ids)
                        logger.info(f"Detached shared node {label}:{node_id} from case ({detached_count} relationships)")
                        
                        # After detaching, check if node is now isolated and non-preset
                        # Non-preset isolated shared nodes should be deleted
                        is_preset = uploader.get_node_preset(label, node_id)
                        if not is_preset:
                            has_connections = uploader.check_node_has_connections(label, node_id)
                            if not has_connections:
                                uploader.delete_node(label, node_id)
                                logger.info(f"Deleted isolated non-preset shared node {label}:{node_id}")
                        # Preset nodes always preserved (detach only)
            
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
            
            # *** CRITICAL: Mark Neo4j as committed ***
            # The upload_graph_data method commits its transaction internally
            # If we reach this point, Neo4j has the data
            neo4j_committed = True
            nodes_count = len(uploaded_data.get("nodes", []))
            edges_count = len(uploaded_data.get("edges", []))
            logger.info(f"Neo4j upload COMMITTED for case {case_id}: {nodes_count} nodes, {edges_count} edges")
            
        except Exception as neo4j_error:
            logger.exception(f"Neo4j upload failed for case {case_id}")
            db.rollback()
            return {"success": False, "error": "Neo4j upload failed"}
        
        # ============================================================
        # PHASE 2: Postgres Operations (with retry logic)
        # ============================================================
        try:
            from app.lib.property_filter import prepare_for_postgres_save, add_temp_ids
            from app.lib.neo4j_client import neo4j_client
            
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
            
            # Check if this is the first KG submission (no published snapshot yet)
            is_first_submit = rec.get("kg_submitted_at") is None or rec.get("kg_extracted") is None
            
            # Persist the *published* snapshot and log events based on "last published" -> "new published"
            cleaned = prepare_for_postgres_save(updated_data)

            # Ensure Postgres connection is healthy before event logging
            ensure_postgres_connection(db)
            
            # Log graph events with retry logic
            def do_event_logging():
                nonlocal is_first_submit, cleaned, published_data
                event_count = 0
                if is_first_submit:
                    # First publish: treat everything as created (with existing-node skips for node-level creates).
                    created_nodes_list = cleaned.get("nodes", []) or []
                    created_edges_list = cleaned.get("edges", []) or []
                    event_count = log_published_graph_events(
                        conn=db.connection(),
                        case_id=case_id,
                        user_id=user_id,
                        created_nodes=created_nodes_list,
                        updated_nodes=[],
                        deleted_nodes=[],
                        created_edges=created_edges_list,
                        updated_edges=[],
                        deleted_edges=[],
                    )
                    logger.info(f"Logged {event_count} create events for first KG publish of case {case_id}")
                else:
                    created_nodes_diff, updated_nodes_diff, deleted_nodes_diff, created_edges_diff, updated_edges_diff, deleted_edges_diff = diff_published_graph(
                        old_data=published_data,
                        new_data=cleaned,
                    )
                    event_count = log_published_graph_events(
                        conn=db.connection(),
                        case_id=case_id,
                        user_id=user_id,
                        created_nodes=created_nodes_diff,
                        updated_nodes=updated_nodes_diff,
                        deleted_nodes=deleted_nodes_diff,
                        created_edges=created_edges_diff,
                        updated_edges=updated_edges_diff,
                        deleted_edges=deleted_edges_diff,
                    )
                    logger.info(f"Logged {event_count} graph_events for KG publish of case {case_id}")
                return event_count
            
            retry_postgres_operation(do_event_logging, "event logging")
            
            # Always update entity_ids for any events that used temp_ids (legacy safety)
            # This handles both first submit (edge events) and subsequent submits (new node events)
            if id_mapping:
                def do_update_entity_ids():
                    return graph_events_repo.update_entity_ids_for_case(
                        conn=db.connection(),
                        case_id=case_id,
                        id_mapping=id_mapping,
                    )
                
                events_updated = retry_postgres_operation(do_update_entity_ids, "entity ID update")
                if events_updated > 0:
                    logger.info(f"Updated {events_updated} graph events with new UUIDs for case {case_id}")
            
            # Save updated draft + published snapshot back to Postgres with Neo4j-generated _ids
            def do_case_update():
                case_repo.update_case(db.connection(), case_id, cleaned, user_id)
                case_repo.set_kg_extracted(db.connection(), case_id, cleaned)
                case_repo.set_kg_submitted(db.connection(), case_id, user_id)
            
            retry_postgres_operation(do_case_update, "case update")
            
            # Commit all Postgres changes
            def do_commit():
                db.commit()
            
            retry_postgres_operation(do_commit, "commit")
            
            logger.info(f"Postgres operations completed for case {case_id}")
            
            nodes_count = len(updated_data.get("nodes", []))
            edges_count = len(updated_data.get("edges", []))
            
            # Post-upload: verify all embeddings are present in Neo4j
            from app.lib.case_comparison import check_neo4j_embeddings
            embeddings_result = check_neo4j_embeddings(
                neo4j_client, 
                updated_data.get("nodes", [])
            )
            
            embeddings_complete = embeddings_result.get("all_present", True)
            missing_embeddings = embeddings_result.get("missing", [])
            
            if not embeddings_complete:
                logger.warning(
                    f"KG submit for case {case_id}: {len(missing_embeddings)} embeddings missing. "
                    f"Missing: {missing_embeddings[:5]}{'...' if len(missing_embeddings) > 5 else ''}"
                )
            
            logger.info(f"KG submit complete for case {case_id}: {nodes_count} nodes, {edges_count} edges uploaded to Neo4j and saved to Postgres")
            
            # Queue auto-comparison after successful KG submit
            try:
                from app.lib.queue import comparison_queue
                from app.jobs.comparison_job import compare_single_case
                comparison_queue.enqueue(
                    compare_single_case,
                    case_id,
                    True,  # force=True to ensure fresh comparison
                    job_timeout=300,  # 5 minute timeout
                )
                logger.info(f"Queued auto-comparison for case {case_id}")
            except Exception as comp_error:
                # Don't fail the KG submit if comparison queue fails
                logger.warning(f"Failed to queue auto-comparison for case {case_id}: {comp_error}")
            
            return {
                "success": True, 
                "nodes": nodes_count, 
                "edges": edges_count,
                "embeddings_complete": embeddings_complete,
                "missing_embeddings": missing_embeddings if not embeddings_complete else [],
                "embeddings_summary": {
                    "expected": embeddings_result.get("total_expected", 0),
                    "present": embeddings_result.get("total_present", 0),
                    "missing": embeddings_result.get("total_missing", 0)
                }
            }
            
        except (OperationalError, DBAPIError) as postgres_error:
            # Postgres-specific error after Neo4j succeeded
            logger.exception(f"Postgres operations failed for case {case_id} (Neo4j committed={neo4j_committed})")
            db.rollback()
            
            if neo4j_committed:
                # CRITICAL: Neo4j has the data but Postgres doesn't
                # Return partial success so user knows to retry
                logger.error(
                    f"PARTIAL SUCCESS for case {case_id}: Neo4j upload succeeded but Postgres failed. "
                    "User should retry the submit to sync Postgres."
                )
                return {
                    "success": False, 
                    "error": "Postgres save failed after Neo4j upload succeeded. Please retry.",
                    "neo4j_committed": True,
                    "partial_success": True,
                }
            else:
                return {"success": False, "error": "Database operation failed"}
            
    except Exception as e:
        logger.exception(f"KG submit failed for case {case_id}")
        db.rollback()
        # Don't leak details to frontend; return generic 200 with success false
        return {"success": False}


