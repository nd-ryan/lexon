import React from 'react'
import { validateRequiredFields } from './validation'
import type { Schema } from '@/types/case-graph'
import type { GraphState } from '@/hooks/cases/useGraphState'

const schema: Schema = [
  {
    label: 'Person',
    properties: {
      name: { ui: { required: true, label: 'Name' } }
    },
    relationships: {
      KNOWS: {
        target: 'Person',
        properties: {
          since: { ui: { required: true, label: 'Since' } }
        }
      }
    }
  }
]

const baseGraph: GraphState = {
  nodes: [
    {
      temp_id: 'n1',
      label: 'Person',
      properties: { name: '' },
      status: 'active',
      source: 'user-created'
    },
    {
      temp_id: 'n2',
      label: 'Person',
      properties: { name: 'Alice' },
      status: 'active',
      source: 'user-created'
    }
  ],
  edges: [
    {
      from: 'n1',
      to: 'n2',
      label: 'KNOWS',
      properties: {},
      status: 'active'
    }
  ]
}

describe('validateRequiredFields', () => {
  it('flags required node and relationship properties', () => {
    const pendingEditsRef = { current: {} } as React.MutableRefObject<Record<string, any>>

    const result = validateRequiredFields(baseGraph, schema, pendingEditsRef)

    expect(result.isValid).toBe(false)
    expect(result.errors).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ propertyName: 'name', nodeId: 'n1' }),
        expect.objectContaining({ propertyName: 'since', edgeLabel: 'KNOWS' })
      ])
    )
  })

  it('applies pending edits before validation', () => {
    const pendingEditsRef = {
      current: {
        'nodes.n1.properties.name': 'Bob',
        'nodes.n1.properties.extra': 'ignored'
      }
    } as React.MutableRefObject<Record<string, any>>

    const result = validateRequiredFields(baseGraph, schema, pendingEditsRef)

    expect(result.errors.some(e => e.propertyName === 'name')).toBe(false)
  })

  it('enforces min_per_case on connected nodes (connected-only rule)', () => {
    const schemaWithMin: Schema = [
      {
        label: 'Case',
        min_per_case: 1,
        properties: {
          name: { ui: { required: true, label: 'Name' } }
        }
      },
      {
        label: 'Party',
        min_per_case: 1,
        properties: {
          name: { ui: { required: false, label: 'Name' } }
        }
      }
    ]

    const graph: GraphState = {
      nodes: [
        {
          temp_id: 'case1',
          label: 'Case',
          properties: { name: 'My Case' },
          status: 'active',
          source: 'user-created'
        }
        // Note: no Party node connected
      ],
      edges: []
    }

    const pendingEditsRef = { current: {} } as React.MutableRefObject<Record<string, any>>
    const result = validateRequiredFields(graph, schemaWithMin, pendingEditsRef)
    expect(result.isValid).toBe(false)
    expect(result.errors).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ propertyName: 'min_per_case', nodeLabel: 'Party' })
      ])
    )
  })

  it('treats disconnected nodes as not satisfying min_per_case (connected-only rule)', () => {
    const schemaWithMin: Schema = [
      { label: 'Case', min_per_case: 1, properties: { name: { ui: { required: true, label: 'Name' } } } },
      { label: 'Party', min_per_case: 1, properties: { name: { ui: { required: false, label: 'Name' } } } }
    ]

    // Party exists but is not connected to Case via any edge.
    const graph: GraphState = {
      nodes: [
        { temp_id: 'case1', label: 'Case', properties: { name: 'My Case' }, status: 'active', source: 'user-created' },
        { temp_id: 'p1', label: 'Party', properties: { name: 'Alice' }, status: 'active', source: 'user-created' }
      ],
      edges: []
    }

    const pendingEditsRef = { current: {} } as React.MutableRefObject<Record<string, any>>
    const result = validateRequiredFields(graph, schemaWithMin, pendingEditsRef)
    expect(result.isValid).toBe(false)
    expect(result.errors.some(e => e.propertyName === 'min_per_case' && e.nodeLabel === 'Party')).toBe(true)
  })

  it('passes min_per_case when nodes are connected to the case graph', () => {
    const schemaWithMin: Schema = [
      { label: 'Case', min_per_case: 1, properties: { name: { ui: { required: true, label: 'Name' } } } },
      { label: 'Party', min_per_case: 1, properties: { name: { ui: { required: false, label: 'Name' } } } }
    ]

    const graph: GraphState = {
      nodes: [
        { temp_id: 'case1', label: 'Case', properties: { name: 'My Case' }, status: 'active', source: 'user-created' },
        { temp_id: 'p1', label: 'Party', properties: { name: 'Alice' }, status: 'active', source: 'user-created' }
      ],
      edges: [
        { from: 'p1', to: 'case1', label: 'CONTAINS', status: 'active', properties: {} }
      ] as any
    }

    const pendingEditsRef = { current: {} } as React.MutableRefObject<Record<string, any>>
    const result = validateRequiredFields(graph, schemaWithMin, pendingEditsRef)
    expect(result.errors.some(e => e.propertyName === 'min_per_case')).toBe(false)
  })
})
