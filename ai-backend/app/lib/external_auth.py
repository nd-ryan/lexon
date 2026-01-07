"""
Authentication module for external API access.

External clients use a separate API key from internal services.
This ensures external clients cannot access internal routes even
if they discover the endpoints.

Security layers:
1. Edge secret (X-Lexon-Edge) - Validates request came through Cloudflare
2. API key (X-API-Key or Authorization: Bearer) - Validates client identity
3. Rate limiting - Applied per API key
"""
import hashlib
import os
import uuid
from typing import Optional
from fastapi import Security, HTTPException, status, Request, Depends
from fastapi.security.api_key import APIKeyHeader
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

API_KEY_NAME = "X-API-Key"
EDGE_SECRET_HEADER = "X-Lexon-Edge"
REQUEST_ID_HEADER = "X-Request-ID"

# Support both X-API-Key header and Authorization: Bearer
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)

# Edge-to-origin secret - Cloudflare injects this header
# If requests bypass Cloudflare, they won't have this header
LEXON_EDGE_SECRET = os.environ.get("LEXON_EDGE_SECRET")

# External API keys - comma-separated list for rotation support
# Example: "key_client_abc123,key_client_xyz789"
_raw_keys = os.environ.get("EXTERNAL_API_KEYS", "")
EXTERNAL_API_KEYS = [k.strip() for k in _raw_keys.split(",") if k.strip()]

# Backward compatibility: also check single key if list is empty
_single_key = os.environ.get("EXTERNAL_API_KEY")
if not EXTERNAL_API_KEYS and _single_key:
    EXTERNAL_API_KEYS = [_single_key]

if not EXTERNAL_API_KEYS:
    print("Warning: No external API keys configured. External API will reject all requests.")

if not LEXON_EDGE_SECRET:
    print("Warning: LEXON_EDGE_SECRET not set. Edge secret validation will be skipped (not recommended for production).")


def hash_key_id(api_key: str) -> str:
    """
    Generate a non-reversible key identifier for logging.
    
    Uses SHA-256 hash to create a correlatable identifier without
    exposing any part of the actual secret key material.
    
    Returns first 8 characters of the hex digest.
    """
    return hashlib.sha256(api_key.encode()).hexdigest()[:8]


def generate_request_id() -> str:
    """Generate a unique request ID."""
    return str(uuid.uuid4())


class ExternalAuthContext:
    """Context object returned by external auth dependency."""
    
    def __init__(self, request_id: str, key_id: str):
        self.request_id = request_id
        self.key_id = key_id  # First 8 chars of SHA-256(api_key) for audit logging


async def require_edge_secret(request: Request) -> None:
    """
    Dependency that validates the edge-to-origin secret header.
    
    This ensures requests came through Cloudflare and not directly to the origin.
    If LEXON_EDGE_SECRET is not configured, this check is skipped (dev mode).
    
    Raises:
        HTTPException: 403 if edge secret is configured but header is missing/invalid
    """
    if not LEXON_EDGE_SECRET:
        # Skip check if not configured (dev mode)
        return
    
    edge_header = request.headers.get(EDGE_SECRET_HEADER)
    if edge_header != LEXON_EDGE_SECRET:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden",
        )


def extract_api_key(
    x_api_key: Optional[str],
    bearer: Optional[HTTPAuthorizationCredentials],
) -> Optional[str]:
    """
    Extract API key from either X-API-Key header or Authorization: Bearer.
    
    Priority:
    1. Authorization: Bearer (preferred)
    2. X-API-Key header (legacy/alternative)
    """
    if bearer and bearer.credentials:
        return bearer.credentials
    if x_api_key:
        return x_api_key
    return None


async def require_external_api_key(
    request: Request,
    x_api_key: Optional[str] = Security(api_key_header),
    bearer: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    _edge: None = Depends(require_edge_secret),
) -> ExternalAuthContext:
    """
    Dependency that validates the external API key.
    
    Accepts API key via:
    - Authorization: Bearer <api_key> (preferred)
    - X-API-Key: <api_key> (alternative)
    
    Checks:
    1. Edge secret (via dependency) - Ensures request came through Cloudflare
    2. API key - Validates client identity against configured keys
    
    Returns an ExternalAuthContext with:
    - request_id: Unique identifier for this request (from header or generated)
    - key_id: First 8 chars of SHA-256 hash of API key (for audit logging)
    
    Raises:
        HTTPException: 401 if the API key is invalid or missing
        HTTPException: 403 if edge secret validation fails
        HTTPException: 503 if no API keys are configured
    """
    # Get request_id from header (set by middleware) or generate one
    request_id = request.headers.get(REQUEST_ID_HEADER) or generate_request_id()
    
    if not EXTERNAL_API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "request_id": request_id,
                "error": "service_unavailable",
                "message": "External API is not configured",
            },
        )
    
    # Extract API key from either header
    api_key = extract_api_key(x_api_key, bearer)
    
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "request_id": request_id,
                "error": "unauthorized",
                "message": "API key required. Use 'Authorization: Bearer <key>' or 'X-API-Key: <key>'",
            },
        )
    
    if api_key not in EXTERNAL_API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "request_id": request_id,
                "error": "unauthorized",
                "message": "Invalid API key",
            },
        )
    
    # Generate key_id from hash for audit logging
    # Uses SHA-256 so logs never contain actual key material
    key_id = hash_key_id(api_key)
    
    return ExternalAuthContext(request_id=request_id, key_id=key_id)
