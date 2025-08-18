import { NextRequest, NextResponse } from 'next/server';

const AI_BACKEND_URL = process.env.AI_BACKEND_URL || 'http://localhost:8000';
const API_KEY = process.env.FASTAPI_API_KEY;

export async function GET(req: NextRequest) {
  if (!API_KEY) {
    return NextResponse.json({ detail: 'Internal server configuration error.' }, { status: 500 });
  }

  const { searchParams } = new URL(req.url);
  const label = searchParams.get('label');
  const id_value = searchParams.get('id_value');

  if (!label || !id_value) {
    return NextResponse.json({ detail: 'Missing required query params: label and id_value' }, { status: 400 });
  }

  try {
    const cleanedUrl = AI_BACKEND_URL.replace(/\/$/, '');
    const targetUrl = `${cleanedUrl}/api/ai/node/enriched?label=${encodeURIComponent(label)}&id_value=${encodeURIComponent(id_value)}`;
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
  } catch {
    return NextResponse.json({ detail: 'Failed to fetch enriched node' }, { status: 500 });
  }
}


