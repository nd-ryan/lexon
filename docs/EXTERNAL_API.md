# External API Documentation

This document describes the Lexon External API for third-party client integration.

## Overview

The External API provides programmatic access to Lexon's legal knowledge graph. It allows you to execute natural language queries and receive structured data about legal cases, doctrines, issues, rulings, and more.

## Quick mental model (Lexon has *two* API “surfaces”)

The most important thing to know is that Lexon has:

- **External API (for customers / third parties)**: lives on **`api.lexon.law`** and is what this document describes.
- **Internal API (for the Lexon web app + admins)**: used by the Lexon product itself and **is not for external clients**.

These two surfaces intentionally use **different routes and different API keys**.

### Which hostname should I use?

- **If you’re building an integration** (your server talking to Lexon): use **`https://api.lexon.law`**
- **If you’re using the Lexon web app / staff docs pages**: you’ll be on **`https://lexon.law`**

### Why do I sometimes see `/v1/...` and sometimes `/external/v1/...`?

- **What external clients should call (production):** `https://api.lexon.law/v1/...`
- **What the backend implements internally:** the external API is mounted at `.../external/v1/...`

In production, the edge (e.g., Cloudflare) rewrites:

- `https://api.lexon.law/v1/*` → `https://<origin>/external/v1/*`

So **external clients should always use `/v1`**, even though the Python backend internally uses `/external/v1`.

### Which API key goes where?

- **External API key** (provided to customers): used on `api.lexon.law` external endpoints.
  - Accepted headers:
    - `Authorization: Bearer <external_key>`
    - `X-API-Key: <external_key>`
- **Internal API key** (`FASTAPI_API_KEY`): used only by the Lexon app/server to call internal endpoints like `/api/ai/*` and `/api/v1/*`.
  - Accepted header:
    - `X-API-Key: <internal_key>`

### What happens if I use the wrong key or wrong endpoint?

- **External key → internal endpoint** (example: `GET https://api.lexon.law/api/ai/shared-nodes`): typically **401 Unauthorized**
- **Internal key → external endpoint** (example: `POST https://api.lexon.law/v1/query`): typically **401 Unauthorized**

This is by design: external clients should not be able to call internal routes even if they guess URLs.

## Important: Server-to-Server Only

**This API is intended for server-to-server use only.**

- Do not call this API from browsers or client-side code
- Do not expose your API key in frontend applications
- Do not rely on CORS as a security boundary. This service is protected primarily by API key auth and (in production) an edge-to-origin secret check.

## Interactive Documentation

### Internal Staff

Interactive API documentation is available to authenticated Lexon users with **`developer` or `admin`** role:

- **Swagger UI:** `https://lexon.law/api/docs/swagger` (requires Lexon login)
- **ReDoc:** `https://lexon.law/api/docs/redoc` (requires Lexon login)
- **OpenAPI JSON:** `https://lexon.law/api/docs/openapi` (requires Lexon login)

For local development:
- Swagger UI: `http://localhost:3000/api/docs/swagger`
- ReDoc: `http://localhost:3000/api/docs/redoc`
- OpenAPI JSON: `http://localhost:3000/api/docs/openapi`

**Note:** These documentation pages are served by the **Next.js app** on `lexon.law` and proxy the external API OpenAPI spec server-side.

**Note (common confusion):** Swagger/ReDoc UIs are “views” of the OpenAPI schema. They may not always display the correct production hostname unless the schema explicitly sets it. When in doubt, use the **Base URL** in this document (`https://api.lexon.law/v1`).

### External Clients

The OpenAPI specification is available via authenticated request:

```bash
curl "https://api.lexon.law/v1/openapi.json" \
  -H "Authorization: Bearer your_api_key_here"
```

This spec can be imported directly into Postman, Insomnia, or code generators.

## Base URL

```
https://api.lexon.law/v1
```

**Implementation note:** The FastAPI service is mounted at `/external/v1/*` in the backend app. Production traffic is routed via `api.lexon.law` and rewritten so that `/v1/*` maps to the backend’s `/external/v1/*`.

For local development (running the FastAPI backend directly on port 8000):

```
http://localhost:8000/external/v1
```

## Data Handling and Privacy

**Important:** Please review this section carefully before integrating.

### Data Persistence

