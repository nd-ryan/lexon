import { NextRequest, NextResponse } from 'next/server';

const AI_BACKEND_URL = process.env.AI_BACKEND_URL || 'http://localhost:8000';
const API_KEY = process.env.FASTAPI_API_KEY;

export async function POST(req: NextRequest) {
  console.log('=== Search Crew Proxy Debug ===');
  console.log('AI_BACKEND_URL:', AI_BACKEND_URL);
  console.log('API_KEY exists:', !!API_KEY);

  if (!API_KEY) {
    console.error('FASTAPI_API_KEY is not set in the environment.');
    return NextResponse.json({ detail: 'Internal server configuration error.' }, { status: 500 });
  }

  try {
    const body = await req.json();
    const query = body.query;
    console.log('Query received:', query);

    if (!query) {
      return NextResponse.json({ detail: 'Query parameter is required.' }, { status: 400 });
    }

    const targetUrl = `${AI_BACKEND_URL}/api/ai/search/crew`;
    console.log('Attempting to fetch:', targetUrl);

    const response = await fetch(targetUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': API_KEY,
      },
      body: JSON.stringify({ query }),
    });

    console.log('Response status:', response.status);
    console.log('Response ok:', response.ok);

    const data = await response.json();
    console.log('Response data received');

    if (!response.ok) {
      console.error('Backend error:', data);
      return NextResponse.json({ detail: data.detail || 'An error occurred with the AI backend.' }, { status: response.status });
    }

    return NextResponse.json(data);
  } catch (error) {
    console.error('Error proxying to AI backend:', error);
    console.error('Error details:', {
      name: error instanceof Error ? error.name : 'Unknown',
      message: error instanceof Error ? error.message : String(error),
      stack: error instanceof Error ? error.stack : undefined
    });
    return NextResponse.json({ 
      detail: 'An error occurred while proxying the request.',
      debug: process.env.NODE_ENV === 'development' ? (error instanceof Error ? error.message : String(error)) : undefined
    }, { status: 500 });
  }
} 