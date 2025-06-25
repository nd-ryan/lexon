import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth/next';
import { authOptions } from '@/lib/auth';
import jwt from 'jsonwebtoken';

export async function POST(req: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { jobId } = await req.json();
    
    if (!jobId) {
      return NextResponse.json({ error: 'Job ID is required' }, { status: 400 });
    }

    const jwtSecret = process.env.JWT_SECRET;
    const backendUrl = process.env.AI_BACKEND_URL;

    if (!jwtSecret) {
      console.error('JWT_SECRET is not configured');
      return NextResponse.json({ error: 'Server configuration error' }, { status: 500 });
    }

    if (!backendUrl) {
      console.error('AI_BACKEND_URL is not configured');
      return NextResponse.json({ error: 'Server configuration error' }, { status: 500 });
    }

    // Create a short-lived token (30 minutes)
    const token = jwt.sign(
      { 
        userId: session.user?.id || session.user?.email,
        jobId,
        purpose: 'stream_access',
        exp: Math.floor(Date.now() / 1000) + (30 * 60) // 30 minutes
      },
      jwtSecret
    );

    return NextResponse.json({
      token,
      backendUrl
    });

  } catch (error: unknown) {
    console.error('Error generating stream token:', error);
    return NextResponse.json({ 
      error: error instanceof Error ? error.message : 'An internal server error occurred.' 
    }, { status: 500 });
  }
} 