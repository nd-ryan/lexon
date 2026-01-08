import { getServerSession } from 'next-auth/next';
import { NextRequest, NextResponse } from 'next/server';
import { authOptions } from '@/lib/auth';
import { hasDbAtLeastRole } from '@/lib/rbac';

export async function POST(request: NextRequest) {
  // Check authentication - only admin users can access
  const session = await getServerSession(authOptions);
  if (!session?.user?.id) {
    return NextResponse.json(
      { detail: 'Unauthorized. Admin access required.' },
      { status: 401 }
    );
  }
  const isAdmin = await hasDbAtLeastRole(session, 'admin')
  if (!isAdmin.ok) {
    return NextResponse.json(
      { detail: 'Forbidden. Admin access required.' },
      { status: 403 }
    );
  }

  try {
    const body = await request.json();

    const backendUrl = process.env.AI_BACKEND_URL || 'http://localhost:8000';
    const apiKey = process.env.FASTAPI_API_KEY || '';

    if (!apiKey) {
      console.error('FASTAPI_API_KEY environment variable not set');
      return NextResponse.json(
        { detail: 'Server configuration error' },
        { status: 500 }
      );
    }

    const response = await fetch(`${backendUrl}/api/v1/eval/step`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': apiKey,
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      return NextResponse.json(
        {
          detail: errorData.detail || 'Eval backend error',
          statusText: response.statusText,
        },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Eval step proxy error:', error);
    return NextResponse.json(
      { detail: 'Failed to process eval step request' },
      { status: 500 }
    );
  }
}


