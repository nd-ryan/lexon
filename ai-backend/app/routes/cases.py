from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request
from sqlalchemy.orm import Session
from app.lib.security import get_api_key
from app.lib.db import get_db
from app.lib.case_repo import case_repo
from app.lib.property_filter import filter_case_data, filter_display_data
from app.lib.graph_events_repo import graph_events_repo, compute_content_hash, make_edge_id
import tempfile
import os
import logging
import uuid
from typing import Dict, Any, List, Set, Tuple


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cases", dependencies=[Depends(get_api_key)])


def get_user_id_from_header(request: Request) -> str:
    """Extract user ID from X-User-Id header (set by Next.js API routes)."""
    return request.headers.get("X-User-Id", "unknown")


def diff_graph_data(
    old_data: Dict[str, Any], 
    new_data: Dict[str, Any]
) -> Tuple[List[Dict], List[Dict], List[Dict], List[Dict], List[Dict], List[Dict]]:
    """
    Compare old and new graph data to find created, updated, and deleted nodes/edges.
    
    Returns:
        Tuple of (created_nodes, updated_nodes, deleted_nodes, created_edges, updated_edges, deleted_edges)
    """
    old_nodes = {n.get("temp_id"): n for n in old_data.get("nodes", []) if isinstance(n, dict) and n.get("temp_id")}
    new_nodes = {n.get("temp_id"): n for n in new_data.get("nodes", []) if isinstance(n, dict) and n.get("temp_id")}
    
    old_node_ids = set(old_nodes.keys())
    new_node_ids = set(new_nodes.keys())
    
    created_nodes = [new_nodes[nid] for nid in (new_node_ids - old_node_ids)]
    deleted_nodes = [old_nodes[nid] for nid in (old_node_ids - new_node_ids)]
    
    # Check for updated nodes (same temp_id but different content)
    updated_nodes = []
    for nid in (old_node_ids & new_node_ids):
        old_hash = compute_content_hash(old_nodes[nid].get("properties", {}))
        new_hash = compute_content_hash(new_nodes[nid].get("properties", {}))
        if old_hash != new_hash:
            updated_nodes.append(new_nodes[nid])
    
    # Compare edges
    def edge_key(e: Dict) -> str:
        return make_edge_id(e.get("from", ""), e.get("to", ""), e.get("label", ""))
    
    old_edges = {edge_key(e): e for e in old_data.get("edges", []) if isinstance(e, dict)}
    new_edges = {edge_key(e): e for e in new_data.get("edges", []) if isinstance(e, dict)}
    
    old_edge_ids = set(old_edges.keys())
    new_edge_ids = set(new_edges.keys())
    
    created_edges = [new_edges[eid] for eid in (new_edge_ids - old_edge_ids)]
    deleted_edges = [old_edges[eid] for eid in (old_edge_ids - new_edge_ids)]
    
    # Check for updated edges
    updated_edges = []
    for eid in (old_edge_ids & new_edge_ids):
        old_hash = compute_content_hash(old_edges[eid].get("properties", {}))
        new_hash = compute_content_hash(new_edges[eid].get("properties", {}))
        if old_hash != new_hash:
            updated_edges.append(new_edges[eid])
    
    return created_nodes, updated_nodes, deleted_nodes, created_edges, updated_edges, deleted_edges


