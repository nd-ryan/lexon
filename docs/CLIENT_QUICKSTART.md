# Lexon External API - Quick Start Guide

Get started with the Lexon External API in 5 minutes.

## Base URL

```
https://api.lexon.law/v1
```

## Authentication

All authenticated endpoints require your API key. **Send both headers** for reliable rate limiting:

```
Authorization: Bearer YOUR_API_KEY
X-API-Key: YOUR_API_KEY
```

## Quick Test

### 1. Verify connectivity (no auth required)

```bash
curl "https://api.lexon.law/v1/health"
```

Expected response:
```json
{"status": "ok", "timestamp": "2026-01-08T..."}
```

### 2. Check API version (no auth required)

```bash
curl "https://api.lexon.law/v1/version"
```

Expected response:
```json
{"version": "1.2.0", "api": "Lexon External API"}
```

### 3. Make your first query

```bash
curl -X POST "https://api.lexon.law/v1/query" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{
    "query": "What are the elements of a monopolization claim?",
    "limit": 10
  }'
```

## Postman Collection

Import the Lexon API into Postman:

1. Download the collection from your Lexon dashboard (API Docs → Download Postman Collection)
2. In Postman: **Import** → Select the downloaded JSON file
3. Set the `api_key` variable to your API key
4. Start testing!

Alternatively, fetch the OpenAPI spec directly:

```bash
curl "https://api.lexon.law/v1/openapi.json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -o lexon-openapi.json
```

Import `lexon-openapi.json` into Postman, Insomnia, or your preferred API tool.

## Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | No | Health check |
| `/version` | GET | No | API version |
| `/query` | POST | Yes | Query knowledge graph |
| `/openapi.json` | GET | Yes | OpenAPI specification |

## Query Endpoint

### Request

```json
{
  "query": "Your natural language query here",
  "limit": 50
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | string | Yes | - | Natural language query (1-12,000 chars) |
| `limit` | integer | No | 50 | Max nodes to return (1-200) |

### Response

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "enriched_nodes": [
    {
      "node_label": "Doctrine",
      "doctrine_id": "...",
      "name": "Rule of Reason",
      "description": "...",
      "relationships": {"issue": 5, "ruling": 2}
    }
  ],
  "total_count": 15,
  "truncated": false
}
```

| Field | Description |
|-------|-------------|
| `request_id` | Unique ID for this request (include in support requests) |
| `enriched_nodes` | Array of matching nodes from the knowledge graph |
| `total_count` | Total nodes found before applying limit |
| `truncated` | `true` if more results exist beyond the limit |

## Rate Limits

- **60 requests per minute** per API key
- Response headers include rate limit info:
  - `X-RateLimit-Limit`: Max requests per window
  - `X-RateLimit-Reset`: Unix timestamp when limit resets
- 429 responses include `Retry-After` header

## Error Handling

| Status | Error Code | Action |
|--------|------------|--------|
| 401 | `unauthorized` | Check your API key |
| 422 | `validation_error` | Check request body format |
| 429 | `rate_limit_exceeded` | Wait for `Retry-After` seconds |
| 504 | `timeout` | Try a more specific query |
| 500 | `internal_error` | Retry with exponential backoff |

### Retry Strategy

```python
# Pseudocode
for attempt in range(3):
    response = make_request()
    
    if response.status == 429:
        wait(response.headers['Retry-After'])
        continue
    
    if response.status in (500, 503):
        wait(2 ** attempt)  # 1s, 2s, 4s
        continue
    
    break
```

## Data Handling

- **Query content is NOT logged** by Lexon (only metadata like timing and counts)
- **Query content IS sent to Google Gemini** for processing (reasoning, planning, embeddings)
- Response data is sanitized (no internal fields exposed)

## Support

When contacting support, include:

1. The `request_id` from the response (or `X-Request-ID` header)
2. Timestamp of the request
3. Error message received

**Do not share your API key in support requests.**

---

For comprehensive documentation, see the full [External API Documentation](EXTERNAL_API.md).
