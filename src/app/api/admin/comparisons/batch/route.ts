import { NextRequest, NextResponse } from 'next/server'
import { getServerSession } from 'next-auth/next'
import { authOptions } from '@/lib/auth'
import { isAdminEmail } from '@/lib/admin'

export async function POST(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!isAdminEmail(session?.user?.email)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const backendUrl = process.env.AI_BACKEND_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''

  try {
    const body = await req.json()
    
    const res = await fetch(
      `${backendUrl}/api/ai/admin/comparisons/batch`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': apiKey,
        },
        body: JSON.stringify(body),
      }
    )
    
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (error) {
    console.error('Failed to start batch comparison:', error)
    return NextResponse.json({ error: 'Failed to start batch comparison' }, { status: 500 })
  }
}

