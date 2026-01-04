from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request, Query
from sqlalchemy.orm import Session
from app.lib.security import get_api_key
from app.lib.db import get_db
from app.lib.case_repo import case_repo
from app.lib.property_filter import filter_case_data, filter_display_data
from app.lib.graph_events_repo import graph_events_repo
import tempfile
import os
import logging
import uuid
import re
from typing import Dict, Any, List, Set, Optional


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cases", dependencies=[Depends(get_api_key)])


def get_user_id_from_header(request: Request) -> str:
    """Extract user ID from X-User-Id header (set by Next.js API routes)."""
    return request.headers.get("X-User-Id", "unknown")


_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _looks_like_uuid(value: Any) -> bool:
    return isinstance(value, str) and bool(_UUID_RE.match(value))


def _get_case_node_ids_for_kg_cleanup(nodes: List[Dict[str, Any]]) -> Set[str]:
    """Return a set of node IDs usable by Neo4j cleanup routines.

    Prefer schema-driven *_id properties when present; fall back to UUID temp_ids
    (published graphs use UUID temp_ids).
    """
    ids: Set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        props = node.get("properties") or {}
        if isinstance(props, dict):
            for key, val in props.items():
                if isinstance(key, str) and key.endswith("_id") and val:
                    ids.add(str(val))
        temp_id = node.get("temp_id")
        if _looks_like_uuid(temp_id):
            ids.add(temp_id)
    return ids


def _get_node_id_for_label(label: str, node: Dict[str, Any], schema: List[Dict[str, Any]]) -> Optional[str]:
    """Extract the node's primary *_id value (or a UUID temp_id fallback) for a given label."""
    from app.lib.neo4j_uploader import get_id_prop_for_label

    props = node.get("properties") or {}
    if isinstance(props, dict):
        id_prop = get_id_prop_for_label(label, schema)
        val = props.get(id_prop)
        if val:
            return str(val)
        # Fallback: any *_id property present
        for key, v in props.items():
            if isinstance(key, str) and key.endswith("_id") and v:
                return str(v)

    # Last resort: published graphs often use UUID temp_ids that match Neo4j *_id
    temp_id = node.get("temp_id")
    if _looks_like_uuid(temp_id):
        return temp_id
    return None

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
def list_cases(
    limit: int = 50, 
    offset: int = 0, 
    comparison_status: Optional[str] = Query(None, description="Filter by comparison status: issues|synced|pending|not_checked|not_in_kg|needs_completion"),
    db: Session = Depends(get_db)
):
    """
    List cases with optional comparison status filter.
    
    Comparison status values:
    - issues: Cases where comparison found differences (sync issues)
    - needs_completion: Cases synced correctly but missing required properties
    - synced: Cases where comparison passed (all_match=true, no missing required)
    - pending: Cases with unsaved changes (updated_at > kg_submitted_at)
    - not_checked: Cases in KG but no comparison run yet
    - not_in_kg: Cases not yet submitted to KG
    """
    from app.lib.comparison_repo import comparison_repo
    
    conn = db.connection()
    items = case_repo.list_cases(conn, q=None, limit=limit, offset=offset)
    
    # Get case IDs for batch comparison lookup
    case_ids = [str(item["id"]) for item in items]
    
    # Batch fetch comparison results
    comparisons = comparison_repo.get_comparisons_for_cases(conn, case_ids)
    
    # Enrich items with comparison data and compute status
    enriched_items = []
    for item in items:
        case_id = str(item["id"])
        comparison = comparisons.get(case_id)
        
        updated_at = item.get("updated_at")
        kg_submitted_at = item.get("kg_submitted_at")
        
        # Compute comparison status
        if kg_submitted_at is None:
            status = "not_in_kg"
        elif updated_at and kg_submitted_at and updated_at > kg_submitted_at:
            status = "pending"
        elif comparison is None:
            status = "not_checked"
        elif comparison.get("all_match"):
            status = "synced"
        elif comparison.get("needs_completion"):
            # Synced correctly but missing required properties
            status = "needs_completion"
        else:
            status = "issues"
        
        # Add comparison info to item
        item["comparison_status"] = status
        item["comparison"] = {
            "all_match": comparison.get("all_match") if comparison else None,
            "needs_completion": comparison.get("needs_completion") if comparison else None,
            "nodes_differ_count": comparison.get("nodes_differ_count", 0) if comparison else 0,
            "edges_differ_count": comparison.get("edges_differ_count", 0) if comparison else 0,
            "embeddings_missing_count": comparison.get("embeddings_missing_count", 0) if comparison else 0,
            "required_missing_count": comparison.get("required_missing_count", 0) if comparison else 0,
            "compared_at": comparison.get("compared_at") if comparison else None,
        } if comparison else None
        
        enriched_items.append(item)
    
    # Apply status filter if provided
    if comparison_status:
        enriched_items = [
            item for item in enriched_items 
            if item["comparison_status"] == comparison_status
        ]
    
    return {"success": True, "items": enriched_items}


