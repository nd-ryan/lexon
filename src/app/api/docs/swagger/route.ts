import { NextResponse } from 'next/server'
import { getServerSession } from 'next-auth/next'
import { authOptions } from '@/lib/auth'
import { hasDbAtLeastRole } from '@/lib/rbac'

const AI_BACKEND_URL = process.env.AI_BACKEND_URL || 'http://localhost:8000'
const AI_BACKEND_EXTERNAL_URL = process.env.AI_BACKEND_EXTERNAL_URL || AI_BACKEND_URL
const LEXON_API_KEY = process.env.LEXON_API_KEY
const OPENAPI_ENDPOINT_PRIMARY = '/v1/openapi.json'
const OPENAPI_ENDPOINT_FALLBACK = '/external/v1/openapi.json'

/**
 * GET /api/docs/swagger
 * 
 * Serves Swagger UI as a standalone HTML page.
 * Requires NextAuth session.
 */
export async function GET() {
  const session = await getServerSession(authOptions)
  
  if (!session?.user) {
    return NextResponse.redirect(new URL('/auth/signin', process.env.NEXTAUTH_URL || 'http://localhost:3000'))
  }
  const canAccess = await hasDbAtLeastRole(session, 'developer')
  if (!canAccess.ok) {
    return NextResponse.redirect(new URL('/', process.env.NEXTAUTH_URL || 'http://localhost:3000'))
  }

  // Fetch OpenAPI spec
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let spec: Record<string, any> = {}
  if (LEXON_API_KEY) {
    try {
      const fetchSpec = async (endpoint: string) =>
        fetch(`${AI_BACKEND_EXTERNAL_URL}${endpoint}`, {
          headers: {
            Authorization: `Bearer ${LEXON_API_KEY}`,
          },
          cache: 'no-store',
        })

      let response = await fetchSpec(OPENAPI_ENDPOINT_PRIMARY)
      if (!response.ok) {
        response = await fetchSpec(OPENAPI_ENDPOINT_FALLBACK)
      }

      if (response.ok) {
        spec = await response.json()
        // Rewrite servers to use the Next.js proxy for "Try it out" functionality
        // This bypasses CORS since the external API is server-to-server only
        spec.servers = [
          { url: '/api/docs/proxy', description: 'Proxied via Next.js (for Swagger UI)' }
        ]
        
        // Normalize paths by removing any /external/v1 or /v1 prefixes
        // This ensures Swagger UI constructs correct URLs via the proxy
        if (spec.paths) {
          const normalizedPaths: Record<string, unknown> = {}
          for (const [path, value] of Object.entries(spec.paths)) {
            let normalizedPath = path
            if (path.startsWith('/external/v1')) {
              normalizedPath = path.slice('/external/v1'.length) || '/'
            } else if (path.startsWith('/v1')) {
              normalizedPath = path.slice('/v1'.length) || '/'
            }
            normalizedPaths[normalizedPath] = value
          }
          spec.paths = normalizedPaths
        }
      }
    } catch (e) {
      console.error('Failed to fetch OpenAPI spec:', e)
    }
  }

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Lexon External API - Swagger UI</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
  <style>
    body { margin: 0; padding: 0; }
    .swagger-ui .topbar { display: none; }
    .swagger-ui .info { margin: 30px 0; }
    .swagger-ui .info .title { font-size: 32px; font-weight: 600; }
    .swagger-ui .scheme-container { background: #f8f9fa; padding: 20px; }
  </style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.onload = function() {
      SwaggerUIBundle({
        spec: ${JSON.stringify(spec)},
        dom_id: '#swagger-ui',
        presets: [
          SwaggerUIBundle.presets.apis,
          SwaggerUIBundle.SwaggerUIStandalonePreset
        ],
        layout: "BaseLayout"
      });
    };
  </script>
</body>
</html>`

  return new NextResponse(html, {
    headers: {
      'Content-Type': 'text/html',
    },
  })
}
