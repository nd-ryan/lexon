/**
 * Tests for cascade delete utilities
 */

import {
  buildUIHierarchy,
  buildCardinalityMap,
  computeCascadePlan,
  checkCascadeMinPerCase,
  applyCascadePlan,
  type UIHierarchyEntry,
  type CascadePlan
} from './cascadeDelete'
import type { Schema } from '@/types/case-graph'

// =============================================================================
// Test fixtures
// =============================================================================

const mockViewsConfig = {
  holdingsCentric: {
    description: 'Test view',
    topLevel: {
      case: { label: 'Case', single: true },
      proceedings: { label: 'Proceeding', via: 'HAS_PROCEEDING', from: 'Case' },
      parties: { label: 'Party', via: 'INVOLVES', from: 'Proceeding' }
    },
    issues: {
      root: 'Issue',
      structure: {
        issue: { self: true },
        ruling: {
          via: 'SETS',
          direction: 'incoming',
          single: true,
          include: {
            arguments: {
              via: 'EVALUATED_IN',
              direction: 'incoming',
              label: 'Argument',
              include: {
                doctrine: {
                  via: 'RELATES_TO_DOCTRINE',
                  label: 'Doctrine'
                }
              }
            }
          }
        }
      }
    }
  }
}

const mockSchema: Schema = [
  {
    label: 'Case',
    case_unique: true,
    min_per_case: 1,
    properties: {},
    relationships: {
      HAS_PROCEEDING: { target: 'Proceeding', cardinality: 'one-to-many' }
    }
  },
  {
    label: 'Proceeding',
    case_unique: true,
    min_per_case: 1,
    properties: {},
    relationships: {
      INVOLVES: { target: 'Party', cardinality: 'one-to-many' }
    }
  },
  {
    label: 'Party',
    case_unique: false,
    min_per_case: 1,
    properties: {},
    relationships: {}
  },
  {
    label: 'Issue',
    case_unique: true,
    min_per_case: 1,
    properties: {},
    relationships: {}
  },
  {
    label: 'Ruling',
    case_unique: true,
    min_per_case: 1,
    properties: {},
    relationships: {
      SETS: { target: 'Issue', cardinality: 'one-to-one' }
    }
  },
  {
    label: 'Argument',
    case_unique: true,
    min_per_case: 1,
    properties: {},
    relationships: {
      EVALUATED_IN: { target: 'Ruling', cardinality: 'many-to-many' },
      RELATES_TO_DOCTRINE: { target: 'Doctrine', cardinality: 'many-to-many' }
    }
  },
  {
    label: 'Doctrine',
    case_unique: false,
    properties: {},
    relationships: {}
  }
]

// =============================================================================
// buildUIHierarchy tests
// =============================================================================

describe('buildUIHierarchy', () => {
  it('extracts topLevel relationships', () => {
    const hierarchy = buildUIHierarchy(mockViewsConfig)
    
    // Case -> Proceeding via HAS_PROCEEDING
    expect(hierarchy).toContainEqual({
      parentLabel: 'Case',
      childLabel: 'Proceeding',
      relationshipLabel: 'HAS_PROCEEDING',
      direction: 'outgoing'
    })
    
    // Proceeding -> Party via INVOLVES
    expect(hierarchy).toContainEqual({
      parentLabel: 'Proceeding',
      childLabel: 'Party',
      relationshipLabel: 'INVOLVES',
      direction: 'outgoing'
    })
  })

  it('extracts nested structure relationships with correct direction', () => {
    const hierarchy = buildUIHierarchy(mockViewsConfig)
    
    // Issue -> Ruling via SETS (incoming means Ruling -> Issue in graph)
    expect(hierarchy).toContainEqual({
      parentLabel: 'Issue',
      childLabel: 'Ruling',
      relationshipLabel: 'SETS',
      direction: 'incoming'
    })
    
    // Ruling -> Argument via EVALUATED_IN (incoming)
    expect(hierarchy).toContainEqual({
      parentLabel: 'Ruling',
      childLabel: 'Argument',
      relationshipLabel: 'EVALUATED_IN',
      direction: 'incoming'
    })
    
    // Argument -> Doctrine via RELATES_TO_DOCTRINE (outgoing by default)
    expect(hierarchy).toContainEqual({
      parentLabel: 'Argument',
      childLabel: 'Doctrine',
      relationshipLabel: 'RELATES_TO_DOCTRINE',
      direction: 'outgoing'
    })
  })

  it('returns empty array for null/undefined config', () => {
    expect(buildUIHierarchy(null)).toEqual([])
    expect(buildUIHierarchy(undefined)).toEqual([])
  })
})

