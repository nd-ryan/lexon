from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlalchemy.orm import Session
from app.lib.security import get_api_key
from app.lib.db import get_db
from app.lib.case_repo import case_repo
from app.lib.property_filter import filter_case_data, filter_display_data
import tempfile
import os
import logging
import uuid


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cases", dependencies=[Depends(get_api_key)])


@router.post("/upload")
async def upload_case(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Start async case extraction job and return job_id for progress tracking."""
    try:
        file_bytes = await file.read()
        file_extension = os.path.splitext(file.filename)[1] or '.docx'
        
        logger.info(f"Received file upload: {file.filename}, size: {len(file_bytes)} bytes")

        # Create case record
        case_id = case_repo.create_case(db.connection(), file.filename)
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
def update_case(case_id: str, payload: dict, db: Session = Depends(get_db)):
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
        
        user_id = "editor"  # TODO: integrate auth user
        cleaned_payload = prepare_for_postgres_save(payload)
        updated = case_repo.update_case(db.connection(), case_id, cleaned_payload, user_id)
        db.commit()
        logger.info(f"Case {case_id} saved successfully by {user_id}")
        return {"success": True, "case": updated}
    except HTTPException:
        # Re-raise HTTPExceptions (like validation errors) without wrapping
        raise
    except Exception as e:
        logger.error(f"Case {case_id} save failed with unexpected error: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to save case: {str(e)}")


@router.delete("/{case_id}")
def delete_case(case_id: str, db: Session = Depends(get_db)):
    ok = case_repo.delete_case(db.connection(), case_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    db.commit()
    return {"success": True}


