"""
Document Processing Tool for CrewAI

This module contains tools for processing documents using AI-powered dynamic extraction
with direct Neo4j integration.
"""

import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from crewai.tools import tool

logger = logging.getLogger(__name__)

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
        from ...lib.dynamic_document_processor import dynamic_processor
        
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

 