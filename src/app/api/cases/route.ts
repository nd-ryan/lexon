import { NextRequest, NextResponse } from 'next/server'

export async function GET(req: NextRequest) {
  const FASTAPI_URL = process.env.AI_BACKEND_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''
  const url = new URL(req.url)
  const res = await fetch(`${FASTAPI_URL}/api/ai/cases?${url.searchParams.toString()}`, {
    headers: { 'X-API-Key': apiKey },
  })
  const data = await res.json()
  return NextResponse.json(data, { status: res.status })
}


