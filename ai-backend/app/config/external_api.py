"""
External API configuration constants.

This module centralizes all external API configuration values to ensure
consistency across code, tests, and documentation.

To update limits or settings, modify the values here and regenerate
documentation using the script in scripts/generate_external_api_docs.py
"""
from typing import Dict, Any

# ============================================================================
# Query Limits
# ============================================================================

# Maximum length of query text in characters
QUERY_MAX_LENGTH = 12000

# Minimum length of query text in characters
QUERY_MIN_LENGTH = 1

# Maximum number of nodes to return in a single query
QUERY_RESULT_LIMIT_MAX = 200

# Default number of nodes to return if limit not specified
QUERY_RESULT_LIMIT_DEFAULT = 50

# ============================================================================
# Rate Limiting
# ============================================================================

# Rate limit string format: "requests/time_period"
# Examples: "60/minute", "1000/hour", "10000/day"
RATE_LIMIT = "60/minute"

# Extract numeric rate limit for documentation
RATE_LIMIT_NUMERIC = 60
RATE_LIMIT_PERIOD = "minute"

# ============================================================================
# Timeouts
# ============================================================================

# Query execution timeout in seconds
QUERY_TIMEOUT_SECONDS = 30.0

# ============================================================================
# Export configuration dict for documentation generation
# ============================================================================

def get_config_dict() -> Dict[str, Any]:
    """
    Get all configuration values as a dictionary.
    
    Useful for documentation generation and testing.
    """
    return {
        "query_max_length": QUERY_MAX_LENGTH,
        "query_min_length": QUERY_MIN_LENGTH,
        "query_result_limit_max": QUERY_RESULT_LIMIT_MAX,
        "query_result_limit_default": QUERY_RESULT_LIMIT_DEFAULT,
        "rate_limit": RATE_LIMIT,
        "rate_limit_numeric": RATE_LIMIT_NUMERIC,
        "rate_limit_period": RATE_LIMIT_PERIOD,
        "query_timeout_seconds": QUERY_TIMEOUT_SECONDS,
    }


def format_query_length_description() -> str:
    """Format query length description for documentation."""
    return f"Natural language query ({QUERY_MIN_LENGTH}-{QUERY_MAX_LENGTH:,} chars)"


def format_rate_limit_description() -> str:
    """Format rate limit description for documentation."""
    return f"{RATE_LIMIT_NUMERIC} requests per {RATE_LIMIT_PERIOD}"
