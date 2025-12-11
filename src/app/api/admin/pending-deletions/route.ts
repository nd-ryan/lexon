import { NextRequest, NextResponse } from 'next/server'
import { getServerSession } from 'next-auth/next'
import { authOptions } from '@/lib/auth'

const ADMIN_EMAIL = process.env.NEXT_PUBLIC_ADMIN_EMAIL

export async function GET(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session?.user?.email || session.user.email !== ADMIN_EMAIL) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const FASTAPI_URL = process.env.AI_BACKEND_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''
  
  const url = new URL(req.url)
  const status = url.searchParams.get('status')
  
  try {
    const backendUrl = `${FASTAPI_URL}/api/ai/pending-deletions${status ? `?status=${status}` : ''}`
    const res = await fetch(backendUrl, {
      headers: { 
        'X-API-Key': apiKey,
        'X-User-Id': (session.user as { id?: string })?.id || '',
      },
    })
    
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (error) {
    console.error('[Pending Deletions GET] Error:', error)
    return NextResponse.json(
      { error: 'Failed to fetch pending deletions' },
      { status: 500 }
    )
  }
}
