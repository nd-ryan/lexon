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

  if (!API_KEY) {
    console.error('FASTAPI_API_KEY is not set in the environment.');
    return NextResponse.json({ detail: 'Internal server configuration error.' }, { status: 500 });
  }
  
  // Always use the advanced (direct Neo4j) endpoint as it's more reliable
  const endpoint = '/api/ai/import-kg/advanced';

  try {
    const formData = await req.formData();
    const file = formData.get('file') as File;

    if (!file) {
      return NextResponse.json({ detail: 'File is required.' }, { status: 400 });
    }
    
    // We need to reconstruct the FormData to forward it
    const backendFormData = new FormData();
    backendFormData.append('file', file);

    const response = await fetch(`${AI_BACKEND_URL}${endpoint}`, {
      method: 'POST',
      headers: {
        'X-API-Key': API_KEY,
        // 'Content-Type' is set automatically by fetch for FormData
      },
      body: backendFormData,
    });

    const data = await response.json();

    if (!response.ok) {
      return NextResponse.json({ detail: data.detail || 'An error occurred with the AI backend.' }, { status: response.status });
    }

    return NextResponse.json(data);
  } catch (error) {
    console.error('Error proxying file upload to AI backend:', error);
    return NextResponse.json({ detail: 'An error occurred while proxying the request.' }, { status: 500 });
  }
} 