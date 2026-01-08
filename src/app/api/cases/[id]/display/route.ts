import { NextRequest, NextResponse } from 'next/server'
import { getServerSession } from 'next-auth/next'
import { authOptions } from '@/lib/auth'

export async function GET(
  req: NextRequest, 
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await getServerSession(authOptions)
  if (!session?.user?.id) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const { id } = await params
  const FASTAPI_URL = process.env.AI_BACKEND_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''
  
  // Get view parameter from query string (defaults to holdingsCentric)
  const searchParams = req.nextUrl.searchParams
  const view = searchParams.get('view') || 'holdingsCentric'
  
  try {
    const res = await fetch(
      `${FASTAPI_URL}/api/ai/cases/${id}/display?view=${view}`, 
      { 
        headers: { 'X-API-Key': apiKey },
        cache: 'no-store' 
      }
    )
    
    const contentType = res.headers.get('content-type')
    if (!contentType?.includes('application/json')) {
      const text = await res.text()
      console.error('[Case Display GET] Non-JSON response:', text.substring(0, 200))
      return NextResponse.json(
        { error: 'Backend returned non-JSON response', detail: text.substring(0, 200) },
        { status: res.status || 500 }
      )
    }
    
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (error) {
    console.error('[Case Display GET] Error:', error)
    return NextResponse.json(
      { error: 'Failed to fetch case display', detail: error instanceof Error ? error.message : String(error) },
      { status: 500 }
    )
  }
}

