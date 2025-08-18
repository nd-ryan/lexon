from crewai import Agent, Task, Crew
from crewai.project import CrewBase
from app.models.search import (
    GeneratedCypherQuery, 
    LabelIdBlock, 
    LabelIdQueryResult, 
    EnrichedNodeData,
    SearchInsights, 
    StructuredSearchResponse
)
from crewai.flow.flow import Flow, listen, start
from app.lib.mcp_integration import MCPEnabledAgents, get_mcp_tools
from app.lib.batch_query_utils import build_batch_query
from app.lib.logging_config import setup_logger
from typing import Dict, Any, Optional, List
from pydantic import BaseModel
import time
import yaml
import json
import re

# Use our custom logger setup
logger = setup_logger("new-search-flow")


def _remove_embedding_fields(data: Any) -> Any:
    """Recursively remove any keys that end with '_embedding' or '_upload_code' from dict-like structures."""
    if isinstance(data, dict):
        return {
            key: _remove_embedding_fields(value)
            for key, value in data.items()
            if not (str(key).endswith("_embedding") or str(key).endswith("_upload_code"))
        }
    if isinstance(data, list):
        return [_remove_embedding_fields(item) for item in data]
    return data


def _strip_cypher_comments(query: str) -> str:
    """Remove line (//...) and block (/*...*/) comments from a Cypher query safely."""
    if not isinstance(query, str):
        return query
    # Remove block comments first (non-greedy across newlines)
    no_block = re.sub(r"/\*[\s\S]*?\*/", " ", query)
    # Remove line comments, but preserve URLs like http:// by requiring // not preceded by :
    no_line = re.sub(r"(?<!:)//.*", " ", no_block)
    # Collapse excessive whitespace
    cleaned = re.sub(r"\s+", " ", no_line).strip()
    return cleaned


class NewSearchState(BaseModel):
    """
    Pydantic model for structured state management in NewSearchFlow.
    """
    query: str = ""
    neo4j_schema: Optional[Any] = None
    generated_query: Optional[GeneratedCypherQuery] = None
    label_id_blocks: Optional[LabelIdQueryResult] = None
    enriched_data: Optional[EnrichedNodeData] = None
    insights: Optional[SearchInsights] = None
    # Keep track of timing
    start_time: float = 0.0
    schema_time: float = 0.0
    query_gen_time: float = 0.0
    initial_execution_time: float = 0.0
    batch_enrichment_time: float = 0.0
    insights_time: float = 0.0
    total_time: float = 0.0