**Lexon does not persist request bodies.** Operational logs store metadata only:
- `request_id` - unique identifier
- `key_id` - first 8 characters of a one-way hash of your API key (for correlation, not credential material)
- `query_len` - length of query in characters
- `elapsed` - processing time
- `total` - total nodes found
- `returned` - nodes returned (after limit applied)
- `truncated` - whether results were truncated
- `breakdown` - node types returned (e.g., "3 Doctrine, 2 Issue")

**Lexon does NOT log or persist:**
- Query content
- Request body content
- Any user-provided text

### What Is Sent to OpenAI

Query text **IS sent to OpenAI** via the OpenAI API for processing. This is required for the query pipeline to work:

1. **Reasoning** - GPT analyzes your query to identify relevant node types
2. **Planning** - GPT creates a search strategy
3. **Embeddings** - OpenAI generates embeddings for semantic search

**OpenAI Data Handling:**
- OpenAI's API data usage and retention terms apply to query text
- Review [OpenAI's API Data Usage Policy](https://openai.com/policies/api-data-usage-policies) for details
- If you require specific data retention or non-retention guarantees, discuss with Lexon before enabling production traffic

### Subprocessors

**Current subprocessors for this endpoint:** OpenAI (LLM reasoning + embeddings).

Contact Lexon for the current subprocessor list and applicable terms.

### Sensitive Data Guidance

Since query text is sent to OpenAI, we recommend:

- **Avoid including** client names, deal terms, trade secrets, or personally identifiable information in queries where possible
- **Prefer generalized descriptions** (e.g., "antitrust implications of vertical integration" rather than "Company X's acquisition of Company Y")
- **Review your organization's policies** regarding third-party LLM usage for sensitive data

### Summary

| Data | Logged by Lexon | Persisted by Lexon | Sent to OpenAI |
|------|-----------------|-------------------|----------------|
| Query text | **No** | **No** | **Yes** |
| Request metadata | Yes | No | No |
| Response data | No | No | No |

## Authentication

All requests to the authenticated endpoints **under the Base URL** must include an API key:

- `POST https://api.lexon.law/v1/query`
- `GET https://api.lexon.law/v1/openapi.json`

### Preferred: Authorization Header

```
Authorization: Bearer your_api_key_here
```

### Alternative: X-API-Key Header

```
X-API-Key: your_api_key_here
```

### Production edge enforcement (Cloudflare)

In production, the backend can require an **edge-to-origin secret** (`LEXON_EDGE_SECRET`) which is expected to be injected by Lexon’s edge (e.g. Cloudflare). If you attempt to call the origin directly (bypassing the edge), you may receive **HTTP 403** even with a valid API key.

You should **not** set this edge header yourself as an external client; instead, ensure you are calling the Lexon-provided public base URL.

Your API key will be provided by Lexon. Keep it secure and do not expose it in client-side code.

**Environment Variable:** We recommend storing your key as `LEXON_API_KEY` in your environment:

```bash
# Single key
export LEXON_API_KEY="your_api_key_here"

# Or multiple keys for rotation (backend only)
export LEXON_API_KEYS="key1,key2"
```

**Note:** The `/health` and `/version` endpoints do not require authentication and return minimal, non-sensitive information only (status/timestamp and version/name respectively).

## Rate Limits

| Endpoint | Limit | Key |
|----------|-------|-----|
| `/query` | 60 requests/minute | Per API key |

Exceeding the limit returns HTTP 429 with a `Retry-After` header.

### Rate Limit Response Headers

`POST /query` responses include rate limit information:

| Header | Description |
|--------|-------------|
| `X-RateLimit-Limit` | Maximum requests per window |
| `X-RateLimit-Reset` | Unix timestamp when the rate limit resets |
| `X-Request-ID` | Unique identifier for the request (always present) |

On 429 responses:

| Header | Description |
|--------|-------------|
| `Retry-After` | Seconds to wait before retrying |
| `X-RateLimit-Remaining` | Will be "0" |

**Important (current implementation detail):** Rate limiting is currently keyed off the `X-API-Key` header. If you authenticate using **only** `Authorization: Bearer ...` (without also sending `X-API-Key`), rate limiting may fall back to an IP-based key (depending on deployment topology).

## Request Limits

| Limit | Value |
|-------|-------|
| Max query length | 12,000 characters |
| Request timeout | 30 seconds |

**Note:** The FastAPI app enforces max query length and request validation. It does **not** currently enforce a fixed maximum request body size at the application layer; upstream proxies/load balancers may impose their own limits.

## Request ID

Every response includes an `X-Request-ID` header containing a unique identifier for the request.

`POST /query` responses include this ID in the response body as `request_id`. Many error responses also include a `request_id` in the JSON body, but some (notably edge-secret 403s) may not.

**Important:** The request ID is generated before validation, so even 422 validation errors will include a valid `request_id`. Always include this ID when contacting support.

## Endpoints

### POST /query

Execute a natural language query against the knowledge graph.

#### Request

```bash
# Recommended: send BOTH headers (auth works with either; rate limiting is keyed off X-API-Key)
curl -X POST "https://api.lexon.law/v1/query" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_api_key_here" \
  -H "X-API-Key: your_api_key_here" \
  -d '{
    "query": "What doctrines apply to platform monopolies in antitrust law?",
    "limit": 50
  }'

# Alternative: X-API-Key header only
curl -X POST "https://api.lexon.law/v1/query" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_api_key_here" \
  -d '{
    "query": "What doctrines apply to platform monopolies in antitrust law?",
    "limit": 50
  }'
```

**Request Body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | string | Yes | - | Natural language query (1-12,000 chars). **Not logged. Sent to OpenAI.** |
| `limit` | integer | No | 50 | Maximum nodes to return (1-200) |

**Note:** Unknown fields are rejected (HTTP 422).

#### Response

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "enriched_nodes": [
    {
      "node_label": "Issue",
      "issue_id": "d989df7f-1234-5678-9abc-def012345678",
      "text": "Whether the defendant maintained monopoly power in the relevant market",
      "relationships": {
        "doctrine": 3,
        "proceeding": 1
      }
    },
    {
      "node_label": "Doctrine",
      "doctrine_id": "b2f35703-abcd-efgh-ijkl-mnopqrstuvwx",
      "name": "Rule of Reason",
      "description": "Courts consider procompetitive justifications when evaluating antitrust claims",
      "relationships": {
        "issue": 5,
        "ruling": 2
      }
    }
  ],
  "total_count": 2,
  "truncated": false
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `request_id` | string | Unique identifier for this request (useful for support) |
| `enriched_nodes` | array | List of matching nodes (up to `limit`) |
| `total_count` | integer | Total nodes found before applying limit |
| `truncated` | boolean | `true` if results were truncated due to limit |

**Node Structure:**

Each node in `enriched_nodes` contains:
- `node_label`: The type of node (e.g., "Issue", "Doctrine", "Ruling", "Case", "Law")
- Exactly one `*_id` field matching the node_label (e.g., `issue_id` for "Issue" nodes)
- Type-specific properties (e.g., `text`, `name`, `description`, `summary`)
- `relationships`: A summary of connected nodes by type and count

**Note:** Internal fields (embeddings, upload codes, internal IDs) are never returned.

### GET /health

Health check endpoint. Unauthenticated; returns minimal info only.

```bash
curl "https://api.lexon.law/v1/health"
```

**Response:**

```json
{
  "status": "ok",
  "timestamp": "2026-01-07T15:30:00.000000+00:00"
}
```

### GET /version

API version information. Unauthenticated; returns minimal info only.

```bash
curl "https://api.lexon.law/v1/version"
```

**Response:**

```json
{
  "version": "1.2.0",
  "api": "Lexon External API"
}
```

**Note:** No environment details, git SHA, build info, or other fingerprinting data is exposed.

### GET /openapi.json

OpenAPI specification. **Requires authentication.**

```bash
curl "https://api.lexon.law/v1/openapi.json" \
  -H "Authorization: Bearer your_api_key_here"
```

**Response:** Full OpenAPI 3.x specification (JSON)

Use cases:
- Import into Postman or Insomnia
- Code generation from spec
- Client SDK generation

**Note:** This endpoint requires API key authentication to prevent schema enumeration.

## Error Responses

### Body shapes (current implementation)

Every response includes an `X-Request-ID` header.

Some responses also include `request_id` in the JSON body, but **not all error bodies are identical** (due to FastAPI’s default `HTTPException` serialization).

### Standard error body (used by 422 validation, 429 rate limit, and unexpected 500 internal_error)

These errors follow a consistent top-level format and include `request_id`:

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "error": "error_code",
  "message": "Human-readable error message"
}
```

Validation errors include additional details:

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "error": "validation_error",
  "message": "Invalid request body",
  "details": [
    {"field": "body.query", "message": "Field required"},
    {"field": "body.limit", "message": "Input should be less than or equal to 200"}
  ]
}
```

