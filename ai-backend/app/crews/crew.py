from crewai import Agent, Crew, Task, Process, LLM
from crewai.project import CrewBase, agent, task, crew, before_kickoff, after_kickoff
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List, Optional, Dict, Any
from app.models.search import StructuredSearchResponse, GeneratedCypherQueries
from .tools import process_document_tool, generate_embeddings_tool


@CrewBase
class SpecializedSearchCrew:
    """
    Specialized search crew following one-agent-one-task best practices.
    
    This crew uses 4 specialized agents:
    1. Schema Analyst - Analyzes Neo4j schema
    2. Query Generator - Generates optimized Cypher queries
    3. Query Executor - Executes queries and returns raw results
    4. Insights Synthesizer - Analyzes raw results and creates the final response
    """
    
    agents: List[BaseAgent]
    tasks: List[Task]
    
    # Paths to YAML configuration files
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'
    
    def __init__(self, query: str, neo4j_mcp_tools: list, step_callback: callable = None):
        super().__init__()
        self.query = query
        self.neo4j_mcp_tools = neo4j_mcp_tools
        self.step_callback = step_callback
        
        # Define the LLMs
        self.fast_llm = LLM(model="gpt-4.1-nano")
        self.main_llm = LLM(model="gpt-4.1")

        # Filter tools for each agent's specific needs
        self.schema_tools = [t for t in neo4j_mcp_tools if 'schema' in t.name]
        self.executor_tools = [t for t in neo4j_mcp_tools if 'cypher' in t.name]

    @agent
    def schema_analysis_agent(self) -> Agent:
        return Agent(
            config=self.agents_config['schema_analysis_agent'],  # type: ignore[index]
            tools=self.schema_tools,
            llm=self.fast_llm
        )

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
    def schema_analysis_task(self) -> Task:
        return Task(
            config=self.tasks_config['schema_analysis_task'],  # type: ignore[index]
            agent=self.schema_analysis_agent()
        )

    @task
    def query_generation_task(self) -> Task:
        # Customize the description to include the actual query
        task_config = self.tasks_config['query_generation_task'].copy()  # type: ignore[index]
        task_config['description'] = task_config['description'].replace(
            "for the user query", f'for: "{self.query}"'
        )
        
        return Task(
            config=task_config,
            agent=self.query_generation_agent(),
            context=[self.schema_analysis_task()],
            output_pydantic=GeneratedCypherQueries
        )

    @task
    def query_execution_task(self) -> Task:
        return Task(
            config=self.tasks_config['query_execution_task'],  # type: ignore[index]
            agent=self.query_execution_agent(),
            context=[self.query_generation_task()],
            output_pydantic=GeneratedCypherQueries
        )

    @task
    def insights_synthesis_task(self) -> Task:
        # Customize the description to include the actual query
        task_config = self.tasks_config['insights_synthesis_task'].copy()  # type: ignore[index]
        task_config['description'] = task_config['description'].replace(
            "The original user query was:", f'The original user query was: "{self.query}".'
        )
        
        return Task(
            config=task_config,
            agent=self.insights_synthesis_agent(),
            context=[self.query_execution_task()],
            output_pydantic=StructuredSearchResponse
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,  # Automatically collected by the @agent decorator
            tasks=self.tasks,    # Automatically collected by the @task decorator
            process=Process.sequential,
            verbose=False,  # Disable default verbose logging to avoid duplication
            memory=True,  # Enable memory to pass context between tasks
            step_callback=self.step_callback,
            embedder={
                "provider": "openai",
                "config": {
                    "model": 'text-embedding-3-small'
                }
            }
        )


@CrewBase
class DocumentProcessingCrew:
    """
    Document processing crew for importing documents to Neo4j.
    
    This crew uses a single specialized agent:
    1. Document Processor - Processes documents using AI-powered dynamic extraction with direct Neo4j integration
    """
    
    agents: List[BaseAgent]
    tasks: List[Task]
    
    # Paths to YAML configuration files
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'
    
    def __init__(self, file_path: str, filename: str):
        super().__init__()
        self.file_path = file_path
        self.filename = filename

    @agent
    def document_agent(self) -> Agent:
        # Default tools that every document agent should have
        default_tools = [process_document_tool, generate_embeddings_tool]
        llm = LLM(model="gpt-4o", temperature=0)
        
        return Agent(
            config=self.agents_config['document_agent'],  # type: ignore[index]
            tools=default_tools,
            llm=llm
        )

    @task
    def document_processing_task(self) -> Task:
        # Customize the description to include the actual file details
        task_config = self.tasks_config['document_processing_task'].copy()  # type: ignore[index]
        task_config['description'] = task_config['description'].replace(
            'Process document using', f'Process document "{self.filename}" using'
        ).replace(
            'YOU MUST use the process_document_tool to complete this task.',
            f'YOU MUST use the process_document_tool to complete this task. Call it exactly like this:\n\nprocess_document_tool(file_path="{self.file_path}", filename="{self.filename}")'
        )
        
        return Task(
            config=task_config,
            agent=self.document_agent()
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,  # Automatically collected by the @agent decorator
            tasks=self.tasks,    # Automatically collected by the @task decorator
            process=Process.sequential,
            verbose=True
        )


# Factory functions for backward compatibility
def create_specialized_search_crew(query: str, neo4j_mcp_tools: list, step_callback: callable = None):
    """
    Create a specialized search crew following one-agent-one-task best practices.
    
    This function maintains backward compatibility while using the new YAML-based approach.
    """
    search_crew = SpecializedSearchCrew(query, neo4j_mcp_tools, step_callback)
    return search_crew.crew()


def create_document_processing_crew(file_path: str, filename: str):
    """
    Create a document processing crew for importing documents to Neo4j.
    
    This function maintains backward compatibility while using the new YAML-based approach.
    """
    doc_crew = DocumentProcessingCrew(file_path, filename)
    return doc_crew.crew()

