import { NextRequest, NextResponse } from 'next/server'

export async function GET(req: NextRequest) {
  const FASTAPI_URL = process.env.AI_BACKEND_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''
  const url = new URL(req.url)
  
  try {
    const res = await fetch(`${FASTAPI_URL}/api/ai/cases?${url.searchParams.toString()}`, {
      headers: { 'X-API-Key': apiKey },
    })
    
    // Check content type before parsing
    const contentType = res.headers.get('content-type')
    if (!contentType?.includes('application/json')) {
      const text = await res.text()
      console.error('[Cases API] Non-JSON response:', text.substring(0, 200))
      return NextResponse.json(
        { error: 'Backend returned non-JSON response', detail: text.substring(0, 200) },
        { status: res.status || 500 }
      )
    }
    
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (error) {
    console.error('[Cases API] Error:', error)
    return NextResponse.json(
      { error: 'Failed to fetch cases', detail: error instanceof Error ? error.message : String(error) },
      { status: 500 }
    )
  }
}


