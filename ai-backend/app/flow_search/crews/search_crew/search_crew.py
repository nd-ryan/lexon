from crewai import Agent, Crew, Task, Process, LLM
from crewai.project import CrewBase, agent, task, crew
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List, Any
from app.models.search import GeneratedCypherQueries, QueryExecutionResults, SearchInsights, FinalSearchResponse
from app.lib.logging_config import setup_logger
import json

# Use our custom logger setup
logger = setup_logger("search-crew")


@CrewBase
class SearchCrew:
    """
    Specialized search crew for Neo4j knowledge graph queries.
    
    This crew uses 3 specialized agents following one-agent-one-task best practices:
    1. Query Generator - Generates optimized Cypher queries using provided schema
    2. Query Executor - Executes queries and returns raw results
    3. Insights Synthesizer - Analyzes raw results and creates the final response
    
    Note: Schema retrieval is handled directly in the flow for better performance.
    """
    
    agents: List[BaseAgent]
    tasks: List[Task]
    
    # Paths to YAML configuration files
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'
    
    def __init__(self, query: str, schema: Any, neo4j_mcp_tools: list, step_callback: callable = None):
        super().__init__()
        self.query = query
        self.schema = schema  # Pre-retrieved schema data from the flow (MCP tool result)
        self.neo4j_mcp_tools = neo4j_mcp_tools
        self.step_callback = step_callback
        
        # Define the LLMs
        self.fast_llm = LLM(model="gpt-4.1-nano")
        self.main_llm = LLM(model="gpt-4.1")

        # Only need executor tools since schema is provided
        self.executor_tools = [t for t in neo4j_mcp_tools if 'cypher' in t.name]

    def _format_schema_for_task(self) -> str:
        """
        Return the full schema data for task descriptions.
        No formatting or summarization - pass the complete raw response.
        """
        if not self.schema:
            return "No schema information available"
        
        try:
            # Handle different schema formats and return the full content
            if isinstance(self.schema, str):
                # Return as-is if it's already a string
                return self.schema
            elif isinstance(self.schema, dict):
                # Convert dict to formatted JSON string (full content)
                return json.dumps(self.schema, indent=2)
            else:
                # Convert other types to string representation (full content)
                return str(self.schema)
                
        except Exception as e:
            logger.warning(f"Error converting schema to string: {e}")
            return f"Schema available but could not be converted to string: {str(e)}"

    @agent
    def query_generation_agent(self) -> Agent:
        return Agent(
            config=self.agents_config['query_generation_agent'],  # type: ignore[index]
            tools=[],  # No tools needed - this agent just generates queries
            llm=self.main_llm
        )

    @agent
    def query_execution_agent(self) -> Agent:
        return Agent(
            config=self.agents_config['query_execution_agent'],  # type: ignore[index]
            tools=self.executor_tools,
            llm=self.main_llm
        )

    @agent
    def insights_synthesis_agent(self) -> Agent:
        return Agent(
            config=self.agents_config['insights_synthesis_agent'],  # type: ignore[index]
            tools=[],  # No tools needed - this agent synthesizes provided information
            llm=self.main_llm
        )

    @task
    def query_generation_task(self) -> Task:
        # Customize the description to include the actual query and schema
        task_config = self.tasks_config['query_generation_task'].copy()  # type: ignore[index]
        
        # Format schema safely
        formatted_schema = self._format_schema_for_task()
        
        # Update task description with query and formatted schema
        updated_description = task_config['description'].replace(
            "for the user query", f'for the user query: "{self.query}"'
        ).replace(
            "using the provided schema information", 
            f"using the following Neo4j schema information:\n\n{formatted_schema}"
        )
        
        task_config['description'] = updated_description
        
        return Task(
            config=task_config,
            agent=self.query_generation_agent(),
            # No context needed since schema is provided in description
            output_pydantic=GeneratedCypherQueries
        )

    @task
    def query_execution_task(self) -> Task:
        return Task(
            config=self.tasks_config['query_execution_task'],  # type: ignore[index]
            agent=self.query_execution_agent(),
            context=[self.query_generation_task()],  # This should ensure it runs after query generation
            output_pydantic=QueryExecutionResults  # Returns only raw results and executed queries
        )

    @task
    def insights_synthesis_task(self) -> Task:
        # Customize the description to include the actual query
        task_config = self.tasks_config['insights_synthesis_task'].copy()  # type: ignore[index]
        task_config['description'] = task_config['description'].replace(
            '"{query}"', f'"{self.query}"'
        )
        
        return Task(
            config=task_config,
            agent=self.insights_synthesis_agent(),
            context=[self.query_execution_task()],  # This should ensure it runs after query execution
            output_pydantic=SearchInsights  # Returns only insights/summary
        )

    def combine_results(self, execution_results: QueryExecutionResults, insights: SearchInsights) -> FinalSearchResponse:
        """
        Combine the execution results with the insights to create the final response.
        
        Args:
            execution_results: Raw query execution results
            insights: Analysis and summary from insights synthesis
            
        Returns:
            FinalSearchResponse: Combined final response
        """
        return FinalSearchResponse(
            success=execution_results.success,
            explanation=insights.summary,
            raw_results=execution_results.raw_results,
            cypher_queries=execution_results.cypher_queries,
            query=self.query
        )

    @crew
    def crew(self) -> Crew:
        # Create tasks explicitly to ensure proper dependencies
        gen_task = self.query_generation_task()
        exec_task = self.query_execution_task() 
        insights_task = self.insights_synthesis_task()
        
        return Crew(
            agents=[
                self.query_generation_agent(),
                self.query_execution_agent(),
                self.insights_synthesis_agent()
            ],  # Explicitly defined agents
            tasks=[gen_task, exec_task, insights_task],  # Explicit task order with dependencies
            process=Process.sequential,
            verbose=False,  # Enable verbose to see task execution
            memory=True,  # Enable memory to pass context between tasks
            step_callback=self.step_callback,
            embedder={
                "provider": "openai",
                "config": {
                    "model": 'text-embedding-3-small'
                }
            }
        ) 