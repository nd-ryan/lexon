/**
 * Graph manipulation and analysis utilities
 */

import type { GraphNode } from '@/types/case-graph'
import type { Schema } from '@/types/case-graph'

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

/**
 * Compute which descendants would become "truly orphaned" if `nodeId` were deleted:
 * orphaned = descendants that would have NO incoming edges from any "supported" active parent after deletion.
 *
 * This matches the editor's semantics: nodes only become orphaned if they are no longer connected to
 * the active graph through any remaining active parent chain.
 */
export function getOrphanedDescendantsAfterDelete(nodeId: string, graphState: any): string[] {
  const nodes: any[] = Array.isArray(graphState?.nodes) ? graphState.nodes : []
  const edges: any[] = Array.isArray(graphState?.edges) ? graphState.edges : []

  const activeEdges = edges.filter((e: any) => e?.status === 'active' || e?.status === undefined)
  const descendants = findDescendants(nodeId, activeEdges)
  if (descendants.length === 0) return []

  const descendantsSet = new Set(descendants)
  const nodeById = new Map<string, any>()
  nodes.forEach((n: any) => {
    if (n?.temp_id) nodeById.set(n.temp_id, n)
  })

  // Edges remaining after deleting nodeId (we remove edges that touch the deleted node).
  const remainingEdges = activeEdges.filter((e: any) => e?.from !== nodeId && e?.to !== nodeId)

  const childrenByFrom = new Map<string, string[]>()
  const parentsByTo = new Map<string, string[]>()
  remainingEdges.forEach((e: any) => {
    if (!e?.from || !e?.to) return
    if (!childrenByFrom.has(e.from)) childrenByFrom.set(e.from, [])
    childrenByFrom.get(e.from)!.push(e.to)
    if (!parentsByTo.has(e.to)) parentsByTo.set(e.to, [])
    parentsByTo.get(e.to)!.push(e.from)
  })

  // Seed "supported" descendants: any descendant with an incoming edge from an active parent OUTSIDE the deletion subtree.
  const supported = new Set<string>()
  const queue: string[] = []

  descendants.forEach((descId) => {
    const parents = parentsByTo.get(descId) || []
    const hasOutsideActiveParent = parents.some((parentId) => {
      if (parentId === nodeId) return false
      if (descendantsSet.has(parentId)) return false
      const parent = nodeById.get(parentId)
      return parent && parent.status === 'active'
    })
    if (hasOutsideActiveParent) {
      supported.add(descId)
      queue.push(descId)
    }
  })

  // Propagate support downward: if a node is supported, its children in the subtree become supported too.
  while (queue.length > 0) {
    const current = queue.shift()!
    const children = childrenByFrom.get(current) || []
    children.forEach((childId) => {
      if (!descendantsSet.has(childId)) return
      if (supported.has(childId)) return
      supported.add(childId)
      queue.push(childId)
    })
  }

  return descendants.filter((id) => !supported.has(id))
}

/**
 * Connectivity-based orphaning rule:
 * when `nodeId` is deleted, any node that was previously reachable from the Case root(s)
 * but becomes unreachable (treating edges as undirected) is considered "orphaned".
 *
 * This intentionally does NOT depend on edge direction, which may vary by relationship label.
 */
export function getOrphanedNodesAfterDelete(nodeId: string, graphState: any): string[] {
  const before = computeReachableFromCaseRoots(graphState?.nodes || [], graphState?.edges || [])
  if (before.size === 0) return []

  const after = computeReachableFromCaseRoots(graphState?.nodes || [], graphState?.edges || [], {
    excludeNodeId: nodeId
  })

  const orphaned: string[] = []
  for (const id of before) {
    if (id === String(nodeId)) continue
    if (!after.has(id)) orphaned.push(id)
  }
  return orphaned
}

export function filterActiveNodes(nodes: any[], deletedNodeIds: Set<string>, orphanedNodeIds: Set<string>): any[] {
  if (!Array.isArray(nodes)) return []
  // Node types that shouldn't appear in general node lists (handled by special UI components)
  const EXCLUDED_NODE_TYPES = new Set(['ReliefType', 'Forum', 'Jurisdiction', 'Domain'])
  
  return nodes.filter((n: any) => 
    n?.temp_id && 
    !deletedNodeIds.has(n.temp_id) && 
    !orphanedNodeIds.has(n.temp_id) &&
    !EXCLUDED_NODE_TYPES.has(n?.label)
  )
}