// =============================================================================
// buildCardinalityMap tests
// =============================================================================

describe('buildCardinalityMap', () => {
  it('maps relationships to cardinality info', () => {
    const map = buildCardinalityMap(mockSchema)
    
    expect(map.get('Ruling.SETS')).toEqual({
      sourceLabel: 'Ruling',
      relationshipLabel: 'SETS',
      targetLabel: 'Issue',
      cardinality: 'one-to-one',
      canHaveMultipleTargets: false
    })
    
    expect(map.get('Argument.EVALUATED_IN')).toEqual({
      sourceLabel: 'Argument',
      relationshipLabel: 'EVALUATED_IN',
      targetLabel: 'Ruling',
      cardinality: 'many-to-many',
      canHaveMultipleTargets: true
    })
  })

  it('returns empty map for null schema', () => {
    expect(buildCardinalityMap(null)).toEqual(new Map())
    expect(buildCardinalityMap(undefined)).toEqual(new Map())
  })
})

// =============================================================================
// computeCascadePlan tests
// =============================================================================

describe('computeCascadePlan', () => {
  const uiHierarchy: UIHierarchyEntry[] = [
    { parentLabel: 'Issue', childLabel: 'Ruling', relationshipLabel: 'SETS', direction: 'incoming' },
    { parentLabel: 'Ruling', childLabel: 'Argument', relationshipLabel: 'EVALUATED_IN', direction: 'incoming' },
    { parentLabel: 'Argument', childLabel: 'Doctrine', relationshipLabel: 'RELATES_TO_DOCTRINE', direction: 'outgoing' }
  ]

  const cardinalityMap = buildCardinalityMap(mockSchema)

  it('cascades delete through one-to-one relationships', () => {
    // Deleting Issue should cascade to Ruling (one-to-one)
    const graphState = {
      nodes: [
        { temp_id: 'issue1', label: 'Issue', properties: { label: 'Issue 1' }, status: 'active' },
        { temp_id: 'ruling1', label: 'Ruling', properties: { label: 'Ruling 1' }, status: 'active' }
      ],
      edges: [
        { from: 'ruling1', to: 'issue1', label: 'SETS', status: 'active' }
      ]
    }

    const plan = computeCascadePlan('issue1', graphState, uiHierarchy, cardinalityMap, mockSchema)

    expect(plan.primaryNode.nodeId).toBe('issue1')
    expect(plan.toDelete).toHaveLength(1)
    expect(plan.toDelete[0].nodeId).toBe('ruling1')
    expect(plan.toDetachOnly).toHaveLength(0)
  })

  it('cascades delete through many-to-many when no other parents', () => {
    // Argument -> Ruling is many-to-many, but if Argument has only one Ruling, it cascades
    const graphState = {
      nodes: [
        { temp_id: 'ruling1', label: 'Ruling', properties: {}, status: 'active' },
        { temp_id: 'arg1', label: 'Argument', properties: { label: 'Arg 1' }, status: 'active' }
      ],
      edges: [
        { from: 'arg1', to: 'ruling1', label: 'EVALUATED_IN', status: 'active' }
      ]
    }

    const plan = computeCascadePlan('ruling1', graphState, uiHierarchy, cardinalityMap, mockSchema)

    expect(plan.primaryNode.nodeId).toBe('ruling1')
    expect(plan.toDelete).toContainEqual(expect.objectContaining({ nodeId: 'arg1' }))
    expect(plan.toDetachOnly).toHaveLength(0)
  })

  it('only detaches when many-to-many child has other parents', () => {
    // Argument connected to two Rulings - deleting one Ruling should only detach
    const graphState = {
      nodes: [
        { temp_id: 'ruling1', label: 'Ruling', properties: {}, status: 'active' },
        { temp_id: 'ruling2', label: 'Ruling', properties: {}, status: 'active' },
        { temp_id: 'arg1', label: 'Argument', properties: { label: 'Arg 1' }, status: 'active' }
      ],
      edges: [
        { from: 'arg1', to: 'ruling1', label: 'EVALUATED_IN', status: 'active' },
        { from: 'arg1', to: 'ruling2', label: 'EVALUATED_IN', status: 'active' }
      ]
    }

    const plan = computeCascadePlan('ruling1', graphState, uiHierarchy, cardinalityMap, mockSchema)

    expect(plan.primaryNode.nodeId).toBe('ruling1')
    expect(plan.toDelete).toHaveLength(0)
    expect(plan.toDetachOnly).toContainEqual(expect.objectContaining({ nodeId: 'arg1' }))
  })

  it('detaches shared child when it has other parents (ReliefType scenario)', () => {
    // Relief -> ReliefType is many-to-one (many Reliefs can share one ReliefType)
    // Deleting one Relief should detach ReliefType if another Relief also uses it
    const reliefHierarchy: UIHierarchyEntry[] = [
      { parentLabel: 'Ruling', childLabel: 'Relief', relationshipLabel: 'RESULTS_IN', direction: 'outgoing' },
      { parentLabel: 'Relief', childLabel: 'ReliefType', relationshipLabel: 'IS_TYPE', direction: 'outgoing' }
    ]

    const reliefSchema: Schema = [
      { label: 'Relief', case_unique: true, properties: {}, relationships: { IS_TYPE: { target: 'ReliefType', cardinality: 'many-to-one' } } },
      { label: 'ReliefType', case_unique: false, properties: {}, relationships: {} }
    ]
    const reliefCardinalityMap = buildCardinalityMap(reliefSchema)

    const graphState = {
      nodes: [
        { temp_id: 'relief1', label: 'Relief', properties: {}, status: 'active' },
        { temp_id: 'relief2', label: 'Relief', properties: {}, status: 'active' },
        { temp_id: 'reliefType1', label: 'ReliefType', properties: { type: 'damages' }, status: 'active' }
      ],
      edges: [
        // Both Reliefs point to the same ReliefType
        { from: 'relief1', to: 'reliefType1', label: 'IS_TYPE', status: 'active' },
        { from: 'relief2', to: 'reliefType1', label: 'IS_TYPE', status: 'active' }
      ]
    }

    const plan = computeCascadePlan('relief1', graphState, reliefHierarchy, reliefCardinalityMap, reliefSchema)

    expect(plan.primaryNode.nodeId).toBe('relief1')
    // ReliefType should NOT cascade because relief2 also uses it
    expect(plan.toDelete).toHaveLength(0)
    expect(plan.toDetachOnly).toContainEqual(expect.objectContaining({ nodeId: 'reliefType1' }))
  })

  it('recursively cascades through multiple levels', () => {
    // Issue -> Ruling -> Argument -> Doctrine (full cascade)
    const graphState = {
      nodes: [
        { temp_id: 'issue1', label: 'Issue', properties: { label: 'Issue 1' }, status: 'active' },
        { temp_id: 'ruling1', label: 'Ruling', properties: {}, status: 'active' },
        { temp_id: 'arg1', label: 'Argument', properties: {}, status: 'active' },
        { temp_id: 'doc1', label: 'Doctrine', properties: { name: 'Doctrine 1' }, status: 'active' }
      ],
      edges: [
        { from: 'ruling1', to: 'issue1', label: 'SETS', status: 'active' },
        { from: 'arg1', to: 'ruling1', label: 'EVALUATED_IN', status: 'active' },
        { from: 'arg1', to: 'doc1', label: 'RELATES_TO_DOCTRINE', status: 'active' }
      ]
    }

    const plan = computeCascadePlan('issue1', graphState, uiHierarchy, cardinalityMap, mockSchema)

    expect(plan.primaryNode.nodeId).toBe('issue1')
    
    // Ruling cascades (one-to-one)
    expect(plan.toDelete).toContainEqual(expect.objectContaining({ nodeId: 'ruling1' }))
    
    // Argument cascades (only one ruling)
    expect(plan.toDelete).toContainEqual(expect.objectContaining({ nodeId: 'arg1' }))
    
    // Doctrine cascades (only one argument)
    expect(plan.toDelete).toContainEqual(expect.objectContaining({ nodeId: 'doc1' }))
  })

  it('sets caseUnique correctly from schema', () => {
    const graphState = {
      nodes: [
        { temp_id: 'arg1', label: 'Argument', properties: {}, status: 'active' },
        { temp_id: 'doc1', label: 'Doctrine', properties: { name: 'Doctrine 1' }, status: 'active' }
      ],
      edges: [
        { from: 'arg1', to: 'doc1', label: 'RELATES_TO_DOCTRINE', status: 'active' }
      ]
    }

    const plan = computeCascadePlan('arg1', graphState, uiHierarchy, cardinalityMap, mockSchema)

    expect(plan.primaryNode.caseUnique).toBe(true) // Argument is case_unique
    expect(plan.toDelete[0].caseUnique).toBe(false) // Doctrine is not case_unique
  })

  it('collects all edges to remove', () => {
    const graphState = {
      nodes: [
        { temp_id: 'issue1', label: 'Issue', properties: {}, status: 'active' },
        { temp_id: 'ruling1', label: 'Ruling', properties: {}, status: 'active' }
      ],
      edges: [
        { from: 'ruling1', to: 'issue1', label: 'SETS', status: 'active' }
      ]
    }

    const plan = computeCascadePlan('issue1', graphState, uiHierarchy, cardinalityMap, mockSchema)

    expect(plan.edgesToRemove).toContainEqual({ from: 'ruling1', to: 'issue1', label: 'SETS' })
  })
})

