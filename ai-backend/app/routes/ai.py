from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from fastapi.responses import StreamingResponse
from app.lib.auth import validate_stream_token_async
from app.crews.crew import create_document_processing_crew
from app.lib.security import get_api_key
import logging
import json

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(get_api_key)])
streaming_router = APIRouter()  # No API key dependency for streaming endpoints

# Import models from separate module
from app.models.search import (
    QueryRequest
)

@router.post("/import-kg/advanced")
async def import_with_direct_processing(file: UploadFile = File(...)):
    """
    Import and process documents using CrewAI agents with direct Neo4j integration.
    Uses the proven direct Neo4j approach for reliable processing.
    """
    import tempfile
    import os
    
    try:
        file_content = await file.read()
        
        # Create a temporary file to store the document
        with tempfile.NamedTemporaryFile(delete=False, suffix='.docx') as temp_file:
            temp_file.write(file_content)
            temp_file_path = temp_file.name
        
        try:
            # Use direct Neo4j approach (no MCP initialization)
            print(f"📄 Processing document: {file.filename}")
            print(f"Document processing started for: {file.filename}")
            
            # Create and execute document processing crew
            crew = create_document_processing_crew(temp_file_path, file.filename)
            
            print("🚀 Starting document processing crew...")
            result = crew.kickoff()
            
            # Extract result
            result_text = result.raw if hasattr(result, 'raw') else str(result)
            
            return {
                "success": True,
                "filename": file.filename,
                "result": result_text,
                "processing_method": "direct_neo4j",
                "message": "Document processed successfully using direct Neo4j integration"
            }
            
        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
                
    except Exception as e:
        logger.error(f"Document processing failed: {e}")
        return {
            "success": False,
            "filename": file.filename if file else "unknown",
            "error": str(e),
            "processing_method": "direct_neo4j"
        }

@router.post("/search/crew/stream")
async def enqueue_search_job(request: QueryRequest):
    """
    Accepts a search query, enqueues it as a background job,
    and returns a job ID for the client to use for retrieving results.
    """
    import uuid
    from app.lib.queue import search_queue
    from app.jobs.search_crew_job import run_search_crew

    job_id = str(uuid.uuid4())
    # Set a 10-minute timeout for the job
    search_queue.enqueue(run_search_crew, request.query, job_id, job_timeout="10m")
    
    return {"job_id": job_id}

@streaming_router.get("/search/results/{job_id}")
async def get_search_results(
    job_id: str,
    token_data: dict = Depends(validate_stream_token_async)
):
    """
    A streaming endpoint that listens to a Redis channel for results
    from a background job and streams them to the client.
    Requires valid JWT token for authentication.
    """
    from app.lib.queue import redis_conn
    import asyncio
    
    # Verify the token is for this specific job
    if token_data.get("jobId") != job_id:
        raise HTTPException(status_code=403, detail="Token not valid for this job")
    
    logger.info(f"Starting stream for job {job_id} for user {token_data.get('userId')}")

    async def event_stream():
        pubsub = redis_conn.pubsub()
        channel_name = f"job:{job_id}"
        await asyncio.to_thread(pubsub.subscribe, channel_name)
        
        try:
            while True:
                # Use asyncio.to_thread to run the blocking get_message in a separate thread
                message = await asyncio.to_thread(pubsub.get_message, ignore_subscribe_messages=True, timeout=60.0)
                if message:
                    # Decode message data
                    message_data = message['data'].decode('utf-8')
                    try:
                        data = json.loads(message_data)
                        yield f"data: {json.dumps(data)}\n\n"
                        # Stop listening if the worker signals the end
                        if data.get("type") == "end":
                            # Add a small delay to ensure the final message is fully delivered
                            await asyncio.sleep(0.1)
                            break
                    except json.JSONDecodeError:
                        logger.warning(f"Received non-JSON message on channel {channel_name}: {message_data}")

                # Prevent busy-waiting
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            # This is expected when the client disconnects
            logger.info(f"Client disconnected from job {job_id}")
            raise
        finally:
            # Clean up the subscription
            logger.info(f"Closing pubsub for job {job_id}")
            pubsub.unsubscribe(channel_name)
            pubsub.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream")

