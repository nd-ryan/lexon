import { NextRequest, NextResponse } from 'next/server'
import { getServerSession } from 'next-auth/next'
import { authOptions } from '@/lib/auth'
import { isAdminEmail } from '@/lib/admin'

export async function GET(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!isAdminEmail(session?.user?.email)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const FASTAPI_URL = process.env.AI_BACKEND_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''
  
  const url = new URL(req.url)
  const queryParams = url.searchParams.toString()
  
  try {
    const backendUrl = `${FASTAPI_URL}/api/ai/graph-events${queryParams ? `?${queryParams}` : ''}`
    const res = await fetch(backendUrl, {
      headers: { 
        'X-API-Key': apiKey,
      },
    })
    
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (error) {
    console.error('[Graph Events GET] Error:', error)
    return NextResponse.json(
      { error: 'Failed to fetch graph events' },
      { status: 500 }
    )
  }
}
