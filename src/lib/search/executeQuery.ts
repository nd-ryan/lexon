import { driver } from '@/lib/neo4jLoader';
import { isNode, isRelationship, isPath, isInt } from 'neo4j-driver';

// Helper to convert Neo4j's integer type to a standard number
function convertInts(obj: any): any {
  if (isInt(obj)) {
    return obj.toNumber();
  }
  if (Array.isArray(obj)) {
    return obj.map(convertInts);
  }
  if (typeof obj === 'object' && obj !== null) {
    const newObj: { [key: string]: any } = {};
    for (const key in obj) {
      newObj[key] = convertInts(obj[key]);
    }
    return newObj;
  }
  return obj;
}

// A more robust transformer to handle different Neo4j data types
function transformRecord(record: any) {
  const transformed: { [key: string]: any } = {};
  for (const key of record.keys) {
    const value = record.get(key);
    if (isNode(value)) {
      transformed[key] = convertInts(value.properties);
    } else if (isRelationship(value)) {
      transformed[key] = convertInts(value.properties);
    } else if (isPath(value)) {
      transformed[key] = {
        start: convertInts(value.start.properties),
        end: convertInts(value.end.properties),
        segments: value.segments.map((segment: any) => ({
          start: convertInts(segment.start.properties),
          end: convertInts(segment.end.properties),
          relationship: convertInts(segment.relationship.properties),
        })),
      };
    } else {
      transformed[key] = convertInts(value);
    }
  }
  return transformed;
}

export async function executeQuery(query: string) {
  const session = driver.session();
  try {
    const result = await session.run(query);
    const results = result.records.map(record => transformRecord(record));
    return results;
  } catch (error) {
    console.error('Error executing Cypher query:', error);
    throw new Error('Failed to execute Cypher query.');
  } finally {
    await session.close();
  }
} 