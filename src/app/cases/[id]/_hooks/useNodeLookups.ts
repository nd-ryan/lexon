import { useMemo, useCallback } from 'react'
import { NodeLike, EdgeLike, GraphState, NodeLookups } from '@/types/case-editor'

export function useNodeLookups(nodesArray: NodeLike[], edgesArray: EdgeLike[], graphState: GraphState): NodeLookups {
  // Create edge lookup maps for O(1) access
  const edgesByFrom = useMemo(() => {
    const map = new Map<string, EdgeLike[]>()
    edgesArray.forEach(edge => {
      if (!map.has(edge.from)) map.set(edge.from, [])
      map.get(edge.from)!.push(edge)
    })
    return map
  }, [edgesArray])

  const edgesByTo = useMemo(() => {
    const map = new Map<string, EdgeLike[]>()
    edgesArray.forEach(edge => {
      if (!map.has(edge.to)) map.set(edge.to, [])
      map.get(edge.to)!.push(edge)
    })
    return map
  }, [edgesArray])
  
  // Create node lookup map for O(1) access
  const nodeById = useMemo(() => {
    const map = new Map<string, NodeLike>()
    nodesArray.forEach(node => map.set(node.temp_id, node))
    return map
  }, [nodesArray])

  // Memoize relief type lookups to avoid repeated searches
  // NOTE: Use graphState.nodes (not nodesArray) to include enriched catalog nodes
  const reliefTypeByReliefId = useMemo(() => {
    const map: Record<string, NodeLike> = {}
    edgesArray.forEach((e) => {
      if (e.label === 'IS_TYPE') {
        const reliefTypeNode = graphState.nodes.find((n) => n.temp_id === e.to && n.status === 'active')
        if (reliefTypeNode) {
          map[e.from] = reliefTypeNode
        }
      }
    })
    return map
  }, [edgesArray, graphState.nodes])

  const getLiveReliefType = useCallback((reliefId: string): NodeLike | null => {
    return reliefTypeByReliefId[reliefId] || null
  }, [reliefTypeByReliefId])

  // Memoize forum and jurisdiction lookups for proceedings
  // NOTE: Use graphState.nodes (not nodesArray) to include enriched catalog nodes
  const forumAndJurisdictionByProceedingId = useMemo(() => {
    const map: Record<string, { forum: NodeLike; jurisdiction: NodeLike | null }> = {}
    edgesArray.forEach((e) => {
      if (e.label === 'HEARD_IN') {
        const forumNode = graphState.nodes.find((n) => n.temp_id === e.to && n.status === 'active')
        if (forumNode) {
          // Find jurisdiction for this forum
          const partOfEdge = edgesArray.find((edge) => 
            edge.from === forumNode.temp_id && edge.label === 'PART_OF'
          )
          const jurisdictionNode = partOfEdge 
            ? graphState.nodes.find((n) => n.temp_id === partOfEdge.to && n.status === 'active')
            : null
          
          map[e.from] = { forum: forumNode, jurisdiction: jurisdictionNode || null }
        }
      }
    })
    return map
  }, [edgesArray, graphState.nodes])

  const getLiveForumAndJurisdiction = useCallback((proceedingId: string): { forum: NodeLike | null; jurisdiction: NodeLike | null } => {
    return forumAndJurisdictionByProceedingId[proceedingId] || { forum: null, jurisdiction: null }
  }, [forumAndJurisdictionByProceedingId])

  return {
    edgesByFrom,
    edgesByTo,
    nodeById,
    reliefTypeByReliefId,
    forumAndJurisdictionByProceedingId,
    getLiveReliefType,
    getLiveForumAndJurisdiction
  }
}

