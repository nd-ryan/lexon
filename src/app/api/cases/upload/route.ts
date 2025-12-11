import { NextRequest, NextResponse } from 'next/server'
import { getServerSession } from 'next-auth/next'
import { authOptions } from '@/lib/auth'

export async function POST(req: NextRequest) {
  try {
    const session = await getServerSession(authOptions)
    if (!session?.user?.id) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const formData = await req.formData()
    const FASTAPI_URL = process.env.AI_BACKEND_URL || 'http://localhost:8000'
    const apiKey = process.env.FASTAPI_API_KEY || ''
    
    // Start async extraction job - returns immediately with job_id
    const res = await fetch(`${FASTAPI_URL}/api/ai/cases/upload`, {
      method: 'POST',
      headers: { 
        'X-API-Key': apiKey,
        'X-User-Id': session.user.id,  // Server-extracted, not client-provided
      },
      body: formData,
    })
    
    const data = await res.json()
    
    if (!res.ok) {
      return NextResponse.json(data, { status: res.status })
    }
    
    // Return job_id for progress tracking
    return NextResponse.json({
      success: true,
      caseId: data.caseId,
      jobId: data.jobId,
    })
  } catch (error) {
    console.error('Upload API error:', error)
    return NextResponse.json(
      { success: false, error: 'Failed to start upload' },
      { status: 500 }
    )
  }
}


