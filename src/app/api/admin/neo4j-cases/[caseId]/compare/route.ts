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

  const { caseId: neo4jCaseId } = await params
  const { searchParams } = new URL(req.url)
  const postgresCaseId = searchParams.get('postgres_case_id')

  if (!postgresCaseId) {
    return NextResponse.json({ error: 'postgres_case_id is required' }, { status: 400 })
  }

  const backendUrl = process.env.AI_BACKEND_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''

  try {
    const res = await fetch(
      `${backendUrl}/api/ai/neo4j-cases/${encodeURIComponent(neo4jCaseId)}/compare?postgres_case_id=${encodeURIComponent(postgresCaseId)}`,
      { headers: { 'X-API-Key': apiKey } }
    )
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (error) {
    console.error('Failed to compare case data:', error)
    return NextResponse.json({ error: 'Failed to compare case data' }, { status: 500 })
  }
}