def log_graph_events(
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
    """Log graph events for all changes and return total count."""
    count = 0
    
    for node in created_nodes:
        graph_events_repo.log_node_event(
            conn=conn,
            case_id=case_id,
            node_temp_id=node.get("temp_id", ""),
            node_label=node.get("label", ""),
            action="create",
            user_id=user_id,
            properties=node.get("properties", {}),
        )
        count += 1
    
    for node in updated_nodes:
        graph_events_repo.log_node_event(
            conn=conn,
            case_id=case_id,
            node_temp_id=node.get("temp_id", ""),
            node_label=node.get("label", ""),
            action="update",
            user_id=user_id,
            properties=node.get("properties", {}),
        )
        count += 1
    
    for node in deleted_nodes:
        graph_events_repo.log_node_event(
            conn=conn,
            case_id=case_id,
            node_temp_id=node.get("temp_id", ""),
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


@router.post("/upload")
async def upload_case(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Start async case extraction job and return job_id for progress tracking."""
    try:
        file_bytes = await file.read()
        file_extension = os.path.splitext(file.filename)[1] or '.docx'
        user_id = get_user_id_from_header(request)
        
        logger.info(f"Received file upload: {file.filename}, size: {len(file_bytes)} bytes, user: {user_id}")

        # Create case record with original author
        case_id = case_repo.create_case(db.connection(), file.filename, original_author_id=user_id)
        
        # Upload file to Tigris object storage
        try:
            from app.lib.storage import upload_file
            file_key = upload_file(case_id, file.filename, file_bytes)
            case_repo.set_file_key(db.connection(), case_id, file_key)
            logger.info(f"Uploaded file to Tigris: {file_key}")
        except Exception as e:
            # Log but don't fail - file storage is optional for now
            logger.warning(f"Failed to upload file to Tigris (continuing anyway): {e}")
        
        db.commit()

        # Generate job ID for tracking
        job_id = str(uuid.uuid4())

        # Store file content in Redis temporarily (expires in 1 hour)
        # This ensures the worker on any instance can access it
        from app.lib.queue import redis_conn
        redis_key = f"file_upload:{job_id}"
        redis_conn.setex(
            redis_key,
            3600,  # 1 hour TTL
            file_bytes
        )
        
        logger.info(f"Stored file content in Redis: {redis_key}, size: {len(file_bytes)} bytes")

        # Queue the extraction job
        from app.lib.queue import case_extraction_queue as q
        from app.jobs.case_extraction_job import run_case_extraction
        
        # Pass job_id and extension instead of file path
        # Worker will retrieve content from Redis
        job = q.enqueue(
            run_case_extraction,
            args=(job_id, file.filename, file_extension, case_id),
            job_id=job_id,
            job_timeout='30m',
        )

        logger.info(f"Queued case extraction job {job_id} for case {case_id}")
        return {"success": True, "caseId": case_id, "jobId": job_id}
    except Exception as e:
        logger.exception("Failed to queue case upload")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/upload/progress/{job_id}")
async def get_upload_progress(job_id: str):
    """Stream progress updates for case extraction job via Server-Sent Events."""
    from fastapi.responses import StreamingResponse
    from app.lib.queue import redis_conn
    import asyncio
    import json
    import time
    
    async def event_stream():
        pubsub = redis_conn.pubsub()
        channel_name = f"job:{job_id}"
        logger.info(f"Client connected to progress stream for job {job_id}")
        
        try:
            await asyncio.to_thread(pubsub.subscribe, channel_name)
            
            # Send initial connection message
            yield f"data: {json.dumps({'type': 'connected', 'jobId': job_id})}\n\n"
            
            last_keepalive = time.time()
            
            while True:
                message = await asyncio.to_thread(pubsub.get_message, ignore_subscribe_messages=True, timeout=1.0)
                if message:
                    message_data = message['data'].decode('utf-8')
                    try:
                        data = json.loads(message_data)
                        yield f"data: {json.dumps(data)}\n\n"
                        last_keepalive = time.time()
                        if data.get("type") == "end":
                            await asyncio.sleep(0.1)
                            break
                    except json.JSONDecodeError:
                        logger.warning(f"Received non-JSON message on channel {channel_name}: {message_data}")
                
                # Send keepalive every 15 seconds
                if time.time() - last_keepalive > 15:
                    yield f"data: {json.dumps({'type': 'keepalive'})}\n\n"
                    last_keepalive = time.time()
                    
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.info(f"Client disconnected from job {job_id}")
            raise
        except Exception as e:
            logger.error(f"Error in progress stream for job {job_id}: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            logger.info(f"Closing pubsub for job {job_id}")
            pubsub.unsubscribe(channel_name)
            pubsub.close()
    
    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("")
def list_cases(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    items = case_repo.list_cases(db.connection(), q=None, limit=limit, offset=offset)
    return {"success": True, "items": items}


@router.get("/{case_id}")
def get_case(case_id: str, db: Session = Depends(get_db)):
    data = case_repo.get_case(db.connection(), case_id)
    if not data:
        raise HTTPException(404, "Not found")
    
    # Filter hidden properties from extracted data before returning
    extracted = data.get("extracted")
    if extracted:
        data["extracted"] = filter_case_data(extracted)
    
    # Compute kg_diverged flag
    updated_at = data.get("updated_at")
    kg_submitted_at = data.get("kg_submitted_at")
    
    if kg_submitted_at is None:
        kg_diverged = True  # Never submitted to KG
    elif updated_at is None:
        kg_diverged = False
    else:
        kg_diverged = updated_at > kg_submitted_at
    
    data["kg_diverged"] = kg_diverged
    
    return {"success": True, "case": data}


@router.get("/{case_id}/display")
def get_case_display(case_id: str, view: str = "holdingsCentric", db: Session = Depends(get_db)):
    """Get structured view of case data optimized for display"""
    case_data = case_repo.get_case(db.connection(), case_id)
    if not case_data:
        raise HTTPException(404, "Not found")
    
    extracted = case_data.get("extracted")
    if not extracted:
        raise HTTPException(400, "Case has no extracted data")
    
    try:
        from app.lib.case_view_builder import build_case_display_view, load_views_config
        structured = build_case_display_view(extracted, view)
        views_config = load_views_config()
        view_config = views_config.get(view, {})
        
        # Filter hidden properties from structured display data
        filtered_structured = filter_display_data(structured)
        
        return {
            "success": True,
            "view": view,
            "viewConfig": view_config,
            "data": filtered_structured,
            "metadata": {
                "case_id": case_data.get("id"),
                "filename": case_data.get("filename"),
                "status": case_data.get("status"),
                "updated_at": case_data.get("updated_at")
            }
        }
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception(f"Failed to build display view for case {case_id}")
        raise HTTPException(500, f"Failed to build view: {str(e)}")


@router.put("/{case_id}")
def update_case(case_id: str, payload: dict, request: Request, db: Session = Depends(get_db)):
    # Validate catalog IDs before saving
    from app.lib.catalog_validator import validate_catalog_ids
    from app.lib.property_filter import prepare_for_postgres_save
    
    try:
        nodes = payload.get("nodes", [])
        is_valid, errors = validate_catalog_ids(nodes)
        
        if not is_valid:
            error_msg = f"Invalid catalog references: {'; '.join(errors)}"
            logger.warning(f"Case {case_id} save failed - validation errors: {error_msg}")
            raise HTTPException(400, error_msg)
        
        user_id = get_user_id_from_header(request)
        
        # Get current case data for diff
        current = case_repo.get_case(db.connection(), case_id)
        old_data = current.get("extracted", {}) if current else {}
        
        # Check if case has been submitted to KG before
        # Only log events for edits after first KG submission
        has_been_submitted = current.get("kg_submitted_at") is not None if current else False
        
        cleaned_payload = prepare_for_postgres_save(payload)
        
        event_count = 0
        if has_been_submitted:
            # Case was previously submitted to KG - log changes
            created_nodes, updated_nodes, deleted_nodes, created_edges, updated_edges, deleted_edges = diff_graph_data(
                old_data, cleaned_payload
            )
            
            event_count = log_graph_events(
                conn=db.connection(),
                case_id=case_id,
                user_id=user_id,
                created_nodes=created_nodes,
                updated_nodes=updated_nodes,
                deleted_nodes=deleted_nodes,
                created_edges=created_edges,
                updated_edges=updated_edges,
                deleted_edges=deleted_edges,
            )
        
        updated = case_repo.update_case(db.connection(), case_id, cleaned_payload, user_id)
        db.commit()
        
        if has_been_submitted:
            logger.info(f"Case {case_id} saved by {user_id} ({event_count} events logged)")
        else:
            logger.info(f"Case {case_id} saved by {user_id} (draft - no events logged)")
        return {"success": True, "case": updated}
    except HTTPException:
        # Re-raise HTTPExceptions (like validation errors) without wrapping
        raise
    except Exception as e:
        logger.error(f"Case {case_id} save failed with unexpected error: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to save case: {str(e)}")


@router.delete("/{case_id}")
def delete_case(case_id: str, request: Request, db: Session = Depends(get_db)):
    """Delete a case, cleaning up KG data and file storage as needed."""
    user_id = get_user_id_from_header(request)
    
    # Get the case first
    case_data = case_repo.get_case(db.connection(), case_id)
    if not case_data:
        raise HTTPException(status_code=404, detail="Not found")
    
    extracted = case_data.get("extracted", {})
    nodes = extracted.get("nodes", [])
    edges = extracted.get("edges", [])
    file_key = case_data.get("file_key")
    kg_submitted_at = case_data.get("kg_submitted_at")
    
    # If case was submitted to KG, clean up Neo4j
    if kg_submitted_at is not None:
        try:
            from app.lib.neo4j_uploader import Neo4jUploader
            from app.lib.neo4j_client import neo4j_client
            from app.routes.kg import load_schema, get_case_unique_labels, get_case_node_ids
            
            schema = load_schema()
            case_unique_labels = get_case_unique_labels(schema)
            uploader = Neo4jUploader(schema, neo4j_client)
            
            # Get all node IDs in this case for detachment
            case_node_ids = get_case_node_ids(nodes)
            
            # Process each node
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                
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
                
                is_existing = node.get("is_existing", False)
                
                if is_existing:
                    # Pre-existing node: just detach from this case's nodes, leave in KG
                    try:
                        detached = uploader.detach_node_from_case(label, node_id, case_node_ids)
                        logger.info(f"Detached pre-existing node {label}:{node_id} ({detached} relationships)")
                    except Exception as e:
                        logger.warning(f"Failed to detach pre-existing node {label}:{node_id}: {e}")
                elif label in case_unique_labels:
                    # Case-unique node created by this case: delete from KG
                    try:
                        uploader.delete_node(label, node_id)
                        logger.info(f"Deleted case-unique node {label}:{node_id} from KG")
                    except Exception as e:
                        logger.warning(f"Failed to delete node {label}:{node_id} from KG: {e}")
                else:
                    # Non-case-unique node created by this case: detach from this case's nodes
                    try:
                        detached = uploader.detach_node_from_case(label, node_id, case_node_ids)
                        logger.info(f"Detached non-case-unique node {label}:{node_id} ({detached} relationships)")
                    except Exception as e:
                        logger.warning(f"Failed to detach node {label}:{node_id}: {e}")
            
            logger.info(f"Cleaned up KG for case {case_id}")
        except Exception as e:
            logger.error(f"Failed to clean up KG for case {case_id}: {e}")
            # Continue with deletion even if KG cleanup fails
    
    # Log delete events for all nodes and edges
    for node in nodes:
        if isinstance(node, dict) and not node.get("is_existing"):
            node_id = node.get("temp_id", "")
            if node_id:
                graph_events_repo.log_node_event(
                    conn=db.connection(),
                    case_id=case_id,
                    node_temp_id=node_id,
                    node_label=node.get("label", ""),
                    action="delete",
                    user_id=user_id,
                    properties=node.get("properties", {}),
                )
    
    for edge in edges:
        if isinstance(edge, dict):
            graph_events_repo.log_edge_event(
                conn=db.connection(),
                case_id=case_id,
                from_id=edge.get("from", ""),
                to_id=edge.get("to", ""),
                edge_label=edge.get("label", ""),
                action="delete",
                user_id=user_id,
                properties=edge.get("properties", {}),
            )
    
    # Delete file from Tigris storage
    if file_key:
        try:
            from app.lib.storage import delete_file
            delete_file(file_key)
            logger.info(f"Deleted file from storage: {file_key}")
        except ImportError:
            logger.warning("Storage module not available (boto3 not installed), skipping file deletion")
        except Exception as e:
            logger.warning(f"Failed to delete file {file_key} from storage: {e}")
            # Continue with deletion even if file cleanup fails
    
    # Delete case from Postgres
    ok = case_repo.delete_case(db.connection(), case_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to delete case from database")
    
    db.commit()
    logger.info(f"Case {case_id} deleted by {user_id}")
    return {"success": True}


@router.get("/{case_id}/download")
def download_case_file(case_id: str, db: Session = Depends(get_db)):
    """Return presigned URL for downloading original uploaded file."""
    case = case_repo.get_case(db.connection(), case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    
    file_key = case.get("file_key")
    if not file_key:
        raise HTTPException(status_code=404, detail="Original file not available")
    
    try:
        from app.lib.storage import generate_presigned_url
        url = generate_presigned_url(file_key)
        return {
            "success": True,
            "url": url,
            "filename": case.get("filename"),
        }
    except Exception as e:
        logger.error(f"Failed to generate download URL for case {case_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate download URL")


