import { NextRequest, NextResponse } from 'next/server'
import { getServerSession } from 'next-auth/next'
import { authOptions } from '@/lib/auth'

const ADMIN_EMAIL = process.env.NEXT_PUBLIC_ADMIN_EMAIL

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await getServerSession(authOptions)
  if (!session?.user?.email || session.user.email !== ADMIN_EMAIL) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const { id } = await params
  const FASTAPI_URL = process.env.AI_BACKEND_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''
  
  try {
    const res = await fetch(`${FASTAPI_URL}/api/ai/pending-deletions/${id}/approve`, {
      method: 'POST',
      headers: { 
        'Content-Type': 'application/json',
        'X-API-Key': apiKey,
        'X-User-Id': (session.user as { id?: string })?.id || '',
      },
    })
    
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (error) {
    console.error('[Approve Deletion] Error:', error)
    return NextResponse.json(
      { error: 'Failed to approve deletion' },
      { status: 500 }
    )
  }
}
