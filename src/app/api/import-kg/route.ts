import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth/next';
import { parseDocx } from '@/lib/parseDocxToGraph';
import { loadKg } from '@/lib/neo4jLoader';
import { embedQ } from '@/lib/embeddingsQueue';
import { authOptions } from '@/lib/auth';

export async function POST(req: NextRequest) {
  const session = await getServerSession(authOptions);
  if (!session) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const form = await req.formData();
  const file = form.get('file') as File;
  if (!file) {
    return NextResponse.json({ error: 'file missing' }, { status: 400 });
  }

  if (file.type !== 'application/vnd.openxmlformats-officedocument.wordprocessingml.document') {
    return NextResponse.json({ error: 'Invalid file type. Please upload a .docx file.' }, { status: 400 });
  }

  try {
    const buffer = Buffer.from(await file.arrayBuffer());

    // 1️⃣ parse → KG JSON
    const kg = await parseDocx(buffer);

    // 2️⃣ load nodes + rels
    await loadKg(kg);

    // 3️⃣ enqueue embeddings for new Case ids
    if (kg.cases.length > 0) {
      await embedQ.add('embed-cases', { ids: kg.cases.map(c => c.case_id) });
    }

    return NextResponse.json({ ok: true, counts: {
      cases: kg.cases.length, parties: kg.parties.length, provisions: kg.provisions.length
    }});
  } catch (error) {
    console.error('Error processing file upload:', error);
    return NextResponse.json({ error: 'Failed to process file.' }, { status: 500 });
  }
} 