class NewSearchFlow(Flow[NewSearchState]):
    """
    New flow for handling search queries with label/id block approach and batch enrichment.
    
    This flow orchestrates a two-stage search process:
    1. Initial query to identify relevant nodes (returns label/id blocks)
    2. Batch queries to retrieve enriched data for identified nodes
    3. Synthesis of comprehensive insights from enriched data
    """
    def __init__(self, **data):
        super().__init__(**data)
        # Load agent and task definitions from new YAML files
        with open('app/flow_search/crews/search_crew/config/new_agents.yaml', 'r') as f:
            self.agents_config = yaml.safe_load(f)
        with open('app/flow_search/crews/search_crew/config/new_tasks.yaml', 'r') as f:
            self.tasks_config = yaml.safe_load(f)

    @start()
    def search_kickoff(self) -> Dict[str, Any]:
        """
        Initialize the new search flow with a user query from flow state.
        """
        logger.info(f"🔌 STARTING NEW SEARCH FLOW - Query: '{self.state.query}'")
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
    async def generate_label_id_query(self) -> None:
        """
        Generate a Cypher query that returns label/id blocks using the new_query_generation_agent.
        """
        logger.info("🧠 Generating label/id block query...")
        query_gen_start_time = time.time()

        agent = Agent(config=self.agents_config['new_query_generation_agent'], tools=[], llm="gpt-4.1")
        
        task_description = self.tasks_config['new_query_generation_task']['description'].format(
            query=self.state.query,
            schema=self.state.neo4j_schema
        )
        
        result = await agent.kickoff_async(task_description, response_format=GeneratedCypherQuery)
        
        # Debug: Log what the agent actually returned
        logger.info(f"🔍 Agent result type: {type(result)}")
        logger.info(f"🔍 Agent result: {result}")
        logger.info(f"🔍 Agent result.pydantic: {getattr(result, 'pydantic', 'NO PYDANTIC ATTR')}")
        logger.info(f"🔍 Agent result.raw: {getattr(result, 'raw', 'NO RAW ATTR')}")
        
        if result.pydantic:
            # Sanitize generated query to avoid comment-related syntax issues
            sanitized = _strip_cypher_comments(result.pydantic.generated_query)
            self.state.generated_query = GeneratedCypherQuery(generated_query=sanitized)
            logger.info(f"🧠 Generated label/id query:")
            logger.info(f"   {self.state.generated_query.generated_query}")
        else:
            # Try to extract from raw result if available
            if hasattr(result, 'raw') and result.raw:
                logger.info(f"🔍 Attempting to parse from raw result: {result.raw}")
                try:
                    import json
                    if isinstance(result.raw, str):
                        raw_data = json.loads(result.raw)
                    else:
                        raw_data = result.raw
                    
                    if isinstance(raw_data, dict) and 'generated_query' in raw_data:
                        sanitized = _strip_cypher_comments(raw_data['generated_query'])
                        self.state.generated_query = GeneratedCypherQuery(generated_query=sanitized)
                        logger.info(f"🧠 Generated label/id query from raw:")
                        logger.info(f"   {self.state.generated_query.generated_query}")
                    else:
                        raise ValueError(f"Raw result doesn't contain expected 'generated_query' field: {raw_data}")
                except Exception as e:
                    logger.error(f"❌ Failed to parse raw result: {e}")
                    raise ValueError(f"Label/ID query generation failed. Raw result: {result.raw}")
            else:
                raise ValueError(f"Label/ID query generation did not return a valid Pydantic model. Result: {result}")

        self.state.query_gen_time = time.time() - query_gen_start_time
        logger.info(f"✅ Label/ID query generated in {self.state.query_gen_time:.2f}s")

    @listen(generate_label_id_query)
    async def execute_initial_query(self) -> None:
        """
        Execute the initial query to get label/id blocks with retry logic.
        """
        logger.info("⚙️ Executing initial query for label/id blocks...")
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
            
            while current_attempt <= max_attempts:
                logger.info(f"🔄 Attempt {current_attempt}/{max_attempts}")
                
                # Get the current query (either initial or regenerated)
                if current_attempt == 1:
                    current_query = self.state.generated_query
                else:
                    # Generate a new query based on previous failure
                    logger.info("🔄 Generating alternative query due to no results...")
                    current_query = await self._generate_alternative_label_id_query(current_attempt)
                
                # Execute the current query
                try:
                    # Ensure we strip any comments that may have slipped into regenerated queries
                    cypher_query = _strip_cypher_comments(current_query.generated_query)
                    logger.info(f"🔍 Executing query (attempt {current_attempt}):")
                    logger.info(f"   {cypher_query}")
                    
                    result = cypher_tool.run(query=cypher_query)
                    
                    # Debug: Log the exact result structure
                    logger.info(f"🔍 Raw Neo4j result type: {type(result)}")
                    logger.info(f"🔍 Raw Neo4j result content: {result}")
                    
                    # Parse the JSON string result into a Python list
                    if isinstance(result, str):
                        try:
                            parsed_result = json.loads(result)
                            logger.info(f"🔍 Parsed result type: {type(parsed_result)}")
                            logger.info(f"🔍 Parsed result content: {parsed_result}")
                        except json.JSONDecodeError as e:
                            logger.error(f"❌ Failed to parse JSON result: {e}")
                            parsed_result = []
                    else:
                        parsed_result = result
                        logger.info(f"🔍 Direct result (not string): {parsed_result}")
                    
                    # Check if we got results and convert to label/id blocks
                    if isinstance(result, str) and result.startswith("Error"):
                        logger.error(f"❌ Query attempt {current_attempt} failed with MCP error: {result}")
                        if current_attempt < max_attempts:
                            logger.info("🔄 Will try alternative query...")
                        else:
                            logger.warning("❌ All query attempts failed - proceeding with empty results")
                            successful_results = LabelIdQueryResult(
                                success=False,
                                label_id_blocks=[]
                            )
                    elif isinstance(parsed_result, list) and len(parsed_result) > 0:
                        logger.info(f"✅ Query attempt {current_attempt} successful with raw result")
                        logger.info(f"🔍 Raw parsed result structure: {parsed_result}")
                        
                        # Extract label/id blocks from predictable Neo4j result structure
                        actual_blocks = []
                        
                        # With "AS result", we expect: [{"result": [list of blocks]}]
                        for item in parsed_result:
                            if isinstance(item, dict):
                                # Primary expected structure with "result" key
                                if 'result' in item and isinstance(item['result'], list):
                                    for block in item['result']:
                                        if isinstance(block, dict) and all(k in block for k in ['label', 'id_field', 'id_values']):
                                            actual_blocks.append(block)
                                            logger.info(f"✅ Found label/id block: {block['label']} with {len(block['id_values'])} IDs")
                                # Fallback: direct structure (for backward compatibility)
                                elif all(k in item for k in ['label', 'id_field', 'id_values']):
                                    actual_blocks.append(item)
                                    logger.info(f"✅ Found direct label/id block: {item['label']} with {len(item['id_values'])} IDs")
                                # Fallback: any other key structure (legacy support)
                                else:
                                    for key, value in item.items():
                                        if isinstance(value, list):
                                            for block in value:
                                                if isinstance(block, dict) and all(k in block for k in ['label', 'id_field', 'id_values']):
                                                    actual_blocks.append(block)
                                                    logger.info(f"⚠️ Found legacy label/id block under key '{key}': {block['label']}")
                            elif isinstance(item, list):
                                # Direct list of blocks
                                for block in item:
                                    if isinstance(block, dict) and all(k in block for k in ['label', 'id_field', 'id_values']):
                                        actual_blocks.append(block)
                                        logger.info(f"✅ Found direct list label/id block: {block['label']}")
                        
                        logger.info(f"📊 Extracted {len(actual_blocks)} label/id blocks from result")
                        
                        # Convert to LabelIdBlock objects
                        label_blocks = []
                        for block in actual_blocks:
                            try:
                                label_blocks.append(LabelIdBlock(**block))
                                logger.info(f"✅ Added {block['label']} block with {len(block['id_values'])} IDs")
                            except Exception as e:
                                logger.warning(f"⚠️ Failed to create LabelIdBlock from {block}: {e}")
                        
                        if len(label_blocks) > 0:
                            successful_results = LabelIdQueryResult(
                                success=True,
                                label_id_blocks=label_blocks
                            )
                            break
                        else:
                            logger.warning(f"⚠️ No valid label/id blocks found in result")
                            if current_attempt < max_attempts:
                                logger.info("🔄 Will try alternative query...")
                            else:
                                logger.warning("❌ All query attempts failed - proceeding with empty results")
                                successful_results = LabelIdQueryResult(
                                    success=False,
                                    label_id_blocks=[]
                                )
                    else:
                        logger.warning(f"⚠️ Query attempt {current_attempt} returned no results")
                        if current_attempt < max_attempts:
                            logger.info("🔄 Will try alternative query...")
                        else:
                            logger.warning("❌ All query attempts failed - proceeding with empty results")
                            successful_results = LabelIdQueryResult(
                                success=False,
                                label_id_blocks=[]
                            )
                except Exception as e:
                    logger.error(f"❌ Query attempt {current_attempt} failed with error: {e}")
                    if current_attempt < max_attempts:
                        logger.info("🔄 Will try alternative query...")
                    else:
                        raise RuntimeError(f"All query attempts failed: {e}")
                
                current_attempt += 1
            
            # Store the final results
            self.state.label_id_blocks = successful_results
            self.state.initial_execution_time = time.time() - execution_start_time
            logger.info(f"✅ Initial query executed in {self.state.initial_execution_time:.2f}s")
            logger.info(f"📊 Found {len(successful_results.label_id_blocks)} label/id blocks")

    async def _generate_alternative_label_id_query(self, attempt_number: int) -> GeneratedCypherQuery:
        """
        Generate an alternative label/id query when the previous one returned no results.
        """
        agent = Agent(config=self.agents_config['new_query_generation_agent'], tools=[], llm="gpt-4.1")
        
        alternative_prompts = {
            2: "The previous query returned no results. Generate a more general/broader query that returns label/id blocks with more flexible matching patterns or searching across more node types.",
            3: "The previous queries returned no results. Generate a very broad query that searches across all node types with very loose matching criteria to find any potentially relevant label/id blocks."
        }
        
        prompt = alternative_prompts.get(attempt_number, "Generate an alternative label/id query.")
        
        task_description = f"""
        {self.tasks_config['new_query_generation_task']['description'].format(
            query=self.state.query,
            schema=self.state.neo4j_schema
        )}
        
        IMPORTANT: {prompt}
        
        Make sure your query returns label/id blocks and uses different search strategies from previous attempts.
        """
        
        result = await agent.kickoff_async(task_description, response_format=GeneratedCypherQuery)
        
        if result.pydantic:
            logger.info(f"🔄 Generated alternative label/id query (attempt {attempt_number}):")
            logger.info(f"   {result.pydantic.generated_query}")
            # Sanitize alternative as well
            sanitized = _strip_cypher_comments(result.pydantic.generated_query)
            return GeneratedCypherQuery(generated_query=sanitized)
        else:
            raise ValueError(f"Alternative label/id query generation attempt {attempt_number} failed")

    @listen(execute_initial_query)
    async def execute_batch_enrichment(self) -> None:
        """
        Execute batch queries to retrieve enriched data for the identified label/id blocks.
        """
        logger.info("🔄 Executing batch enrichment queries...")
        batch_start_time = time.time()
        
        if not self.state.label_id_blocks.success or not self.state.label_id_blocks.label_id_blocks:
            logger.warning("⚠️ No label/id blocks to process - skipping batch enrichment")
            self.state.enriched_data = EnrichedNodeData(
                success=False,
                enriched_results=[],
                cypher_queries=[]
            )
            self.state.batch_enrichment_time = time.time() - batch_start_time
            return

        with MCPEnabledAgents() as mcp_context:
            neo4j_tools = get_mcp_tools()
            cypher_tool = next((t for t in neo4j_tools if 'cypher' in t.name.lower()), None)
            
            if not cypher_tool:
                raise RuntimeError("Neo4j Cypher tool not found in MCP tools")
            
            enriched_results = []
            executed_queries = []
            
            # Process each label/id block
            for block in self.state.label_id_blocks.label_id_blocks:
                logger.info(f"🔍 Processing {block.label} nodes with {len(block.id_values)} IDs")
                
                # Build the batch query for this label/id_field combination
                query = build_batch_query(block.label, block.id_field, block.id_values)
                # Track and log the query used for this block
                executed_queries.append(query)
                logger.info(f"🔎 Executing batch query for {block.label} ({len(block.id_values)} IDs)")
                
                try:
                    # Execute the batch query
                    result = cypher_tool.run(query=query)
                    
                    # Parse the result
                    if isinstance(result, str):
                        try:
                            parsed_result = json.loads(result)
                        except json.JSONDecodeError as e:
                            logger.error(f"❌ Failed to parse batch query result: {e}")
                            continue
                    else:
                        parsed_result = result
                    
                    # Add enriched nodes to results
                    if isinstance(parsed_result, list):
                        for record in parsed_result:
                            if isinstance(record, dict) and 'n' in record:
                                # Strip any *_embedding properties before storing
                                enriched_results.append(_remove_embedding_fields(record['n']))
                        logger.info(f"✅ Retrieved {len(parsed_result)} enriched {block.label} nodes")
                    
                except Exception as e:
                    logger.error(f"❌ Failed to execute batch query for {block.label}: {e}")
                    continue
            
            # Remove duplicate queries while preserving order (if any)
            executed_queries_unique = list(dict.fromkeys(executed_queries))

            # Store the enriched data
            self.state.enriched_data = EnrichedNodeData(
                success=len(enriched_results) > 0,
                enriched_results=enriched_results,
                cypher_queries=executed_queries_unique
            )
            
            self.state.batch_enrichment_time = time.time() - batch_start_time
            logger.info(f"✅ Batch enrichment completed in {self.state.batch_enrichment_time:.2f}s")
            logger.info(f"📊 Retrieved {len(enriched_results)} total enriched nodes")

    @listen(execute_batch_enrichment)
    async def synthesize_insights(self) -> None:
        """
        Synthesize insights from the enriched data using the insights_synthesis_agent.
        """
        logger.info("✍️ Synthesizing insights from enriched data...")
        insights_start_time = time.time()
        
        agent = Agent(config=self.agents_config['insights_synthesis_agent'], tools=[], llm="gpt-4.1")
        
        task_input = self.state.enriched_data.model_dump()
        task_description = self.tasks_config['new_insights_synthesis_task']['description'].replace(
            '"{query}"', f'"{self.state.query}"'
        ).format(enriched_data=task_input)

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
            success=self.state.enriched_data.success,
            explanation=self.state.insights.summary,
            raw_results=self.state.enriched_data.enriched_results,
            cypher_queries=self.state.enriched_data.cypher_queries,
            query=self.state.query,
            execution_time=total_time
        )
        
        logger.info(f"✅ New search flow completed in {total_time:.2f}s")
        return final_response


# Factory function for creating new search flow
def create_new_search_flow() -> NewSearchFlow:
    """
    Factory function to create a NewSearchFlow instance.
    
    Returns:
        NewSearchFlow: A new search flow instance
    """
    return NewSearchFlow() 