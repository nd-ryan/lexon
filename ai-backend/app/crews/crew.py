from crewai import Crew, Process, LLM
from .agents import (
    create_research_agent, create_writer_agent, 
    # NEW: Specialized agents for one-agent-one-task pattern
    create_schema_analysis_agent, create_query_generation_agent, 
    create_query_execution_agent, create_insights_synthesis_agent,
    create_search_agent
)
from .tasks import (
    create_research_task, create_writing_task,
    # NEW: Specialized tasks for one-agent-one-task pattern
    create_schema_analysis_task, create_query_generation_task,
    create_query_execution_task, create_insights_synthesis_task,
    create_search_task
)
from app.models.search import StructuredSearchResponse

def create_research_crew(topic: str):
    # Create agents
    research_agent = create_research_agent()
    writer_agent = create_writer_agent()
    
    # Create tasks
    research_task = create_research_task(research_agent, topic)
    writing_task = create_writing_task(writer_agent, "Research findings")
    
    # Create crew
    crew = Crew(
        agents=[research_agent, writer_agent],
        tasks=[research_task, writing_task],
        process=Process.sequential,
        verbose=True,
    )
    
    return crew

def create_specialized_search_crew(query: str, neo4j_mcp_tools: list, step_callback: callable = None):
    """
    Create a specialized search crew following one-agent-one-task best practices.
    
    This crew uses 4 specialized agents:
    1. Schema Analyst - Analyzes Neo4j schema
    2. Query Generator - Generates optimized Cypher queries
    3. Query Executor - Executes queries and returns raw results
    4. Insights Synthesizer - Analyzes raw results and creates the final response
    """
    
    # Define the LLMs
    fast_llm = LLM(model="gpt-4.1-nano")
    main_llm = LLM(model="gpt-4.1")

    # Filter tools for each agent's specific needs
    schema_tools = [t for t in neo4j_mcp_tools if 'schema' in t.name]
    executor_tools = [t for t in neo4j_mcp_tools if 'cypher' in t.name]

    # Create specialized agents
    schema_agent = create_schema_analysis_agent(tools=schema_tools, llm=fast_llm)
    query_gen_agent = create_query_generation_agent(llm=main_llm)
    query_exec_agent = create_query_execution_agent(tools=executor_tools, llm=main_llm)
    insights_agent = create_insights_synthesis_agent(llm=main_llm)
    
    # Create specialized tasks with explicit context passing
    schema_task = create_schema_analysis_task(schema_agent, query)
    query_gen_task = create_query_generation_task(
        query_gen_agent, query, context=[schema_task]
    )
    query_exec_task = create_query_execution_task(
        query_exec_agent, context=[query_gen_task]
    )
    insights_task = create_insights_synthesis_task(
        insights_agent, query, context=[query_exec_task]
    )
    
    # Create crew with sequential process
    crew = Crew(
        agents=[schema_agent, query_gen_agent, query_exec_agent, insights_agent],
        tasks=[schema_task, query_gen_task, query_exec_task, insights_task],
        process=Process.sequential,
        verbose=False,  # Disable default verbose logging to avoid duplication
        memory=True,  # Enable memory to pass context between tasks
        step_callback=step_callback,
        embedder={
            "provider": "openai",
            "config":{
                "model": 'text-embedding-3-small'
            }
        }
    )
    
    return crew

def create_legacy_search_crew(query: str, neo4j_mcp_tools: list):
    """Create a legacy single-agent search crew."""
    
    # Create a single search agent with all tools
    search_agent = create_search_agent(tools=neo4j_mcp_tools)
    
    # Create a single comprehensive search task
    search_task = create_search_task(
        search_agent, 
        query,
        structured_output=True
    )
    
    crew = Crew(
        agents=[search_agent],
        tasks=[search_task],
        process=Process.sequential,
        verbose=True
    )
    
    return crew

async def run_research_crew(topic: str):
    crew = create_research_crew(topic)
    result = crew.kickoff()
    return result