"""
External Query API endpoint.

This endpoint exposes QueryFlow directly for external client consumption,
returning structured node data from the knowledge graph.

SECURITY POLICY - REQUEST TEXT IS NEVER LOGGED:
- Query content is NEVER logged by Lexon (only query length is recorded)
- Query content IS sent to OpenAI for processing (reasoning, planning, embeddings)
- Response data is sanitized to whitelist allowed fields only
- Rate limiting is applied per API key
- Request timeout prevents hung queries
"""
import asyncio
import os
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, ConfigDict
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.lib.external_auth import require_external_api_key, ExternalAuthContext
from app.lib.logging_config import setup_logger

logger = setup_logger("external-query")

# Configuration
RATE_LIMIT = "60/minute"
QUERY_TIMEOUT_SECONDS = 30.0

# Debug flag - OFF by default. Only enable temporarily for debugging specific issues.
# When enabled, query content will be logged. Use with extreme caution.
DEBUG_LOG_QUERIES = os.environ.get("EXTERNAL_DEBUG_LOG_QUERIES", "false").lower() == "true"

if DEBUG_LOG_QUERIES:
    logger.warning("⚠️  EXTERNAL_DEBUG_LOG_QUERIES is enabled - query content will be logged!")

# Rate limiter - keyed by API key for per-client limits
def get_api_key_from_header(request: Request) -> str:
    """Extract API key from request header for rate limiting."""
    return request.headers.get("X-API-Key", get_remote_address(request))

limiter = Limiter(key_func=get_api_key_from_header)

router = APIRouter(prefix="/external/v1/query", tags=["External Query"])


# Whitelist of allowed fields in response nodes
# This prevents leaking internal fields like embeddings, upload codes, etc.
ALLOWED_NODE_FIELDS = {
    # Metadata
    "node_label",
    "relationships",
    # ID fields (stable UUIDs)
    "case_id",
    "issue_id",
    "doctrine_id",
    "ruling_id",
    "proceeding_id",
    "party_id",
    "argument_id",
    "relief_id",
    "law_id",
    "fact_pattern_id",
    "policy_id",
    "forum_id",
    "jurisdiction_id",
    "relief_type_id",
    "domain_id",
    # Content fields
    "name",
    "text",
    "description",
    "summary",
    "reasoning",
    "ratio",
    "outcome",
    "citation",
    "court",
    "date",
    "role",
    "type",
    "label",
    "disposition_text",
    # Case-specific
    "case_name",
    "docket_number",
    "filing_date",
    "decision_date",
    # Party-specific
    "party_type",
    # Proceeding-specific
    "proceeding_type",
    "judge",
}


