import { Queue, Worker } from 'bullmq';
import { driver } from './neo4jLoader';
import OpenAI from 'openai';

const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

const connection = {
  host: process.env.REDIS_HOST!,
  port: parseInt(process.env.REDIS_PORT!, 10),
  password: process.env.REDIS_PASSWORD!,
};

export const embedQ = new Queue('embeddings', { connection });

if (process.env.WORKER_ENABLED) {
  new Worker('embeddings', async job => {
    const session = driver.session();
    try {
      const { ids } = job.data as { ids: string[] };
      if (!ids || ids.length === 0) return;
  
      const res = await session.run(`
        MATCH (c:Case) WHERE c.case_id IN $ids 
        RETURN c.case_id AS id, c.summary AS txt
      `, { ids });
  
      for (const record of res.records) {
        const id = record.get('id');
        const txt = record.get('txt');
        if (!txt) continue;
  
        const vector = (await openai.embeddings.create({
          model: 'text-embedding-3-small',
          input: txt
        })).data[0].embedding;
  
        await session.run(`
          MATCH (c:Case {case_id: $id})
          SET c.embedding = $vec
        `, { id, vec: vector });
      }
    } finally {
      await session.close();
    }
  }, { connection });
} 