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
  const { searchParams } = new URL(req.url)
  const view = searchParams.get('view') || 'holdingsCentric'

  const backendUrl = process.env.AI_BACKEND_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''

  try {
    const res = await fetch(
      `${backendUrl}/api/ai/neo4j-cases/${encodeURIComponent(caseId)}/view?view=${encodeURIComponent(view)}`,
      { headers: { 'X-API-Key': apiKey } }
    )
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (error) {
    console.error('Failed to fetch neo4j case view:', error)
    return NextResponse.json({ error: 'Failed to fetch neo4j case view' }, { status: 500 })
  }
}