// =============================================================================
// checkCascadeMinPerCase tests
// =============================================================================

describe('checkCascadeMinPerCase', () => {
  // Simplified schema for these tests (no min_per_case on Case/Proceeding/Party)
  const minPerCaseSchema: Schema = [
    { label: 'Case', case_unique: true, properties: {}, relationships: {} },
    { label: 'Issue', case_unique: true, min_per_case: 1, properties: {}, relationships: {} },
    { label: 'Ruling', case_unique: true, min_per_case: 1, properties: {}, relationships: {} }
  ]

  it('returns valid when no min_per_case violations', () => {
    const graphState = {
      nodes: [
        { temp_id: 'case1', label: 'Case', status: 'active' },
        { temp_id: 'issue1', label: 'Issue', status: 'active' },
        { temp_id: 'issue2', label: 'Issue', status: 'active' },
        { temp_id: 'ruling1', label: 'Ruling', status: 'active' },
        { temp_id: 'ruling2', label: 'Ruling', status: 'active' }
      ],
      edges: []
    }

    const cascadePlan: CascadePlan = {
      primaryNode: { nodeId: 'issue1', label: 'Issue', name: 'Issue 1', caseUnique: true },
      toDelete: [{ nodeId: 'ruling1', label: 'Ruling', name: 'Ruling 1', caseUnique: true }],
      toDetachOnly: [],
      edgesToRemove: []
    }

    const result = checkCascadeMinPerCase(graphState, cascadePlan, minPerCaseSchema)

    expect(result.valid).toBe(true)
  })

  it('returns invalid when min_per_case would be violated', () => {
    // Only one Issue, deleting it violates min_per_case: 1
    const graphState = {
      nodes: [
        { temp_id: 'case1', label: 'Case', status: 'active' },
        { temp_id: 'issue1', label: 'Issue', status: 'active' },
        { temp_id: 'ruling1', label: 'Ruling', status: 'active' },
        { temp_id: 'ruling2', label: 'Ruling', status: 'active' }
      ],
      edges: []
    }

    const cascadePlan: CascadePlan = {
      primaryNode: { nodeId: 'issue1', label: 'Issue', name: 'Issue 1', caseUnique: true },
      toDelete: [{ nodeId: 'ruling1', label: 'Ruling', name: 'Ruling 1', caseUnique: true }],
      toDetachOnly: [],
      edgesToRemove: []
    }

    const result = checkCascadeMinPerCase(graphState, cascadePlan, minPerCaseSchema)

    expect(result.valid).toBe(false)
    expect(result.reason).toContain('Issue')
    expect(result.violations).toContainEqual(expect.objectContaining({ label: 'Issue' }))
  })

  it('ignores already deleted nodes in count', () => {
    const graphState = {
      nodes: [
        { temp_id: 'case1', label: 'Case', status: 'active' },
        { temp_id: 'issue1', label: 'Issue', status: 'deleted' }, // Already deleted
        { temp_id: 'issue2', label: 'Issue', status: 'active' },
        { temp_id: 'issue3', label: 'Issue', status: 'active' },
        { temp_id: 'ruling1', label: 'Ruling', status: 'active' }
      ],
      edges: []
    }

    const cascadePlan: CascadePlan = {
      primaryNode: { nodeId: 'issue2', label: 'Issue', name: 'Issue 2', caseUnique: true },
      toDelete: [],
      toDetachOnly: [],
      edgesToRemove: []
    }

    // Should be valid because issue3 remains
    const result = checkCascadeMinPerCase(graphState, cascadePlan, minPerCaseSchema)
    expect(result.valid).toBe(true)
  })
})

