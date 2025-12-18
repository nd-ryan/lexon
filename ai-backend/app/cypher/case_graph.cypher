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
    RETURN collect(DISTINCT {
      role: inv.role,
      party: apoc.map.removeKeys(properties(party), [k IN keys(party) WHERE k ENDS WITH "_embedding"])
    }) AS parties
  }

  CALL (p) {
    WITH p
    OPTIONAL MATCH (p)-[:ADDRESSES]->(i:Issue)
    WITH DISTINCT i
    RETURN collect(
      CASE WHEN i IS NULL THEN NULL ELSE
        apoc.map.merge(
          apoc.map.removeKeys(properties(i), [k IN keys(i) WHERE k ENDS WITH "_embedding"]),
          {
            doctrines: [
              (i)-[:RELATES_TO_DOCTRINE]->(doc:Doctrine) |
              apoc.map.removeKeys(properties(doc), [k IN keys(doc) WHERE k ENDS WITH "_embedding"])
            ],
            policies: [
              (i)-[:RELATES_TO_POLICY]->(po:Policy) |
              apoc.map.removeKeys(properties(po), [k IN keys(po) WHERE k ENDS WITH "_embedding"])
            ],
            fact_patterns: [
              (i)-[:RELATES_TO_FACTPATTERN]->(fp:FactPattern) |
              apoc.map.removeKeys(properties(fp), [k IN keys(fp) WHERE k ENDS WITH "_embedding"])
            ]
          }
        )
      END
    ) AS issues
  }

  CALL (p) {
    WITH p
    OPTIONAL MATCH (p)-[:RESULTS_IN]->(r:Ruling)
    WITH DISTINCT r
    RETURN collect(
      CASE WHEN r IS NULL THEN NULL ELSE
        apoc.map.merge(
          apoc.map.removeKeys(properties(r), [k IN keys(r) WHERE k ENDS WITH "_embedding"]),
          {
            sets_issue: head([
              (r)-[s:SETS]->(i:Issue) |
              apoc.map.merge(
                apoc.map.removeKeys(properties(i), [k IN keys(i) WHERE k ENDS WITH "_embedding"]),
                { in_favor: s.in_favor }
              )
            ]),

            reliefs: [
              (r)-[rr:RESULTS_IN]->(rel:Relief) |
              apoc.map.merge(
                apoc.map.removeKeys(properties(rel), [k IN keys(rel) WHERE k ENDS WITH "_embedding"]),
                {
                  relief_status: rr.relief_status,
                  relief_type: head([
                    (rel)-[:IS_TYPE]->(rt:ReliefType) |
                    apoc.map.removeKeys(properties(rt), [k IN keys(rt) WHERE k ENDS WITH "_embedding"])
                  ])
                }
              )
            ],

            laws: [
              (r)-[:RELIES_ON_LAW]->(law:Law) |
              apoc.map.removeKeys(properties(law), [k IN keys(law) WHERE k ENDS WITH "_embedding"])
            ],

            arguments: [
              (r)<-[ev:EVALUATED_IN]-(a:Argument) |
              apoc.map.merge(
                apoc.map.removeKeys(properties(a), [k IN keys(a) WHERE k ENDS WITH "_embedding"]),
                {
                  status: ev.status,
                  doctrines: [
                    (a)-[:RELATES_TO_DOCTRINE]->(doc:Doctrine) |
                    apoc.map.removeKeys(properties(doc), [k IN keys(doc) WHERE k ENDS WITH "_embedding"])
                  ],
                  policies: [
                    (a)-[:RELATES_TO_POLICY]->(po:Policy) |
                    apoc.map.removeKeys(properties(po), [k IN keys(po) WHERE k ENDS WITH "_embedding"])
                  ],
                  fact_patterns: [
                    (a)-[:RELATES_TO_FACTPATTERN]->(fp:FactPattern) |
                    apoc.map.removeKeys(properties(fp), [k IN keys(fp) WHERE k ENDS WITH "_embedding"])
                  ]
                }
              )
            ]
          }
        )
      END
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


