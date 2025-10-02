import { NextRequest, NextResponse } from 'next/server'

export async function GET(_: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const FASTAPI_URL = process.env.FASTAPI_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''
  const res = await fetch(`${FASTAPI_URL}/api/ai/cases/${id}`, { headers: { 'X-API-Key': apiKey } })
  const data = await res.json()
  return NextResponse.json(data, { status: res.status })
}

export async function PUT(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const body = await req.json()
  const FASTAPI_URL = process.env.FASTAPI_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''
  const res = await fetch(`${FASTAPI_URL}/api/ai/cases/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', 'X-API-Key': apiKey },
    body: JSON.stringify(body),
  })
  const data = await res.json()
  return NextResponse.json(data, { status: res.status })
}

export async function DELETE(_: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const FASTAPI_URL = process.env.FASTAPI_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''
  const res = await fetch(`${FASTAPI_URL}/api/ai/cases/${id}`, {
    method: 'DELETE',
    headers: { 'X-API-Key': apiKey },
  })
  const contentType = res.headers.get('content-type') || ''
  let data: any = null
  if (contentType.includes('application/json')) {
    data = await res.json()
  }
  return NextResponse.json(data ?? { success: res.ok }, { status: res.status })
}


