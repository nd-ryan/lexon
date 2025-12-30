import { NextRequest } from 'next/server'
import { getServerSession } from 'next-auth/next'
import { authOptions } from '@/lib/auth'
import { isAdminEmail } from '@/lib/admin'

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ jobId: string }> }
) {
  const session = await getServerSession(authOptions)
  if (!isAdminEmail(session?.user?.email)) {
    return new Response(JSON.stringify({ error: 'Unauthorized' }), { 
      status: 401,
      headers: { 'Content-Type': 'application/json' }
    })
  }

  const { jobId } = await params
  const backendUrl = process.env.AI_BACKEND_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''

  try {
    // Proxy the SSE stream from the backend
    const response = await fetch(
      `${backendUrl}/api/ai/admin/comparisons/progress/${encodeURIComponent(jobId)}`,
      {
        headers: {
          'X-API-Key': apiKey,
          'Accept': 'text/event-stream',
        },
      }
    )

    if (!response.ok) {
      return new Response(JSON.stringify({ error: 'Failed to connect to progress stream' }), {
        status: response.status,
        headers: { 'Content-Type': 'application/json' }
      })
    }

    // Return the SSE stream directly
    return new Response(response.body, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no',
      },
    })
  } catch (error) {
    console.error('Failed to proxy progress stream:', error)
    return new Response(JSON.stringify({ error: 'Failed to connect to progress stream' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    })
  }
}