@router.get("/{case_id}")
def get_case(case_id: str, db: Session = Depends(get_db)):
    data = case_repo.get_case(db.connection(), case_id)
    if not data:
        raise HTTPException(404, "Not found")

    # Do not expose the last-published KG snapshot to clients; it's used only for backend diffing/logging.
    data.pop("kg_extracted", None)
    
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
        
        cleaned_payload = prepare_for_postgres_save(payload)

        updated = case_repo.update_case(db.connection(), case_id, cleaned_payload, user_id)
        db.commit()

        logger.info(f"Case {case_id} saved by {user_id} (draft save - no graph_events logged)")
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
    
    # Prefer the last published snapshot for KG cleanup/audit since it reliably contains KG IDs.
    extracted = case_data.get("kg_extracted") or case_data.get("extracted") or {}
    nodes = extracted.get("nodes", []) or []
    edges = extracted.get("edges", []) or []
    file_key = case_data.get("file_key")
    kg_submitted_at = case_data.get("kg_submitted_at")
    kg_cleanup_ok = True
    kg_cleanup_notes: List[str] = []
    
    # If case was submitted to KG, clean up Neo4j
    if kg_submitted_at is not None:
        try:
            from app.lib.neo4j_uploader import Neo4jUploader
            from app.lib.neo4j_client import neo4j_client
            from app.routes.kg import load_schema, get_case_unique_labels, get_case_node_ids
            
            schema = load_schema()
            case_unique_labels = get_case_unique_labels(schema)
            uploader = Neo4jUploader(schema, neo4j_client)
            
            # Get all node IDs in this case for detachment/isolation checks.
            # Use a robust method that can fall back to UUID temp_ids when *_id props are missing.
            case_node_ids = _get_case_node_ids_for_kg_cleanup(nodes)
            if not case_node_ids:
                kg_cleanup_ok = False
                kg_cleanup_notes.append("No node IDs found in case payload; KG cleanup may be a no-op.")
                logger.warning(f"Case {case_id} KG cleanup: case_node_ids is empty; payload may be missing *_id fields")
            
            # Process each node
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                
                label = node.get("label")
                node_id = _get_node_id_for_label(label, node, schema) if label else None
                
                if not label or not node_id:
                    continue
                
                is_existing = node.get("is_existing", False)
                
                if is_existing:
                    # Pre-existing node: detach from this case's nodes
                    try:
                        detached = uploader.detach_node_from_case(label, node_id, case_node_ids)
                        logger.info(f"Detached pre-existing node {label}:{node_id} ({detached} relationships)")
                        
                        # After detaching, check if node is now isolated and non-preset
                        # Non-preset isolated shared nodes should be deleted
                        if label not in case_unique_labels:
                            is_preset = uploader.get_node_preset(label, node_id)
                            if not is_preset:
                                has_connections = uploader.check_node_has_connections(label, node_id)
                                if not has_connections:
                                    uploader.delete_node(label, node_id)
                                    logger.info(f"Deleted isolated non-preset shared node {label}:{node_id}")
                    except Exception as e:
                        kg_cleanup_ok = False
                        kg_cleanup_notes.append(f"Failed to detach pre-existing node {label}:{node_id}: {e}")
                        logger.warning(f"Failed to detach pre-existing node {label}:{node_id}: {e}")
                elif label in case_unique_labels:
                    # Case-unique node created by this case: delete from KG if it is isolated to this case.
                    #
                    # Defensive safety: if a "case-unique" node ever ends up with external connections
                    # (bug, reuse edge-case, manual changes), avoid deleting it globally; detach it
                    # from this case instead. This matches the behavior used during /kg/submit.
                    try:
                        is_isolated = uploader.check_node_isolation(label, node_id, case_node_ids)
                        if is_isolated:
                            uploader.delete_node(label, node_id)
                            logger.info(f"Deleted case-unique node {label}:{node_id} from KG")
                        else:
                            detached = uploader.detach_node_from_case(label, node_id, case_node_ids)
                            logger.warning(
                                f"Case-unique node {label}:{node_id} has external connections; detached only ({detached} relationships)"
                            )
                    except Exception as e:
                        kg_cleanup_ok = False
                        kg_cleanup_notes.append(f"Failed to delete/detach case-unique node {label}:{node_id}: {e}")
                        logger.warning(f"Failed to delete node {label}:{node_id} from KG: {e}")
                else:
                    # Non-case-unique node created by this case: detach from this case's nodes
                    try:
                        detached = uploader.detach_node_from_case(label, node_id, case_node_ids)
                        logger.info(f"Detached non-case-unique node {label}:{node_id} ({detached} relationships)")
                        
                        # After detaching, check if node is now isolated and non-preset
                        # Non-preset isolated shared nodes should be deleted
                        is_preset = uploader.get_node_preset(label, node_id)
                        if not is_preset:
                            has_connections = uploader.check_node_has_connections(label, node_id)
                            if not has_connections:
                                uploader.delete_node(label, node_id)
                                logger.info(f"Deleted isolated non-preset shared node {label}:{node_id}")
                    except Exception as e:
                        kg_cleanup_ok = False
                        kg_cleanup_notes.append(f"Failed to detach node {label}:{node_id}: {e}")
                        logger.warning(f"Failed to detach node {label}:{node_id}: {e}")
            
            logger.info(f"Cleaned up KG for case {case_id}")
        except Exception as e:
            kg_cleanup_ok = False
            kg_cleanup_notes.append(f"Top-level KG cleanup error: {e}")
            logger.error(f"Failed to clean up KG for case {case_id}: {e}")
            # Continue with deletion even if KG cleanup fails
    
    # Log delete events only for KG-submitted cases (audit trail reflects KG mutations)
    if kg_submitted_at is not None:
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
    return {
        "success": True,
        "kgCleanupAttempted": kg_submitted_at is not None,
        "kgCleanupOk": kg_cleanup_ok,
        "kgCleanupNotes": kg_cleanup_notes,
    }


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


