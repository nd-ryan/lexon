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
})
