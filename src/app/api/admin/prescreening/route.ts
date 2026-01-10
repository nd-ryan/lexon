import { NextRequest, NextResponse } from 'next/server'
import { getServerSession } from 'next-auth/next'
import { authOptions } from '@/lib/auth'
import { hasDbAtLeastRole } from '@/lib/rbac'

export async function POST(req: NextRequest) {
  try {
    // Check authentication
    const session = await getServerSession(authOptions)
    if (!session?.user?.id) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }
    
    // Check admin role
    const isAdmin = await hasDbAtLeastRole(session, 'admin')
    if (!isAdmin.ok) {
      return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
    }

    // Get the form data from the request
    const formData = await req.formData()
    
    const FASTAPI_URL = process.env.AI_BACKEND_URL || 'http://localhost:8000'
    const apiKey = process.env.FASTAPI_API_KEY || ''
    
    // Forward to backend prescreening endpoint
    const res = await fetch(`${FASTAPI_URL}/api/ai/prescreening/analyze`, {
      method: 'POST',
      headers: { 
        'X-API-Key': apiKey,
      },
      body: formData,
    })
    
    const data = await res.json()
    
    if (!res.ok) {
      return NextResponse.json(data, { status: res.status })
    }
    
    return NextResponse.json(data)
  } catch (error) {
    console.error('Prescreening API error:', error)
    return NextResponse.json(
      { error: 'Failed to analyze PDF' },
      { status: 500 }
    )
  }
}
