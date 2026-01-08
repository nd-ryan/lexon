import { NextResponse } from 'next/server'
import { getServerSession } from 'next-auth/next'
import { authOptions } from '@/lib/auth'
import { hasDbAtLeastRole } from '@/lib/rbac'
import { readFile } from 'fs/promises'
import { join } from 'path'

/**
 * GET /api/docs/postman
 * 
 * Serve the Postman collection for download.
 * 
 * Security:
 * - Requires NextAuth session
 * - Requires developer or admin role
 */
export async function GET() {
  const session = await getServerSession(authOptions)
  
  if (!session?.user) {
    return NextResponse.json(
      { error: 'Unauthorized' },
      { status: 401 }
    )
  }
  
  const canAccess = await hasDbAtLeastRole(session, 'developer')
  if (!canAccess.ok) {
    return NextResponse.json(
      { error: 'Forbidden' },
      { status: 403 }
    )
  }

  try {
    // Read the Postman collection from public directory
    const collectionPath = join(process.cwd(), 'public', 'lexon-external-api.postman_collection.json')
    const collection = await readFile(collectionPath, 'utf-8')
    
    return new NextResponse(collection, {
      headers: {
        'Content-Type': 'application/json',
        'Content-Disposition': 'attachment; filename="lexon-external-api.postman_collection.json"',
      },
    })
  } catch (error) {
    console.error('Failed to read Postman collection:', error)
    return NextResponse.json(
      { error: 'Failed to load Postman collection' },
      { status: 500 }
    )
  }
}
