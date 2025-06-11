from crewai import Agent
from crewai_tools import MCPServerAdapter
from mcp import StdioServerParameters
import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
from ..lib.cypher_generator import generate_cypher_query_async
from ..lib.neo4j_client import neo4j_client
from ..lib.embeddings import find_similar_cases, generate_embeddings_for_cases

# MCP Configuration - Updated to use Neo4j's official MCP server
def get_neo4j_mcp_server_params():
    """Get MCP server parameters for Neo4j's official MCP server"""
    return StdioServerParameters(
        command="mcp-neo4j-cypher",  # Use official Neo4j MCP server
        args=[
            "--db-url", os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            "--username", os.getenv("NEO4J_USERNAME", "neo4j"),
            "--password", os.getenv("NEO4J_PASSWORD", "password"),
            "--database", os.getenv("NEO4J_DATABASE", "neo4j")
        ],
        env=os.environ,  # Pass through all environment variables
    )

# Global MCP tools instance - will be set by create_mcp_enabled_agents
_mcp_tools = None

def initialize_mcp_tools():
    """Initialize MCP tools for Neo4j access."""
    global _mcp_tools
    if _mcp_tools is None:
        try:
            server_params = get_neo4j_mcp_server_params()
            _mcp_tools = MCPServerAdapter([server_params])
            return _mcp_tools
        except Exception as e:
            print(f"Warning: Could not initialize MCP tools: {e}")
            return None
    return _mcp_tools

def get_mcp_tools():
    """Get the global MCP tools instance."""
    return _mcp_tools

# Step callback function to capture agent thinking
def agent_step_callback(step):
    """Callback function to log each step of agent reasoning"""
    print(f"🤔 Agent Step: {step}")
    return {
        "step_type": getattr(step, 'step_type', 'unknown'),
        "content": str(step),
        "timestamp": str(step.timestamp) if hasattr(step, 'timestamp') else None,
        "agent_name": getattr(step, 'agent_name', 'unknown')
    }

# Search and Query Agent (MCP-enabled)
def create_search_agent(tools: Optional[List] = None) -> Agent:
    """Create a search agent with optional MCP tools"""
    agent_tools = tools or []
    
    return Agent(
        role="Knowledge Graph Search Specialist",
        goal="Execute precise searches against Neo4j knowledge graphs using available tools",
        backstory="You are an expert at navigating and querying knowledge graphs. You understand how to use both direct database queries and MCP tools to find relevant information efficiently.",
        tools=agent_tools,
        verbose=True,
        allow_delegation=False
    )

# Document Processing Agent
def create_document_agent(tools: Optional[List] = None) -> Agent:
    """Create a document processing agent with optional MCP tools"""
    agent_tools = tools or []
    
    return Agent(
        role="Document Processing Specialist", 
        goal="Process and analyze documents using available tools to extract meaningful information",
        backstory="You are an expert at processing various document types and extracting structured information. You understand how to work with different document formats and databases.",
        tools=agent_tools,
        verbose=True,
        allow_delegation=False
    )

# Semantic Analysis Agent  
def create_embeddings_agent():
    """Create an agent specialized in semantic analysis and similarity matching."""
    return Agent(
        role="Semantic Analysis Specialist",
        goal="I am an expert in semantic meaning, vector representations, and finding conceptual relationships between legal cases and documents",
        backstory="""I am a specialist in semantic analysis with deep expertise in natural language understanding, 
        vector embeddings, and similarity matching. I excel at identifying conceptual relationships 
        and semantic patterns that may not be immediately obvious through keyword-based searches.""",
        tools=[],  # Keep without tools for now
        verbose=True,
        allow_delegation=False,
        max_iter=25,
        step_callback=agent_step_callback,
        reasoning=True,
        max_reasoning_attempts=3,
    )

# Research Agent  
def create_research_agent(tools: Optional[List] = None) -> Agent:
    """Create a research agent with optional MCP tools"""
    agent_tools = tools or []
    
    return Agent(
        role="Research Analyst",
        goal="Conduct comprehensive research using available tools and synthesize findings into clear, actionable insights",
        backstory="You are a skilled research analyst who can work with various data sources and tools. You excel at finding patterns, connections, and insights from complex information.",
        tools=agent_tools,
        verbose=True,
        allow_delegation=False
    )

# Writer Agent
def create_writer_agent():
    """Create an agent specialized in transforming research into clear, compelling content."""
    return Agent(
        role="Legal Content Specialist",
        goal="I transform complex legal research and analysis into clear, compelling, and well-structured content that is accessible to the intended audience",
        backstory="""I am a legal content specialist with expertise in legal writing, technical communication, 
        and information synthesis. I excel at taking complex research findings and transforming them into 
        clear, engaging content while maintaining accuracy and legal precision.""",
        tools=[],  # Keep without tools for now
        verbose=True,
        allow_delegation=False,
        max_iter=25,
        step_callback=agent_step_callback,
        reasoning=True,
        max_reasoning_attempts=2,
    )