export function buildGlobalNodeNumbering(graphState: any, displayData: any): Record<string, Record<string, number>> {
  const numbering: Record<string, Record<string, number>> = {}
  const activeNodes = graphState.nodes.filter((n: any) => n.status === 'active')
  
  // Node types that shouldn't be numbered (handled as dropdowns/selectors instead)
  const EXCLUDED_FROM_NUMBERING = new Set(['ReliefType', 'Forum', 'Jurisdiction', 'Domain'])
  
  // Group nodes by label
  const nodesByLabel: Record<string, Array<{ temp_id: string, firstSeen: number }>> = {}
  
  // Walk through display data to collect nodes in order they appear
  const seenNodes = new Set<string>()
  const nodeOrder: Array<{ temp_id: string, label: string }> = []
  
  const collectNodes = (data: any) => {
    if (!data || typeof data !== 'object') return
    
    if (data.temp_id && !seenNodes.has(data.temp_id)) {
      const node = activeNodes.find((n: any) => n.temp_id === data.temp_id)
      // Skip nodes that are handled as dropdowns/selectors
      if (node && !EXCLUDED_FROM_NUMBERING.has(node.label)) {
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
  
  // Create node lookup map for O(1) access to node labels
  const nodeById = new Map<string, any>()
  graphState.nodes
    .filter((n: any) => n.status === 'active')
    .forEach((node: any) => {
      nodeById.set(node.temp_id, node)
    })
  
  // Count unique parents for each node (incoming edges)
  graphState.edges
    .filter((e: any) => e.status === 'active')
    .forEach((edge: any) => {
      if (!nodeParents[edge.to]) {
        nodeParents[edge.to] = new Set()
      }
      nodeParents[edge.to].add(edge.from)
    })
  
  // Mark nodes with multiple parents as reused (excluding catalog-only nodes)
  const CATALOG_NODE_TYPES = new Set(['ReliefType', 'Forum', 'Jurisdiction', 'Domain'])
  Object.entries(nodeParents).forEach(([nodeId, parents]) => {
    if (parents.size > 1) {
      const node = nodeById.get(nodeId)
      // Skip catalog-only nodes - they can be shared without showing as "reused"
      if (node && !CATALOG_NODE_TYPES.has(node.label)) {
        reused.add(nodeId)
      }
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
    Object.entries(relTargets).forEach(([, targets]) => {
      if (targets.size > 1) {
        reused.add(nodeId)
      }
    })
  })
  
  return reused
}

export function buildNodeOptions(nodesArray: GraphNode[], pickNodeName: (node: GraphNode) => string | undefined) {
  // Node types that shouldn't appear in generic selection dropdowns (handled by special selectors)
  const EXCLUDED_FROM_OPTIONS = new Set(['ReliefType', 'Forum', 'Jurisdiction', 'Domain'])
  
  return (nodesArray || [])
    .filter((n) => !EXCLUDED_FROM_OPTIONS.has(n?.label))
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

type MinPerCaseViolation = {
  label: string
  min: number
  countAfter: number
}

function isActiveStatus(val: any): boolean {
  // Treat missing status as active for plain GraphNode/GraphEdge shapes
  return val === undefined || val === null || val === 'active'
}

function getMinPerCaseByLabel(schema: Schema | null | undefined): Map<string, number> {
  const out = new Map<string, number>()
  if (!schema) return out
  for (const item of schema) {
    const min = typeof (item as any)?.min_per_case === 'number' ? Number((item as any).min_per_case) : 0
    if (item?.label && min > 0) out.set(item.label, min)
  }
  return out
}

function buildUndirectedAdjacency(
  edges: any[],
  activeNodeIds: Set<string>,
  opts?: {
    excludeNodeId?: string
    excludeEdgeOnce?: { from: string; to: string; label: string }
  }
): Map<string, Set<string>> {
  const adj = new Map<string, Set<string>>()
  let excludedEdgeUsed = false
  const excludeEdge = opts?.excludeEdgeOnce
  const excludeNodeId = opts?.excludeNodeId

  for (const e of edges || []) {
    if (!e) continue
    if (!isActiveStatus(e.status)) continue
    const from = String(e.from || '')
    const to = String(e.to || '')
    const label = String(e.label || '')
    if (!from || !to) continue

    if (excludeNodeId && (from === excludeNodeId || to === excludeNodeId)) continue

    if (excludeEdge && !excludedEdgeUsed) {
      if (from === excludeEdge.from && to === excludeEdge.to && label === excludeEdge.label) {
        excludedEdgeUsed = true
        continue
      }
    }

    // Only traverse within the active node set
    if (!activeNodeIds.has(from) || !activeNodeIds.has(to)) continue

    if (!adj.has(from)) adj.set(from, new Set())
    if (!adj.has(to)) adj.set(to, new Set())
    adj.get(from)!.add(to)
    adj.get(to)!.add(from)
  }

  return adj
}

function computeReachableFromCaseRoots(
  nodes: any[],
  edges: any[],
  opts?: {
    excludeNodeId?: string
    excludeEdgeOnce?: { from: string; to: string; label: string }
  }
): Set<string> {
  const activeNodes = (nodes || []).filter((n: any) => n?.temp_id && isActiveStatus(n.status))
  const activeNodeIds = new Set<string>(activeNodes.map((n: any) => String(n.temp_id)))

  const excludeNodeId = opts?.excludeNodeId
  if (excludeNodeId) activeNodeIds.delete(String(excludeNodeId))

  const roots = activeNodes
    .filter((n: any) => n?.label === 'Case')
    .map((n: any) => String(n.temp_id))
    .filter((id: string) => activeNodeIds.has(id))

  // If there's no Case node, we can't define "connected-only" meaningfully; return empty set (no enforcement).
  if (roots.length === 0) return new Set()

  const adj = buildUndirectedAdjacency(edges, activeNodeIds, opts)
  const visited = new Set<string>()
  const queue: string[] = []

  for (const r of roots) {
    visited.add(r)
    queue.push(r)
  }

  while (queue.length > 0) {
    const cur = queue.shift()!
    const neigh = adj.get(cur)
    if (!neigh) continue
    for (const nxt of neigh) {
      if (visited.has(nxt)) continue
      visited.add(nxt)
      queue.push(nxt)
    }
  }

  return visited
}

function countReachableByLabel(nodes: any[], reachable: Set<string>): Map<string, number> {
  const counts = new Map<string, number>()
  for (const n of nodes || []) {
    if (!n?.temp_id || !n?.label) continue
    if (!isActiveStatus(n.status)) continue
    const id = String(n.temp_id)
    if (!reachable.has(id)) continue
    const lbl = String(n.label)
    counts.set(lbl, (counts.get(lbl) || 0) + 1)
  }
  return counts
}

function computeViolationsFromCounts(counts: Map<string, number>, mins: Map<string, number>): MinPerCaseViolation[] {
  const violations: MinPerCaseViolation[] = []
  for (const [label, min] of mins.entries()) {
    const c = counts.get(label) || 0
    if (c < min) violations.push({ label, min, countAfter: c })
  }
  return violations
}

export function getMinPerCaseViolationsConnected(
  graphState: any,
  schema: Schema | null | undefined
): MinPerCaseViolation[] {
  const mins = getMinPerCaseByLabel(schema)
  if (mins.size === 0) return []

  const reachable = computeReachableFromCaseRoots(graphState?.nodes || [], graphState?.edges || [])
  if (reachable.size === 0) return []

  const counts = countReachableByLabel(graphState?.nodes || [], reachable)
  return computeViolationsFromCounts(counts, mins)
}

function computeDeficitsFromCounts(counts: Map<string, number>, mins: Map<string, number>): Map<string, number> {
  const deficits = new Map<string, number>()
  for (const [label, min] of mins.entries()) {
    const c = counts.get(label) || 0
    const deficit = Math.max(0, min - c)
    deficits.set(label, deficit)
  }
  return deficits
}

/**
 * Returns only the `min_per_case` violations that would become WORSE (deficit increases)
 * after deleting `nodeId`. This avoids disabling actions just because the current graph
 * is temporarily invalid (e.g. catalog nodes not yet enriched on initial load).
 */
export function getMinPerCaseWorseningAfterDeleteNode(
  graphState: any,
  schema: Schema | null | undefined,
  nodeId: string
): MinPerCaseViolation[] {
  const mins = getMinPerCaseByLabel(schema)
  if (mins.size === 0) return []

  const beforeReachable = computeReachableFromCaseRoots(graphState?.nodes || [], graphState?.edges || [])
  if (beforeReachable.size === 0) return []
  const beforeCounts = countReachableByLabel(graphState?.nodes || [], beforeReachable)
  const beforeDeficits = computeDeficitsFromCounts(beforeCounts, mins)

  const afterReachable = computeReachableFromCaseRoots(graphState?.nodes || [], graphState?.edges || [], {
    excludeNodeId: nodeId
  })
  const afterCounts = afterReachable.size === 0 ? new Map<string, number>() : countReachableByLabel(graphState?.nodes || [], afterReachable)
  const afterDeficits = computeDeficitsFromCounts(afterCounts, mins)

  const worsening: MinPerCaseViolation[] = []
  for (const [label, min] of mins.entries()) {
    const before = beforeDeficits.get(label) || 0
    const after = afterDeficits.get(label) || 0
    if (after > before) {
      worsening.push({ label, min, countAfter: afterCounts.get(label) || 0 })
    }
  }
  return worsening
}

/**
 * Returns only the `min_per_case` violations that would become WORSE (deficit increases)
 * after removing the given edge once.
 */
export function getMinPerCaseWorseningAfterUnlinkEdge(
  graphState: any,
  schema: Schema | null | undefined,
  edge: { from: string; to: string; label: string }
): MinPerCaseViolation[] {
  const mins = getMinPerCaseByLabel(schema)
  if (mins.size === 0) return []

  const beforeReachable = computeReachableFromCaseRoots(graphState?.nodes || [], graphState?.edges || [])
  if (beforeReachable.size === 0) return []
  const beforeCounts = countReachableByLabel(graphState?.nodes || [], beforeReachable)
  const beforeDeficits = computeDeficitsFromCounts(beforeCounts, mins)

  const afterReachable = computeReachableFromCaseRoots(graphState?.nodes || [], graphState?.edges || [], {
    excludeEdgeOnce: { from: edge.from, to: edge.to, label: edge.label }
  })
  const afterCounts = afterReachable.size === 0 ? new Map<string, number>() : countReachableByLabel(graphState?.nodes || [], afterReachable)
  const afterDeficits = computeDeficitsFromCounts(afterCounts, mins)

  const worsening: MinPerCaseViolation[] = []
  for (const [label, min] of mins.entries()) {
    const before = beforeDeficits.get(label) || 0
    const after = afterDeficits.get(label) || 0
    if (after > before) {
      worsening.push({ label, min, countAfter: afterCounts.get(label) || 0 })
    }
  }
  return worsening
}

export function getMinPerCaseViolationsAfterDeleteNode(
  graphState: any,
  schema: Schema | null | undefined,
  nodeId: string
): MinPerCaseViolation[] {
  const mins = getMinPerCaseByLabel(schema)
  if (mins.size === 0) return []

  const reachable = computeReachableFromCaseRoots(graphState?.nodes || [], graphState?.edges || [], {
    excludeNodeId: nodeId
  })
  if (reachable.size === 0) return computeViolationsFromCounts(new Map(), mins)

  const counts = countReachableByLabel(graphState?.nodes || [], reachable)
  return computeViolationsFromCounts(counts, mins)
}

export function getMinPerCaseViolationsAfterUnlinkEdge(
  graphState: any,
  schema: Schema | null | undefined,
  edge: { from: string; to: string; label: string }
): MinPerCaseViolation[] {
  const mins = getMinPerCaseByLabel(schema)
  if (mins.size === 0) return []

  const reachable = computeReachableFromCaseRoots(graphState?.nodes || [], graphState?.edges || [], {
    excludeEdgeOnce: { from: edge.from, to: edge.to, label: edge.label }
  })
  if (reachable.size === 0) return computeViolationsFromCounts(new Map(), mins)

  const counts = countReachableByLabel(graphState?.nodes || [], reachable)
  return computeViolationsFromCounts(counts, mins)
}

