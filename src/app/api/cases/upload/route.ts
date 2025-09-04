import { NextRequest, NextResponse } from 'next/server'

export async function POST(req: NextRequest) {
  const formData = await req.formData()
  const FASTAPI_URL = process.env.FASTAPI_URL || 'http://localhost:8000'
  const apiKey = process.env.FASTAPI_API_KEY || ''
  const res = await fetch(`${FASTAPI_URL}/api/ai/cases/upload`, {
    method: 'POST',
    headers: { 'X-API-Key': apiKey },
    body: formData,
  })
  const data = await res.json()
  return NextResponse.json(data, { status: res.status })
}