### FastAPI HTTPException wrapper (commonly used by auth + query failures)

Some errors are returned as:

```json
{
  "detail": {
    "request_id": "550e8400-e29b-41d4-a716-446655440000",
    "error": "unauthorized",
    "message": "Invalid API key"
  }
}
```

### Edge-secret failures (403)

If edge validation is enabled and the request bypasses the edge, the 403 body may be:

```json
{
  "detail": "Forbidden"
}
```

In all cases, prefer the `X-Request-ID` header when correlating failures with Lexon support.

### Error Codes

| HTTP Status | Error Code | Description |
|-------------|------------|-------------|
| 401 | `unauthorized` | API key is missing or invalid |
| 403 | (unstructured) | Request rejected (origin validation failed; body may be `{"detail":"Forbidden"}`) |
| 422 | `validation_error` | Invalid request body (see `details` for specifics) |
| 429 | `rate_limit_exceeded` | Too many requests. Check `Retry-After` header. |
| 500 | `query_failed` | Error processing the query (may be wrapped under `detail`) |
| 500 | `internal_error` | Unexpected server error (top-level error response) |
| 503 | `service_unavailable` | External API is not configured |
| 504 | `timeout` | Query exceeded 30 second timeout |

## Retry Guidance

Different errors require different retry strategies:

