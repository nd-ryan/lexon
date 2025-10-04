"""Background job for case extraction with progress updates via Redis pub/sub."""
import os
import json
import asyncio
from app.lib.queue import redis_conn
from app.lib.logging_config import setup_logger
from app.lib.db import SessionLocal
from app.lib.case_repo import case_repo


logger = setup_logger("case-extraction-job")


def publish_progress(job_id: str, message: str, phase: str = "", progress: int = 0):
    """Publish progress update to Redis channel."""
    try:
        redis_conn.publish(
            f"job:{job_id}",
            json.dumps({
                "type": "progress",
                "message": message,
                "phase": phase,
                "progress": progress,
            })
        )
    except Exception as e:
        logger.error(f"Failed to publish progress: {e}")


def publish_complete(job_id: str, case_id: str):
    """Publish completion message to Redis channel."""
    try:
        redis_conn.publish(
            f"job:{job_id}",
            json.dumps({
                "type": "complete",
                "caseId": case_id,
                "message": "Case extraction completed successfully",
            })
        )
        redis_conn.publish(f"job:{job_id}", json.dumps({"type": "end"}))
    except Exception as e:
        logger.error(f"Failed to publish completion: {e}")


def publish_error(job_id: str, error: str):
    """Publish error message to Redis channel."""
    try:
        redis_conn.publish(
            f"job:{job_id}",
            json.dumps({
                "type": "error",
                "message": error,
            })
        )
        redis_conn.publish(f"job:{job_id}", json.dumps({"type": "end"}))
    except Exception as e:
        logger.error(f"Failed to publish error: {e}")


def run_case_extraction(job_id: str, filename: str, file_extension: str, case_id: str):
    """Run case extraction flow and publish progress updates."""
    logger.info(f"Starting case extraction job {job_id} for case {case_id}")
    logger.info(f"Redis connection: {redis_conn}")
    
    # Retrieve file content from Redis
    redis_key = f"file_upload:{job_id}"
    file_bytes = redis_conn.get(redis_key)
    
    if not file_bytes:
        error_msg = f"File content not found in Redis: {redis_key}"
        logger.error(error_msg)
        publish_error(job_id, error_msg)
        return
    
    logger.info(f"Retrieved file content from Redis: {len(file_bytes)} bytes")
    
    # Create temporary file on this worker instance
    import tempfile
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=file_extension, prefix=f"case_extraction_{job_id}_")
    try:
        with os.fdopen(tmp_fd, 'wb') as tmp_file:
            tmp_file.write(file_bytes)
        logger.info(f"Created local temp file: {tmp_path}, size: {len(file_bytes)} bytes")
    except Exception as e:
        os.close(tmp_fd)
        error_msg = f"Failed to create temp file: {e}"
        logger.error(error_msg)
        publish_error(job_id, error_msg)
        return
    
    # Delete from Redis now that we have it locally
    try:
        redis_conn.delete(redis_key)
        logger.info(f"Deleted file content from Redis: {redis_key}")
    except Exception as e:
        logger.warning(f"Failed to delete Redis key {redis_key}: {e}")
    
    try:
        publish_progress(job_id, f"Starting extraction for {filename}", "init", 0)
        logger.info(f"Published initial progress for job {job_id}")
    except Exception as e:
        logger.error(f"Failed to publish initial progress: {e}", exc_info=True)
    
    try:
        # Import flow
        from app.flow_cases import CaseExtractFlow  # type: ignore
        
        publish_progress(job_id, "Initializing extraction flow", "init", 5)
        
        # Create and configure flow
        flow = CaseExtractFlow()
        flow.state.file_path = tmp_path
        flow.state.filename = filename
        flow.state.case_id = case_id
        
        # Set progress callback so the flow can publish updates
        flow.state.progress_callback = lambda msg, phase, pct: publish_progress(job_id, msg, phase, pct)
        
        publish_progress(job_id, "Reading document and preparing schema", "phase0", 10)
        
        # Run flow asynchronously (CrewAI flows support async)
        async def run_async_flow():
            return await flow.kickoff_async()
        
        # Execute in event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Periodically publish progress during execution
            publish_progress(job_id, "Extracting case-unique nodes (Phase 1)", "phase1", 20)
            result = loop.run_until_complete(run_async_flow())
        finally:
            loop.close()
        
        publish_progress(job_id, "Saving extraction results", "saving", 90)
        
        # Save results to database
        db = SessionLocal()
        try:
            case_repo.save_extraction(db.connection(), case_id, result)
            db.commit()
        finally:
            db.close()
        
        publish_progress(job_id, "Extraction completed", "complete", 100)
        publish_complete(job_id, case_id)
        
        logger.info(f"Case extraction job {job_id} completed successfully")
        
    except Exception as e:
        logger.exception(f"Case extraction job {job_id} failed")
        publish_error(job_id, f"Extraction failed: {str(e)}")
        raise
    finally:
        # Clean up temporary file
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
                logger.info(f"Cleaned up temp file: {tmp_path}")
            except Exception as e:
                logger.warning(f"Failed to clean up temp file {tmp_path}: {e}")

