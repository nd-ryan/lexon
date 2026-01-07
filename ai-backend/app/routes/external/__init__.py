"""
External API for third-party client access.

This module creates a separate FastAPI sub-application for external routes,
providing dedicated documentation and consistent error handling.

Endpoints:
- POST /query - Execute knowledge graph queries (auth required, rate-limited)
- GET /health - Health check (unauthenticated, minimal info)
- GET /version - API version info (unauthenticated, minimal info)
- GET /openapi.json - OpenAPI spec (auth required)

Documentation:
- Swagger UI and ReDoc are disabled on the API
- Access docs via authenticated Next.js pages at /admin/api-docs
- OpenAPI spec requires external API authentication

Security:
- Server-to-server only; CORS not enabled
- Query endpoint is rate-limited per API key
- Request bodies are not persisted; logs contain metadata only
- OpenAPI spec requires authentication to prevent schema enumeration
"""
import time
import uuid
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from fastapi import Depends
from fastapi.openapi.utils import get_openapi

from .query import router as query_router, limiter, RATE_LIMIT
from app.lib.external_auth import require_external_api_key, ExternalAuthContext

# API version - update when making breaking changes
API_VERSION = "1.2.0"

# Request ID header name
REQUEST_ID_HEADER = "X-Request-ID"

# API description for OpenAPI docs
API_DESCRIPTION = """
## Lexon External API

Query the Lexon legal knowledge graph to retrieve structured data about legal cases, 
doctrines, issues, rulings, and more.

### Important: Server-to-Server Only

This API is intended for **server-to-server use only**. Do not call it from browsers 
or client-side code. CORS is not enabled for `/external` endpoints.

### Data Handling

- **Lexon does not persist request bodies.** Operational logs store metadata only (request_id, timing, counts).
- **Query content IS sent to OpenAI** via the OpenAI API for processing.
- OpenAI's API data usage and retention terms apply to query text.
- If you require specific data retention or non-retention guarantees, discuss with Lexon before enabling production traffic.

**Current subprocessors:** OpenAI (LLM reasoning + embeddings). Contact Lexon for current list and terms.

### Authentication

All requests to `/query` must include an API key via one of:

**Preferred:**
```
Authorization: Bearer your_api_key_here
```

**Alternative:**
```
X-API-Key: your_api_key_here
```

The `/health` and `/version` endpoints do not require authentication and return minimal, non-sensitive information only.

The `/openapi.json` endpoint requires authentication and can be used to import the API spec into Postman, Insomnia, or code generators.

### Rate Limits

- `/query`: 60 requests per minute per API key
- Response headers include rate limit information
- 429 responses include a `Retry-After` header
"""

# Create the external API sub-application
# All docs endpoints are disabled - served via authenticated routes instead
external_app = FastAPI(
    title="Lexon External API",
    description=API_DESCRIPTION,
    version=API_VERSION,
    docs_url=None,  # Disabled - use /admin/api-docs instead
    redoc_url=None,  # Disabled - use /admin/api-docs/redoc instead
    openapi_url=None,  # Disabled - custom authenticated route below
    contact={
        "name": "Lexon Support",
    },
    license_info={
        "name": "Proprietary",
    },
)


# ============================================================================
# Middleware
# ============================================================================