### 429 Rate Limit Exceeded
- **Action:** Respect the `Retry-After` header value
- **Strategy:** Wait the specified number of seconds, then retry once
- **Do not:** Retry immediately or in a tight loop

### 504 Gateway Timeout
- **Action:** Refine your query to be more specific
- **Strategy:** Simplify the query, then retry with exponential backoff (1s, 2s, 4s)
- **Max retries:** 3
- **Note:** Broad queries like "tell me about antitrust" are more likely to timeout

### 500 Internal Error / 503 Service Unavailable
- **Action:** Retry with exponential backoff
- **Strategy:** Wait 1s, 2s, 4s, 8s between retries
- **Max retries:** 3-5
- **Support:** If errors persist, contact support with `request_id`

### General Retry Best Practices
- Always include `X-Request-ID` (or `request_id` from response) when contacting support
- Implement circuit breaker patterns for sustained failures
- Log all error responses for debugging

## Node Types

The knowledge graph contains the following node types:

| Node Type | Description | Key Properties |
|-----------|-------------|----------------|
| `Case` | Legal case | `case_id`, `name`, `summary`, `citation` |
| `Issue` | Legal issue within a case | `issue_id`, `text` |
| `Doctrine` | Legal doctrine or principle | `doctrine_id`, `name`, `description` |
| `Ruling` | Court ruling | `ruling_id`, `outcome`, `reasoning` |
| `Law` | Statute or regulation | `law_id`, `name`, `text` |
| `Proceeding` | Court proceeding | `proceeding_id`, `court`, `date` |
| `Party` | Party to a case | `party_id`, `name`, `role` |
| `FactPattern` | Factual pattern | `fact_pattern_id`, `description` |
| `Argument` | Legal argument | `argument_id`, `text` |
| `Relief` | Requested/awarded relief | `relief_id`, `type`, `description` |
| `Policy` | Policy consideration | `policy_id`, `text` |
| `Forum` | Forum | `forum_id`, `name` |
| `Jurisdiction` | Jurisdiction | `jurisdiction_id`, `name` |
| `ReliefType` | Relief type | `relief_type_id`, `name` |
| `Domain` | Domain/category | `domain_id`, `name` |

## Query Flow

When you submit a query, it goes through a multi-stage pipeline:

1. **Reasoning**: Analyzes your query to identify relevant node types (uses OpenAI GPT)
2. **Planning**: Creates a search strategy with embedding and traversal steps (uses OpenAI GPT)
3. **Vector Search**: Performs semantic search using embeddings (uses OpenAI for embedding generation)
4. **Traversal**: Follows graph relationships to find connected nodes (local processing)
5. **Enrichment**: Fetches complete data for all matching nodes (local processing)

