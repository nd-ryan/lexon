import { NextResponse } from 'next/server'

const AI_BACKEND_URL = process.env.AI_BACKEND_URL || 'http://localhost:8000'
const API_KEY = process.env.FASTAPI_API_KEY

export async function GET() {
  if (!API_KEY) {
    return NextResponse.json({ success: false, error: 'FASTAPI_API_KEY is not configured' }, { status: 500 })
  }

  const backendUrl = AI_BACKEND_URL.replace(/\/$/, '')
  try {
    const res = await fetch(`${backendUrl}/api/ai/schema`, {
      headers: { 'X-API-Key': API_KEY },
      cache: 'no-store',
    })
    const data = await res.json()
    if (!res.ok) {
      return NextResponse.json({ success: false, error: data?.detail || 'Backend error' }, { status: res.status })
    }
    return NextResponse.json(data)
  } catch (err: any) {
    return NextResponse.json({ success: false, error: err?.message || 'Failed to fetch schema' }, { status: 500 })
  }
}


