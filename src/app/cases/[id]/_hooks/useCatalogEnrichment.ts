import { useEffect, useCallback } from 'react'
import { CatalogNodes } from '@/types/case-editor'

/**
 * Hook to automatically enrich graph state with catalog nodes referenced by edges.
 * Handles cases where catalog nodes (Forum, Jurisdiction, Domain, ReliefType) are
 * referenced by edges but not included in the initial node set.
 */
export function useCatalogEnrichment(
  data: any,
  catalogNodes: CatalogNodes,
  graphState: any,
  setGraphState: (state: any) => void,
  setHasUnsavedChanges: (value: boolean) => void
) {
  // Helper function to enrich nodes with catalog-only nodes referenced by edges
  const enrichNodesWithCatalogReferences = useCallback((nodes: any[], edges: any[]) => {
    const nodeIdsInState = new Set(nodes.map((n: any) => n.temp_id))
    const enrichedNodes = [...nodes]
    
    // Map of edge labels to their expected catalog node types
    const edgeToCatalogType: Record<string, string> = {
      'IS_TYPE': 'ReliefType',
      'HEARD_IN': 'Forum',
      'PART_OF': 'Jurisdiction',
      'CONTAINS': 'Domain'
    }
    
    // Find all edges that might reference catalog nodes
    edges.forEach((edge: any) => {
      const catalogType = edgeToCatalogType[edge.label]
      if (!catalogType) return
      
      // Check if the target node is missing (for most edges) or source (for CONTAINS which goes Domain -> Case)
      const missingNodeId = edge.label === 'CONTAINS' ? edge.from : edge.to
      
      if (!nodeIdsInState.has(missingNodeId)) {
        // Look for the node in catalog
        const catalogItems = catalogNodes[catalogType] || []
        const catalogNode = catalogItems.find((item: any) => item.temp_id === missingNodeId)
        
        if (catalogNode) {
          // Add the catalog node if not already present
          enrichedNodes.push({
            ...catalogNode,
            status: 'active' as const,
            source: 'initial' as const
          })
          nodeIdsInState.add(missingNodeId)
        }
      }
    })
    
    return enrichedNodes
  }, [catalogNodes])

  // Update graph state when data loads
  useEffect(() => {
    if (data) {
      // Handle both data structures: data.extracted or data directly
      const extracted = (data as any)?.extracted || data
      const nodes = extracted?.nodes || []
      const edges = extracted?.edges || []
      
      const initialNodes = nodes.map((n: any) => ({ 
        ...n, 
        status: 'active' as const, 
        source: 'initial' as const 
      }))
      const initialEdges = edges.map((e: any) => {
        // Ensure edges have properties object (not just empty {})
        const edge = { 
          ...e, 
          status: 'active' as const 
        }
        // If properties exist but are empty, keep them (backend should have normalized)
        // If no properties field, add empty object
        if (!edge.properties) {
          edge.properties = {}
        }
        return edge
      })
      
      // Enrich nodes with catalog nodes (Forum, Jurisdiction, Domain, ReliefType) referenced by edges
      const enrichedNodes = enrichNodesWithCatalogReferences(initialNodes, initialEdges)
      
      setGraphState({
        nodes: enrichedNodes,
        edges: initialEdges
      })
      // Reset unsaved changes when fresh data loads
      setHasUnsavedChanges(false)
    }
  }, [data, setGraphState, enrichNodesWithCatalogReferences, setHasUnsavedChanges])

  // Also enrich when catalogNodes loads (in case catalog loads after data)
  // This handles the race condition where catalog loads after initial data
  useEffect(() => {
    if (!data) return // Don't run if data isn't loaded yet
    
    // Check if any catalog types are loaded
    const hasCatalog = catalogNodes && (
      (catalogNodes['ReliefType'] && catalogNodes['ReliefType'].length > 0) ||
      (catalogNodes['Forum'] && catalogNodes['Forum'].length > 0) ||
      (catalogNodes['Jurisdiction'] && catalogNodes['Jurisdiction'].length > 0) ||
      (catalogNodes['Domain'] && catalogNodes['Domain'].length > 0)
    )
    
    if (!hasCatalog) return // No catalog loaded yet
    
    // Check if there are catalog-referencing edges that might need enrichment
    const catalogEdgeLabels = ['IS_TYPE', 'HEARD_IN', 'PART_OF', 'CONTAINS']
    const hasCatalogEdges = graphState.edges.some((e: any) => 
      catalogEdgeLabels.includes(e.label) && e.status === 'active'
    )
    
    if (!hasCatalogEdges) return // No catalog edges to enrich
    
    // Check if any catalog edge references are missing from nodes
    const nodeIds = new Set(graphState.nodes.map((n: any) => n.temp_id))
    const hasMissingNodes = graphState.edges.some((e: any) => {
      if (!catalogEdgeLabels.includes(e.label) || e.status !== 'active') return false
      const checkId = e.label === 'CONTAINS' ? e.from : e.to
      return !nodeIds.has(checkId)
    })
    
    if (!hasMissingNodes) return // All catalog nodes are already present
    
    // Enrich with missing catalog nodes
    const enrichedNodes = enrichNodesWithCatalogReferences(graphState.nodes, graphState.edges)
    
    // Only update if we actually added nodes
    if (enrichedNodes.length > graphState.nodes.length) {
      setGraphState((prev: any) => ({
        ...prev,
        nodes: enrichedNodes
      }))
    }
  }, [catalogNodes, data, enrichNodesWithCatalogReferences, setGraphState, graphState])
}

