import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth/next';
import { generateCypher } from '@/lib/search/generateCypher';
import { executeQuery } from '@/lib/search/executeQuery';
import { authOptions } from '@/lib/auth';

export async function POST(req: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const body = await req.json();
    const userQuery = body.query;

    if (!userQuery) {
      return NextResponse.json({ error: 'Query is required' }, { status: 400 });
    }

    // 1. Generate Cypher from user's natural language query
    const cypherQuery = await generateCypher(userQuery);

    // 2. Execute the generated Cypher query
    const results = await executeQuery(cypherQuery);

    // 3. Return the results and the generated query for debugging
    return NextResponse.json({ 
      cypherQuery,
      results 
    });

  } catch (error: any) {
    console.error('Error in search API:', error);
    return NextResponse.json({ error: error.message || 'An internal server error occurred.' }, { status: 500 });
  }
} 