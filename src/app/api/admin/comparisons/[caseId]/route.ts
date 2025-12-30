import { NextRequest, NextResponse } from 'next/server'
import { getServerSession } from 'next-auth/next'
import { authOptions } from '@/lib/auth'
import { isAdminEmail } from '@/lib/admin'

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ caseId: string }> }
) {
  const session = await getServerSession(authOptions)
  if (!isAdminEmail(session?.user?.email)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const { caseId } = await params
  const backendUrl = process.env.AI_BACKEND_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''

  try {
    const res = await fetch(
      `${backendUrl}/api/ai/admin/comparisons/${encodeURIComponent(caseId)}`,
      { headers: { 'X-API-Key': apiKey } }
    )
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (error) {
    console.error('Failed to get comparison result:', error)
    return NextResponse.json({ error: 'Failed to get comparison result' }, { status: 500 })
  }
}

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ caseId: string }> }
) {
  const session = await getServerSession(authOptions)
  if (!isAdminEmail(session?.user?.email)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const { caseId } = await params
  const backendUrl = process.env.AI_BACKEND_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''

  try {
    const body = await req.json().catch(() => ({}))
    
    const res = await fetch(
      `${backendUrl}/api/ai/admin/comparisons/${encodeURIComponent(caseId)}`,
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
    console.error('Failed to run comparison:', error)
    return NextResponse.json({ error: 'Failed to run comparison' }, { status: 500 })
  }
}

