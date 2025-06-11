#!/usr/bin/env python3
"""
Neo4j MCP Server for CrewAI Integration
Provides Neo4j database access through the Model Context Protocol
"""

import os
import sys
import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List

# Add the project root to the Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("neo4j_mcp_server")

# Initialize FastMCP server
mcp = FastMCP("neo4j_server")

# Neo4j connection details
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j") 
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

# Import Neo4j driver
try:
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    logger.info(f"Connected to Neo4j at {NEO4J_URI}")
except Exception as e:
    logger.error(f"Failed to connect to Neo4j: {e}")
    driver = None

def execute_cypher_query(query: str, parameters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    """Execute a Cypher query and return results."""
    if not driver:
        raise Exception("Neo4j driver not initialized")
    
    with driver.session() as session:
        try:
            result = session.run(query, parameters or {})
            records = []
            for record in result:
                record_dict = {}
                for key in record.keys():
                    value = record[key]
                    # Convert Neo4j types to Python types
                    if hasattr(value, 'items'):  # Node or Relationship
                        if hasattr(value, 'labels'):  # Node
                            record_dict[key] = {
                                "labels": list(value.labels),
                                "properties": dict(value.items())
                            }
                        else:  # Relationship
                            record_dict[key] = {
                                "type": value.type,
                                "properties": dict(value.items())
                            }
                    elif hasattr(value, '__iter__') and not isinstance(value, str):
                        record_dict[key] = list(value)
                    else:
                        record_dict[key] = value
                records.append(record_dict)
            return records
        except Exception as e:
            logger.error(f"Error executing query: {e}")
            raise

@mcp.tool(name="get_neo4j_schema", description="Get the Neo4j database schema including nodes, relationships, and properties")
def get_neo4j_schema() -> Dict[str, Any]:
    """Get comprehensive Neo4j database schema information."""
    try:
        schema_info = {}
        
        # Get node labels and their properties
        node_query = """
        CALL db.labels() YIELD label
        CALL apoc.meta.nodeTypeProperties() YIELD nodeType, propertyName, propertyTypes
        WHERE nodeType = ':' + label
        RETURN label, collect({property: propertyName, types: propertyTypes}) as properties
        ORDER BY label
        """
        
        # Fallback if APOC is not available
        simple_node_query = """
        CALL db.labels() YIELD label
        RETURN label, [] as properties
        ORDER BY label
        """
        
        try:
            nodes = execute_cypher_query(node_query)
        except:
            # Fallback to simple query if APOC is not available
            nodes = execute_cypher_query(simple_node_query)
        
        schema_info["nodes"] = nodes
        
        # Get relationship types
        rel_query = "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType ORDER BY relationshipType"
        relationships = execute_cypher_query(rel_query)
        schema_info["relationships"] = relationships
        
        # Get constraints
        constraint_query = "SHOW CONSTRAINTS YIELD name, type, entityType, labelsOrTypes, properties"
        try:
            constraints = execute_cypher_query(constraint_query)
        except:
            # Fallback for older Neo4j versions
            constraints = []
        schema_info["constraints"] = constraints
        
        # Get indexes
        index_query = "SHOW INDEXES YIELD name, type, entityType, labelsOrTypes, properties"
        try:
            indexes = execute_cypher_query(index_query)
        except:
            # Fallback for older Neo4j versions
            indexes = []
        schema_info["indexes"] = indexes
        
        logger.info("Schema retrieved successfully")
        return {
            "success": True,
            "schema": schema_info
        }
        
    except Exception as e:
        logger.error(f"Error getting schema: {e}")
        return {
            "success": False,
            "error": str(e),
            "schema": {}
        }

@mcp.tool(name="read_cypher", description="Execute a read-only Cypher query against the Neo4j database")
def read_cypher(query: str, parameters: Dict[str, Any] = None) -> Dict[str, Any]:
    """Execute a read-only Cypher query."""
    try:
        # Basic check for write operations (not foolproof, but helpful)
        query_upper = query.upper()
        write_keywords = ['CREATE', 'MERGE', 'SET', 'DELETE', 'REMOVE', 'DROP']
        
        if any(keyword in query_upper for keyword in write_keywords):
            return {
                "success": False,
                "error": "Write operations are not allowed in read_cypher. Use write_cypher for modifications.",
                "results": []
            }
        
        results = execute_cypher_query(query, parameters)
        
        logger.info(f"Read query executed successfully, returned {len(results)} records")
        return {
            "success": True,
            "query": query,
            "parameters": parameters or {},
            "results": results,
            "count": len(results)
        }
        
    except Exception as e:
        logger.error(f"Error executing read query: {e}")
        return {
            "success": False,
            "error": str(e),
            "query": query,
            "results": [],
            "count": 0
        }

@mcp.tool(name="write_cypher", description="Execute a write Cypher query against the Neo4j database (CREATE, MERGE, SET, DELETE, etc.)")
def write_cypher(query: str, parameters: Dict[str, Any] = None) -> Dict[str, Any]:
    """Execute a write Cypher query."""
    try:
        results = execute_cypher_query(query, parameters)
        
        logger.info(f"Write query executed successfully")
        return {
            "success": True,
            "query": query,
            "parameters": parameters or {},
            "results": results,
            "count": len(results)
        }
        
    except Exception as e:
        logger.error(f"Error executing write query: {e}")
        return {
            "success": False,
            "error": str(e),
            "query": query,
            "results": [],
            "count": 0
        }

@mcp.tool(name="generate_cypher", description="Generate a Cypher query from natural language description")
def generate_cypher(description: str) -> Dict[str, Any]:
    """Generate a Cypher query from natural language description."""
    try:
        # Import the existing cypher generator
        from app.lib.cypher_generator import generate_cypher_query_async
        import asyncio
        
        # Run the async function
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            cypher_query = loop.run_until_complete(generate_cypher_query_async(description))
        finally:
            loop.close()
        
        logger.info("Cypher query generated successfully")
        return {
            "success": True,
            "description": description,
            "cypher_query": cypher_query
        }
        
    except Exception as e:
        logger.error(f"Error generating Cypher query: {e}")
        return {
            "success": False,
            "error": str(e),
            "description": description,
            "cypher_query": ""
        }

@mcp.tool(name="search_knowledge_graph", description="Search the knowledge graph using natural language - combines query generation and execution")
def search_knowledge_graph(query: str) -> Dict[str, Any]:
    """Complete knowledge graph search: generate Cypher from natural language and execute it."""
    try:
        # First generate the Cypher query
        cypher_result = generate_cypher(query)
        
        if not cypher_result["success"]:
            return cypher_result
        
        cypher_query = cypher_result["cypher_query"]
        
        # Then execute the query
        search_result = read_cypher(cypher_query)
        
        # Combine the results
        return {
            "success": search_result["success"],
            "natural_language_query": query,
            "generated_cypher": cypher_query,
            "results": search_result["results"],
            "count": search_result["count"],
            "error": search_result.get("error")
        }
        
    except Exception as e:
        logger.error(f"Error in knowledge graph search: {e}")
        return {
            "success": False,
            "error": str(e),
            "natural_language_query": query,
            "generated_cypher": "",
            "results": [],
            "count": 0
        }

# Health check for the MCP server
@mcp.tool(name="health_check", description="Check the health of the Neo4j MCP server connection")
def health_check() -> Dict[str, Any]:
    """Check if the Neo4j connection is healthy."""
    try:
        # Simple query to test connection
        test_result = execute_cypher_query("RETURN 1 as test")
        
        return {
            "success": True,
            "status": "healthy",
            "neo4j_uri": NEO4J_URI,
            "connection_test": "passed"
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "success": False,
            "status": "unhealthy", 
            "error": str(e),
            "neo4j_uri": NEO4J_URI,
            "connection_test": "failed"
        }

if __name__ == "__main__":
    logger.info("Starting Neo4j MCP Server")
    logger.info(f"Connecting to Neo4j at: {NEO4J_URI}")
    
    # Test connection on startup
    health_result = health_check()
    if health_result["success"]:
        logger.info("✅ Neo4j connection successful")
    else:
        logger.error(f"❌ Neo4j connection failed: {health_result['error']}")
    
    try:
        mcp.run(transport="stdio")
    except Exception as e:
        logger.exception("Neo4j MCP server crashed")
        sys.exit(1) 