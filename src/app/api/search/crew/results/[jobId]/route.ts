import { NextRequest } from 'next/server';

const AI_BACKEND_URL = process.env.AI_BACKEND_URL || 'http://localhost:8000';
const API_KEY = process.env.FASTAPI_API_KEY;

export async function GET(
  req: NextRequest,
  { params }: { params: { jobId: string } }
) {
  const jobId = params.jobId;
  console.log(`=== SSE Proxy for Job ID: ${jobId} ===`);

  if (!API_KEY) {
    console.error('FASTAPI_API_KEY is not set.');
    return new Response('Internal server configuration error.', { status: 500 });
  }

  if (!jobId) {
    return new Response('Job ID is required.', { status: 400 });
  }

  const targetUrl = `${AI_BACKEND_URL}/api/ai/search/results/${jobId}`;
  console.log('Connecting to backend for SSE:', targetUrl);

  try {
    const response = await fetch(targetUrl, {
      method: 'GET',
      headers: {
        'Accept': 'text/event-stream',
        'X-API-Key': API_KEY,
      },
      // This is a streaming request, so we pass the readable stream directly to the Next.js response
    });
    
    if (!response.ok) {
        const errorText = await response.text();
        console.error(`Backend error for job ${jobId}:`, errorText);
        return new Response(errorText, { status: response.status });
    }

    // Return a streaming response
    return new Response(response.body, {
      status: 200,
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
      },
    });

  } catch (error) {
    console.error(`Error proxying SSE for job ${jobId}:`, error);
    return new Response('An error occurred while setting up the stream.', { status: 500 });
  }
} 