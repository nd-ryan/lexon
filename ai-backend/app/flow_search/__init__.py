"""
Search Flow Package

This package contains the CrewAI Flow for handling search queries against 
the Neo4j knowledge graph using MCP tools.

Currently using the new search flow with label/id block approach and batch enrichment.
Original search flow is preserved in search_flow.py for rollback if needed.
"""

from .new_search_flow import NewSearchFlow as SearchFlow, create_new_search_flow as create_search_flow

__all__ = ["SearchFlow", "create_search_flow"] 