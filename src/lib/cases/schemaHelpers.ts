/**
 * Schema helper utilities for extracting and analyzing schema information
 */

import type { Schema } from '@/types/case-graph'

export function extractNodeTypesFromSchema(schemaPayload: any): string[] {
  const labels = new Set<string>()
  const push = (val: any) => {
    if (typeof val === 'string' && val.trim()) labels.add(val.trim())
  }
  if (!schemaPayload) return []

  // Normalize string payloads
  let normalized: any = schemaPayload
  if (typeof normalized === 'string') {
    try {
      normalized = JSON.parse(normalized)
    } catch {
      // eslint-disable-next-line no-console
      console.warn('Schema was a string but could not be parsed as JSON')
      return []
    }
  }

  // Common shapes: array of { label, attributes, relationships }
  if (Array.isArray(normalized)) {
    for (const item of normalized) {
      if (!item) continue
      if (typeof item === 'string') push(item)
      else if (typeof item === 'object') push(item.label || item.name || item.type)
    }
  }

  // Alternative shapes: object with arrays of labels
  const candidates = [
    normalized?.nodeLabels,
    normalized?.labels,
    normalized?.node_types,
    normalized?.nodeTypes,
    normalized?.nodes,
  ].filter(Boolean)
  for (const arr of candidates) {
    if (Array.isArray(arr)) {
      for (const item of arr) {
        if (typeof item === 'string') push(item)
        else if (item && typeof item === 'object') push(item.label || item.name || item.type)
      }
    } else if (arr && typeof arr === 'object') {
      // Sometimes nodes can be an object map of label -> definition
      for (const key of Object.keys(arr)) push(key)
    }
  }

  return Array.from(labels).sort((a, b) => a.localeCompare(b))
}

export function getPropertySchema(
  path: (string | number)[],
  propName: string,
  graphState: any,
  schema: Schema | null
): any {
  // Determine node label from path (e.g., ['nodes', temp_id] -> find node by temp_id)
  let nodeLabel: string | undefined
  if (path[0] === 'nodes' && typeof path[1] === 'string') {
    const nodeId = path[1]
    const node = graphState.nodes.find((n: any) => n.temp_id === nodeId)
    nodeLabel = node?.label
  }
  
  if (!nodeLabel || !schema) return null
  
  // Find label definition in schema
  const schemaArray = Array.isArray(schema) ? schema : []
  const labelDef = schemaArray.find((s: any) => s?.label === nodeLabel)
  if (!labelDef?.properties) return null
  
  return labelDef.properties[propName]
}

export function getRelationshipPropertySchema(
  sourceLabel: string,
  relLabel: string,
  propName: string,
  schema: Schema | null
): any {
  if (!schema) return null
  const schemaArray = Array.isArray(schema) ? schema : []
  const sourceDef = schemaArray.find((s: any) => s?.label === sourceLabel)
  if (!sourceDef?.relationships?.[relLabel]) return null
  const relDef = sourceDef.relationships[relLabel]
  if (typeof relDef === 'string') return null
  if (typeof relDef !== 'object' || relDef === null) return null
  return (relDef as any).properties?.[propName] || null
}

