from crewai.flow.flow import Flow, listen, start
from app.lib.mcp_integration import MCPEnabledAgents, get_mcp_tools
from app.lib.callbacks import agent_step_callback
from .crews.search_crew.search_crew import SearchCrew
from app.models.search import StructuredSearchResponse, QueryExecutionResults, SearchInsights, FinalSearchResponse
from app.lib.logging_config import setup_logger
from typing import Dict, Any, Optional
from pydantic import BaseModel
import time

# Use our custom logger setup
logger = setup_logger("search-flow")


class SearchState(BaseModel):
    """
    Pydantic model for structured state management in SearchFlow.
    """
    query: str = ""
    neo4j_schema: Optional[Any] = None


class SearchFlow(Flow[SearchState]):
    """
    Flow for handling search queries against the Neo4j knowledge graph.
    
    This flow orchestrates the search process using MCP tools directly and the SearchCrew.
    The schema retrieval is done as a direct MCP tool call rather than using an agent.
    """

    @start()
    def search_kickoff(self) -> Dict[str, Any]:
        """
        Initialize the search flow with a user query from flow state.
        The query should be set in state before calling kickoff().
        
        Returns:
            Dict containing the query and initialization status
        """
        
        # Get query from state (should be set before kickoff)
        query = self.state.query
        
        return {
            "query": query,
            "status": "initialized"
        }

    @listen(search_kickoff)
    def execute_search_with_schema(self, context: Dict[str, Any]) -> StructuredSearchResponse:
        """
        Execute the complete search flow with schema retrieval and crew execution in a single MCP connection.
        This eliminates the need for two separate MCP connections and improves efficiency.
        
        Args:
            context: Context from the previous step containing the query
            
        Returns:
            StructuredSearchResponse: The search results
        """
        # Get query from flow state (CrewAI Flows pattern)
        query = self.state.query
        flow_start_time = time.time()
        logger.info(f"🔌 STARTING SEARCH FLOW - Query: '{query}'")
        
        # Reset agent timing for this search job
        from app.lib.callbacks import reset_agent_timing
        reset_agent_timing()
        
        # Use single MCP context manager for the entire search operation
        with MCPEnabledAgents() as mcp_context:
            if not mcp_context.mcp_adapter:
                raise RuntimeError("Failed to initialize MCP tools")
            
            # Get the Neo4j MCP tools once for both schema and execution
            neo4j_tools = get_mcp_tools()
            
            # Step 1: Retrieve schema using MCP tools directly
            schema_start_time = time.time()
            logger.info("📊 Retrieving Neo4j schema")
            schema_tool = None
            for tool in neo4j_tools:
                if 'schema' in tool.name.lower():
                    schema_tool = tool
                    break
            
            if not schema_tool:
                raise RuntimeError("Neo4j schema tool not found in MCP tools")
            
            try:
                # Call the MCP schema tool directly
                logger.info(f"Calling MCP schema tool: {schema_tool.name}")
                schema_result = schema_tool.run({})
                
                # Store schema in state
                self.state.neo4j_schema = schema_result
                
                schema_duration = time.time() - schema_start_time
                logger.info(f"✅ Schema retrieved successfully")
                logger.info(f"⏱️ Schema retrieval completed in {schema_duration:.2f}s")
                logger.debug(f"Schema preview: {str(schema_result)[:200]}...")
                
            except Exception as e:
                schema_duration = time.time() - schema_start_time
                logger.error(f"❌ Error retrieving schema: {e} (took {schema_duration:.2f}s)")
                raise RuntimeError(f"Failed to retrieve Neo4j schema: {e}")
            
            # Step 2: Execute search crew with the same MCP connection
            crew_start_time = time.time()
            logger.info(f"🧠 EXECUTE_SEARCH - Query: '{query}'")
            logger.info(f"Executing search crew for query: {query}")
            
            # Create and run the search crew with pre-retrieved schema
            search_crew = SearchCrew(
                query=query,
                schema=schema_result,
                neo4j_mcp_tools=neo4j_tools,
                step_callback=agent_step_callback
            )
            
            # Execute the crew
            crew_instance = search_crew.crew()
            result = crew_instance.kickoff()
            
            crew_duration = time.time() - crew_start_time
            total_flow_duration = time.time() - flow_start_time
            
            # Access individual task results to combine them properly
            # The crew has 3 tasks in order: query_generation, query_execution, insights_synthesis
            # We need results from query_execution (raw data) and insights_synthesis (summary)
            try:
                # Get the execution results from the query_execution_task (index 1)
                execution_task_output = crew_instance.tasks[1].output
                # Get the insights from the insights_synthesis_task (index 2) 
                insights_task_output = crew_instance.tasks[2].output
                
                logger.info(f"🔍 Execution task output type: {type(execution_task_output)}")
                logger.info(f"🔍 Insights task output type: {type(insights_task_output)}")
                
                # Access the actual Pydantic models from the TaskOutput objects
                execution_pydantic = execution_task_output.pydantic  # QueryExecutionResults
                insights_pydantic = insights_task_output.pydantic    # SearchInsights
                
                logger.info(f"🔍 Execution pydantic type: {type(execution_pydantic)}")
                logger.info(f"🔍 Insights pydantic type: {type(insights_pydantic)}")
                
                # Use the search crew's combine_results method to properly merge the data
                final_result = search_crew.combine_results(execution_pydantic, insights_pydantic)
                
                # Convert to dict for StructuredSearchResponse
                result_data = final_result.model_dump()
                logger.info("✅ Successfully combined task results")
                
            except Exception as e:
                logger.error(f"❌ Error accessing individual task results: {e}")
                logger.info("🔄 Falling back to final task result only")
                
                # Fallback to using the final result (insights only)
                if hasattr(result, 'model_dump'):
                    insights_data = result.model_dump()
                    # Create a minimal response with just the summary
                    result_data = {
                        "success": True,
                        "explanation": insights_data.get("summary", "No summary available"),
                        "raw_results": [],
                        "cypher_queries": [],
                        "query": query,
                    }
                else:
                    result_data = {
                        "success": False,
                        "explanation": f"Could not process results: {str(result)}",
                        "raw_results": [],
                        "cypher_queries": [],
                        "query": query,
                    }
            
            # Create StructuredSearchResponse with execution time
            final_response = StructuredSearchResponse(
                success=result_data.get("success", True),
                explanation=result_data.get("explanation", "No explanation available"),
                raw_results=result_data.get("raw_results", []),
                cypher_queries=result_data.get("cypher_queries", []),
                query=query,
                execution_time=total_flow_duration
            )
            
            logger.info("✅ Search crew execution completed")
            logger.info(f"⏱️ Crew execution: {crew_duration:.2f}s, Total flow: {total_flow_duration:.2f}s")
            return final_response


# Factory function for backward compatibility
def create_search_flow() -> SearchFlow:
    """
    Factory function to create a SearchFlow instance.
    
    Returns:
        SearchFlow: A new search flow instance
    """
    return SearchFlow() 