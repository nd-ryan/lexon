"""API routes for case comparison operations (admin only)."""

import uuid
import json
import asyncio
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.lib.security import get_api_key
from app.lib.db import get_db
from app.lib.queue import comparison_queue, redis_conn
from app.lib.comparison_repo import comparison_repo
from app.lib.case_repo import case_repo
from app.lib.logging_config import setup_logger


logger = setup_logger("comparisons-route")

# Router with API key dependency (admin access enforced at Next.js proxy layer)
router = APIRouter(prefix="/admin/comparisons", dependencies=[Depends(get_api_key)])


class BatchComparisonRequest(BaseModel):
    """Request body for batch comparison."""
    case_ids: Optional[List[str]] = None  # None means all KG-submitted cases
    force: bool = False  # Force re-run even if fresh


class SingleComparisonRequest(BaseModel):
    """Request body for single case comparison."""
    force: bool = False


@router.post("/batch")
async def start_batch_comparison(
    request: BatchComparisonRequest,
    db: Session = Depends(get_db),
):
    """
    Start a batch comparison job for multiple cases.
    
    Returns job_id for progress tracking.
    """
    job_id = str(uuid.uuid4())
    
    conn = db.connection()
    
    # Determine which cases to compare
    case_ids = request.case_ids
    if case_ids is None:
        # Get all KG-submitted cases
        from sqlalchemy import text
        import os, re
        _schema_raw = os.getenv("POSTGRES_SCHEMA", "public")
        schema = _schema_raw if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", _schema_raw or "") else "public"
        result = conn.execute(text(
            f"SELECT id FROM {schema}.cases WHERE kg_submitted_at IS NOT NULL ORDER BY updated_at DESC"
        ))
        case_ids = [str(row[0]) for row in result]
    
    if not case_ids:
        return {
            "job_id": job_id,
            "queued_count": 0,
            "message": "No cases to compare"
        }
    
    # Queue the batch job
    from app.jobs.comparison_job import run_batch_comparisons
    comparison_queue.enqueue(
        run_batch_comparisons,
        job_id,
        case_ids,
        request.force,
        job_timeout=3600,  # 1 hour timeout for large batches
    )
    
    logger.info(f"Queued batch comparison job {job_id} with {len(case_ids)} cases")
    
    return {
        "job_id": job_id,
        "queued_count": len(case_ids),
        "message": f"Queued {len(case_ids)} cases for comparison"
    }


@router.get("/progress/{job_id}")
async def stream_batch_progress(job_id: str):
    """
    SSE endpoint for streaming batch comparison progress.
    """
    async def event_generator():
        pubsub = redis_conn.pubsub()
        channel = f"comparison_batch:{job_id}"
        pubsub.subscribe(channel)
        
        try:
            # Initial connection message
            yield f"data: {json.dumps({'type': 'connected', 'job_id': job_id})}\n\n"
            
            while True:
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                
                if message and message["type"] == "message":
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    
                    yield f"data: {data}\n\n"
                    
                    # Check for end message
                    try:
                        parsed = json.loads(data)
                        if parsed.get("type") == "end":
                            break
                    except json.JSONDecodeError:
                        pass
                
                # Small sleep to prevent tight loop
                await asyncio.sleep(0.1)
                
        finally:
            pubsub.unsubscribe(channel)
            pubsub.close()
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/{case_id}")
async def get_comparison_result(
    case_id: str,
    db: Session = Depends(get_db),
):
    """
    Get the comparison result for a single case.
    """
    conn = db.connection()
    
    # Verify case exists
    case_data = case_repo.get_case(conn, case_id)
    if not case_data:
        raise HTTPException(status_code=404, detail="Case not found")
    
    updated_at = case_data.get("updated_at")
    kg_submitted_at = case_data.get("kg_submitted_at")
    
    # Check if not in KG
    if not kg_submitted_at:
        return {
            "exists": False,
            "case_id": case_id,
            "is_pending_sync": False,
            "not_in_kg": True,
            "message": "Case has not been submitted to Knowledge Graph"
        }
    
    # Check if pending sync (Postgres updated after KG submit)
    is_pending_sync = bool(updated_at and kg_submitted_at and updated_at > kg_submitted_at)
    
    # Get comparison result
    result = comparison_repo.get_comparison(conn, case_id)
    
    if not result:
        return {
            "exists": False,
            "case_id": case_id,
            "is_pending_sync": is_pending_sync,
            "message": "No comparison result available"
        }
    
    # Check if stale (comparison is outdated)
    is_stale = comparison_repo.is_stale(
        result,
        updated_at,
        kg_submitted_at,
    )
    
    return {
        "exists": True,
        "is_stale": is_stale,
        "is_pending_sync": is_pending_sync,
        **result
    }


@router.post("/{case_id}")
async def run_single_comparison(
    case_id: str,
    request: SingleComparisonRequest,
    db: Session = Depends(get_db),
):
    """
    Run comparison for a single case (synchronous, returns result).
    """
    conn = db.connection()
    
    # Verify case exists
    case_data = case_repo.get_case(conn, case_id)
    if not case_data:
        raise HTTPException(status_code=404, detail="Case not found")
    
    # Check if case has been submitted to KG
    if not case_data.get("kg_submitted_at"):
        raise HTTPException(
            status_code=400, 
            detail="Case has not been submitted to Knowledge Graph"
        )
    
    # Run comparison (synchronous for single case)
    from app.jobs.comparison_job import compare_single_case
    result = compare_single_case(case_id, force=request.force)
    
    if result is None:
        raise HTTPException(
            status_code=500,
            detail="Comparison failed - check logs for details"
        )
    
    return {
        "success": True,
        **result
    }

