import { NextResponse } from 'next/server'
import { getServerSession } from 'next-auth/next'
import { authOptions } from '@/lib/auth'

// Hardcoded backend URL - no user input to prevent SSRF
const AI_BACKEND_URL = process.env.AI_BACKEND_URL || 'http://localhost:8000'
const OPENAPI_ENDPOINT = '/external/v1/openapi.json'

// Use Lexon API key to authenticate with the backend
const LEXON_API_KEY = process.env.LEXON_API_KEY

// Request timeout in milliseconds
const FETCH_TIMEOUT_MS = 10000

/**
 * GET /api/docs/openapi.json
 * 
 * Proxy the OpenAPI spec from the external API.
 * 
 * Security:
 * - Requires NextAuth session (any authenticated user)
 * - Uses server-side API key to auth with backend
 * - Hardcoded endpoint URL (no user-supplied params)
 * - Short timeout to prevent hanging connections
 */
export async function GET() {
  const session = await getServerSession(authOptions)
  
  if (!session?.user) {
    return NextResponse.json(
      { error: 'Unauthorized' },
      { status: 401 }
    )
  }

  if (!LEXON_API_KEY) {
    console.error('LEXON_API_KEY not configured')
    return NextResponse.json(
      { error: 'Service configuration error' },
      { status: 500 }
    )
  }
  
  try {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS)

    const response = await fetch(`${AI_BACKEND_URL}${OPENAPI_ENDPOINT}`, {
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${LEXON_API_KEY}`,
      },
      cache: 'no-store',
      signal: controller.signal,
    })

    clearTimeout(timeoutId)
    
    if (!response.ok) {
      return NextResponse.json(
        { error: 'Failed to fetch OpenAPI spec' },
        { status: response.status === 401 || response.status === 403 ? 503 : response.status }
      )
    }
    
    const spec = await response.json()
    
    return NextResponse.json(spec)
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      console.error('OpenAPI spec fetch timed out')
    } else {
      console.error('Error fetching OpenAPI spec')
    }
    return NextResponse.json(
      { error: 'Failed to fetch OpenAPI spec' },
      { status: 500 }
    )
  }
}
