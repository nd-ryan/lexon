import json
import time
from app.flow_query import QueryFlow
from app.lib.queue import redis_conn
from app.lib.logging_config import setup_logger

# Use our custom logger setup
logger = setup_logger("query-job")

def run_query_job(query: str, job_id: str):
    """
    The background job that runs the query flow.
    """
    channel_name = f"job:{job_id}"

    def publish_progress(message: str):
        """Helper function to publish progress updates."""
        progress_update = {
            "type": "progress",
            "message": message
        }
        redis_conn.publish(channel_name, json.dumps(progress_update))

    try:
        # Start timing the entire job
        job_start_time = time.time()
        logger.info(f"🚀 JOB START - Query: '{query}' for job: {job_id}")
        publish_progress("Starting query flow...")

        # Create and execute the query flow
        query_flow = QueryFlow()
        query_flow.state.query = query
        
        publish_progress("Processing query...")
        
        flow_start_time = time.time()
        # Kickoff the flow
        result = query_flow.kickoff()
        flow_duration = time.time() - flow_start_time
        total_duration = time.time() - job_start_time
        
        logger.info(f"✅ JOB RESULT - Flow completed. Duration: {flow_duration:.2f}s")
        
        final_response = {
            "success": True,
            "response": query_flow.state.response,
            "query": query,
            "execution_time": total_duration
        }
        
        # Combine the result and the end signal into a single message
        final_message = {
            "type": "end",
            "data": final_response
        }

        # Publish the final message to the job's Redis channel
        redis_conn.publish(channel_name, json.dumps(final_message))

    except Exception as e:
        logger.error(f"Error in query job {job_id}: {e}", exc_info=True)
        # Publish an error message to the channel
        error_message = json.dumps({"type": "error", "message": str(e)})
        redis_conn.publish(channel_name, error_message)
