"""
MCP (Model Context Protocol) Integration for CrewAI

This module provides MCP server configuration and context management
following CrewAI best practices for MCP integration.
"""

import os
import logging
from typing import Optional, List
from crewai_tools import MCPServerAdapter
from mcp import StdioServerParameters

logger = logging.getLogger(__name__)


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


# Global MCP tools instance
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


class MCPEnabledAgents:
    """
    Context manager for agents with Neo4j's official MCP tools.
    
    This follows CrewAI MCP best practices by using a context manager
    to handle MCP server lifecycle management.
    """
    
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