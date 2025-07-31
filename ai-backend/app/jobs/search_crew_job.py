import os
import json
import time
from app.flow_search import SearchFlow
from app.lib.queue import redis_conn
from app.lib.logging_config import setup_logger

# Use our custom logger setup
logger = setup_logger("search-job")

def run_search_crew(query: str, job_id: str):
    """
    The background job that runs the search flow.
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
        publish_progress("Starting search flow...")

        # Create and execute the search flow
        setup_start_time = time.time()
        search_flow = SearchFlow()
        
        # Following CrewAI Flows pattern: set query in state before kickoff
        logger.info(f"⚙️ JOB SETUP - Setting query in flow state: '{query}'")
        search_flow.state.query = query
        setup_duration = time.time() - setup_start_time
        logger.info(f"⏱️ Setup completed in {setup_duration:.2f}s")
        
        publish_progress("Flow initialized. Starting search execution...")
        
        logger.info(f"🚀 JOB KICKOFF - About to call flow.kickoff() with query in state")
        # Use CrewAI Flows pattern - kickoff without inputs since query is in state
        flow_start_time = time.time()
        result = search_flow.kickoff()
        flow_duration = time.time() - flow_start_time
        total_duration = time.time() - job_start_time
        
        logger.info(f"✅ JOB RESULT - Flow completed, result type: {type(result)}")
        logger.info(f"⏱️ Flow execution: {flow_duration:.2f}s, Total job duration: {total_duration:.2f}s")

        # The SearchFlow returns a StructuredSearchResponse directly
        publish_progress("Analysis complete. Finalizing results...")
        
        # Convert result to dict format for JSON serialization
        if hasattr(result, 'model_dump'):
            final_response = result.model_dump()
        elif hasattr(result, 'dict'):
            final_response = result.dict()
        else:
            # Fallback for unexpected result format
            final_response = {
                "success": False,
                "explanation": f"Unexpected result format: {str(result)}",
                "raw_results": [],
                "cypher_queries": [],
                "query": query,
            }
        
        # Combine the result and the end signal into a single message
        final_message = {
            "type": "end",
            "data": final_response
        }

        # Publish the final message to the job's Redis channel
        redis_conn.publish(channel_name, json.dumps(final_message))

    except Exception as e:
        logger.error(f"Error in search flow job {job_id}: {e}", exc_info=True)
        # Publish an error message to the channel
        error_message = json.dumps({"type": "error", "message": str(e)})
        redis_conn.publish(channel_name, error_message) 