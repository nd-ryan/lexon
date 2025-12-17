/**
 * Cascade delete utilities for case editor.
 * 
 * Derives delete rules dynamically from views config (UI hierarchy) and schema (cardinality).
 * When a node is deleted, its UI-children are either cascade-deleted or just have their edge removed,
 * depending on cardinality and whether they have other parents of the same type.
 */

import type { Schema, SchemaItem, RelationshipCardinality } from '@/types/case-graph'
import { pickNodeName } from './formatting'

// ============================================================================
// Types
// ============================================================================

/**
 * Represents a parent-child relationship in the UI hierarchy.
 * direction: 'outgoing' means parent -[rel]-> child
 * direction: 'incoming' means child -[rel]-> parent (edge points to parent)
 */
export interface UIHierarchyEntry {
  parentLabel: string
  childLabel: string
  relationshipLabel: string
  direction: 'outgoing' | 'incoming'
}

/**
 * Cardinality info for a relationship, keyed by "SourceLabel.RELATIONSHIP_LABEL"
 */
export interface CardinalityEntry {
  sourceLabel: string
  relationshipLabel: string
  targetLabel: string
  cardinality: RelationshipCardinality
  /** True if source can connect to multiple targets (*-to-many) */
  canHaveMultipleTargets: boolean
}

/**
 * A node scheduled for deletion/unlinking in the cascade plan
 */
export interface CascadeNode {
  nodeId: string
  label: string
  name: string
  caseUnique: boolean
}

/**
 * An edge to be removed
 */
export interface CascadeEdge {
  from: string
  to: string
  label: string
}

/**
 * The full cascade plan for a delete operation
 */
export interface CascadePlan {
  /** The primary node being deleted */
  primaryNode: CascadeNode
  /** Nodes that will be cascade-deleted (removed from graph) */
  toDelete: CascadeNode[]
  /** Nodes that will just have their edge removed (still connected elsewhere) */
  toDetachOnly: CascadeNode[]
  /** All edges that will be removed */
  edgesToRemove: CascadeEdge[]
}

/**
 * Result of min_per_case validation
 */
export interface CascadeValidation {
  valid: boolean
  reason?: string
  violations?: Array<{ label: string; min: number; countAfter: number }>
}

// ============================================================================
// Build UI Hierarchy from views config
// ============================================================================

/**
 * Recursively extract parent-child relationships from a structure config object
 */
function extractHierarchyFromStructure(
  parentLabel: string,
  structure: Record<string, any>,
  entries: UIHierarchyEntry[]
): void {
  for (const [key, config] of Object.entries(structure)) {
    if (!config || typeof config !== 'object') continue
    
    // Skip "self" entries - they represent the node itself, not a child
    if (config.self) continue
    
    // This is a child relationship
    const childLabel = config.label || key.charAt(0).toUpperCase() + key.slice(1)
    const relationshipLabel = config.via
    const direction: 'outgoing' | 'incoming' = config.direction === 'incoming' ? 'incoming' : 'outgoing'
    
    if (relationshipLabel) {
      entries.push({
        parentLabel,
        childLabel,
        relationshipLabel,
        direction
      })
    }
    
    // Recurse into nested includes
    if (config.include && typeof config.include === 'object') {
      extractHierarchyFromStructure(childLabel, config.include, entries)
    }
  }
}

/**
 * Build the complete UI hierarchy from views config.
 * This maps out all parent-child relationships as displayed in the UI.
 */
export function buildUIHierarchy(viewsConfig: any): UIHierarchyEntry[] {
  const entries: UIHierarchyEntry[] = []
  
  if (!viewsConfig) return entries
  
  // Get the active view (usually holdingsCentric)
  const view = viewsConfig.holdingsCentric || viewsConfig
  if (!view) return entries
  
  // Process topLevel relationships
  const topLevel = view.topLevel || {}
  for (const [key, config] of Object.entries(topLevel)) {
    if (!config || typeof config !== 'object') continue
    const cfg = config as any
    
    if (cfg.via && cfg.from) {
      entries.push({
        parentLabel: cfg.from,
        childLabel: cfg.label || key.charAt(0).toUpperCase() + key.slice(1),
        relationshipLabel: cfg.via,
        direction: 'outgoing' // topLevel relationships are typically outgoing
      })
    }
  }
  
  // Process root-level structures (issues, holdings, etc.)
  for (const [key, config] of Object.entries(view)) {
    if (key === 'topLevel' || key === 'description') continue
    if (!config || typeof config !== 'object') continue
    
    const cfg = config as any
    if (cfg.root && cfg.structure) {
      extractHierarchyFromStructure(cfg.root, cfg.structure, entries)
    }
  }
  
  return entries
}

