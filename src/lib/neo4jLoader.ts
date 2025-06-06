import neo4j, { Driver } from 'neo4j-driver';
import { KG, CaseNode, PartyNode, ProvisionNode, DoctrineNode, ArgumentNode, AllegationNode, RulingNode, ReliefNode, EvidenceNode } from './parseDocxToGraph';

export const driver: Driver = neo4j.driver(
  process.env.NEO4J_URI!, neo4j.auth.basic(process.env.NEO4J_USER!, process.env.NEO4J_PASSWORD!)
);

export async function loadKg(kg: KG) {
  const s = driver.session({ defaultAccessMode: neo4j.session.WRITE });
  try {
    await s.run(`CREATE CONSTRAINT case_id IF NOT EXISTS FOR (c:Case) REQUIRE c.case_id IS UNIQUE`);
    await s.run(`CREATE CONSTRAINT party_id IF NOT EXISTS FOR (p:Party) REQUIRE p.party_id IS UNIQUE`);
    await s.run(`CREATE CONSTRAINT provision_id IF NOT EXISTS FOR (v:Provision) REQUIRE v.provision_id IS UNIQUE`);
    await s.run(`CREATE CONSTRAINT doctrine_id IF NOT EXISTS FOR (d:Doctrine) REQUIRE d.doctrine_id IS UNIQUE`);
    await s.run(`CREATE CONSTRAINT argument_id IF NOT EXISTS FOR (a:Argument) REQUIRE a.argument_id IS UNIQUE`);
    await s.run(`CREATE CONSTRAINT allegation_id IF NOT EXISTS FOR (al:Allegation) REQUIRE al.allegation_id IS UNIQUE`);
    await s.run(`CREATE CONSTRAINT ruling_id IF NOT EXISTS FOR (r:Ruling) REQUIRE r.ruling_id IS UNIQUE`);
    await s.run(`CREATE CONSTRAINT relief_id IF NOT EXISTS FOR (re:Relief) REQUIRE re.relief_id IS UNIQUE`);
    await s.run(`CREATE CONSTRAINT evidence_id IF NOT EXISTS FOR (ev:Evidence) REQUIRE ev.document_id IS UNIQUE`);

    type MergableNodes = (CaseNode | PartyNode | ProvisionNode | DoctrineNode | ArgumentNode | AllegationNode | RulingNode | ReliefNode | EvidenceNode)[];
    const mergeNodes = async (label: string, id: string, rows: MergableNodes) => {
      if (!rows || rows.length === 0) return;
      await s.run(`
        UNWIND $rows AS row
        MERGE (n:${label} {${id}: row.${id}})
        SET   n += row
      `, { rows });
    };
    await mergeNodes('Case', 'case_id', kg.cases);
    await mergeNodes('Party', 'party_id', kg.parties);
    await mergeNodes('Provision', 'provision_id', kg.provisions);
    await mergeNodes('Doctrine', 'doctrine_id', kg.doctrines);
    await mergeNodes('Argument', 'argument_id', kg.arguments);
    await mergeNodes('Allegation', 'allegation_id', kg.allegations);
    await mergeNodes('Ruling', 'ruling_id', kg.rulings);
    await mergeNodes('Relief', 'relief_id', kg.reliefs);
    await mergeNodes('Evidence', 'document_id', kg.evidence);
    
    // Helper for merging relationships
    const mergeRelationships = async (cypher: string, rows: any[]) => {
      if (!rows || rows.length === 0) return;
      await s.run(cypher, { rows });
    };

    await mergeRelationships(`
      UNWIND $rows AS row
      MATCH (c:Case {case_id: row.case_id})
      MATCH (p:Party {party_id: row.party_id})
      MERGE (c)-[r:HAS_PARTY]->(p)
      SET r.role = row.role
    `, kg.caseParties);

    await mergeRelationships(`
      UNWIND $rows AS row
      MATCH (c:Case {case_id: row.case_id})
      MATCH (v:Provision {provision_id: row.provision_id})
      MERGE (c)-[:CITES_PROVISION]->(v)
    `, kg.caseProvisions);

    await mergeRelationships(`
      UNWIND $rows AS row
      MATCH (c:Case {case_id: row.case_id})
      MATCH (a:Allegation {allegation_id: row.allegation_id})
      MERGE (c)-[:INCLUDES_ALLEGATION]->(a)
    `, kg.caseAlleg);
    
    await mergeRelationships(`
      UNWIND $rows AS row
      MATCH (al:Allegation {allegation_id: row.allegation_id})
      OPTIONAL MATCH (p:Party {party_id: row.target_id})
      OPTIONAL MATCH (v:Provision {provision_id: row.target_id})
      FOREACH (_ IN CASE WHEN p IS NOT NULL THEN [1] END | MERGE (al)-[:ALLEGES_AGAINST]->(p))
      FOREACH (_ IN CASE WHEN v IS NOT NULL THEN [1] END | MERGE (al)-[:ALLEGES_AGAINST]->(v))
    `, kg.allegTargets);

    await mergeRelationships(`
      UNWIND $rows AS row
      MATCH (c:Case {case_id: row.case_id})
      MATCH (a:Argument {argument_id: row.argument_id})
      MERGE (c)-[:HAS_ARGUMENT]->(a)
    `, kg.caseArgs);

    await mergeRelationships(`
      UNWIND $rows AS row
      MATCH (a:Argument {argument_id: row.argument_id})
      MATCH (p:Party {party_id: row.party_id})
      MERGE (a)-[:SUBMITTED_BY]->(p)
    `, kg.argSubmit);

    await mergeRelationships(`
      UNWIND $rows AS row
      MATCH (a:Argument {argument_id: row.argument_id})
      MATCH (d:Doctrine {doctrine_id: row.doctrine_id})
      MERGE (a)-[:SUPPORTS_DOCTRINE]->(d)
    `, kg.argDoctrine);

    await mergeRelationships(`
      UNWIND $rows AS row
      MATCH (c:Case {case_id: row.case_id})
      MATCH (r:Ruling {ruling_id: row.ruling_id})
      MERGE (c)-[:HAS_RULING]->(r)
    `, kg.caseRuling);

    await mergeRelationships(`
      UNWIND $rows AS row
      MATCH (r:Ruling {ruling_id: row.ruling_id})
      MATCH (d:Doctrine {doctrine_id: row.doctrine_id})
      MERGE (r)-[:APPLIES_DOCTRINE]->(d)
    `, kg.rulingDoctrine);

    await mergeRelationships(`
      UNWIND $rows AS row
      MATCH (c:Case {case_id: row.case_id})
      MATCH (re:Relief {relief_id: row.relief_id})
      MERGE (c)-[:HAS_RELIEF]->(re)
    `, kg.caseRelief);

    await mergeRelationships(`
      UNWIND $rows AS row
      MATCH (ev:Evidence {document_id: row.document_id})
      MATCH (c:Case {case_id: row.case_id})
      MERGE (ev)-[r:EVIDENCE_IN]->(c)
      SET r.type = row.type, r.description = row.description
    `, kg.evidIn);

  } finally {
    await s.close();
  }
} 