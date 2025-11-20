from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.lib.auth import validate_stream_token_async
from app.lib.security import get_api_key
import logging
import json
import uuid
import asyncio

logger = logging.getLogger(__name__)

# Create the router
# Prefix is /query so it becomes /api/v1/query
router = APIRouter(prefix="/query", tags=["query"])

class QueryRequest(BaseModel):
    query: str

@router.post("/stream")
async def start_query_stream(request: QueryRequest, api_key: str = Depends(get_api_key)):
    """
    Start a query stream job.
    Returns a job_id that can be used to subscribe to the results.
    """
    from app.lib.queue import search_queue
    from app.jobs.query_job import run_query_job

    job_id = str(uuid.uuid4())
    # Enqueue the job
    search_queue.enqueue(run_query_job, request.query, job_id, job_timeout="10m")
    
    return {"job_id": job_id}

@router.get("/results/{job_id}")
async def get_query_results(
    job_id: str,
    token_data: dict = Depends(validate_stream_token_async)
):
    """
    Stream results for a specific query job.
    Requires a valid stream token.
    """
    from app.lib.queue import redis_conn
    
    # Verify the token is for this specific job
    if token_data.get("jobId") != job_id:
        raise HTTPException(status_code=403, detail="Token not valid for this job")
    
    logger.info(f"Starting query stream for job {job_id}")

    async def event_stream():
        pubsub = redis_conn.pubsub()
        channel_name = f"job:{job_id}"
        await asyncio.to_thread(pubsub.subscribe, channel_name)
        
        try:
            while True:
                message = await asyncio.to_thread(pubsub.get_message, ignore_subscribe_messages=True, timeout=60.0)
                if message:
                    message_data = message['data'].decode('utf-8')
                    try:
                        data = json.loads(message_data)
                        yield f"data: {json.dumps(data)}\n\n"
                        
                        if data.get("type") == "end" or data.get("type") == "error":
                            # Small delay to ensure delivery
                            await asyncio.sleep(0.1)
                            break
                    except json.JSONDecodeError:
                        logger.warning(f"Received non-JSON message: {message_data}")

                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.info(f"Client disconnected from job {job_id}")
            raise
        finally:
            logger.info(f"Closing pubsub for job {job_id}")
            pubsub.unsubscribe(channel_name)
            pubsub.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream")