// ============================================================================
// Build Cardinality Map from schema
// ============================================================================

/**
 * Build a map of relationship cardinalities from schema.
 * Key format: "SourceLabel.RELATIONSHIP_LABEL"
 */
export function buildCardinalityMap(schema: Schema | null | undefined): Map<string, CardinalityEntry> {
  const map = new Map<string, CardinalityEntry>()
  
  if (!schema || !Array.isArray(schema)) return map
  
  for (const item of schema) {
    if (!item?.label || !item?.relationships) continue
    
    for (const [relLabel, relConfig] of Object.entries(item.relationships)) {
      if (!relConfig || typeof relConfig !== 'object') continue
      
      const target = relConfig.target
      const cardinality = relConfig.cardinality || 'many-to-many'
      
      // *-to-many means source can have multiple targets
      const canHaveMultipleTargets = cardinality.endsWith('-to-many')
      
      const key = `${item.label}.${relLabel}`
      map.set(key, {
        sourceLabel: item.label,
        relationshipLabel: relLabel,
        targetLabel: target,
        cardinality,
        canHaveMultipleTargets
      })
    }
  }
  
  return map
}

/**
 * Get case_unique status for a label from schema
 */
function getCaseUnique(schema: Schema | null | undefined, label: string): boolean {
  if (!schema || !Array.isArray(schema)) return true // default to true (safer)
  const item = schema.find((s: SchemaItem) => s.label === label)
  return item?.case_unique !== false // default to true if not specified
}

// ============================================================================
// Compute Cascade Plan
// ============================================================================

/**
 * Find UI-children of a node based on the UI hierarchy and actual graph edges
 */
function findUIChildren(
  nodeId: string,
  nodeLabel: string,
  graphState: { nodes: any[]; edges: any[] },
  uiHierarchy: UIHierarchyEntry[]
): Array<{ childId: string; childLabel: string; relationshipLabel: string; direction: 'outgoing' | 'incoming' }> {
  const children: Array<{ childId: string; childLabel: string; relationshipLabel: string; direction: 'outgoing' | 'incoming' }> = []
  
  // Find all hierarchy entries where this node type is the parent
  const childRelationships = uiHierarchy.filter(h => h.parentLabel === nodeLabel)
  
  const activeEdges = graphState.edges.filter((e: any) => e.status === 'active' || e.status === undefined)
  
  for (const rel of childRelationships) {
    // Find edges matching this relationship
    let matchingEdges: any[]
    
    if (rel.direction === 'incoming') {
      // Edge points TO this node (child -> parent)
      matchingEdges = activeEdges.filter((e: any) => 
        e.to === nodeId && e.label === rel.relationshipLabel
      )
      for (const edge of matchingEdges) {
        const childNode = graphState.nodes.find((n: any) => 
          n.temp_id === edge.from && 
          n.label === rel.childLabel &&
          (n.status === 'active' || n.status === undefined)
        )
        if (childNode) {
          children.push({
            childId: childNode.temp_id,
            childLabel: childNode.label,
            relationshipLabel: rel.relationshipLabel,
            direction: rel.direction
          })
        }
      }
    } else {
      // Edge points FROM this node (parent -> child)
      matchingEdges = activeEdges.filter((e: any) => 
        e.from === nodeId && e.label === rel.relationshipLabel
      )
      for (const edge of matchingEdges) {
        const childNode = graphState.nodes.find((n: any) => 
          n.temp_id === edge.to && 
          n.label === rel.childLabel &&
          (n.status === 'active' || n.status === undefined)
        )
        if (childNode) {
          children.push({
            childId: childNode.temp_id,
            childLabel: childNode.label,
            relationshipLabel: rel.relationshipLabel,
            direction: rel.direction
          })
        }
      }
    }
  }
  
  return children
}

/**
 * Count how many other parents of the same relationship type a child has
 */
