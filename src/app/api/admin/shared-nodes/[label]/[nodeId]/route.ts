import { NextRequest, NextResponse } from 'next/server'
import { getServerSession } from 'next-auth/next'
import { authOptions } from '@/lib/auth'

const ADMIN_EMAIL = process.env.NEXT_PUBLIC_ADMIN_EMAIL

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ label: string; nodeId: string }> }
) {
  const session = await getServerSession(authOptions)
  if (!session?.user?.email || session.user.email !== ADMIN_EMAIL) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const { label, nodeId } = await params
  const backendUrl = process.env.AI_BACKEND_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''

  try {
    const res = await fetch(`${backendUrl}/api/ai/shared-nodes/${label}/${nodeId}`, {
      headers: { 'X-API-Key': apiKey },
    })
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (error) {
    console.error('Failed to fetch shared node:', error)
    return NextResponse.json({ error: 'Failed to fetch shared node' }, { status: 500 })
  }
}

export async function PUT(
  req: NextRequest,
  { params }: { params: Promise<{ label: string; nodeId: string }> }
) {
  const session = await getServerSession(authOptions)
  if (!session?.user?.email || session.user.email !== ADMIN_EMAIL) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const { label, nodeId } = await params
  const body = await req.json()
  const backendUrl = process.env.AI_BACKEND_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''

  try {
    const res = await fetch(`${backendUrl}/api/ai/shared-nodes/${label}/${nodeId}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': apiKey,
      },
      body: JSON.stringify(body),
    })
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (error) {
    console.error('Failed to update shared node:', error)
    return NextResponse.json({ error: 'Failed to update shared node' }, { status: 500 })
  }
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ label: string; nodeId: string }> }
) {
  const session = await getServerSession(authOptions)
  if (!session?.user?.email || session.user.email !== ADMIN_EMAIL) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const { label, nodeId } = await params
  const { searchParams } = new URL(req.url)
  const forcePartial = searchParams.get('force_partial') === 'true'
  
  const backendUrl = process.env.AI_BACKEND_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''

  try {
    const url = `${backendUrl}/api/ai/shared-nodes/${label}/${nodeId}?force_partial=${forcePartial}`
    const res = await fetch(url, {
      method: 'DELETE',
      headers: { 'X-API-Key': apiKey },
    })
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (error) {
    console.error('Failed to delete shared node:', error)
    return NextResponse.json({ error: 'Failed to delete shared node' }, { status: 500 })
  }
}
