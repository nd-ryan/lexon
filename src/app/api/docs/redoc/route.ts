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
 * GET /api/docs/redoc
 * 
 * Serves ReDoc as a standalone HTML page.
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
  let spec = {}
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

      if (response.ok) spec = await response.json()
    } catch (e) {
      console.error('Failed to fetch OpenAPI spec:', e)
    }
  }

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Lexon External API - ReDoc</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    body { margin: 0; padding: 0; }
  </style>
</head>
<body>
  <div id="redoc-container"></div>
  <script src="https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js"></script>
  <script>
    Redoc.init(${JSON.stringify(spec)}, {
      scrollYOffset: 0,
      hideDownloadButton: false,
      expandResponses: '200,201',
      pathInMiddlePanel: true,
      theme: {
        colors: {
          primary: { main: '#1a56db' }
        },
        typography: {
          fontSize: '15px',
          fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
          headings: { fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif' }
        },
        sidebar: { width: '280px' },
        rightPanel: { backgroundColor: '#263238' }
      }
    }, document.getElementById('redoc-container'));
  </script>
</body>
</html>`

  return new NextResponse(html, {
    headers: {
      'Content-Type': 'text/html',
    },
  })
}
