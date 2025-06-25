import { NextRequest } from 'next/server';

const AI_BACKEND_URL = process.env.AI_BACKEND_URL || 'http://localhost:8000';
const API_KEY = process.env.FASTAPI_API_KEY;

export async function POST(req: NextRequest) {
  console.log('=== Search Crew Stream Proxy Debug ===');
  console.log('AI_BACKEND_URL:', AI_BACKEND_URL);
  console.log('API_KEY exists:', !!API_KEY);

  if (!API_KEY) {
    console.error('FASTAPI_API_KEY is not set in the environment.');
    return new Response('Internal server configuration error.', { status: 500 });
  }

  try {
    const body = await req.json();
    const query = body.query;
    console.log('Query received:', query);

    if (!query) {
      return new Response('Query parameter is required.', { status: 400 });
    }

    const targetUrl = `${AI_BACKEND_URL}/api/ai/search/crew/stream`;
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
      return new Response(errorText, { status: response.status });
    }

    // This should return a JSON response with job_id
    const result = await response.json();
    console.log('Job enqueued successfully:', result);
    
    return new Response(JSON.stringify(result), {
      status: 200,
      headers: {
        'Content-Type': 'application/json',
      },
    });
  } catch (error) {
    console.error('Stream proxy error:', error);
    return new Response('An error occurred while processing the request.', { status: 500 });
  }
} 