class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware that ensures every request has a unique X-Request-ID.
    
    This runs before validation, so even 422 errors will have a request_id.
    """
    async def dispatch(self, request: Request, call_next):
        # Generate request_id if not provided
        request_id = request.headers.get(REQUEST_ID_HEADER)
        if not request_id:
            request_id = str(uuid.uuid4())
        
        # Store in request state for access by handlers
        request.state.request_id = request_id
        
        # Process request
        response = await call_next(request)
        
        # Always include X-Request-ID in response
        response.headers[REQUEST_ID_HEADER] = request_id
        
        return response


# Add middlewares (order matters - first added = outermost)
external_app.add_middleware(RequestIDMiddleware)
external_app.add_middleware(SlowAPIMiddleware)

# Configure rate limiter
external_app.state.limiter = limiter


# ============================================================================
# Helper Functions
# ============================================================================

def get_request_id(request: Request) -> str:
    """Get request_id from request state or generate one."""
    if hasattr(request.state, 'request_id'):
        return request.state.request_id
    return str(uuid.uuid4())


# ============================================================================
# Custom Exception Handlers
# ============================================================================

@external_app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """
    Handle rate limit exceeded errors with consistent JSON format and headers.
    """
    request_id = get_request_id(request)
    
    # Extract retry-after from the exception
    retry_after = "60"  # Default to 60 seconds
    if hasattr(exc, 'detail') and exc.detail:
        # slowapi puts the limit info in detail
        retry_after = str(exc.detail).split()[-1] if exc.detail else "60"
    
    # Calculate reset timestamp (current time + retry_after seconds)
    try:
        reset_timestamp = int(time.time()) + int(retry_after)
    except (ValueError, TypeError):
        reset_timestamp = int(time.time()) + 60
    
    return JSONResponse(
        status_code=429,
        content={
            "request_id": request_id,
            "error": "rate_limit_exceeded",
            "message": f"Too many requests. Retry after {retry_after} seconds.",
        },
        headers={
            REQUEST_ID_HEADER: request_id,
            "Retry-After": retry_after,
            "X-RateLimit-Limit": "60",
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(reset_timestamp),
        }
    )


@external_app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Handle Pydantic validation errors with consistent JSON format.
    Request ID is always included even for validation errors.
    """
    request_id = get_request_id(request)
    
    # Simplify error messages for client
    errors = []
    for error in exc.errors():
        loc = ".".join(str(l) for l in error.get("loc", []))
        msg = error.get("msg", "Invalid value")
        errors.append({"field": loc, "message": msg})
    
    return JSONResponse(
        status_code=422,
        content={
            "request_id": request_id,
            "error": "validation_error",
            "message": "Invalid request body",
            "details": errors,
        },
        headers={
            REQUEST_ID_HEADER: request_id,
        }
    )


@external_app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """
    Handle unexpected errors with consistent JSON format.
    Never expose internal error details to clients.
    """
    request_id = get_request_id(request)
    
    return JSONResponse(
        status_code=500,
        content={
            "request_id": request_id,
            "error": "internal_error",
            "message": "An unexpected error occurred. Please try again later.",
        },
        headers={
            REQUEST_ID_HEADER: request_id,
        }
    )


# ============================================================================
# Response Models
# ============================================================================

class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(..., description="Service status")
    timestamp: str = Field(..., description="Current server timestamp (ISO 8601)")


class VersionResponse(BaseModel):
    """Version info response."""
    version: str = Field(..., description="API version")
    api: str = Field(..., description="API name")


class ErrorResponse(BaseModel):
    """Standard error response format."""
    request_id: str = Field(..., description="Unique identifier for this request")
    error: str = Field(..., description="Error code")
    message: str = Field(..., description="Human-readable error message")


# ============================================================================
# Routes
# ============================================================================

# Include the query router
external_app.include_router(query_router)


@external_app.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Check if the external API is healthy. Unauthenticated; returns minimal info only.",
    tags=["Status"],
)
async def health() -> HealthResponse:
    """
    Health check endpoint.
    
    Returns the service status and current timestamp only.
    This endpoint does not require authentication and returns minimal information.
    """
    return HealthResponse(
        status="ok",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@external_app.get(
    "/version",
    response_model=VersionResponse,
    summary="API version",
    description="Get the current API version. Unauthenticated; returns minimal info only.",
    tags=["Status"],
)
async def version() -> VersionResponse:
    """
    Version info endpoint.
    
    Returns the API version number and API name only.
    This endpoint does not require authentication and returns minimal information.
    No environment details, git SHA, or other fingerprinting data is exposed.
    """
    return VersionResponse(
        version=API_VERSION,
        api="Lexon External API",
    )


@external_app.get(
    "/openapi.json",
    summary="OpenAPI specification",
    description="Get the OpenAPI specification for this API. **Requires authentication.**",
    tags=["Documentation"],
    include_in_schema=False,  # Don't show this endpoint in itself
)
async def get_openapi_spec(
    auth: ExternalAuthContext = Depends(require_external_api_key),
) -> dict:
    """
    OpenAPI specification endpoint.
    
    Returns the full OpenAPI 3.x specification for this API.
    This endpoint requires authentication to prevent schema enumeration.
    
    Use cases:
    - Import into Postman, Insomnia, or other API tools
    - Code generation from spec
    - Client SDK generation
    """
    # Generate OpenAPI schema dynamically
    if not external_app.openapi_schema:
        external_app.openapi_schema = get_openapi(
            title=external_app.title,
            version=external_app.version,
            description=external_app.description,
            routes=external_app.routes,
            contact=external_app.contact,
            license_info=external_app.license_info,
        )
    return external_app.openapi_schema


# ============================================================================
# Exports
# ============================================================================

# Export the app and limiter for use in main.py
# Note: We now export external_app instead of router
__all__ = ["external_app", "limiter"]