// =============================================================================
// applyCascadePlan tests
// =============================================================================

describe('applyCascadePlan', () => {
  it('marks primary node as deleted', () => {
    const graphState = {
      nodes: [
        { temp_id: 'n1', label: 'Issue', status: 'active' }
      ],
      edges: []
    }

    const plan: CascadePlan = {
      primaryNode: { nodeId: 'n1', label: 'Issue', name: 'Issue 1', caseUnique: true },
      toDelete: [],
      toDetachOnly: [],
      edgesToRemove: []
    }

    const result = applyCascadePlan(graphState, plan)

    expect(result.nodes.find(n => n.temp_id === 'n1')?.status).toBe('deleted')
  })

  it('marks cascaded nodes as deleted', () => {
    const graphState = {
      nodes: [
        { temp_id: 'n1', label: 'Issue', status: 'active' },
        { temp_id: 'n2', label: 'Ruling', status: 'active' }
      ],
      edges: []
    }

    const plan: CascadePlan = {
      primaryNode: { nodeId: 'n1', label: 'Issue', name: 'Issue 1', caseUnique: true },
      toDelete: [{ nodeId: 'n2', label: 'Ruling', name: 'Ruling 1', caseUnique: true }],
      toDetachOnly: [],
      edgesToRemove: []
    }

    const result = applyCascadePlan(graphState, plan)

    expect(result.nodes.find(n => n.temp_id === 'n1')?.status).toBe('deleted')
    expect(result.nodes.find(n => n.temp_id === 'n2')?.status).toBe('deleted')
  })

  it('marks detach-only nodes as deleted (they are removed from this case)', () => {
    const graphState = {
      nodes: [
        { temp_id: 'n1', label: 'Argument', status: 'active' },
        { temp_id: 'n2', label: 'Doctrine', status: 'active' }
      ],
      edges: []
    }

    const plan: CascadePlan = {
      primaryNode: { nodeId: 'n1', label: 'Argument', name: 'Arg 1', caseUnique: true },
      toDelete: [],
      toDetachOnly: [{ nodeId: 'n2', label: 'Doctrine', name: 'Doctrine 1', caseUnique: false }],
      edgesToRemove: []
    }

    const result = applyCascadePlan(graphState, plan)

    expect(result.nodes.find(n => n.temp_id === 'n2')?.status).toBe('deleted')
  })

  it('marks specified edges as deleted', () => {
    const graphState = {
      nodes: [
        { temp_id: 'n1', label: 'Issue', status: 'active' },
        { temp_id: 'n2', label: 'Ruling', status: 'active' }
      ],
      edges: [
        { from: 'n2', to: 'n1', label: 'SETS', status: 'active' }
      ]
    }

    const plan: CascadePlan = {
      primaryNode: { nodeId: 'n1', label: 'Issue', name: 'Issue 1', caseUnique: true },
      toDelete: [],
      toDetachOnly: [],
      edgesToRemove: [{ from: 'n2', to: 'n1', label: 'SETS' }]
    }

    const result = applyCascadePlan(graphState, plan)

    expect(result.edges[0].status).toBe('deleted')
  })

  it('marks edges connected to deleted nodes as deleted', () => {
    const graphState = {
      nodes: [
        { temp_id: 'n1', label: 'Issue', status: 'active' },
        { temp_id: 'n2', label: 'Ruling', status: 'active' }
      ],
      edges: [
        { from: 'n2', to: 'n1', label: 'SETS', status: 'active' },
        { from: 'n1', to: 'n3', label: 'OTHER', status: 'active' }
      ]
    }

    const plan: CascadePlan = {
      primaryNode: { nodeId: 'n1', label: 'Issue', name: 'Issue 1', caseUnique: true },
      toDelete: [],
      toDetachOnly: [],
      edgesToRemove: []
    }

    const result = applyCascadePlan(graphState, plan)

    // Both edges should be deleted because they touch n1
    expect(result.edges.every(e => e.status === 'deleted')).toBe(true)
  })

  it('preserves unaffected nodes and edges', () => {
    const graphState = {
      nodes: [
        { temp_id: 'n1', label: 'Issue', status: 'active' },
        { temp_id: 'n2', label: 'Party', status: 'active' }
      ],
      edges: [
        { from: 'n2', to: 'n3', label: 'INVOLVES', status: 'active' }
      ]
    }

    const plan: CascadePlan = {
      primaryNode: { nodeId: 'n1', label: 'Issue', name: 'Issue 1', caseUnique: true },
      toDelete: [],
      toDetachOnly: [],
      edgesToRemove: []
    }

    const result = applyCascadePlan(graphState, plan)

    expect(result.nodes.find(n => n.temp_id === 'n2')?.status).toBe('active')
    expect(result.edges[0].status).toBe('active')
  })
})

