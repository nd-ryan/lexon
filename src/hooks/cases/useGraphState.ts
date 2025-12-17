/**
 * Hook for managing graph state with CRUD operations
 */

import { useCallback, useMemo, useState } from 'react'
import type { GraphEdge, GraphNode } from '@/types/case-graph'
import { getOrphanedNodesAfterDelete } from '@/lib/cases/graphHelpers'
import type { CascadePlan } from '@/lib/cases/cascadeDelete'
import { applyCascadePlan } from '@/lib/cases/cascadeDelete'

type NodeStatus = 'active' | 'deleted' | 'orphaned'

export interface UnifiedNode extends GraphNode {
  status: NodeStatus
  source: 'initial' | 'user-created'
}

export interface UnifiedEdge extends GraphEdge {
  status: 'active' | 'deleted'
  properties?: Record<string, any>
}

export interface GraphState {
  nodes: UnifiedNode[]
  edges: UnifiedEdge[]
}

export function useGraphState(initialNodes: GraphNode[], initialEdges: GraphEdge[]) {
  const [graphState, setGraphState] = useState<GraphState>({
    nodes: initialNodes.map((n: any) => ({ 
      ...n, 
      status: 'active' as const, 
      source: 'initial' as const 
    })),
    edges: initialEdges.map((e: any) => ({ 
      ...e, 
      status: 'active' as const 
    }))
  })

  // Get active nodes for display (excludes deleted and orphaned)
  const nodesArray = useMemo<GraphNode[]>(() => {
    // Exclude special node types handled by dedicated selectors (e.g., ReliefType)
    const EXCLUDED_NODE_TYPES = new Set(['ReliefType', 'Forum', 'Jurisdiction', 'Domain'])
    
    return graphState.nodes
      .filter(n => n.status === 'active' && !EXCLUDED_NODE_TYPES.has(n.label))
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      .map(({ status, source, ...node }) => node) // Strip metadata
  }, [graphState])
  
  // Unfiltered nodes array for modals (includes orphaned nodes but excludes deleted)
  // Also excludes special node types handled by dedicated selectors (e.g., ReliefType)
  const nodesArrayForModals = useMemo<GraphNode[]>(() => {
    const EXCLUDED_FROM_MODALS = new Set(['ReliefType', 'Forum', 'Jurisdiction', 'Domain'])
    
    return graphState.nodes
      .filter(n => n.status !== 'deleted' && !EXCLUDED_FROM_MODALS.has(n.label))
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      .map(({ status, source, ...node }) => node) // Strip metadata
  }, [graphState])
  
  // Get active edges
  const edgesArray = useMemo<GraphEdge[]>(() => {
    return graphState.edges
      .filter(e => e.status === 'active')
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      .map(({ status, ...edge }) => edge) // Strip metadata
  }, [graphState])

  // Helper sets for filtering displayData nodes
  const deletedNodeIds = useMemo(() => 
    new Set(graphState.nodes.filter(n => n.status === 'deleted').map(n => n.temp_id)),
    [graphState]
  )
  const orphanedNodeIds = useMemo(() => 
    new Set(graphState.nodes.filter(n => n.status === 'orphaned').map(n => n.temp_id)),
    [graphState]
  )

  // Get list of truly orphaned nodes for display (nodes with no active parents)
  const orphanedNodes = useMemo(() => {
    const activeEdges = graphState.edges.filter(e => e.status === 'active')
    
    return graphState.nodes.filter(n => {
      if (n.status !== 'orphaned') return false
      
      // Check if this node has ANY incoming edges from active nodes
      const hasActiveParent = activeEdges.some(e => 
        e.to === n.temp_id && 
        graphState.nodes.find(parent => 
          parent.temp_id === e.from && parent.status === 'active'
        )
      )
      
      // Only include if it has NO active parents (truly orphaned)
      return !hasActiveParent
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    }).map(({ status, source, ...node }) => node) // Strip metadata for display
  }, [graphState])

  // Delete a node and orphan its descendants (only if they have no other active parents)
  const deleteNode = useCallback((nodeId: string) => {
    setGraphState(prev => {
      const orphanedNodes = getOrphanedNodesAfterDelete(nodeId, prev)
      const orphanedSet = new Set(orphanedNodes)
      
      return {
        nodes: prev.nodes.map(n => {
          if (n.temp_id === nodeId) {
            // Mark parent as deleted
            return { ...n, status: 'deleted' as const }
          }
          if (orphanedSet.has(n.temp_id)) {
            return { ...n, status: 'orphaned' as const }
          }
          return n
        }),
        edges: prev.edges.map(e => {
          // Mark edges connected to deleted node as deleted
          if (e.from === nodeId || e.to === nodeId) {
            return { ...e, status: 'deleted' as const }
          }
          return e
        })
      }
    })
  }, [])
  
  // Restore an orphaned node (make it active again)
  const restoreOrphanedNode = useCallback((nodeId: string) => {
    setGraphState(prev => ({
      ...prev,
      nodes: prev.nodes.map(n => 
        n.temp_id === nodeId 
          ? { ...n, status: 'active' as const }
          : n
      )
    }))
  }, [])

  // Unlink a node from its parent (remove the edge only)
  const unlinkNode = useCallback((nodeId: string, parentId: string, edgeLabel: string) => {
    setGraphState(prev => ({
      ...prev,
      edges: prev.edges.map(e => 
        e.from === parentId && e.to === nodeId && e.label === edgeLabel
          ? { ...e, status: 'deleted' as const }
          : e
      )
    }))
  }, [])

  // Delete a node using a pre-computed cascade plan
  // This handles UI-hierarchy-aware deletion with proper cascade/detach logic
  const deleteNodeWithCascade = useCallback((cascadePlan: CascadePlan) => {
    setGraphState(prev => applyCascadePlan(prev, cascadePlan))
  }, [])

  return {
    graphState,
    setGraphState,
    nodesArray,
    nodesArrayForModals,
    edgesArray,
    deletedNodeIds,
    orphanedNodeIds,
    orphanedNodes,
    deleteNode,
    deleteNodeWithCascade,
    restoreOrphanedNode,
    unlinkNode
  }
}