function countOtherParents(
  childId: string,
  parentId: string,
  relationshipLabel: string,
  direction: 'outgoing' | 'incoming',
  graphState: { nodes: any[]; edges: any[] },
  deletedNodeIds: Set<string>
): number {
  const activeEdges = graphState.edges.filter((e: any) => e.status === 'active' || e.status === undefined)
  
  let count = 0
  
  if (direction === 'incoming') {
    // Edge is child -> parent, so we count other nodes that child points to via this relationship
    // (excluding the parent being deleted)
    for (const edge of activeEdges) {
      if (edge.from === childId && edge.label === relationshipLabel && edge.to !== parentId) {
        // Check if target is still active and not being deleted
        const targetNode = graphState.nodes.find((n: any) => 
          n.temp_id === edge.to && 
          (n.status === 'active' || n.status === undefined) &&
          !deletedNodeIds.has(n.temp_id)
        )
        if (targetNode) count++
      }
    }
  } else {
    // Edge is parent -> child, so we count other nodes pointing to this child via this relationship
    for (const edge of activeEdges) {
      if (edge.to === childId && edge.label === relationshipLabel && edge.from !== parentId) {
        const sourceNode = graphState.nodes.find((n: any) => 
          n.temp_id === edge.from && 
          (n.status === 'active' || n.status === undefined) &&
          !deletedNodeIds.has(n.temp_id)
        )
        if (sourceNode) count++
      }
    }
  }
  
  return count
}

/**
 * Compute the full cascade plan for deleting a node.
 * 
 * Algorithm:
 * 1. Mark the deleted node
 * 2. Find all UI-children of this node
 * 3. For each child:
 *    - Look up cardinality (can child have multiple targets of this relationship?)
 *    - Count actual edges to other parents
 *    - If *-to-one OR no other parents: cascade delete the child
 *    - If *-to-many AND other parents exist: just remove this edge
 * 4. Recurse for cascaded children
 */
export function computeCascadePlan(
  nodeId: string,
  graphState: { nodes: any[]; edges: any[] },
  uiHierarchy: UIHierarchyEntry[],
  cardinalityMap: Map<string, CardinalityEntry>,
  schema: Schema | null | undefined
): CascadePlan {
  const node = graphState.nodes.find((n: any) => n.temp_id === nodeId)
  if (!node) {
    return {
      primaryNode: { nodeId, label: 'Unknown', name: nodeId, caseUnique: true },
      toDelete: [],
      toDetachOnly: [],
      edgesToRemove: []
    }
  }
  
  const primaryNode: CascadeNode = {
    nodeId,
    label: node.label,
    name: pickNodeName(node) || nodeId,
    caseUnique: getCaseUnique(schema, node.label)
  }
  
  const toDelete: CascadeNode[] = []
  const toDetachOnly: CascadeNode[] = []
  const edgesToRemove: CascadeEdge[] = []
  const processedNodes = new Set<string>([nodeId])
  
  // Collect all edges touching the primary node
  const activeEdges = graphState.edges.filter((e: any) => e.status === 'active' || e.status === undefined)
  for (const edge of activeEdges) {
    if (edge.from === nodeId || edge.to === nodeId) {
      edgesToRemove.push({ from: edge.from, to: edge.to, label: edge.label })
    }
  }
  
  // Process cascade recursively
  const processCascade = (currentNodeId: string, currentLabel: string, deletedSet: Set<string>) => {
    const children = findUIChildren(currentNodeId, currentLabel, graphState, uiHierarchy)
    
    for (const child of children) {
      if (processedNodes.has(child.childId)) continue
      processedNodes.add(child.childId)
      
      const childNode = graphState.nodes.find((n: any) => n.temp_id === child.childId)
      if (!childNode) continue
      
      // Count other parents in the actual graph
      // This is the primary determinant for cascade vs detach
      const otherParents = countOtherParents(
        child.childId,
        currentNodeId,
        child.relationshipLabel,
        child.direction,
        graphState,
        deletedSet
      )
      
      // Collect the edge to remove
      if (child.direction === 'incoming') {
        edgesToRemove.push({ from: child.childId, to: currentNodeId, label: child.relationshipLabel })
      } else {
        edgesToRemove.push({ from: currentNodeId, to: child.childId, label: child.relationshipLabel })
      }
      
      // Decide: cascade or just detach?
      // If no other parents exist for this child, it should cascade.
      // If other parents exist, just detach (remove edge) - the child remains active.
      const shouldCascade = otherParents === 0
      
      const cascadeNode: CascadeNode = {
        nodeId: child.childId,
        label: child.childLabel,
        name: pickNodeName(childNode) || child.childId,
        caseUnique: getCaseUnique(schema, child.childLabel)
      }
      
      if (shouldCascade) {
        toDelete.push(cascadeNode)
        deletedSet.add(child.childId)
        
        // Collect all edges touching this cascaded node
        for (const edge of activeEdges) {
          if (edge.from === child.childId || edge.to === child.childId) {
            const edgeKey = `${edge.from}|${edge.to}|${edge.label}`
            if (!edgesToRemove.some(e => `${e.from}|${e.to}|${e.label}` === edgeKey)) {
              edgesToRemove.push({ from: edge.from, to: edge.to, label: edge.label })
            }
          }
        }
        
        // Recurse
        processCascade(child.childId, child.childLabel, deletedSet)
      } else {
        toDetachOnly.push(cascadeNode)
      }
    }
  }
  
  const deletedSet = new Set([nodeId])
  processCascade(nodeId, node.label, deletedSet)
  
  return {
    primaryNode,
    toDelete,
    toDetachOnly,
    edgesToRemove
  }
}