// =============================================================================
// Integration test: Full cascade scenario
// =============================================================================

describe('Full cascade integration', () => {
  // Schema with relaxed min_per_case for integration test
  const integrationSchema: Schema = [
    { label: 'Case', case_unique: true, properties: {}, relationships: {} },
    { label: 'Issue', case_unique: true, min_per_case: 1, properties: {}, relationships: {} },
    { label: 'Ruling', case_unique: true, min_per_case: 1, properties: {}, relationships: { SETS: { target: 'Issue', cardinality: 'one-to-one' } } },
    { label: 'Argument', case_unique: true, min_per_case: 1, properties: {}, relationships: { EVALUATED_IN: { target: 'Ruling', cardinality: 'many-to-many' }, RELATES_TO_DOCTRINE: { target: 'Doctrine', cardinality: 'many-to-many' } } },
    { label: 'Doctrine', case_unique: false, properties: {}, relationships: {} }
  ]

  it('handles deleting an Issue with full nested hierarchy', () => {
    const uiHierarchy = buildUIHierarchy(mockViewsConfig)
    const cardinalityMap = buildCardinalityMap(integrationSchema)

    const graphState = {
      nodes: [
        { temp_id: 'case1', label: 'Case', properties: { name: 'Test Case' }, status: 'active' },
        { temp_id: 'issue1', label: 'Issue', properties: { label: 'Issue 1' }, status: 'active' },
        { temp_id: 'issue2', label: 'Issue', properties: { label: 'Issue 2' }, status: 'active' },
        { temp_id: 'ruling1', label: 'Ruling', properties: {}, status: 'active' },
        { temp_id: 'ruling2', label: 'Ruling', properties: {}, status: 'active' },
        { temp_id: 'arg1', label: 'Argument', properties: {}, status: 'active' },
        { temp_id: 'arg2', label: 'Argument', properties: {}, status: 'active' },
        { temp_id: 'doc1', label: 'Doctrine', properties: { name: 'Doctrine 1' }, status: 'active' }
      ],
      edges: [
        { from: 'ruling1', to: 'issue1', label: 'SETS', status: 'active' },
        { from: 'ruling2', to: 'issue2', label: 'SETS', status: 'active' },
        { from: 'arg1', to: 'ruling1', label: 'EVALUATED_IN', status: 'active' },
        { from: 'arg2', to: 'ruling2', label: 'EVALUATED_IN', status: 'active' },
        { from: 'arg1', to: 'doc1', label: 'RELATES_TO_DOCTRINE', status: 'active' },
        { from: 'arg2', to: 'doc1', label: 'RELATES_TO_DOCTRINE', status: 'active' }
      ]
    }

    // Delete issue1
    const plan = computeCascadePlan('issue1', graphState, uiHierarchy, cardinalityMap, integrationSchema)

    // Primary node
    expect(plan.primaryNode.nodeId).toBe('issue1')

    // Ruling1 should cascade (one-to-one with issue1)
    expect(plan.toDelete).toContainEqual(expect.objectContaining({ nodeId: 'ruling1' }))

    // Arg1 should cascade (only connected to ruling1)
    expect(plan.toDelete).toContainEqual(expect.objectContaining({ nodeId: 'arg1' }))

    // Doc1 should NOT cascade - it's still connected to arg2
    expect(plan.toDelete).not.toContainEqual(expect.objectContaining({ nodeId: 'doc1' }))
    expect(plan.toDetachOnly).toContainEqual(expect.objectContaining({ nodeId: 'doc1' }))

    // issue2, ruling2, arg2 should not be affected
    expect(plan.toDelete.map(n => n.nodeId)).not.toContain('issue2')
    expect(plan.toDelete.map(n => n.nodeId)).not.toContain('ruling2')
    expect(plan.toDelete.map(n => n.nodeId)).not.toContain('arg2')

    // Validation should pass (issue2, ruling2, arg2 remain)
    const validation = checkCascadeMinPerCase(graphState, plan, integrationSchema)
    expect(validation.valid).toBe(true)

    // Apply and verify
    const result = applyCascadePlan(graphState, plan)
    
    expect(result.nodes.find(n => n.temp_id === 'issue1')?.status).toBe('deleted')
    expect(result.nodes.find(n => n.temp_id === 'ruling1')?.status).toBe('deleted')
    expect(result.nodes.find(n => n.temp_id === 'arg1')?.status).toBe('deleted')
    expect(result.nodes.find(n => n.temp_id === 'doc1')?.status).toBe('deleted') // detach = deleted from case
    expect(result.nodes.find(n => n.temp_id === 'issue2')?.status).toBe('active')
    expect(result.nodes.find(n => n.temp_id === 'ruling2')?.status).toBe('active')
    expect(result.nodes.find(n => n.temp_id === 'arg2')?.status).toBe('active')
  })
})

