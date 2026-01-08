import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth/next'
import { authOptions } from '@/lib/auth'
import { hasDbAtLeastRole } from '@/lib/rbac'

const AI_BACKEND_URL = process.env.AI_BACKEND_URL || 'http://localhost:8000';
const API_KEY = process.env.FASTAPI_API_KEY;

export async function POST(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session?.user?.id) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 })
  }
  const isAdmin = await hasDbAtLeastRole(session, 'admin')
  if (!isAdmin.ok) {
    return NextResponse.json({ detail: 'Forbidden' }, { status: 403 })
  }

  console.log('=== Search Crew Stream Proxy Debug ===');
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

    const cleanedUrl = AI_BACKEND_URL.replace(/\/$/, '');
    const targetUrl = `${cleanedUrl}/api/ai/search/crew/stream`;
    console.log('Attempting to enqueue job at:', targetUrl);

    const response = await fetch(targetUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': API_KEY,
      },
      body: JSON.stringify({ query }),
    });

    console.log('Enqueue response status:', response.status);
    console.log('Enqueue response ok:', response.ok);

    if (!response.ok) {
      const errorText = await response.text();
      console.error('Backend enqueue error:', errorText);
      return NextResponse.json({ detail: errorText }, { status: response.status });
    }

    // This should return a JSON response with job_id
    const result = await response.json();
    console.log('Job enqueued successfully:', result);
    
    return NextResponse.json(result);
  } catch (error) {
    console.error('Stream proxy error:', error);
    return NextResponse.json({ 
      detail: 'An error occurred while processing the request.',
      debug: process.env.NODE_ENV === 'development' ? (error instanceof Error ? error.message : String(error)) : undefined
    }, { status: 500 });
  }
} 