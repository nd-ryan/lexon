import { NextRequest, NextResponse } from 'next/server'
import { getServerSession } from 'next-auth/next'
import { authOptions } from '@/lib/auth'
import { hasDbAtLeastRole } from '@/lib/rbac'

// Hardcoded backend URLs - no user input to prevent SSRF
const AI_BACKEND_URL = process.env.AI_BACKEND_URL || 'http://localhost:8000'
const AI_BACKEND_EXTERNAL_URL = process.env.AI_BACKEND_EXTERNAL_URL || AI_BACKEND_URL

// Use Lexon API key to authenticate with the backend
const LEXON_API_KEY = process.env.LEXON_API_KEY

// Request timeout in milliseconds (longer for query endpoint)
const FETCH_TIMEOUT_MS = 35000

// Allowed paths to proxy (whitelist for security)
const ALLOWED_PATHS = new Set(['query', 'health', 'version', 'openapi.json'])

/**
 * Validate and sanitize the path to prevent path traversal attacks.
 * Only allows whitelisted paths.
 * 
 * Handles paths that may include prefixes like 'external/v1/' or 'v1/'
 * which can occur depending on how the OpenAPI spec is generated.
 */
function validatePath(pathSegments: string[]): string | null {
  let path = pathSegments.join('/')
  
  // Strip common prefixes that may be included in OpenAPI spec paths
  // This handles cases where Swagger UI combines server URL with full paths
  const prefixes = ['external/v1/', 'v1/']
  for (const prefix of prefixes) {
    if (path.startsWith(prefix)) {
      path = path.slice(prefix.length)
      break
    }
  }
  
  // Check against whitelist
  if (!ALLOWED_PATHS.has(path)) {
    return null
  }
  
  return path
}

/**
 * Check authentication and authorization.
 * Returns null if authorized, or an error response if not.
 */
async function checkAuth(): Promise<NextResponse | null> {
  const session = await getServerSession(authOptions)
  
  if (!session?.user) {
    return NextResponse.json(
      { error: 'Unauthorized' },
      { status: 401 }
    )
  }
  
  const canAccess = await hasDbAtLeastRole(session, 'developer')
  if (!canAccess.ok) {
    return NextResponse.json(
      { error: 'Forbidden' },
      { status: 403 }
    )
  }
  
  if (!LEXON_API_KEY) {
    console.error('LEXON_API_KEY not configured')
    return NextResponse.json(
      { error: 'Service configuration error' },
      { status: 500 }
    )
  }
  
  return null
}

/**
 * Proxy a request to the external API backend.
 */
async function proxyRequest(
  request: NextRequest,
  path: string,
  method: string
): Promise<NextResponse> {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS)

  try {
    // Build the backend URL - try primary (edge) first, fallback to origin mount
    const primaryUrl = `${AI_BACKEND_EXTERNAL_URL}/v1/${path}`
    const fallbackUrl = `${AI_BACKEND_EXTERNAL_URL}/external/v1/${path}`

    // Prepare headers for backend request
    const headers: HeadersInit = {
      'Authorization': `Bearer ${LEXON_API_KEY}`,
      'X-API-Key': LEXON_API_KEY!,
      'Accept': 'application/json',
    }

    // Add Content-Type for requests with body
    if (method === 'POST' || method === 'PUT' || method === 'PATCH') {
      headers['Content-Type'] = 'application/json'
    }

    // Get request body if present
    let body: string | undefined
    if (method === 'POST' || method === 'PUT' || method === 'PATCH') {
      try {
        body = await request.text()
      } catch {
        // No body
      }
    }

    // Make the request - try primary URL first
    let response = await fetch(primaryUrl, {
      method,
      headers,
      body,
      cache: 'no-store',
      signal: controller.signal,
    })

    // If primary fails with 404, try fallback
    if (response.status === 404) {
      response = await fetch(fallbackUrl, {
        method,
        headers,
        body,
        cache: 'no-store',
        signal: controller.signal,
      })
    }

    clearTimeout(timeoutId)

    // Get response data
    const contentType = response.headers.get('content-type') || ''
    let responseBody: string | object

    if (contentType.includes('application/json')) {
      responseBody = await response.json()
    } else {
      responseBody = await response.text()
    }

    // Forward response headers we care about
    const responseHeaders: HeadersInit = {}
    const headersToForward = [
      'X-Request-ID',
      'X-RateLimit-Limit',
      'X-RateLimit-Remaining',
      'X-RateLimit-Reset',
      'Retry-After',
    ]
    for (const header of headersToForward) {
      const value = response.headers.get(header)
      if (value) {
        responseHeaders[header] = value
      }
    }

    // Return the response
    if (typeof responseBody === 'string') {
      return new NextResponse(responseBody, {
        status: response.status,
        headers: {
          ...responseHeaders,
          'Content-Type': contentType,
        },
      })
    }

    return NextResponse.json(responseBody, {
      status: response.status,
      headers: responseHeaders,
    })
  } catch (error) {
    clearTimeout(timeoutId)
    
    if (error instanceof Error && error.name === 'AbortError') {
      return NextResponse.json(
        { error: 'Request timeout' },
        { status: 504 }
      )
    }
    
    console.error('Proxy error:', error)
    return NextResponse.json(
      { error: 'Proxy error' },
      { status: 502 }
    )
  }
}

/**
 * GET /api/docs/proxy/[...path]
 * 
 * Proxy GET requests to the external API for Swagger UI "Try it out".
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const authError = await checkAuth()
  if (authError) return authError

  const { path: pathSegments } = await params
  const path = validatePath(pathSegments)
  if (!path) {
    return NextResponse.json(
      { error: 'Invalid path' },
      { status: 400 }
    )
  }

  return proxyRequest(request, path, 'GET')
}

/**
 * POST /api/docs/proxy/[...path]
 * 
 * Proxy POST requests to the external API for Swagger UI "Try it out".
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const authError = await checkAuth()
  if (authError) return authError

  const { path: pathSegments } = await params
  const path = validatePath(pathSegments)
  if (!path) {
    return NextResponse.json(
      { error: 'Invalid path' },
      { status: 400 }
    )
  }

  return proxyRequest(request, path, 'POST')
}
