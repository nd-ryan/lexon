"""
Embeddings Generation Tool for CrewAI

This module contains tools for generating embeddings for cases in the knowledge graph.
"""

import asyncio
import logging
from typing import Dict, Any, List
from crewai.tools import tool

logger = logging.getLogger(__name__)

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
        from ...lib.embeddings import generate_embeddings_for_cases
        
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