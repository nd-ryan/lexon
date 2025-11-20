"""
OpenAI Responses API client configuration and utilities.
"""

import os
from typing import Optional
from openai import OpenAI
import logging

logger = logging.getLogger(__name__)

# Default model for Responses API
DEFAULT_RESPONSES_MODEL = "gpt-4o"

def get_responses_model() -> str:
    """Get the model to use for Responses API from environment or default."""
    return os.getenv("OPENAI_RESPONSES_MODEL", DEFAULT_RESPONSES_MODEL)

def get_openai_client() -> OpenAI:
    """
    Get an initialized OpenAI client for Responses API.
    
    Requires OPENAI_API_KEY environment variable to be set.
    
    Returns:
        OpenAI: Configured OpenAI client instance
        
    Raises:
        ValueError: If OPENAI_API_KEY is not set
    """
    api_key = os.getenv("OPENAI_API_KEY")
    
    if not api_key:
        logger.error("OPENAI_API_KEY environment variable is not set")
        raise ValueError("OPENAI_API_KEY environment variable is required")
    
    return OpenAI(api_key=api_key)

