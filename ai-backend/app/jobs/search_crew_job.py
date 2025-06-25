import os
import json
from app.crews.crew import create_specialized_search_crew
from app.crews.agents import MCPEnabledAgents, get_mcp_tools
from app.lib.queue import redis_conn
import logging

logger = logging.getLogger(__name__)

def run_search_crew(query: str, job_id: str):
    """
    The background job that runs the specialized search crew.
    """
    channel_name = f"job:{job_id}"

    def publish_progress(message: str):
        """Helper function to publish progress updates."""
        progress_update = {
            "type": "progress",
            "message": message
        }
        redis_conn.publish(channel_name, json.dumps(progress_update))
        logger.info(f"Published progress for job {job_id}: {message}")

    try:
        publish_progress("Starting specialized search crew...")

        # Define a callback for logging agent steps and publishing progress
        def step_callback(agent_action):
            # A more detailed message can be constructed if the action object structure is known
            # For now, we'll use a generic message based on the string representation
            message = f"Processing step: {str(agent_action)}"
            publish_progress(message)

        with MCPEnabledAgents() as mcp_context:
            neo4j_mcp_tools = get_mcp_tools()
            if not neo4j_mcp_tools:
                publish_progress("Error: MCP tools are not available. Aborting job.")
                raise ValueError("Job failed: MCP tools are not available.")

            publish_progress("MCP tools loaded. Assembling specialized crew...")

            crew = create_specialized_search_crew(
                query,
                neo4j_mcp_tools,
                step_callback=step_callback
            )
            
            publish_progress("Crew assembled. Starting analysis...")
            result = crew.kickoff()

            if hasattr(result, 'pydantic') and result.pydantic:
                final_response = result.pydantic
            else:
                # Handle fallback if Pydantic model fails
                final_response = {
                    "explanation": f"The agent failed to return a structured Pydantic response. The final raw output was: {result.raw if hasattr(result, 'raw') else str(result)}",
                    "raw_results": [],
                    "cypher_queries": [],
                    "query": query,
                }
            
            publish_progress("Analysis complete. Finalizing results...")
            
            # Combine the result and the end signal into a single message
            final_message = {
                "type": "end",
                "data": final_response.model_dump() if hasattr(final_response, 'model_dump') else final_response
            }

            # Publish the final message to the job's Redis channel
            redis_conn.publish(channel_name, json.dumps(final_message))
            logger.info(f"Successfully published final result for job {job_id} to channel {channel_name}")

    except Exception as e:
        logger.error(f"Error in search crew job {job_id}: {e}", exc_info=True)
        # Publish an error message to the channel
        error_message = json.dumps({"type": "error", "message": str(e)})
        redis_conn.publish(channel_name, error_message)
    finally:
        # The 'end' message is now part of the successful result payload,
        # so we don't need a separate publish here.
        # If an error occurs, the error message above will be sent.
        # A final 'end' could be sent in all cases, but this is cleaner for the happy path.
        pass 