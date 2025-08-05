from crewai import Agent, Task, Crew
from crewai.project import CrewBase
from app.models.search import GeneratedCypherQuery, QueryExecutionResults, SearchInsights, StructuredSearchResponse
from crewai.flow.flow import Flow, listen, start
from app.lib.mcp_integration import MCPEnabledAgents, get_mcp_tools
from app.lib.logging_config import setup_logger
from typing import Dict, Any, Optional
from pydantic import BaseModel
import time
import yaml
import json

# Use our custom logger setup
logger = setup_logger("search-flow")


class SearchState(BaseModel):
    """
    Pydantic model for structured state management in SearchFlow.
    """
    query: str = ""
    neo4j_schema: Optional[Any] = None
    generated_queries: Optional[GeneratedCypherQuery] = None
    enhanced_queries: Optional[GeneratedCypherQuery] = None
    execution_results: Optional[QueryExecutionResults] = None
    insights: Optional[SearchInsights] = None
    # Keep track of timing
    start_time: float = 0.0
    schema_time: float = 0.0
    query_gen_time: float = 0.0
    query_enhancement_time: float = 0.0
    execution_time: float = 0.0
    insights_time: float = 0.0
    total_time: float = 0.0


class SearchFlow(Flow[SearchState]):
    """
    Flow for handling search queries against the Neo4j knowledge graph.
    
    This flow orchestrates the search process using a sequence of individual agents,
    rather than a single, monolithic crew. This provides better state management and
    more granular control over the workflow.
    """
    def __init__(self, **data):
        super().__init__(**data)
        # Load agent and task definitions from YAML files
        with open('app/flow_search/crews/search_crew/config/agents.yaml', 'r') as f:
            self.agents_config = yaml.safe_load(f)
        with open('app/flow_search/crews/search_crew/config/tasks.yaml', 'r') as f:
            self.tasks_config = yaml.safe_load(f)

    @start()
    def search_kickoff(self) -> Dict[str, Any]:
        """
        Initialize the search flow with a user query from flow state.
        The query should be set in state before calling kickoff().
        """
        logger.info(f"🔌 STARTING SEARCH FLOW - Query: '{self.state.query}'")
        self.state.start_time = time.time()
        # Reset agent timing for this search job
        from app.lib.callbacks import reset_agent_timing
        reset_agent_timing()
        return {"status": "initialized"}

    @listen(search_kickoff)
    def retrieve_schema(self, context: Dict[str, Any]) -> None:
        """
        Retrieve the Neo4j schema using MCP tools.
        """
        with MCPEnabledAgents() as mcp_context:
            if not mcp_context.mcp_adapter:
                raise RuntimeError("Failed to initialize MCP tools")

            neo4j_tools = get_mcp_tools()
            schema_tool = next((t for t in neo4j_tools if 'schema' in t.name.lower()), None)

            if not schema_tool:
                raise RuntimeError("Neo4j schema tool not found")
            
            logger.info("📊 Retrieving Neo4j schema...")
            schema_start_time = time.time()
            try:
                schema_result = schema_tool.run({})
                self.state.neo4j_schema = schema_result
                self.state.schema_time = time.time() - schema_start_time
                logger.info(f"✅ Schema retrieved successfully in {self.state.schema_time:.2f}s")
                logger.info(f"📊 Schema content: {schema_result}")
            except Exception as e:
                logger.error(f"❌ Error retrieving schema: {e}")
                raise

    @listen(retrieve_schema)
    async def generate_cypher_queries(self) -> None:
        """
        Generate Cypher queries using the query_generation_agent.
        """
        logger.info("🧠 Generating Cypher queries...")
        query_gen_start_time = time.time()

        agent = Agent(config=self.agents_config['query_generation_agent'], tools=[], llm="gpt-4.1")
        
        task_description = self.tasks_config['query_generation_task']['description'].format(
            query=self.state.query,
            schema=self.state.neo4j_schema
        )
        
        result = await agent.kickoff_async(task_description, response_format=GeneratedCypherQuery)
        
        if result.pydantic:
            self.state.generated_queries = result.pydantic
            logger.info(f"🧠 Generated Cypher query:")
            logger.info(f"   {result.pydantic.generated_query}")
        else:
            # Handle case where Pydantic model is not returned
            # For now, we'll raise an error, but you could also have fallback logic
            raise ValueError("Query generation did not return a valid Pydantic model.")

        self.state.query_gen_time = time.time() - query_gen_start_time
        logger.info(f"✅ Cypher queries generated in {self.state.query_gen_time:.2f}s")

    @listen(generate_cypher_queries)
    async def enhance_cypher_query(self) -> None:
        """
        Enhance the generated Cypher queries using the query_enhancement_agent.
        """
        logger.info("🔄 Enhancing Cypher queries...")
        query_enhancement_start_time = time.time()

        agent = Agent(config=self.agents_config['query_enhancement_agent'], tools=[], llm="gpt-4.1")
        
        task_description = self.tasks_config['query_enhancement_task']['description'].format(
            initial_query_json=self.state.generated_queries.model_dump(),
            schema=self.state.neo4j_schema
        )
        
        result = await agent.kickoff_async(task_description, response_format=GeneratedCypherQuery)
        
        if result.pydantic:
            self.state.enhanced_queries = result.pydantic
            logger.info(f"🔄 Enhanced Cypher query:")
            logger.info(f"   {result.pydantic.generated_query}")
        else:
            # Handle case where Pydantic model is not returned
            # For now, we'll raise an error, but you could also have fallback logic
            raise ValueError("Query enhancement did not return a valid Pydantic model.")

        self.state.query_enhancement_time = time.time() - query_enhancement_start_time
        logger.info(f"✅ Cypher queries enhanced in {self.state.query_enhancement_time:.2f}s")

    @listen(enhance_cypher_query)
    async def execute_cypher_queries(self) -> None:
        """
        Execute the generated Cypher queries using the Neo4j MCP tool directly.
        If the first query returns no results, generate alternative queries and retry (up to 3 attempts).
        """
        logger.info("⚙️ Executing Cypher queries...")
        execution_start_time = time.time()

        with MCPEnabledAgents() as mcp_context:
            neo4j_tools = get_mcp_tools()
            cypher_tool = next((t for t in neo4j_tools if 'cypher' in t.name.lower()), None)
            
            if not cypher_tool:
                raise RuntimeError("Neo4j Cypher tool not found in MCP tools")
            
            # Try up to 3 different queries
            max_attempts = 3
            current_attempt = 1
            successful_results = None
            executed_queries = []
            
            while current_attempt <= max_attempts:
                logger.info(f"🔄 Attempt {current_attempt}/{max_attempts}")
                
                # Get the current query (either enhanced or regenerated)
                if current_attempt == 1:
                    # Use the enhanced query from the previous step
                    current_query = self.state.enhanced_queries
                else:
                    # Generate a new query based on previous failure
                    logger.info("🔄 Generating alternative query due to no results...")
                    current_query = await self._generate_alternative_query(current_attempt)
                
                # Execute the current query directly using the MCP tool
                try:
                    cypher_query = current_query.generated_query
                    logger.info(f"🔍 Executing Cypher query (attempt {current_attempt}):")
                    logger.info(f"   {cypher_query}")
                    
                    # Based on the error message, the tool expects a 'query' field
                    # Try with the standard MCP tool parameter structure
                    result = cypher_tool.run(query=cypher_query)
                    
                    # Parse the JSON string result into a Python list
                    if isinstance(result, str):
                        try:
                            parsed_result = json.loads(result)
                        except json.JSONDecodeError as e:
                            logger.error(f"❌ Failed to parse JSON result: {e}")
                            parsed_result = []
                    else:
                        parsed_result = result
                    
                    executed_queries.append(cypher_query)
                    
                    # Check if the result is an error message (string) or actual results (list)
                    if isinstance(result, str) and result.startswith("Error"):
                        logger.error(f"❌ Query attempt {current_attempt} failed with MCP error: {result}")
                        if current_attempt < max_attempts:
                            logger.info("🔄 Will try alternative query...")
                        else:
                            logger.warning("❌ All query attempts failed - proceeding with empty results")
                            successful_results = QueryExecutionResults(
                                success=False,
                                raw_results=[],
                                cypher_queries=executed_queries
                            )
                    elif isinstance(parsed_result, list) and len(parsed_result) > 0:
                        logger.info(f"✅ Query attempt {current_attempt} successful with {len(parsed_result)} results")
                        successful_results = QueryExecutionResults(
                            success=True,
                            raw_results=parsed_result,
                            cypher_queries=executed_queries
                        )
                        break
                    else:
                        logger.warning(f"⚠️ Query attempt {current_attempt} returned no results")
                        if current_attempt < max_attempts:
                            logger.info("🔄 Will try alternative query...")
                        else:
                            logger.warning("❌ All query attempts failed - proceeding with empty results")
                            successful_results = QueryExecutionResults(
                                success=False,
                                raw_results=[],
                                cypher_queries=executed_queries
                            )
                except Exception as e:
                    logger.error(f"❌ Query attempt {current_attempt} failed with error: {e}")
                    if current_attempt < max_attempts:
                        logger.info("🔄 Will try alternative query...")
                    else:
                        raise RuntimeError(f"All query attempts failed: {e}")
                
                current_attempt += 1
            
            # Store the final results (successful or empty)
            self.state.execution_results = successful_results
            self.state.execution_time = time.time() - execution_start_time
            logger.info(f"✅ Cypher queries executed in {self.state.execution_time:.2f}s (attempts: {current_attempt-1})")

    async def _generate_alternative_query(self, attempt_number: int) -> GeneratedCypherQuery:
        """
        Generate an alternative Cypher query when the previous one returned no results.
        
        Args:
            attempt_number: Which attempt this is (2 or 3)
            
        Returns:
            GeneratedCypherQuery: A new query to try
        """
        agent = Agent(config=self.agents_config['query_generation_agent'], tools=[], llm="gpt-4.1")
        
        alternative_prompts = {
            2: "The previous query returned no results. Generate a more general/broader Cypher query that might find related information. Consider using more flexible matching patterns or searching across more node types.",
            3: "The previous queries returned no results. Generate a very broad Cypher query that searches across all node types with very loose matching criteria. Focus on finding any potentially relevant information."
        }
        
        prompt = alternative_prompts.get(attempt_number, "Generate an alternative Cypher query.")
        
        task_description = f"""
        {self.tasks_config['query_generation_task']['description'].format(
            query=self.state.query,
            schema=self.state.neo4j_schema
        )}
        
        IMPORTANT: {prompt}
        
        Make sure your query is different from previous attempts and uses different search strategies.
        """
        
        result = await agent.kickoff_async(task_description, response_format=GeneratedCypherQuery)
        
        if result.pydantic:
            logger.info(f"🔄 Generated alternative Cypher query (attempt {attempt_number}):")
            logger.info(f"   {result.pydantic.generated_query}")
            return result.pydantic
        else:
            raise ValueError(f"Alternative query generation attempt {attempt_number} failed")

    @listen(execute_cypher_queries)
    async def synthesize_insights(self) -> None:
        """
        Synthesize insights from the query results using the insights_synthesis_agent.
        """
        logger.info("✍️ Synthesizing insights...")
        insights_start_time = time.time()
        
        agent = Agent(config=self.agents_config['insights_synthesis_agent'], tools=[], llm="gpt-4.1")
        
        task_input = self.state.execution_results.model_dump()
        task_description = self.tasks_config['insights_synthesis_task']['description'].replace(
            '"{query}"', f'"{self.state.query}"'
        ).format(execution_results_json=task_input)

        result = await agent.kickoff_async(task_description, response_format=SearchInsights)
        
        if result.pydantic:
            self.state.insights = result.pydantic
        else:
            raise ValueError("Insights synthesis did not return a valid Pydantic model.")

        self.state.insights_time = time.time() - insights_start_time
        logger.info(f"✅ Insights synthesized in {self.state.insights_time:.2f}s")

    @listen(synthesize_insights)
    def compile_final_response(self) -> StructuredSearchResponse:
        """
        Compile the final response from the state.
        """
        logger.info("✅ Compiling final response...")
        total_time = time.time() - self.state.start_time
        self.state.total_time = total_time

        final_response = StructuredSearchResponse(
            success=self.state.execution_results.success,
            explanation=self.state.insights.summary,
            raw_results=self.state.execution_results.raw_results,
            cypher_queries=[self.state.enhanced_queries.generated_query],
            query=self.state.query,
            execution_time=total_time
        )
        
        logger.info(f"✅ Search flow completed in {total_time:.2f}s")
        return final_response


# Factory function for backward compatibility
def create_search_flow() -> SearchFlow:
    """
    Factory function to create a SearchFlow instance.
    
    Returns:
        SearchFlow: A new search flow instance
    """
    return SearchFlow()