// ============================================================================
// min_per_case Validation
// ============================================================================

/**
 * Check if the cascade plan would violate min_per_case constraints.
 * Returns validation result with any violations.
 */
export function checkCascadeMinPerCase(
  graphState: { nodes: any[]; edges: any[] },
  cascadePlan: CascadePlan,
  schema: Schema | null | undefined
): CascadeValidation {
  if (!schema || !Array.isArray(schema)) {
    return { valid: true }
  }
  
  // Collect all node IDs that will be deleted
  const deletedIds = new Set([
    cascadePlan.primaryNode.nodeId,
    ...cascadePlan.toDelete.map(n => n.nodeId)
  ])
  
  // Count nodes by label after deletions
  const countsByLabel = new Map<string, number>()
  for (const node of graphState.nodes) {
    if (node.status !== 'active' && node.status !== undefined) continue
    if (deletedIds.has(node.temp_id)) continue
    
    const label = node.label
    countsByLabel.set(label, (countsByLabel.get(label) || 0) + 1)
  }
  
  // Check against min_per_case
  const violations: Array<{ label: string; min: number; countAfter: number }> = []
  
  for (const item of schema) {
    if (!item?.label || item.min_per_case === undefined) continue
    
    const min = item.min_per_case
    if (min <= 0) continue
    
    const countAfter = countsByLabel.get(item.label) || 0
    if (countAfter < min) {
      violations.push({ label: item.label, min, countAfter })
    }
  }
  
  if (violations.length > 0) {
    const firstViolation = violations[0]
    const reason = `Cannot delete: would reduce ${firstViolation.label} count below minimum (${firstViolation.min} required, would have ${firstViolation.countAfter})`
    return { valid: false, reason, violations }
  }
  
  return { valid: true }
}

// ============================================================================
// Helper: Apply cascade plan to graph state
// ============================================================================

/**
 * Apply a cascade plan to graph state, returning the new state.
 * This marks all affected nodes as 'deleted' and all affected edges as 'deleted'.
 */
export function applyCascadePlan(
  graphState: { nodes: any[]; edges: any[] },
  cascadePlan: CascadePlan
): { nodes: any[]; edges: any[] } {
  const deleteNodeIds = new Set([
    cascadePlan.primaryNode.nodeId,
    ...cascadePlan.toDelete.map(n => n.nodeId),
    ...cascadePlan.toDetachOnly.map(n => n.nodeId) // These also get marked deleted from graph
  ])
  
  const edgeKeys = new Set(
    cascadePlan.edgesToRemove.map(e => `${e.from}|${e.to}|${e.label}`)
  )
  
  return {
    nodes: graphState.nodes.map(n => 
      deleteNodeIds.has(n.temp_id)
        ? { ...n, status: 'deleted' as const }
        : n
    ),
    edges: graphState.edges.map(e => {
      const key = `${e.from}|${e.to}|${e.label}`
      if (edgeKeys.has(key) || deleteNodeIds.has(e.from) || deleteNodeIds.has(e.to)) {
        return { ...e, status: 'deleted' as const }
      }
      return e
    })
  }
}

