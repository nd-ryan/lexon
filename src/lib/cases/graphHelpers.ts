/**
 * Graph manipulation and analysis utilities
 */

import type { GraphNode } from '@/types/case-graph'

export function findDescendants(nodeId: string, edges: any[]): string[] {
  const descendants: string[] = []
  const visited = new Set<string>()
  
  const traverse = (currentId: string) => {
    if (visited.has(currentId)) return
    visited.add(currentId)
    
    // Find all outgoing edges from this node
    const children = edges
      .filter((e: any) => e.from === currentId)
      .map((e: any) => e.to)
    
    children.forEach(childId => {
      descendants.push(childId)
      traverse(childId) // Recursively find grandchildren
    })
  }
  
  traverse(nodeId)
  return descendants
}

export function filterActiveNodes(nodes: any[], deletedNodeIds: Set<string>, orphanedNodeIds: Set<string>): any[] {
  if (!Array.isArray(nodes)) return []
  return nodes.filter((n: any) => 
    n?.temp_id && !deletedNodeIds.has(n.temp_id) && !orphanedNodeIds.has(n.temp_id)
  )
}

export function buildGlobalNodeNumbering(graphState: any, displayData: any): Record<string, Record<string, number>> {
  const numbering: Record<string, Record<string, number>> = {}
  const activeNodes = graphState.nodes.filter((n: any) => n.status === 'active')
  
  // Group nodes by label
  const nodesByLabel: Record<string, Array<{ temp_id: string, firstSeen: number }>> = {}
  
  // Walk through display data to collect nodes in order they appear
  const seenNodes = new Set<string>()
  const nodeOrder: Array<{ temp_id: string, label: string }> = []
  
  const collectNodes = (data: any) => {
    if (!data || typeof data !== 'object') return
    
    if (data.temp_id && !seenNodes.has(data.temp_id)) {
      const node = activeNodes.find((n: any) => n.temp_id === data.temp_id)
      if (node) {
        seenNodes.add(data.temp_id)
        nodeOrder.push({ temp_id: data.temp_id, label: node.label })
      }
    }
    
    // Recurse through object/array properties
    if (Array.isArray(data)) {
      data.forEach(collectNodes)
    } else if (typeof data === 'object') {
      Object.values(data).forEach(collectNodes)
    }
  }
  
  // Collect from display data
  if (displayData) {
    collectNodes(displayData)
  }
  
  // Build numbering from collected order
  nodeOrder.forEach(({ temp_id, label }) => {
    if (!nodesByLabel[label]) {
      nodesByLabel[label] = []
    }
    nodesByLabel[label].push({ temp_id, firstSeen: nodesByLabel[label].length })
  })
  
  // Create final numbering map
  Object.entries(nodesByLabel).forEach(([label, nodes]) => {
    numbering[label] = {}
    nodes.forEach((node, idx) => {
      numbering[label][node.temp_id] = idx + 1
    })
  })
  
  return numbering
}

export function detectReusedNodes(graphState: any): Set<string> {
  const reused = new Set<string>()
  const nodeParents: Record<string, Set<string>> = {}
  
  // Count unique parents for each node (incoming edges)
  graphState.edges
    .filter((e: any) => e.status === 'active')
    .forEach((edge: any) => {
      if (!nodeParents[edge.to]) {
        nodeParents[edge.to] = new Set()
      }
      nodeParents[edge.to].add(edge.from)
    })
  
  // Mark nodes with multiple parents as reused
  Object.entries(nodeParents).forEach(([nodeId, parents]) => {
    if (parents.size > 1) {
      reused.add(nodeId)
    }
  })
  
  // Also detect nodes with multiple outgoing edges of specific relationship types
  // that indicate reuse when they appear multiple times (e.g., Arguments with 
  // multiple EVALUATED_IN edges to different Rulings)
  // Note: We exclude normal one-to-many relationships like INVOLVES, HEARD_IN, etc.
  const reuseIndicatingRelationships = ['EVALUATED_IN'] // Add other relationship types that indicate reuse
  
  const nodeOutgoingByRel: Record<string, Record<string, Set<string>>> = {}
  
  graphState.edges
    .filter((e: any) => e.status === 'active' && reuseIndicatingRelationships.includes(e.label))
    .forEach((edge: any) => {
      if (!nodeOutgoingByRel[edge.from]) {
        nodeOutgoingByRel[edge.from] = {}
      }
      if (!nodeOutgoingByRel[edge.from][edge.label]) {
        nodeOutgoingByRel[edge.from][edge.label] = new Set()
      }
      nodeOutgoingByRel[edge.from][edge.label].add(edge.to)
    })
  
  // Mark nodes that have multiple targets for reuse-indicating relationship types as reused
  Object.entries(nodeOutgoingByRel).forEach(([nodeId, relTargets]) => {
    Object.entries(relTargets).forEach(([relLabel, targets]) => {
      if (targets.size > 1) {
        reused.add(nodeId)
      }
    })
  })
  
  return reused
}

export function buildNodeOptions(nodesArray: GraphNode[], pickNodeName: (node: GraphNode) => string | undefined) {
  return (nodesArray || [])
    .map((n) => {
      const id = n?.temp_id
      if (!id) return null
      const label = n?.label ? String(n.label) : String(id)
      const name = pickNodeName(n) || String(id)
      const display = `[${label}] ${name}`
      return { id: String(id), display }
    })
    .filter(Boolean) as { id: string; display: string }[]
}

export function getNodeConnections(nodeId: string, graphState: any) {
  const edges = graphState.edges.filter((e: any) => e.status === 'active')
  const outgoing = edges.map((e: any, idx: number) => ({ ...e, idx })).filter((e: any) => e.from === nodeId)
  const incoming = edges.map((e: any, idx: number) => ({ ...e, idx })).filter((e: any) => e.to === nodeId)
  return { outgoing, incoming }
}