**Timeout:** Queries exceeding 30 seconds return HTTP 504. This typically occurs with very broad queries.

## Best Practices

1. **Be specific**: More specific queries yield better results
   - Good: "What doctrines apply to tying arrangements in antitrust law?"
   - Less effective: "Tell me about antitrust"

2. **Minimize sensitive data**: Avoid including client names, deal terms, or trade secrets in queries (see [Sensitive Data Guidance](#sensitive-data-guidance))

3. **Use the limit parameter**: Control response size with `limit` (default: 50, max: 200)

4. **Check truncated flag**: If `truncated: true`, there are more results than returned

5. **Handle empty results**: If `enriched_nodes` is empty, the query didn't match any nodes. Consider rephrasing.

6. **Always capture request_id**: Store the `request_id` from every response for debugging and support

7. **Implement proper retry logic**: Follow the [Retry Guidance](#retry-guidance) for each error type

8. **Send `X-API-Key` (even if you also send Authorization)**: Authentication supports either header, but rate limiting is currently keyed off `X-API-Key`.

## Code Examples

### Python

```python
import requests
import time

API_KEY = "your_api_key_here"
BASE_URL = "https://api.lexon.law/v1"
MAX_RETRIES = 3

def query_lexon(query: str, limit: int = 50) -> dict:
    """
    Query the Lexon knowledge graph with retry logic.
    
    Args:
        query: Natural language query (NOT logged by Lexon, IS sent to OpenAI)
        limit: Maximum number of nodes to return (1-200, default: 50)
    
    Returns:
        Response dict with enriched_nodes, total_count, and truncated fields
    
    Note:
        Avoid including sensitive data (client names, deal terms) in queries
        as they are sent to OpenAI for processing.
    """
    headers = {
        "Content-Type": "application/json",
        # Auth works with either header; we send both to ensure per-key rate limiting.
        "Authorization": f"Bearer {API_KEY}",
        "X-API-Key": API_KEY,
    }
    
    for attempt in range(MAX_RETRIES):
        response = requests.post(
            f"{BASE_URL}/query",
            headers=headers,
            json={"query": query, "limit": limit},
            timeout=35,  # Slightly longer than server timeout
        )
        
        request_id = response.headers.get("X-Request-ID", "unknown")
        
        # Handle rate limiting
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", "60"))
            print(f"Rate limited. Waiting {retry_after}s... (request_id: {request_id})")
            time.sleep(retry_after)
            continue
        
        # Handle timeout - refine query
        if response.status_code == 504:
            print(f"Query timeout. Consider a more specific query. (request_id: {request_id})")
            raise Exception(f"Query timeout (request_id: {request_id})")
        
        # Handle server errors with exponential backoff
        if response.status_code in (500, 503):
            wait_time = 2 ** attempt
            print(f"Server error. Retrying in {wait_time}s... (request_id: {request_id})")
            time.sleep(wait_time)
            continue
        
        response.raise_for_status()
        return response.json()
    
    raise Exception(f"Max retries exceeded (last request_id: {request_id})")

# Example usage
result = query_lexon("What are the elements of a Sherman Act Section 2 claim?", limit=20)
print(f"Request ID: {result['request_id']}")
print(f"Found {result['total_count']} nodes, returning {len(result['enriched_nodes'])}")
if result['truncated']:
    print("(Results truncated - increase limit to see more)")
for node in result['enriched_nodes']:
    print(f"  - {node['node_label']}: {node.get('name') or node.get('text', '')[:50]}")
```

### Node.js

```javascript
const API_KEY = "your_api_key_here";
const BASE_URL = "https://api.lexon.law/v1";
const MAX_RETRIES = 3;

async function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function queryLexon(query, limit = 50) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 35000);
  
  let lastRequestId = "unknown";

  try {
    for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
      const response = await fetch(`${BASE_URL}/query`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          // Auth works with either header; we send both to ensure per-key rate limiting.
          "Authorization": `Bearer ${API_KEY}`,
          "X-API-Key": API_KEY,
        },
        body: JSON.stringify({ query, limit }),
        signal: controller.signal,
      });

      lastRequestId = response.headers.get("X-Request-ID") || "unknown";

      // Handle rate limiting
      if (response.status === 429) {
        const retryAfter = parseInt(response.headers.get("Retry-After") || "60");
        console.log(`Rate limited. Waiting ${retryAfter}s... (request_id: ${lastRequestId})`);
        await sleep(retryAfter * 1000);
        continue;
      }

      // Handle timeout
      if (response.status === 504) {
        throw new Error(`Query timeout. Try a more specific query. (request_id: ${lastRequestId})`);
      }

      // Handle server errors with exponential backoff
      if (response.status === 500 || response.status === 503) {
        const waitTime = Math.pow(2, attempt) * 1000;
        console.log(`Server error. Retrying in ${waitTime/1000}s... (request_id: ${lastRequestId})`);
        await sleep(waitTime);
        continue;
      }

      if (!response.ok) {
        const error = await response.json();
        throw new Error(`${error.error}: ${error.message} (request_id: ${lastRequestId})`);
      }

      return response.json();
    }
    
    throw new Error(`Max retries exceeded (last request_id: ${lastRequestId})`);
  } finally {
    clearTimeout(timeout);
  }
}

// Example usage
const result = await queryLexon("What are the elements of a Sherman Act Section 2 claim?", 20);
console.log(`Request ID: ${result.request_id}`);
console.log(`Found ${result.total_count} nodes, returning ${result.enriched_nodes.length}`);
if (result.truncated) {
  console.log("(Results truncated - increase limit to see more)");
}
```

## Support

For API support, please contact your Lexon representative with:
- Your `request_id` (from response header `X-Request-ID` or response body)
- Timestamp of the request
- The error message received

**Note:** Do not share your API key in support requests.

## Security Notes (Internal)

### Production Security Checks

In production, the following endpoints should return 403/404:

| Endpoint | Expected Status | Notes |
|----------|-----------------|-------|
| `GET /docs` | 404 | Internal docs disabled in production |
| `GET /redoc` | 404 | Internal docs disabled in production |
| `GET /openapi.json` | 404 | Internal OpenAPI disabled in production |
| `GET /external/v1/docs` | 404 | External docs UI disabled |
| `GET /external/v1/redoc` | 404 | External docs UI disabled |
| `GET /external/v1/openapi.json` (no auth) | 401/403 | Requires API key |

### Acceptance Criteria

- [ ] `GET /` returns `{"status":"ok"}` only (no environment info)
- [ ] Internal docs (`/docs`, `/redoc`, `/openapi.json`) return 404 in production
- [ ] External docs UI disabled (`/external/v1/docs`, `/external/v1/redoc`)
- [ ] External OpenAPI requires auth (`/external/v1/openapi.json`)
- [ ] External OpenAPI spec contains only external routes (no `/api/*`)
- [ ] Next.js docs routes (`/api/docs/*`) require authentication
- [ ] Next.js OpenAPI proxy has timeout and no user-supplied URL params

## Changelog

### v1.2.0 (Current)
- **Security:** Internal FastAPI docs disabled in production (env-gated)
- **Security:** `/openapi.json` endpoint now requires authentication
- **Security:** Root endpoint returns minimal `{"status":"ok"}` response only
- Interactive docs served exclusively via authenticated Next.js pages
- OpenAPI spec accessible to external clients via authenticated API call

### v1.1.0
- **Auth:** Added `Authorization: Bearer` support (preferred over `X-API-Key`)
- **Security:** `key_id` in logs is now a one-way hash (not raw key prefix)
- **Security:** Clarified data persistence policy - request bodies are not persisted
- **Security:** Added subprocessor disclosure (OpenAI)
- **Reliability:** `X-Request-ID` now always present, even on validation errors
- **Docs:** Added comprehensive retry guidance for each error type
- Added `limit` parameter (1-200, default: 50) to control result count
- Added `total_count` and `truncated` fields to response
- Full rate limit headers: `X-RateLimit-Limit`, `X-RateLimit-Reset`, `Retry-After`
- Consistent error format with `details` for validation errors
- Query content is **never logged** by Lexon
- Added `/health` and `/version` endpoints (unauthenticated, minimal info)
- Added request timeout (30 seconds, returns 504)
- Response data sanitized to whitelist allowed fields only
- Strict request validation (unknown fields rejected)
- Edge secret validation for origin protection
- Multi-key support for key rotation

### v1.0.0 (Initial Release)
- `POST /query` endpoint for knowledge graph queries
- API key authentication
- Rate limiting (60 req/min)
