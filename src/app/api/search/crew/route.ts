import { NextRequest, NextResponse } from 'next/server';

const AI_BACKEND_URL = process.env.AI_BACKEND_URL || 'http://localhost:8000';
const API_KEY = process.env.FASTAPI_API_KEY;

export async function POST(req: NextRequest) {
  if (!API_KEY) {
    console.error('FASTAPI_API_KEY is not set in the environment.');
    return NextResponse.json({ detail: 'Internal server configuration error.' }, { status: 500 });
  }

  try {
    const body = await req.json();
    const query = body.query;

    if (!query) {
      return NextResponse.json({ detail: 'Query parameter is required.' }, { status: 400 });
    }

    const response = await fetch(`${AI_BACKEND_URL}/api/ai/search/crew`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': API_KEY,
      },
      body: JSON.stringify({ query }),
    });

    const data = await response.json();

    if (!response.ok) {
      return NextResponse.json({ detail: data.detail || 'An error occurred with the AI backend.' }, { status: response.status });
    }

    return NextResponse.json(data);
  } catch (error) {
    console.error('Error proxying to AI backend:', error);
    return NextResponse.json({ detail: 'An error occurred while proxying the request.' }, { status: 500 });
  }
} 