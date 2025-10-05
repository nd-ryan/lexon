import { NextRequest } from 'next/server'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'
export const revalidate = 0

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ jobId: string }> }
) {
  const { jobId } = await params
  const FASTAPI_URL = process.env.AI_BACKEND_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''

  console.log(`[Progress Proxy] Connecting to FastAPI for job ${jobId}`)
  console.log(`[Progress Proxy] FastAPI URL: ${FASTAPI_URL}/api/ai/cases/upload/progress/${jobId}`)

  try {
    // Proxy the SSE stream from FastAPI to the client, adding auth header
    const response = await fetch(
      `${FASTAPI_URL}/api/ai/cases/upload/progress/${jobId}`,
      {
        headers: {
          'X-API-Key': apiKey,
        },
      }
    )
    
    console.log(`[Progress Proxy] FastAPI response status: ${response.status}`)

    if (!response.ok) {
      console.error(`[Progress Proxy] FastAPI returned error: ${response.status}`)
      return new Response(
        JSON.stringify({ error: 'Failed to connect to progress stream' }),
        { status: response.status }
      )
    }

    console.log(`[Progress Proxy] Streaming response back to client`)
    
    // Return the streaming response
    return new Response(response.body, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache, no-transform',
        'Connection': 'keep-alive',
      },
    })
  } catch (error) {
    console.error('[Progress Proxy] Error:', error)
    return new Response(
      JSON.stringify({ error: 'Failed to connect to backend' }),
      { status: 500 }
    )
  }
}

