import { NextResponse } from 'next/server'

export async function GET() {
  return NextResponse.json({ status: 'ok' })
}

export async function POST() {
  return NextResponse.json({ error: 'Use /api/search/crew/stream for enqueuing jobs.' }, { status: 405 })
}

 