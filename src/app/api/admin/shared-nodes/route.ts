import { NextRequest, NextResponse } from 'next/server'
import { getServerSession } from 'next-auth/next'
import { authOptions } from '@/lib/auth'
import { hasDbAtLeastRole } from '@/lib/rbac'

export async function GET(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session?.user?.id) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }
  const isAdmin = await hasDbAtLeastRole(session, 'admin')
  if (!isAdmin.ok) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  }

  const { searchParams } = new URL(req.url)
  const label = searchParams.get('label') || ''
  const orphanedOnly = searchParams.get('orphaned_only') === 'true'
  const limit = searchParams.get('limit') || '100'
  const offset = searchParams.get('offset') || '0'

  const backendUrl = process.env.AI_BACKEND_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''

  const params = new URLSearchParams()
  if (label) params.set('label', label)
  if (orphanedOnly) params.set('orphaned_only', 'true')
  params.set('limit', limit)
  params.set('offset', offset)

  try {
    const res = await fetch(`${backendUrl}/api/ai/shared-nodes?${params}`, {
      headers: { 'X-API-Key': apiKey },
    })
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (error) {
    console.error('Failed to fetch shared nodes:', error)
    return NextResponse.json({ error: 'Failed to fetch shared nodes' }, { status: 500 })
  }
}
