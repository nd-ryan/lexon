import { NextRequest, NextResponse } from 'next/server'
import { getServerSession } from 'next-auth/next'
import { authOptions } from '@/lib/auth'

export async function GET(_: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const FASTAPI_URL = process.env.AI_BACKEND_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''
  
  try {
    const res = await fetch(`${FASTAPI_URL}/api/ai/cases/${id}`, { headers: { 'X-API-Key': apiKey } })
    
    const contentType = res.headers.get('content-type')
    if (!contentType?.includes('application/json')) {
      const text = await res.text()
      console.error('[Case GET] Non-JSON response:', text.substring(0, 200))
      return NextResponse.json(
        { error: 'Backend returned non-JSON response', detail: text.substring(0, 200) },
        { status: res.status || 500 }
      )
    }
    
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (error) {
    console.error('[Case GET] Error:', error)
    return NextResponse.json(
      { error: 'Failed to fetch case', detail: error instanceof Error ? error.message : String(error) },
      { status: 500 }
    )
  }
}

export async function PUT(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const session = await getServerSession(authOptions)
  if (!session?.user?.id) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const { id } = await params
  const body = await req.json()
  const FASTAPI_URL = process.env.AI_BACKEND_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''
  const res = await fetch(`${FASTAPI_URL}/api/ai/cases/${id}`, {
    method: 'PUT',
    headers: { 
      'Content-Type': 'application/json', 
      'X-API-Key': apiKey,
      'X-User-Id': session.user.id,  // Server-extracted, not client-provided
    },
    body: JSON.stringify(body),
  })
  const data = await res.json()
  return NextResponse.json(data, { status: res.status })
}

export async function DELETE(_: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const session = await getServerSession(authOptions)
  if (!session?.user?.id) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const { id } = await params
  const FASTAPI_URL = process.env.AI_BACKEND_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''
  const res = await fetch(`${FASTAPI_URL}/api/ai/cases/${id}`, {
    method: 'DELETE',
    headers: { 
      'X-API-Key': apiKey,
      'X-User-Id': session.user.id,
    },
  })
  const contentType = res.headers.get('content-type') || ''
  let data: any = null
  if (contentType.includes('application/json')) {
    data = await res.json()
  }
  return NextResponse.json(data ?? { success: res.ok }, { status: res.status })
}


