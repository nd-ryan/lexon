import { NextRequest, NextResponse } from 'next/server'
import { getServerSession } from 'next-auth/next'
import { authOptions } from '@/lib/auth'
import { hasDbAtLeastRole } from '@/lib/rbac'

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ caseId: string }> }
) {
  const session = await getServerSession(authOptions)
  if (!session?.user?.id) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }
  const isAdmin = await hasDbAtLeastRole(session, 'admin')
  if (!isAdmin.ok) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  }

  const { caseId } = await params

  const backendUrl = process.env.AI_BACKEND_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''

  const url = `${backendUrl}/api/ai/neo4j-cases/${encodeURIComponent(caseId)}/graph`

  try {
    const res = await fetch(url, {
      headers: { 'X-API-Key': apiKey },
    })
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (error) {
    console.error('Failed to fetch neo4j case graph:', error)
    return NextResponse.json({ error: 'Failed to fetch neo4j case graph' }, { status: 500 })
  }
}