def sanitize_node(node: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize a node to only include whitelisted fields.
    
    This prevents leaking internal fields like:
    - *_embedding fields
    - *_upload_code fields
    - Internal Neo4j IDs
    - Debug/trace fields
    """
    return {k: v for k, v in node.items() if k in ALLOWED_NODE_FIELDS}


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    
    # Handle Neo4j date/time types
    try:
        obj_type = type(obj)
        if obj_type.__module__ == 'neo4j.time':
            if hasattr(obj, 'iso_format'):
                return obj.iso_format()
            elif hasattr(obj, 'year') and hasattr(obj, 'month') and hasattr(obj, 'day'):
                return f"{obj.year}-{obj.month:02d}-{obj.day:02d}"
            else:
                return str(obj)
    except (AttributeError, TypeError):
        pass
    
    raise TypeError(f"Type {type(obj)} not serializable")


class ExternalQueryRequest(BaseModel):
    """Request model for external query endpoint."""
    
    query: str = Field(
        ...,
        description=(
            "Natural language query to search the knowledge graph. "
            "This field is NOT logged by Lexon, but IS sent to OpenAI for processing."
        ),
        min_length=1,
        max_length=2000,
        examples=["What are the antitrust implications of platform monopolies?"]
    )
    
    limit: Optional[int] = Field(
        default=50,
        ge=1,
        le=200,
        description="Maximum number of nodes to return (1-200, default: 50)"
    )
    
    # Reject unknown fields to prevent accidental data leakage
    model_config = ConfigDict(extra="forbid")


class ExternalQueryResponse(BaseModel):
    """Response model for external query endpoint."""
    
    request_id: str = Field(
        ..., 
        description="Unique identifier for this request (for support/debugging)"
    )
    
    enriched_nodes: List[Dict[str, Any]] = Field(
        ...,
        description="List of enriched nodes from the knowledge graph with properties and relationship summaries"
    )
    
    total_count: int = Field(
        ...,
        description="Total number of nodes found (before applying limit)"
    )
    
    truncated: bool = Field(
        ...,
        description="Whether the results were truncated due to the limit parameter"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "request_id": "550e8400-e29b-41d4-a716-446655440000",
                "enriched_nodes": [
                    {
                        "node_label": "Issue",
                        "issue_id": "d989df7f-1234-5678-9abc-def012345678",
                        "text": "Whether Google maintained monopoly power in the ad tech market",
                        "relationships": {"doctrine": 3, "proceeding": 1}
                    },
                    {
                        "node_label": "Doctrine",
                        "doctrine_id": "b2f35703-abcd-efgh-ijkl-mnopqrstuvwx",
                        "name": "Rule of Reason",
                        "description": "Courts consider procompetitive justifications when evaluating antitrust claims",
                        "relationships": {"issue": 5, "ruling": 2}
                    }
                ],
                "total_count": 2,
                "truncated": False
            }
        }
    )


class ErrorResponse(BaseModel):
    """Error response model."""
    request_id: str = Field(..., description="Unique identifier for this request")
    error: str = Field(..., description="Error code")
    message: str = Field(..., description="Human-readable error message")


async def run_query_flow(query: str) -> Dict[str, Any]:
    """
    Execute QueryFlow and return the results.
    
    NOTE: This sends query text to OpenAI for:
    - Reasoning (planning the search strategy)
    - Planning (converting to formal search steps)
    - Embedding generation (for semantic search)
    
    This runs the full 5-stage pipeline:
    1. Reasoning - LLM plans the search strategy
    2. Planning - Converts to formal search steps
    3. Vector Search - Semantic search on embeddings
    4. Traversal - Graph traversal from found nodes
    5. Enrichment - Fetch full node data
    """
    from app.flow_query import QueryFlow
    
    flow = QueryFlow()
    flow.state.query = query
    
    # Execute all flow steps in sequence
    await flow.reason_query()
    await flow.interpret_query()
    await flow.execute_searches()
    await flow.deterministic_traversal()
    response = await flow.gather_enriched_data()
    
    return response


async def run_query_flow_with_timeout(
    query: str, 
    timeout_seconds: float = QUERY_TIMEOUT_SECONDS
) -> Dict[str, Any]:
    """
    Execute QueryFlow with a timeout.
    
    Args:
        query: The query to execute (sent to OpenAI)
        timeout_seconds: Maximum time to wait (default: 30s)
        
    Returns:
        QueryFlow response dict
        
    Raises:
        asyncio.TimeoutError: If query exceeds timeout
    """
    return await asyncio.wait_for(
        run_query_flow(query), 
        timeout=timeout_seconds
    )


@router.post(
    "",
    response_model=ExternalQueryResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        401: {"model": ErrorResponse, "description": "Invalid or missing API key"},
        403: {"model": ErrorResponse, "description": "Forbidden (edge secret invalid)"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
        504: {"model": ErrorResponse, "description": "Query timeout"},
    },
    summary="Query the knowledge graph",
    description="""
Execute a natural language query against the legal knowledge graph.

The query is processed through a multi-stage pipeline that:
1. Analyzes the query to identify relevant node types (Issues, Doctrines, Rulings, etc.)
2. Performs semantic search using embeddings
3. Traverses graph relationships to find connected nodes
4. Returns enriched node data with properties and relationship summaries

**Data Handling:**
- Query content is **NOT logged** by Lexon (only metadata: request_id, query length, timing, node counts)
- Query content **IS sent to OpenAI** for processing (reasoning, planning, embedding generation)
- See documentation for OpenAI data retention policies

**Result Limits:** Use the `limit` parameter to control the number of results (1-200, default: 50).
The response includes `total_count` and `truncated` to indicate if more results are available.

**Rate Limits:** 60 requests per minute per API key.

**Timeout:** Queries that exceed 30 seconds will return a 504 error.
""",
)
@limiter.limit(RATE_LIMIT)
async def query(
    request: Request,
    body: ExternalQueryRequest,
    response: Response,
    auth: ExternalAuthContext = Depends(require_external_api_key),
) -> ExternalQueryResponse:
    """
    Execute a knowledge graph query and return enriched nodes.
    
    SECURITY: Query content is never logged (only length). Query IS sent to OpenAI.
    """
    start_time = time.time()
    request_id = auth.request_id
    key_id = auth.key_id
    
    # Calculate length for logging - NEVER log actual query content
    query_len = len(body.query)
    
    # Add headers for client debugging and rate limit visibility
    response.headers["X-Request-ID"] = request_id
    response.headers["X-RateLimit-Limit"] = "60"
    response.headers["X-RateLimit-Reset"] = str(int(time.time()) + 60)
    
    # SAFE LOGGING - Never log query content, only metadata
    # Debug mode can be enabled temporarily via EXTERNAL_DEBUG_LOG_QUERIES=true
    if DEBUG_LOG_QUERIES:
        # Only use in development/debugging - logs query content
        logger.info(
            f"[{request_id}] [DEBUG] External query request - "
            f"key_id={key_id}, "
            f"query_len={query_len}, "
            f"query={body.query[:200]}..."
        )
    else:
        # Production mode - NEVER log query content
        logger.info(
            f"[{request_id}] External query request - "
            f"key_id={key_id}, "
            f"query_len={query_len}"
        )
    
    try:
        # Execute with timeout
        # NOTE: Query content is sent to OpenAI here
        result = await run_query_flow_with_timeout(body.query)
        
        enriched_nodes = result.get("enriched_nodes", [])
        
        # Sanitize nodes to only include whitelisted fields
        all_sanitized_nodes = [sanitize_node(node) for node in enriched_nodes]
        total_count = len(all_sanitized_nodes)
        
        # Apply limit
        limit = body.limit or 50
        sanitized_nodes = all_sanitized_nodes[:limit]
        truncated = total_count > limit
        
        # Log summary of results (no query content, only metadata)
        elapsed = time.time() - start_time
        node_counts: Dict[str, int] = {}
        for node in sanitized_nodes:
            label = node.get("node_label", "Unknown")
            node_counts[label] = node_counts.get(label, 0) + 1
        
        breakdown = ", ".join([f"{count} {label}" for label, count in sorted(node_counts.items())]) or "empty"
        
        logger.info(
            f"[{request_id}] External query completed - "
            f"key_id={key_id}, "
            f"elapsed={elapsed:.2f}s, "
            f"total={total_count}, "
            f"returned={len(sanitized_nodes)}, "
            f"truncated={truncated}, "
            f"breakdown={breakdown}"
        )
        
        return ExternalQueryResponse(
            request_id=request_id,
            enriched_nodes=sanitized_nodes,
            total_count=total_count,
            truncated=truncated,
        )
        
    except asyncio.TimeoutError:
        elapsed = time.time() - start_time
        logger.warning(
            f"[{request_id}] External query timeout - "
            f"key_id={key_id}, "
            f"elapsed={elapsed:.2f}s, "
            f"query_len={query_len}"
        )
        raise HTTPException(
            status_code=504,
            detail={
                "request_id": request_id,
                "error": "timeout",
                "message": f"Query exceeded {QUERY_TIMEOUT_SECONDS}s timeout. Please try a more specific query.",
            }
        )
        
    except Exception as e:
        elapsed = time.time() - start_time
        # Log error WITHOUT query content - only error type and metadata
        logger.error(
            f"[{request_id}] External query failed - "
            f"key_id={key_id}, "
            f"elapsed={elapsed:.2f}s, "
            f"query_len={query_len}, "
            f"error_type={type(e).__name__}"
        )
        # Don't use exc_info=True as it might include request body in traceback
        raise HTTPException(
            status_code=500,
            detail={
                "request_id": request_id,
                "error": "query_failed",
                "message": "An error occurred while processing your query. Please try again.",
            }
        )
