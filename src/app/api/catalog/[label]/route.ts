import { NextRequest, NextResponse } from 'next/server';

const AI_BACKEND_URL = process.env.AI_BACKEND_URL || 'http://localhost:8000';
const API_KEY = process.env.FASTAPI_API_KEY;

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ label: string }> }
) {
  const { label } = await params;
  
  if (!API_KEY) {
    return NextResponse.json({ detail: 'Internal server configuration error.' }, { status: 500 });
  }

  try {
    const cleanedUrl = AI_BACKEND_URL.replace(/\/$/, '');
    const targetUrl = `${cleanedUrl}/api/ai/catalog/${encodeURIComponent(label)}`;
    const resp = await fetch(targetUrl, {
      method: 'GET',
      headers: {
        'X-API-Key': API_KEY,
      },
      cache: 'no-store',
    });

    if (!resp.ok) {
      const txt = await resp.text();
      return NextResponse.json({ detail: txt }, { status: resp.status });
    }

    const data = await resp.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Failed to fetch catalog nodes:', error);
    return NextResponse.json(
      { detail: 'Failed to fetch catalog nodes' }, 
      { status: 500 }
    );
  }
}

