/**
 * Hook for managing graph state with CRUD operations
 */

import { useCallback, useMemo, useState } from 'react'
import type { GraphEdge, GraphNode } from '@/types/case-graph'
import { findDescendants } from '@/lib/cases/graphHelpers'

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
    return graphState.nodes
      .filter(n => n.status === 'active')
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      .map(({ status, source, ...node }) => node) // Strip metadata
  }, [graphState])
  
  // Unfiltered nodes array for modals (includes orphaned nodes but excludes deleted)
  const nodesArrayForModals = useMemo<GraphNode[]>(() => {
    return graphState.nodes
      .filter(n => n.status !== 'deleted')
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
      // Find all descendants using complete edge list
      const activeEdges = prev.edges.filter(e => e.status === 'active')
      const descendants = findDescendants(nodeId, activeEdges)
      
      // Helper: Check if a descendant should be orphaned
      // A descendant should only be orphaned if it has NO other active parents
      const shouldOrphan = (descId: string): boolean => {
        // Get all incoming edges to this descendant (excluding edges from the deleted node)
        const incomingEdges = activeEdges.filter(
          e => e.to === descId && e.from !== nodeId
        )
        
        // Check if any of these incoming edges come from nodes that will remain active
        // (i.e., not the deleted node and not other descendants being orphaned)
        const hasActiveParent = incomingEdges.some(e => {
          const parent = prev.nodes.find(n => n.temp_id === e.from)
          return parent && parent.status === 'active' && !descendants.includes(e.from)
        })
        
        return !hasActiveParent
      }
      
      return {
        nodes: prev.nodes.map(n => {
          if (n.temp_id === nodeId) {
            // Mark parent as deleted
            return { ...n, status: 'deleted' as const }
          }
          if (descendants.includes(n.temp_id)) {
            // Only mark as orphaned if this node has no other active parents
            return shouldOrphan(n.temp_id)
              ? { ...n, status: 'orphaned' as const }
              : n  // Keep as active if it has other parents elsewhere
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
    restoreOrphanedNode,
    unlinkNode
  }
}

