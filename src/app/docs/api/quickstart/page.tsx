'use client'

import { useEffect } from 'react'
import { useSession } from 'next-auth/react'
import { useRouter } from 'next/navigation'
import type { Session } from 'next-auth'
import { hasAtLeastRole } from '@/lib/rbac'
import { CodeBlock } from '@/components/ui/CodeBlock'

export default function QuickStartPage() {
  const { data: session, status } = useSession()
  const router = useRouter()

  const role = (session?.user as Session['user'])?.role
  const canAccess = hasAtLeastRole(role, 'developer')

  // Check auth
  useEffect(() => {
    if (status === 'loading') return
    if (!session) {
      router.push('/auth/signin')
      return
    }
    if (!canAccess) {
      router.push('/')
    }
  }, [session, status, canAccess, router])

  if (status === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-gray-500">Loading...</div>
      </div>
    )
  }

  if (!canAccess) {
    return null
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <article className="prose prose-gray max-w-none">
        <h1>Lexon External API - Quick Start Guide</h1>
        <p className="lead">Get started with the Lexon External API in 5 minutes.</p>

        <h2>Base URL</h2>
        <pre><code>https://api.lexon.law/v1</code></pre>

        <h2>Authentication</h2>
        <p>All authenticated endpoints require your API key. <strong>Send both headers</strong> for reliable rate limiting:</p>
        <CodeBlock>{`Authorization: Bearer YOUR_API_KEY
X-API-Key: YOUR_API_KEY`}</CodeBlock>

        <h2>Quick Test</h2>

        <h3>1. Verify connectivity (no auth required)</h3>
        <CodeBlock language="bash">{`curl "https://api.lexon.law/v1/health"`}</CodeBlock>
        <p>Expected response:</p>
        <pre><code>{`{"status": "ok", "timestamp": "2026-01-08T..."}`}</code></pre>

        <h3>2. Check API version (no auth required)</h3>
        <CodeBlock language="bash">{`curl "https://api.lexon.law/v1/version"`}</CodeBlock>
        <p>Expected response:</p>
        <pre><code>{`{"version": "1.2.0", "api": "Lexon External API"}`}</code></pre>

        <h3>3. Make your first query</h3>
        <CodeBlock language="bash">{`curl -X POST "https://api.lexon.law/v1/query" \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "X-API-Key: YOUR_API_KEY" \\
  -d '{
    "query": "What are the elements of a monopolization claim?",
    "limit": 10
  }'`}</CodeBlock>

        <h2>Postman Collection</h2>
        <p>Import the Lexon API into Postman:</p>
        <ol>
          <li>
            <a href="/api/docs/postman" download className="text-blue-600 hover:underline">
              Download the Postman collection
            </a>
          </li>
          <li>In Postman: <strong>Import</strong> → Select the downloaded JSON file</li>
          <li>Set the <code>api_key</code> variable to your API key</li>
          <li>Start testing!</li>
        </ol>

        <h2>Endpoints</h2>
        <div className="overflow-x-auto">
          <table>
            <thead>
              <tr>
                <th>Endpoint</th>
                <th>Method</th>
                <th>Auth</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><code>/health</code></td>
                <td>GET</td>
                <td>No</td>
                <td>Health check</td>
              </tr>
              <tr>
                <td><code>/version</code></td>
                <td>GET</td>
                <td>No</td>
                <td>API version</td>
              </tr>
              <tr>
                <td><code>/query</code></td>
                <td>POST</td>
                <td>Yes</td>
                <td>Query knowledge graph</td>
              </tr>
              <tr>
                <td><code>/openapi.json</code></td>
                <td>GET</td>
                <td>Yes</td>
                <td>OpenAPI specification</td>
              </tr>
            </tbody>
          </table>
        </div>

        <h2>Query Endpoint</h2>

        <h3>Request</h3>
        <pre><code>{`{
  "query": "Your natural language query here",
  "limit": 50
}`}</code></pre>

        <div className="overflow-x-auto">
          <table>
            <thead>
              <tr>
                <th>Field</th>
                <th>Type</th>
                <th>Required</th>
                <th>Default</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><code>query</code></td>
                <td>string</td>
                <td>Yes</td>
                <td>-</td>
                <td>Natural language query (1-12,000 chars)</td>
              </tr>
              <tr>
                <td><code>limit</code></td>
                <td>integer</td>
                <td>No</td>
                <td>50</td>
                <td>Max nodes to return (1-200)</td>
              </tr>
            </tbody>
          </table>
        </div>

        <h3>Response</h3>
        <pre><code>{`{
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
}`}</code></pre>

        <div className="overflow-x-auto">
          <table>
            <thead>
              <tr>
                <th>Field</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><code>request_id</code></td>
                <td>Unique ID for this request (include in support requests)</td>
              </tr>
              <tr>
                <td><code>enriched_nodes</code></td>
                <td>Array of matching nodes from the knowledge graph</td>
              </tr>
              <tr>
                <td><code>total_count</code></td>
                <td>Total nodes found before applying limit</td>
              </tr>
              <tr>
                <td><code>truncated</code></td>
                <td><code>true</code> if more results exist beyond the limit</td>
              </tr>
            </tbody>
          </table>
        </div>

        <h2>Rate Limits</h2>
        <ul>
          <li><strong>60 requests per minute</strong> per API key</li>
          <li>Response headers include rate limit info:
            <ul>
              <li><code>X-RateLimit-Limit</code>: Max requests per window</li>
              <li><code>X-RateLimit-Reset</code>: Unix timestamp when limit resets</li>
            </ul>
          </li>
          <li>429 responses include <code>Retry-After</code> header</li>
        </ul>

        <h2>Error Handling</h2>
        <div className="overflow-x-auto">
          <table>
            <thead>
              <tr>
                <th>Status</th>
                <th>Error Code</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>401</td>
                <td><code>unauthorized</code></td>
                <td>Check your API key</td>
              </tr>
              <tr>
                <td>422</td>
                <td><code>validation_error</code></td>
                <td>Check request body format</td>
              </tr>
              <tr>
                <td>429</td>
                <td><code>rate_limit_exceeded</code></td>
                <td>Wait for <code>Retry-After</code> seconds</td>
              </tr>
              <tr>
                <td>504</td>
                <td><code>timeout</code></td>
                <td>Try a more specific query</td>
              </tr>
              <tr>
                <td>500</td>
                <td><code>internal_error</code></td>
                <td>Retry with exponential backoff</td>
              </tr>
            </tbody>
          </table>
        </div>

        <h2>Data Handling</h2>
        <ul>
          <li><strong>Query content is NOT logged</strong> by Lexon (only metadata like timing and counts)</li>
          <li><strong>Query content IS sent to OpenAI</strong> for processing (reasoning, planning, embeddings)</li>
          <li>Response data is sanitized (no internal fields exposed)</li>
        </ul>

        <h2>Support</h2>
        <p>When contacting support, include:</p>
        <ol>
          <li>The <code>request_id</code> from the response (or <code>X-Request-ID</code> header)</li>
          <li>Timestamp of the request</li>
          <li>Error message received</li>
        </ol>
        <p><strong>Do not share your API key in support requests.</strong></p>

        <hr />

        <p>
          For comprehensive documentation, see the{' '}
          <a href="/docs/api/redoc" className="text-blue-600 hover:underline">full API reference</a>.
        </p>
      </article>
    </div>
  )
}
