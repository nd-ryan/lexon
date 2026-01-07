MATCH (c:Case {case_id: $caseId})
OPTIONAL MATCH (d:Domain)-[:CONTAINS]->(c)

CALL (c) {
  WITH c
  MATCH (c)-[:HAS_PROCEEDING]->(p:Proceeding)

  OPTIONAL MATCH (p)-[:HEARD_IN]->(f:Forum)
  OPTIONAL MATCH (f)-[:PART_OF]->(j:Jurisdiction)

  CALL (p) {
    WITH p
    OPTIONAL MATCH (p)-[inv:INVOLVES]->(party:Party)
    WITH inv, party
    WHERE party IS NOT NULL
    RETURN collect(DISTINCT {
      role: inv.role,
      party: apoc.map.removeKeys(properties(party), [k IN keys(party) WHERE k ENDS WITH "_embedding"])
    }) AS parties
  }

  CALL (p) {
    WITH p
    OPTIONAL MATCH (p)-[:ADDRESSES]->(i:Issue)
    WITH DISTINCT i
    WHERE i IS NOT NULL
    
    // Collect related nodes using subqueries with DISTINCT
    CALL (i) {
      WITH i
      OPTIONAL MATCH (i)-[:RELATES_TO_DOCTRINE]->(doc:Doctrine)
      WITH DISTINCT doc
      WHERE doc IS NOT NULL
      RETURN collect(apoc.map.removeKeys(properties(doc), [k IN keys(doc) WHERE k ENDS WITH "_embedding"])) AS doctrines
    }
    CALL (i) {
      WITH i
      OPTIONAL MATCH (i)-[:RELATES_TO_POLICY]->(po:Policy)
      WITH DISTINCT po
      WHERE po IS NOT NULL
      RETURN collect(apoc.map.removeKeys(properties(po), [k IN keys(po) WHERE k ENDS WITH "_embedding"])) AS policies
    }
    CALL (i) {
      WITH i
      OPTIONAL MATCH (i)-[:RELATES_TO_FACTPATTERN]->(fp:FactPattern)
      WITH DISTINCT fp
      WHERE fp IS NOT NULL
      RETURN collect(apoc.map.removeKeys(properties(fp), [k IN keys(fp) WHERE k ENDS WITH "_embedding"])) AS fact_patterns
    }
    
    RETURN collect(
      apoc.map.merge(
        apoc.map.removeKeys(properties(i), [k IN keys(i) WHERE k ENDS WITH "_embedding"]),
        {
          doctrines: doctrines,
          policies: policies,
          fact_patterns: fact_patterns
        }
      )
    ) AS issues
  }

  CALL (p) {
    WITH p
    OPTIONAL MATCH (p)-[:RESULTS_IN]->(r:Ruling)
    WITH DISTINCT r
    WHERE r IS NOT NULL
    
    // Get all issues this ruling sets (can be multiple)
    OPTIONAL MATCH (r)-[s:SETS]->(setIssue:Issue)
    WITH r, collect(CASE WHEN setIssue IS NULL THEN NULL ELSE {
      props: apoc.map.removeKeys(properties(setIssue), [k IN keys(setIssue) WHERE k ENDS WITH "_embedding"]),
      in_favor: s.in_favor
    } END) AS setsIssuesData
    
    // Collect reliefs
    CALL (r) {
      WITH r
      OPTIONAL MATCH (r)-[rr:RESULTS_IN]->(rel:Relief)
      WITH DISTINCT rel, rr
      WHERE rel IS NOT NULL
      OPTIONAL MATCH (rel)-[:IS_TYPE]->(rt:ReliefType)
      RETURN collect(
        apoc.map.merge(
          apoc.map.removeKeys(properties(rel), [k IN keys(rel) WHERE k ENDS WITH "_embedding"]),
          {
            relief_status: rr.relief_status,
            relief_type: CASE WHEN rt IS NULL THEN NULL ELSE apoc.map.removeKeys(properties(rt), [k IN keys(rt) WHERE k ENDS WITH "_embedding"]) END
          }
        )
      ) AS reliefs
    }
    
    // Collect laws
    CALL (r) {
      WITH r
      OPTIONAL MATCH (r)-[:RELIES_ON_LAW]->(law:Law)
      WITH DISTINCT law
      WHERE law IS NOT NULL
      RETURN collect(apoc.map.removeKeys(properties(law), [k IN keys(law) WHERE k ENDS WITH "_embedding"])) AS laws
    }
    
    // Collect arguments with their nested entities
    CALL (r) {
      WITH r
      OPTIONAL MATCH (r)<-[ev:EVALUATED_IN]-(a:Argument)
      WITH DISTINCT a, ev
      WHERE a IS NOT NULL
      
      // Get doctrines for this argument
      CALL (a) {
        WITH a
        OPTIONAL MATCH (a)-[:RELATES_TO_DOCTRINE]->(doc:Doctrine)
        WITH DISTINCT doc
        WHERE doc IS NOT NULL
        RETURN collect(apoc.map.removeKeys(properties(doc), [k IN keys(doc) WHERE k ENDS WITH "_embedding"])) AS argDoctrines
      }
      // Get policies for this argument
      CALL (a) {
        WITH a
        OPTIONAL MATCH (a)-[:RELATES_TO_POLICY]->(po:Policy)
        WITH DISTINCT po
        WHERE po IS NOT NULL
        RETURN collect(apoc.map.removeKeys(properties(po), [k IN keys(po) WHERE k ENDS WITH "_embedding"])) AS argPolicies
      }
      // Get fact patterns for this argument
      CALL (a) {
        WITH a
        OPTIONAL MATCH (a)-[:RELATES_TO_FACTPATTERN]->(fp:FactPattern)
        WITH DISTINCT fp
        WHERE fp IS NOT NULL
        RETURN collect(apoc.map.removeKeys(properties(fp), [k IN keys(fp) WHERE k ENDS WITH "_embedding"])) AS argFactPatterns
      }
      
      RETURN collect(
        apoc.map.merge(
          apoc.map.removeKeys(properties(a), [k IN keys(a) WHERE k ENDS WITH "_embedding"]),
          {
            status: ev.status,
            doctrines: argDoctrines,
            policies: argPolicies,
            fact_patterns: argFactPatterns
          }
        )
      ) AS arguments
    }
    
    RETURN collect(
      apoc.map.merge(
        apoc.map.removeKeys(properties(r), [k IN keys(r) WHERE k ENDS WITH "_embedding"]),
        {
          sets_issues: [x IN setsIssuesData WHERE x IS NOT NULL | apoc.map.merge(x.props, {in_favor: x.in_favor})],
          reliefs: reliefs,
          laws: laws,
          arguments: arguments
        }
      )
    ) AS rulings
  }

  RETURN collect(
    apoc.map.merge(
      apoc.map.removeKeys(properties(p), [k IN keys(p) WHERE k ENDS WITH "_embedding"]),
      {
        forum:        CASE WHEN f IS NULL THEN NULL ELSE apoc.map.removeKeys(properties(f), [k IN keys(f) WHERE k ENDS WITH "_embedding"]) END,
        jurisdiction: CASE WHEN j IS NULL THEN NULL ELSE apoc.map.removeKeys(properties(j), [k IN keys(j) WHERE k ENDS WITH "_embedding"]) END,
        parties:      [x IN parties WHERE x.party IS NOT NULL],
        issues:       [x IN issues  WHERE x IS NOT NULL],
        rulings:      [x IN rulings WHERE x IS NOT NULL]
      }
    )
  ) AS proceedings
}

RETURN apoc.map.merge(
  apoc.map.removeKeys(properties(c), [k IN keys(c) WHERE k ENDS WITH "_embedding"]),
  {
    domain:      CASE WHEN d IS NULL THEN NULL ELSE apoc.map.removeKeys(properties(d), [k IN keys(d) WHERE k ENDS WITH "_embedding"]) END,
    proceedings: proceedings
  }
) AS case_data;

