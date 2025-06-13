from crewai import Agent, LLM
from crewai.tools import tool
from crewai_tools import MCPServerAdapter
from mcp import StdioServerParameters
import os
import sys
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from ..lib.cypher_generator import generate_cypher_query_async
from ..lib.neo4j_client import neo4j_client
from ..lib.embeddings import find_similar_cases, generate_embeddings_for_cases

logger = logging.getLogger(__name__)

# MCP Configuration - Updated to use Neo4j's official MCP server
def get_neo4j_mcp_server_params():
    """Get MCP server parameters for Neo4j's official MCP server"""
    return StdioServerParameters(
        command="mcp-neo4j-cypher",  # Use official Neo4j MCP server
        args=[
            "--db-url", os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            "--username", os.getenv("NEO4J_USER", "neo4j"),
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
    global _mcp_tools
    if _mcp_tools:
        logger.debug(f"get_mcp_tools() returning {len(_mcp_tools)} tools: {[tool.name for tool in _mcp_tools]}")
    else:
        logger.debug("get_mcp_tools() returning None - no MCP tools available")
    return _mcp_tools

def debug_mcp_tools_status():
    """Debug function to check current MCP tools status"""
    global _mcp_tools
    status = {
        "mcp_tools_available": _mcp_tools is not None,
        "tool_count": len(_mcp_tools) if _mcp_tools else 0,
        "tool_names": [tool.name for tool in _mcp_tools] if _mcp_tools else []
    }
    logger.info(f"MCP Tools Status: {status}")
    return status

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
    """Create a search agent with proper search tools"""
    # Default tools that every search agent should have
    default_tools = [search_knowledge_graph_tool, find_similar_cases_tool]
    
    # Add any additional tools passed in (like MCP tools)
    agent_tools = default_tools + (tools or [])
    
    return Agent(
        role="Search Agent",
        goal="Search the knowledge graph using available tools",
        backstory="You search knowledge graphs using the available search tools.",
        tools=agent_tools,
        verbose=True,
        allow_delegation=False,
        max_iter=3
    )

# Search and Query Tools
@tool
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

@tool 
def find_similar_cases_tool(case_id: str, limit: int = 5) -> Dict[str, Any]:
    """
    Find cases similar to the given case using vector similarity.
    
    Args:
        case_id: ID of the case to find similarities for
        limit: Maximum number of similar cases to return
        
    Returns:
        Dictionary containing similar cases with similarity scores
    """
    try:
        import asyncio
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            similar_cases = loop.run_until_complete(find_similar_cases(case_id, limit))
            return {
                "case_id": case_id,
                "similar_cases": similar_cases,
                "count": len(similar_cases)
            }
        finally:
            loop.close()
            
    except Exception as e:
        return {
            "error": str(e),
            "case_id": case_id,
            "similar_cases": [],
            "count": 0
        }

# Document Processing Tool - Convert to CrewAI tool
@tool
def process_document_tool(file_path: str, filename: str) -> Dict[str, Any]:
    """
    Process a document using AI-powered dynamic extraction with direct Neo4j integration.
    
    Args:
        file_path: Path to the document file
        filename: Name of the file being processed
        
    Returns:
        Dictionary with processing results and statistics
    """
    try:
        from ..lib.dynamic_document_processor import dynamic_processor
        
        logger.info(f"Processing document with direct Neo4j integration: {filename}")
        
        # Read the file content
        with open(file_path, 'rb') as f:
            file_content = f.read()
        
        # Process document using dynamic AI-powered approach with direct Neo4j
        result = dynamic_processor.process_document(file_content, filename)
        
        return result
            
    except Exception as e:
        logger.error(f"Document processing failed for {filename}: {e}")
        return {
            "success": False,
            "filename": filename,
            "error": str(e),
            "extracted_counts": {}
        }

def create_mcp_aware_process_document_tool(mcp_tools=None):
    """Factory function to create a process_document_tool with MCP tools baked in"""
    
    @tool
    def process_document_tool_with_mcp(file_path: str, filename: str) -> Dict[str, Any]:
        """
        Process a document using AI-powered dynamic extraction that adapts to existing Neo4j schema.
        This version has MCP tools pre-configured.
        
        Args:
            file_path: Path to the document file
            filename: Name of the file being processed
            
        Returns:
            Dictionary with processing results and statistics
        """
        try:
            from ..lib.dynamic_document_processor import dynamic_processor
            
            # Set MCP tools if provided
            if mcp_tools:
                dynamic_processor.set_mcp_tools(mcp_tools)
                logger.info(f"Dynamic processor configured with MCP tools: {[tool.name for tool in mcp_tools]}")
            else:
                logger.warning("No MCP tools provided to process_document_tool_with_mcp")
            
            # Read the file content
            with open(file_path, 'rb') as f:
                file_content = f.read()
            
            # Process document using dynamic AI-powered approach
            result = dynamic_processor.process_document(file_content, filename)
            
            return result
                
        except Exception as e:
            return {
                "success": False,
                "filename": filename,
                "error": str(e),
                "extracted_counts": {}
            }
    
    return process_document_tool_with_mcp

@tool
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

# Document Processing Agent
def create_document_agent(tools: Optional[List] = None) -> Agent:
    """Create a document processing agent with direct Neo4j integration"""
    
    # Default tools that every document agent should have
    default_tools = [process_document_tool, generate_embeddings_tool]
    
    # Add any additional tools passed in
    agent_tools = default_tools + (tools or [])
    
    llm = LLM(model="gpt-4o", temperature=0)
    
    return Agent(
        role="Document Processor", 
        goal="Process documents using the process_document_tool with direct Neo4j integration",
        backstory="You process documents by calling the process_document_tool with the file_path and filename. You use direct Neo4j queries for reliable and efficient processing.",
        tools=agent_tools,
        llm=llm,
        verbose=True,
        allow_delegation=False,
        max_iter=3  # Limit iterations to prevent confusion
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
    """Create a research agent with comprehensive research tools"""
    # Default tools that every research agent should have
    default_tools = [search_knowledge_graph_tool, find_similar_cases_tool, generate_embeddings_tool]
    
    # Add any additional tools passed in (like MCP tools)
    agent_tools = default_tools + (tools or [])
    
    return Agent(
        role="Research Agent",
        goal="Research using available tools",
        backstory="You research information using the available tools.",
        tools=agent_tools,
        verbose=True,
        allow_delegation=False,
        max_iter=5
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
            logger.info(f"Initializing MCP server with params: {server_params}")
            
            self.mcp_adapter = MCPServerAdapter([server_params])
            _mcp_tools = self.mcp_adapter.__enter__()
            
            if _mcp_tools:
                tool_names = [tool.name for tool in _mcp_tools]
                print(f"✅ Neo4j MCP Tools initialized: {tool_names}")
                print(f"📊 Available tools: get-neo4j-schema, read-neo4j-cypher, write-neo4j-cypher")
                logger.info(f"MCP tools successfully initialized: {tool_names}")
            else:
                print("⚠️ MCP adapter returned None tools")
                logger.warning("MCP adapter returned None tools")
                
            return self
        except Exception as e:
            print(f"⚠️ Could not initialize Neo4j MCP tools: {e}")
            print(f"💡 Make sure mcp-neo4j-cypher is installed and Neo4j is running")
            logger.error(f"MCP initialization failed: {e}")
            _mcp_tools = None
            return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the context and cleanup MCP tools."""
        global _mcp_tools
        if self.mcp_adapter:
            try:
                self.mcp_adapter.__exit__(exc_type, exc_val, exc_tb)
                print("🔌 Neo4j MCP connection closed")
                logger.info("MCP connection closed successfully")
            except Exception as e:
                print(f"Warning during MCP cleanup: {e}")
                logger.warning(f"MCP cleanup warning: {e}")
        else:
            logger.info("No MCP adapter to cleanup")
        _mcp_tools = None
        logger.info("Global MCP tools reset to None")

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

@tool
def mcp_process_document_tool(file_path: str, filename: str) -> Dict[str, Any]:
    """
    MCP-compatible document processing tool that uses the dynamic document processor.
    This tool is designed to work alongside MCP tools for Neo4j integration.
    
    Args:
        file_path: Path to the document file
        filename: Name of the file being processed
        
    Returns:
        Dictionary with processing results and statistics
    """
    try:
        from ..lib.dynamic_document_processor import dynamic_processor
        
        print(f"🔧 Processing document: {filename}")
        logger.info(f"MCP document processing started for: {filename}")
        
        # Note: MCP tools will be available to the agent, so the dynamic processor
        # should use direct Neo4j queries while the agent uses MCP tools for schema/queries
        
        # Read the file content
        with open(file_path, 'rb') as f:
            file_content = f.read()
        
        # Process document using dynamic AI-powered approach
        # The agent will handle MCP tool usage for Neo4j operations
        result = dynamic_processor.process_document(file_content, filename)
        
        logger.info(f"MCP document processing completed for: {filename}")
        return result
            
    except Exception as e:
        logger.error(f"MCP document processing failed for {filename}: {e}")
        return {
            "success": False,
            "filename": filename,
            "error": str(e),
            "extracted_counts": {}
        }

# All tools are now properly decorated with @tool above
# No need for fallback functions