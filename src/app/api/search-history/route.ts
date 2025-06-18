import { NextRequest, NextResponse } from 'next/server'
import { getServerSession } from 'next-auth/next'
import { authOptions } from '@/lib/auth'
import { prisma } from '@/lib/prisma'

// GET /api/search-history - Retrieve recent search history for the current user
export async function GET(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions)
    
    if (!session?.user?.id) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const searchParams = request.nextUrl.searchParams
    const limit = parseInt(searchParams.get('limit') || '10')
    
    const searchHistory = await prisma.searchHistory.findMany({
      where: {
        userId: session.user.id
      },
      orderBy: {
        createdAt: 'desc'
      },
      take: limit,
      select: {
        id: true,
        query: true,
        queryType: true,
        success: true,
        executionTime: true,
        searchResult: true,
        createdAt: true,
        updatedAt: true
      }
    })

    return NextResponse.json({
      success: true,
      searches: searchHistory,
      count: searchHistory.length
    })
  } catch (error) {
    console.error('Error fetching search history:', error)
    return NextResponse.json(
      { error: 'Failed to fetch search history' },
      { status: 500 }
    )
  }
}

// POST /api/search-history - Save a new search to history
export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions)
    
    if (!session?.user?.id) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const body = await request.json()
    
    // Validate required fields
    if (!body.query || typeof body.success !== 'boolean') {
      return NextResponse.json(
        { error: 'Missing required fields: query, success' },
        { status: 400 }
      )
    }

    const searchHistory = await prisma.searchHistory.create({
      data: {
        userId: session.user.id,
        query: body.query,
        queryType: body.queryType || 'ai_agent',
        success: body.success,
        executionTime: body.executionTime || null,
        
        // Store the complete search result as JSON blob
        searchResult: body // Store the entire request body as the search result
      },
      select: {
        id: true,
        query: true,
        success: true,
        createdAt: true
      }
    })

    return NextResponse.json({
      success: true,
      searchHistory: searchHistory
    })
  } catch (error) {
    console.error('Error saving search history:', error)
    return NextResponse.json(
      { error: 'Failed to save search history' },
      { status: 500 }
    )
  }
} 