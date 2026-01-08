import { NextRequest, NextResponse } from 'next/server'
import { getServerSession } from 'next-auth/next'
import { authOptions } from '@/lib/auth'
import { hasDbAtLeastRole } from '@/lib/rbac'

export async function POST(req: NextRequest) {
  try {
    const session = await getServerSession(authOptions)
    if (!session) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }
    const canSubmit = await hasDbAtLeastRole(session, 'editor')
    if (!canSubmit.ok) {
      return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
    }

    const { id } = await req.json()
    if (!id || typeof id !== 'string') {
      return NextResponse.json({ error: 'Missing id' }, { status: 400 })
    }

    const backendUrl = process.env.AI_BACKEND_URL
    const token = process.env.FASTAPI_API_KEY
    if (!backendUrl || !token) {
      console.error('AI_BACKEND_URL or BACKEND_API_TOKEN not configured')
      return NextResponse.json({ error: 'Server configuration error' }, { status: 500 })
    }

    const userId = (session.user as { id?: string })?.id || ''
    const res = await fetch(`${backendUrl}/api/ai/kg/submit`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
        'X-User-Id': userId,  // Server-extracted, not client-provided
      },
      body: JSON.stringify({ case_id: id })
    })

    const text = await res.text()
    const contentType = res.headers.get('content-type') || 'application/json'
    return new NextResponse(text, { status: res.status, headers: { 'Content-Type': contentType } })
  } catch (err: any) {
    console.error('KG submit error:', err)
    return NextResponse.json({ error: err?.message || 'Internal error' }, { status: 500 })
  }
}


