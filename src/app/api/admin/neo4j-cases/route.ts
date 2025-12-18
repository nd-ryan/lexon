import { NextRequest, NextResponse } from 'next/server'
import { getServerSession } from 'next-auth/next'
import { authOptions } from '@/lib/auth'
import { isAdminEmail } from '@/lib/admin'

export async function GET(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!isAdminEmail(session?.user?.email)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const { searchParams } = new URL(req.url)
  const q = searchParams.get('q') || ''
  const limit = searchParams.get('limit') || '200'
  const offset = searchParams.get('offset') || '0'

  const backendUrl = process.env.AI_BACKEND_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''

  const params = new URLSearchParams()
  if (q) params.set('q', q)
  params.set('limit', limit)
  params.set('offset', offset)

  try {
    const res = await fetch(`${backendUrl}/api/ai/neo4j-cases?${params.toString()}`, {
      headers: { 'X-API-Key': apiKey },
    })
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (error) {
    console.error('Failed to fetch neo4j cases:', error)
    return NextResponse.json({ error: 'Failed to fetch neo4j cases' }, { status: 500 })
  }
}