# Context manager for MCP-enabled agents
class MCPEnabledAgents:
    """Context manager for agents with Neo4j's official MCP tools."""
    
    def __init__(self):
        self.mcp_adapter = None
        
    def __enter__(self):
        """Enter the context and initialize Neo4j's official MCP tools."""
        global _mcp_tools
        try:
            server_params = get_neo4j_mcp_server_params()
            print(f"🔌 Connecting to Neo4j MCP server with URL: {os.getenv('NEO4J_URI', 'bolt://localhost:7687')}")
            self.mcp_adapter = MCPServerAdapter([server_params])
            _mcp_tools = self.mcp_adapter.__enter__()
            print(f"✅ Neo4j MCP Tools initialized: {[tool.name for tool in _mcp_tools]}")
            print(f"📊 Available tools: get-neo4j-schema, read-neo4j-cypher, write-neo4j-cypher")
            return self
        except Exception as e:
            print(f"⚠️ Could not initialize Neo4j MCP tools: {e}")
            print(f"💡 Make sure mcp-neo4j-cypher is installed and Neo4j is running")
            _mcp_tools = None
            return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the context and cleanup MCP tools."""
        global _mcp_tools
        if self.mcp_adapter:
            try:
                self.mcp_adapter.__exit__(exc_type, exc_val, exc_tb)
                print("🔌 Neo4j MCP connection closed")
            except Exception as e:
                print(f"Warning during MCP cleanup: {e}")
        _mcp_tools = None

# Convenience function to create all agents with MCP support
def create_mcp_enabled_agents():
    """Create agents with MCP tools enabled."""
    return {
        "search_agent": create_search_agent(),
        "document_agent": create_document_agent(), 
        "embeddings_agent": create_embeddings_agent(),
        "research_agent": create_research_agent(),
        "writer_agent": create_writer_agent()
    }

# Fallback functions (keep existing functionality for backward compatibility)
def search_knowledge_graph_tool(query: str) -> Dict[str, Any]:
    """
    Search the knowledge graph using natural language queries.
    
    Args:
        query: Natural language question about the knowledge graph
        
    Returns:
        Dictionary containing the generated Cypher query and results
    """
    try:
        # Generate Cypher query from natural language
        cypher_query = generate_cypher_query_async.__wrapped__(query)
        
        # Execute the query
        results = neo4j_client.execute_query(cypher_query)
        
        return {
            "cypher_query": cypher_query,
            "results": results,
            "count": len(results)
        }
    except Exception as e:
        return {
            "error": str(e),
            "cypher_query": None,
            "results": [],
            "count": 0
        }

def find_similar_cases_tool(query_text: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Find cases similar to the given text using semantic similarity.
    
    Args:  
        query_text: Text to find similar cases for
        limit: Maximum number of similar cases to return (default 5)
        
    Returns:
        List of similar cases with similarity scores
    """
    try:
        import asyncio
        # Run the async function
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            results = loop.run_until_complete(find_similar_cases(query_text, limit))
            return results
        finally:
            loop.close()
    except Exception as e:
        return [{"error": str(e)}]

def process_document_tool(file_content: bytes, filename: str) -> Dict[str, Any]:
    """
    Process a document and extract knowledge graph data.
    
    Args:
        file_content: Raw bytes of the document
        filename: Name of the file being processed
        
    Returns:
        Dictionary with processing results and statistics
    """
    try:
        from ..lib.document_processor import parse_docx_to_knowledge_graph, knowledge_graph_to_dict
        import asyncio
        
        # Parse document
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            kg = loop.run_until_complete(parse_docx_to_knowledge_graph(file_content))
            
            # Convert to dict for serialization
            kg_dict = knowledge_graph_to_dict(kg)
            
            # Load into Neo4j
            neo4j_client.load_knowledge_graph(kg_dict)
            
            return {
                "success": True,
                "filename": filename,
                "counts": {
                    "cases": len(kg.cases),
                    "parties": len(kg.parties), 
                    "provisions": len(kg.provisions),
                    "doctrines": len(kg.doctrines),
                },
                "message": f"Successfully processed {filename} and loaded into knowledge graph"
            }
        finally:
            loop.close()
            
    except Exception as e:
        return {
            "success": False,
            "filename": filename,
            "error": str(e),
            "counts": {}
        }

def generate_embeddings_tool(case_ids: List[str]) -> Dict[str, Any]:
    """
    Generate embeddings for the specified cases.
    
    Args:
        case_ids: List of case IDs to generate embeddings for
        
    Returns:
        Dictionary with generation results and statistics
    """
    try:
        import asyncio
        
        # Generate embeddings
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            results = loop.run_until_complete(generate_embeddings_for_cases(case_ids))
            return {
                "success": True,
                "case_ids": case_ids,
                "results": results,
                "count": len(case_ids)
            }
        finally:
            loop.close()
            
    except Exception as e:
        return {
            "success": False,
            "case_ids": case_ids,
            "error": str(e),
            "results": [],
            "count": 0
        }