"use client";
import React, { useEffect, useMemo, useState, useCallback, useTransition } from 'react'
import { useParams } from 'next/navigation'
import type { Schema } from '@/types/case-graph'
import { useAppStore } from '@/lib/store/appStore'
import AddNodeModal from '@/components/cases/AddNodeModal.client'
import SelectNodeModal from '@/components/cases/SelectNodeModal.client'
import RelationshipAction from '@/components/cases/RelationshipAction.client'
import { analyzeRelationship } from '@/lib/relationshipHelpers'

// Hooks
import { useCaseData } from '@/hooks/cases/useCaseData'
import { useGraphState } from '@/hooks/cases/useGraphState'
import { usePendingEdits } from '@/hooks/cases/usePendingEdits'
import { useCaseSave } from '@/hooks/cases/useCaseSave'
import { useRelationshipProperties } from '@/hooks/cases/useRelationshipProperties'

// Utils
import { formatLabel, pickNodeName } from '@/lib/cases/formatting'
import { buildNodeOptions, buildGlobalNodeNumbering, detectReusedNodes, filterActiveNodes } from '@/lib/cases/graphHelpers'
import { isExistingNode } from '@/lib/cases/nodeHelpers'
import { validateRequiredFields } from '@/lib/cases/validation'

// Components
import { NodeCard } from '@/components/cases/editor/NodeCard'
import { RelationshipPropertyField } from '@/components/cases/editor/RelationshipPropertyField'
import { SectionHeader } from '@/components/cases/editor/SectionHeader'
import { CaseSidebar } from '@/components/cases/editor/CaseSidebar'
import { CaseFooter } from '@/components/cases/editor/CaseFooter'
import { OrphanedNodesSection } from '@/components/cases/editor/OrphanedNodesSection'
import { DeleteNodeConfirmation } from '@/components/cases/editor/modals/DeleteNodeConfirmation'
import { EditRelationshipModal } from '@/components/cases/editor/modals/EditRelationshipModal'
import { DeleteRelationshipConfirmation } from '@/components/cases/editor/modals/DeleteRelationshipConfirmation'
import { ReliefTypeSelector } from '@/components/cases/editor/ReliefTypeSelector'
import { ForumSelector } from '@/components/cases/editor/ForumSelector'

export default function CaseEditorPage() {
  const params = useParams()
  const id = params?.id as string
  const schema = useAppStore(s => s.schema as Schema | null)
  const catalogNodes = useAppStore(s => s.catalogNodes)
  
  // Fetch case data
  const { data, setData, displayData, setDisplayData, viewConfig, setViewConfig } = useCaseData(id)
  
  // Initialize graph state with empty arrays first
  const { 
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
  } = useGraphState([], [])
  
  // Pending edits management
  const { pendingEditsRef, pendingEditsVersion, setPendingEdit, clearPendingEdits, versionTimerRef } = usePendingEdits()
  
  // Relationship properties
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
  
  // Helper function to enrich nodes with catalog-only nodes (Forum, Jurisdiction, Domain, ReliefType) referenced by edges
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
      const extracted = (data as any)?.extracted || { nodes: [], edges: [] }
      const initialNodes = extracted.nodes.map((n: any) => ({ 
        ...n, 
        status: 'active' as const, 
        source: 'initial' as const 
      }))
      const initialEdges = extracted.edges.map((e: any) => ({ 
        ...e, 
        status: 'active' as const 
      }))
      
      // Enrich nodes with catalog nodes (Forum, Jurisdiction, Domain, ReliefType) referenced by edges
      const enrichedNodes = enrichNodesWithCatalogReferences(initialNodes, initialEdges)
      
      setGraphState({
        nodes: enrichedNodes,
        edges: initialEdges
      })
      // Reset unsaved changes when fresh data loads
      setHasUnsavedChanges(false)
    }
  }, [data, setGraphState, enrichNodesWithCatalogReferences])

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
  
  const relationshipProps = useRelationshipProperties(graphState, setGraphState, setHasUnsavedChanges)
  
  // Create validation function
  const validateCase = useCallback(() => {
    return validateRequiredFields(graphState, schema, pendingEditsRef)
  }, [graphState, schema, pendingEditsRef])
  
  // Save functionality
  const { saving, submittingKg, error, onSave: saveCase, submitToKg } = useCaseSave(
    id,
    graphState,
    pendingEditsRef,
    versionTimerRef,
    setData,
    setDisplayData,
    setViewConfig,
    setGraphState,
    validateCase
  )
  
  // Wrap save to clear unsaved changes flag
  const onSave = useCallback(async () => {
    const success = await saveCase()
    if (success) {
      setHasUnsavedChanges(false)
      clearPendingEdits()
    }
  }, [saveCase, clearPendingEdits])
  
  // UI state
  const [isViewMode, setIsViewMode] = useState(true)
  const [editingEdgeIdx, setEditingEdgeIdx] = useState<number | null>(null)
  const [editToValue, setEditToValue] = useState<string>('')
  const [confirmDeleteIdx, setConfirmDeleteIdx] = useState<number | null>(null)
  const [scrollHistory, setScrollHistory] = useState<number[]>([])
  const [addModalOpen, setAddModalOpen] = useState(false)
  const [addModalType, setAddModalType] = useState<string>('')
  const [addModalContext, setAddModalContext] = useState<{
    parentId?: string
    relationship: string
    direction: 'outgoing' | 'incoming'
  } | null>(null)
  const [selectModalOpen, setSelectModalOpen] = useState(false)
  const [selectModalType, setSelectModalType] = useState<string>('')
  const [selectModalContext, setSelectModalContext] = useState<{
    parentId?: string
    relationship: string
    direction: 'outgoing' | 'incoming'
  } | null>(null)
  const [activeHoldingId, setActiveHoldingId] = useState<string | null>(null)
  const [activeNodeId, setActiveNodeId] = useState<string | null>(null)
  const [activeNodeContext, setActiveNodeContext] = useState<string | null>(null)
  const [expandedFacts, setExpandedFacts] = useState<Set<string>>(new Set())
  const [deletingNodeId, setDeletingNodeId] = useState<string | null>(null)
  const [partiesExpanded, setPartiesExpanded] = useState(false)
  const [partiesSectionExpanded, setPartiesSectionExpanded] = useState(false)

  // Derived data
  const nodeOptions = useMemo(() => buildNodeOptions(nodesArray, pickNodeName), [nodesArray])
  const nodeIdToDisplay = useMemo(() => {
    const map: Record<string, string> = {}
    nodeOptions.forEach(o => { map[o.id] = o.display })
    return map
  }, [nodeOptions])
  
  const globalNodeNumbering = useMemo(() => 
    buildGlobalNodeNumbering(graphState, displayData),
    [graphState, displayData]
  )
  
  const reusedNodes = useMemo(() => detectReusedNodes(graphState), [graphState])
  
  // Create edge lookup maps for O(1) access
  const edgesByFrom = useMemo(() => {
    const map = new Map<string, any[]>()
    edgesArray.forEach(edge => {
      if (!map.has(edge.from)) map.set(edge.from, [])
      map.get(edge.from)!.push(edge)
    })
    return map
  }, [edgesArray])

  const edgesByTo = useMemo(() => {
    const map = new Map<string, any[]>()
    edgesArray.forEach(edge => {
      if (!map.has(edge.to)) map.set(edge.to, [])
      map.get(edge.to)!.push(edge)
    })
    return map
  }, [edgesArray])
  
  // Create node lookup map for O(1) access
  const nodeById = useMemo(() => {
    const map = new Map<string, any>()
    nodesArray.forEach(node => map.set(node.temp_id, node))
    return map
  }, [nodesArray])
  
  // Domain state
  const domainNode = useMemo(() => {
    return graphState.nodes.find((n: any) => n.label === 'Domain' && n.status === 'active')
  }, [graphState])
  
  const domainName = String(domainNode?.properties?.name || 'Unknown')
  
  const domainOptions = useMemo(() => {
    const domainLabel = schema?.find((l: any) => l.label === 'Domain')
    return domainLabel?.properties?.name?.ui?.options || ['Free Speech', 'Antitrust']
  }, [schema])
  
  // Extract structure key and root label from view config
  const structureInfo = useMemo(() => {
    if (!viewConfig) return { key: null, rootLabel: null, structure: {} }
    
    for (const [key, value] of Object.entries(viewConfig)) {
      if (key === 'topLevel' || key === 'description') continue
      if (typeof value === 'object' && value !== null && 'root' in value) {
        return {
          key,
          rootLabel: (value as any).root,
          structure: (value as any).structure || {}
        }
      }
    }
    return { key: null, rootLabel: null, structure: {} }
  }, [viewConfig])
  
  const rootStructure = useMemo(() => structureInfo.structure, [structureInfo])
  
  // Use backend-structured display data directly
  const rootEntities = useMemo(() => {
    if (!displayData || !structureInfo.key) return []
    const rootCollection = displayData[structureInfo.key]
    if (!Array.isArray(rootCollection)) return []
    return rootCollection
  }, [displayData, structureInfo])
  
  // Case structure helpers
  const caseNode = useMemo(() => {
    return (nodesArray || []).find((n: any) => n.label === 'Case') || null
  }, [nodesArray])
  
  const getLiveNode = useCallback((tempId: string | undefined) => {
    if (!tempId) return null
    return nodeById.get(tempId) || null
  }, [nodeById])
  
  const getRelatedNodes = useCallback((
    parentId: string | undefined,
    relLabel: string,
    direction: 'outgoing' | 'incoming' = 'outgoing'
  ) => {
    if (!parentId) return []
    
    const edges = direction === 'outgoing' 
      ? (edgesByFrom.get(parentId) || []).filter(e => e.label === relLabel)
      : (edgesByTo.get(parentId) || []).filter(e => e.label === relLabel)
    
    const ids = new Set<string>()
    const results: any[] = []
    
    edges.forEach((edge: any) => {
      const targetId = direction === 'outgoing' ? edge.to : edge.from
      if (targetId && !ids.has(targetId)) {
        const node = nodeById.get(targetId)
        if (node) { ids.add(targetId); results.push(node) }
      }
    })
    
    return results
  }, [edgesByFrom, edgesByTo, nodeById])
  
  const proceedingNodes = useMemo(() => {
    return caseNode ? getRelatedNodes(caseNode.temp_id, 'HAS_PROCEEDING', 'outgoing') : []
  }, [caseNode, getRelatedNodes])
  
  const forumNodes = useMemo(() => {
    const seen = new Set<string>()
    const results: any[] = []
    proceedingNodes.forEach((proc: any) => {
      getRelatedNodes(proc.temp_id, 'HEARD_IN', 'outgoing').forEach((n: any) => {
        if (!seen.has(n.temp_id)) { seen.add(n.temp_id); results.push(n) }
      })
    })
    return results
  }, [proceedingNodes, getRelatedNodes])
  
  const partyNodes = useMemo(() => {
    const seen = new Set<string>()
    const results: any[] = []
    proceedingNodes.forEach((proc: any) => {
      getRelatedNodes(proc.temp_id, 'INVOLVES', 'outgoing').forEach((n: any) => {
        if (!seen.has(n.temp_id)) { seen.add(n.temp_id); results.push(n) }
      })
    })
    return results
  }, [proceedingNodes, getRelatedNodes])
  
  const jurisdictionNodes = useMemo(() => {
    const seen = new Set<string>()
    const results: any[] = []
    forumNodes.forEach((forum: any) => {
      getRelatedNodes(forum.temp_id, 'PART_OF', 'outgoing').forEach((n: any) => {
        if (!seen.has(n.temp_id)) { seen.add(n.temp_id); results.push(n) }
      })
    })
    return results
  }, [forumNodes, getRelatedNodes])

  // Pre-compute all relationship states
  const relationshipStates = useMemo(() => {
    const states: Record<string, any> = {}
    
    const getParentNodeFromConfigLocal = (configKey: string): any => {
      const config = viewConfig?.topLevel?.[configKey]
      const fromLabel = config?.from
      
      if (!fromLabel) {
        return caseNode
      }
      
      switch (fromLabel) {
        case 'Case':
          return caseNode
        case 'Proceeding':
          return proceedingNodes[0]
        case 'Forum':
          return forumNodes[0]
        case 'Jurisdiction':
          return jurisdictionNodes[0]
        default:
          return caseNode
      }
    }
    
    // Top-level relationships
    const proceedingParent = getParentNodeFromConfigLocal('proceedings')
    states.proceedings = analyzeRelationship(
      proceedingParent,
      'proceedings',
      viewConfig?.topLevel || {},
      schema,
      { proceedings: proceedingNodes }
    )
    
    const forumParent = getParentNodeFromConfigLocal('forums')
    const forumsForParent = forumParent ? getRelatedNodes(forumParent.temp_id, 'HEARD_IN', 'outgoing') : []
    states.forums = analyzeRelationship(
      forumParent,
      'forums',
      viewConfig?.topLevel || {},
      schema,
      { forums: forumsForParent }
    )
    
    const partyParent = getParentNodeFromConfigLocal('parties')
    const partiesForParent = partyParent ? getRelatedNodes(partyParent.temp_id, 'INVOLVES', 'outgoing') : []
    states.parties = analyzeRelationship(
      partyParent,
      'parties',
      viewConfig?.topLevel || {},
      schema,
      { parties: partiesForParent }
    )
    
    return states
  }, [viewConfig, schema, proceedingNodes, caseNode, forumNodes, partyNodes, jurisdictionNodes, getRelatedNodes])

  // Scroll helpers
  const scrollToHolding = (holdingId: string) => {
    setActiveHoldingId(holdingId)
    setActiveNodeId(holdingId)
    setActiveNodeContext(holdingId)
    const el = document.getElementById(`holding-${holdingId}`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }
  
  const scrollToNodeById = (nodeId: string, holdingId?: string, context?: string) => {
    if (holdingId) setActiveHoldingId(holdingId)
    setActiveNodeId(nodeId)
    setActiveNodeContext(context || holdingId || null)
    // Use context-specific ID if context is provided, otherwise fallback to basic ID
    const elementId = context ? `node-${context}-${nodeId}` : `node-${nodeId}`
    const el = document.getElementById(elementId)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }

  const toggleFact = (factId: string) => {
    setExpandedFacts(prev => {
      const next = new Set(prev)
      if (next.has(factId)) {
        next.delete(factId)
      } else {
        next.add(factId)
      }
      return next
    })
  }

  // Value setter with state management
  const setValueAtPath = useCallback((path: (string|number|string)[], value: any) => {
    if (path[0] === 'nodes' && typeof path[1] === 'string') {
      const nodeId = path[1]
      
      setGraphState(prev => ({
        ...prev,
        nodes: prev.nodes.map(n => {
          if (n.temp_id !== nodeId) return n
          
          const updated = { ...n }
          let cursor: any = updated
          for (let i = 2; i < path.length - 1; i++) {
            const key = path[i]
            const nextVal = cursor[key]
            if (Array.isArray(nextVal)) {
              cursor[key] = [...nextVal]
            } else if (nextVal && typeof nextVal === 'object') {
              cursor[key] = { ...nextVal }
            } else {
              // Create a container object for nested assignment
              cursor[key] = {}
            }
            cursor = cursor[key]
          }
          const lastKey = path[path.length - 1]
          cursor[lastKey] = value
          
          return updated
        })
      }))
    } else if (path[0] === 'edges' && typeof path[1] === 'number') {
      const edgeIdx = path[1]
      setGraphState(prev => {
        const activeEdges = prev.edges.filter((e: any) => e.status === 'active')
        const edge = activeEdges[edgeIdx]
        if (!edge) return prev
        
        return {
          ...prev,
          edges: prev.edges.map((e: any) => {
            if (e.from !== edge.from || e.to !== edge.to || e.label !== edge.label) return e
            const lastKey = path[path.length - 1]
            return { ...e, [lastKey]: value }
          })
        }
      })
    }
    
    setHasUnsavedChanges(true)
  }, [setGraphState])

  // Modal handlers
  const handleAddNode = useCallback((
    nodeType: string, 
    relationship: string, 
    direction: 'outgoing' | 'incoming',
    parentId?: string
  ) => {
    setAddModalType(nodeType)
    setAddModalContext({ parentId, relationship, direction })
    setAddModalOpen(true)
  }, [])

  const handleSelectNode = useCallback((
    nodeType: string, 
    relationship: string, 
    direction: 'outgoing' | 'incoming',
    parentId?: string
  ) => {
    setSelectModalType(nodeType)
    setSelectModalContext({ parentId, relationship, direction })
    setSelectModalOpen(true)
  }, [])

  const getAvailableNodesForSelection = (nodeType: string) => {
    return catalogNodes[nodeType] || []
  }

  const handleSelectNodeSubmit = (selectedNodeId: string) => {
    if (!selectModalContext) return

    const { parentId, relationship, direction } = selectModalContext
    const selectedNode = getAvailableNodesForSelection(selectModalType).find(
      (n: any) => n.temp_id === selectedNodeId
    )
    
    if (!selectedNode) return

    setGraphState((prev: any) => {
      const nodes = [...prev.nodes]
      const edges = [...prev.edges]
      
      if (!nodes.find((n: any) => n.temp_id === selectedNode.temp_id)) {
        nodes.push({
          ...selectedNode,
          status: 'active' as const,
          source: 'user-created' as const
        })
      }
      
      // If Forum, also add its embedded Jurisdiction
      if (selectedNode.label === 'Forum' && selectedNode.related?.jurisdiction) {
        const jurisdiction = selectedNode.related.jurisdiction
        
        if (!nodes.find((n: any) => n.temp_id === jurisdiction.temp_id)) {
          nodes.push({
            ...jurisdiction,
            status: 'active' as const,
            source: 'user-created' as const
          })
        }
        
        const partOfExists = edges.find(
          (e: any) => e.from === selectedNode.temp_id && 
               e.to === jurisdiction.temp_id && 
               e.label === 'PART_OF'
        )
        
        if (!partOfExists) {
          edges.push({
            from: selectedNode.temp_id,
            to: jurisdiction.temp_id,
            label: 'PART_OF',
            status: 'active' as const
          })
        }
      }
      
      const parentEdgeExists = edges.find(
        (e: any) => e.from === (direction === 'outgoing' ? (parentId || '') : selectedNodeId) &&
             e.to === (direction === 'outgoing' ? selectedNodeId : (parentId || '')) &&
             e.label === relationship
      )
      
      if (!parentEdgeExists) {
        edges.push({
          from: direction === 'outgoing' ? (parentId || '') : selectedNodeId,
          to: direction === 'outgoing' ? selectedNodeId : (parentId || ''),
          label: relationship,
          status: 'active' as const
        })
      }
      
      return { nodes, edges }
    })

    if (orphanedNodeIds.has(selectedNodeId)) {
      restoreOrphanedNode(selectedNodeId)
    }

    setHasUnsavedChanges(true)
    setSelectModalOpen(false)
    setSelectModalContext(null)
  }

  const getParentNodeLabel = (parentId: string | undefined): string => {
    if (!parentId) return ''
    const parentNode = nodesArray.find((n: any) => n.temp_id === parentId)
    return parentNode?.label || 'Node'
  }

  const getParentNodeFromConfig = (configKey: string): any => {
    const config = viewConfig?.topLevel?.[configKey]
    const fromLabel = config?.from
    
    if (!fromLabel) {
      return caseNode
    }
    
    switch (fromLabel) {
      case 'Case':
        return caseNode
      case 'Proceeding':
        return proceedingNodes[0]
      case 'Forum':
        return forumNodes[0]
      case 'Jurisdiction':
        return jurisdictionNodes[0]
      default:
        return caseNode
    }
  }

  const findParentEdge = useCallback((parentId: string, nodeId: string) => {
    const edges = edgesByFrom.get(parentId) || []
    return edges.find(e => e.to === nodeId)
  }, [edgesByFrom])

  const getParentLabel = useCallback((parentId: string): string => {
    const parent = nodeById.get(parentId)
    return parent?.label ? formatLabel(parent.label) : 'parent'
  }, [nodeById])

  const shouldShowUnlink = useCallback((nodeId: string, parentId?: string): boolean => {
    if (!parentId) return false
    
    const parentEdge = findParentEdge(parentId, nodeId)
    if (!parentEdge) return false
    
    const incomingEdges = edgesByTo.get(nodeId) || []
    const incomingEdgesOfType = incomingEdges.filter(e => e.label === parentEdge.label)
    
    return incomingEdgesOfType.length > 1
  }, [edgesByTo, findParentEdge])

  const handleUnlink = (nodeId: string, parentId: string) => {
    const parentEdge = findParentEdge(parentId, nodeId)
    if (!parentEdge) return
    unlinkNode(nodeId, parentId, parentEdge.label)
    setHasUnsavedChanges(true)
  }

  const [isPendingReliefType, startReliefTypeTransition] = useTransition()
  
  const handleReliefTypeSelect = useCallback((reliefId: string, reliefTypeNode: any) => {
    // Mark unsaved changes immediately
    setHasUnsavedChanges(true)
    
    // Use transition to make the state update non-blocking
    startReliefTypeTransition(() => {
      setGraphState((prev: any) => {
        const nodes = [...prev.nodes]
        const edges = [...prev.edges]
        
        // Add ReliefType node if it doesn't exist
        if (!nodes.find((n: any) => n.temp_id === reliefTypeNode.temp_id)) {
          nodes.push({
            ...reliefTypeNode,
            status: 'active' as const,
            source: 'user-created' as const
          })
        }
        
        // Remove any existing IS_TYPE edges from this Relief
        const filteredEdges = edges.filter((e: any) => 
          !(e.from === reliefId && e.label === 'IS_TYPE')
        )
        
        // Add new IS_TYPE edge
        filteredEdges.push({
          from: reliefId,
          to: reliefTypeNode.temp_id,
          label: 'IS_TYPE',
          status: 'active' as const
        })
        
        return { nodes, edges: filteredEdges }
      })
    })
  }, [setGraphState, setHasUnsavedChanges, startReliefTypeTransition])

  const [isPendingForum, startForumTransition] = useTransition()
  
  const handleForumSelect = useCallback((proceedingId: string, forumNode: any, jurisdictionNode: any | null) => {
    // Mark unsaved changes immediately
    setHasUnsavedChanges(true)
    
    // Use transition to make the state update non-blocking
    startForumTransition(() => {
      setGraphState((prev: any) => {
        const nodes = [...prev.nodes]
        const edges = [...prev.edges]
        
        // Add Forum node if it doesn't exist
        if (!nodes.find((n: any) => n.temp_id === forumNode.temp_id)) {
          nodes.push({
            ...forumNode,
            status: 'active' as const,
            source: 'user-created' as const
          })
        }
        
        // Add Jurisdiction node if provided and doesn't exist
        if (jurisdictionNode && !nodes.find((n: any) => n.temp_id === jurisdictionNode.temp_id)) {
          nodes.push({
            ...jurisdictionNode,
            status: 'active' as const,
            source: 'user-created' as const
          })
        }
        
        // Remove any existing HEARD_IN edges from this Proceeding
        let filteredEdges = edges.filter((e: any) => 
          !(e.from === proceedingId && e.label === 'HEARD_IN')
        )
        
        // Remove any existing PART_OF edges from old forum
        const oldForumEdge = edges.find((e: any) => e.from === proceedingId && e.label === 'HEARD_IN')
        if (oldForumEdge) {
          filteredEdges = filteredEdges.filter((e: any) => 
            !(e.from === oldForumEdge.to && e.label === 'PART_OF')
          )
        }
        
        // Add new HEARD_IN edge: Proceeding → Forum
        filteredEdges.push({
          from: proceedingId,
          to: forumNode.temp_id,
          label: 'HEARD_IN',
          status: 'active' as const
        })
        
        // Add PART_OF edge: Forum → Jurisdiction (if jurisdiction provided)
        if (jurisdictionNode) {
          filteredEdges.push({
            from: forumNode.temp_id,
            to: jurisdictionNode.temp_id,
            label: 'PART_OF',
            status: 'active' as const
          })
        }
        
        return { nodes, edges: filteredEdges }
      })
    })
  }, [setGraphState, setHasUnsavedChanges, startForumTransition])

  const handleDomainChange = (domainName: string) => {
    const caseNode = graphState.nodes.find((n: any) => n.label === 'Case' && n.status === 'active')
    if (!caseNode) return
    
    let domainProps: Record<string, any> = { name: domainName }
    if (catalogNodes && Array.isArray(catalogNodes)) {
      const catalogDomain = catalogNodes.find((n: any) => 
        n.label === 'Domain' && n.properties?.name === domainName
      )
      if (catalogDomain) {
        domainProps = catalogDomain.properties
      }
    }
    
    setGraphState((prev: any) => {
      const filteredNodes = prev.nodes.filter((n: any) => n.label !== 'Domain')
      const filteredEdges = prev.edges.filter((e: any) => 
        !(e.label === 'CONTAINS' && e.to === caseNode.temp_id)
      )
      
      const domainTempId = `n${Date.now()}`
      return {
        nodes: [...filteredNodes, {
          temp_id: domainTempId,
          label: 'Domain',
          properties: domainProps,
          status: 'active' as const,
          source: 'user-created' as const
        }],
        edges: [...filteredEdges, {
          from: domainTempId,
          to: caseNode.temp_id,
          label: 'CONTAINS',
          status: 'active' as const
        }]
      }
    })
    
    setHasUnsavedChanges(true)
  }

  const getGlobalNodeNumber = (nodeId: string, nodeLabel: string): number | null => {
    return globalNodeNumbering[nodeLabel]?.[nodeId] ?? null
  }

  // Memoize relief type lookups to avoid repeated searches
  // NOTE: Use graphState.nodes (not nodesArray) to include enriched catalog nodes
  const reliefTypeByReliefId = useMemo(() => {
    const map: Record<string, any> = {}
    edgesArray.forEach((e: any) => {
      if (e.label === 'IS_TYPE') {
        const reliefTypeNode = graphState.nodes.find((n: any) => n.temp_id === e.to && n.status === 'active')
        if (reliefTypeNode) {
          map[e.from] = reliefTypeNode
        }
      }
    })
    return map
  }, [edgesArray, graphState.nodes])

  const getLiveReliefType = useCallback((reliefId: string): any => {
    return reliefTypeByReliefId[reliefId] || null
  }, [reliefTypeByReliefId])

  // Memoize forum and jurisdiction lookups for proceedings
  // NOTE: Use graphState.nodes (not nodesArray) to include enriched catalog nodes
  const forumAndJurisdictionByProceedingId = useMemo(() => {
    const map: Record<string, { forum: any; jurisdiction: any }> = {}
    edgesArray.forEach((e: any) => {
      if (e.label === 'HEARD_IN') {
        const forumNode = graphState.nodes.find((n: any) => n.temp_id === e.to && n.status === 'active')
        if (forumNode) {
          // Find jurisdiction for this forum
          const partOfEdge = edgesArray.find((edge: any) => 
            edge.from === forumNode.temp_id && edge.label === 'PART_OF'
          )
          const jurisdictionNode = partOfEdge 
            ? graphState.nodes.find((n: any) => n.temp_id === partOfEdge.to && n.status === 'active')
            : null
          
          map[e.from] = { forum: forumNode, jurisdiction: jurisdictionNode || null }
        }
      }
    })
    return map
  }, [edgesArray, graphState.nodes])

  const getLiveForumAndJurisdiction = useCallback((proceedingId: string): { forum: any; jurisdiction: any } => {
    return forumAndJurisdictionByProceedingId[proceedingId] || { forum: null, jurisdiction: null }
  }, [forumAndJurisdictionByProceedingId])

  // Helper for rendering NodeCard with all required props (must be before early return)
  const renderNodeCard = useCallback((node: any, label: string, options: {
    index?: number
    depth?: number
    badge?: React.ReactNode
    statusBadge?: React.ReactNode
    children?: React.ReactNode
    parentId?: string
    contextId?: string
  } = {}) => {
    const liveNode = getLiveNode(node.temp_id) || node
    const globalNum = getGlobalNodeNumber(node.temp_id, node.label)
    const isReused = reusedNodes.has(node.temp_id)
    const isExisting = isExistingNode(liveNode)
    const showUnlink = shouldShowUnlink(node.temp_id, options.parentId)
    const parentLabel = options.parentId ? getParentLabel(options.parentId) : ''
    
    return (
      <NodeCard
        key={node.temp_id}
        node={liveNode}
        label={label}
        index={options.index}
        depth={options.depth || 0}
        badge={options.badge}
        statusBadge={options.statusBadge}
        parentId={options.parentId}
        contextId={options.contextId}
        isViewMode={isViewMode}
        globalNodeNumber={globalNum}
        isReused={isReused}
        isExistingNode={isExisting}
        shouldShowUnlink={showUnlink}
        parentLabel={parentLabel}
        onDelete={setDeletingNodeId}
        onUnlink={handleUnlink}
        graphState={graphState}
        schema={schema}
        setPendingEdit={(path, value) => {
          setPendingEdit(path, value)
          setHasUnsavedChanges(true)
        }}
        setValueAtPath={setValueAtPath}
        pendingEditsRef={pendingEditsRef}
        pendingEditsVersion={pendingEditsVersion}
        nodeOptions={nodeOptions}
        nodeIdToDisplay={nodeIdToDisplay}
      >
        {options.children}
      </NodeCard>
    )
  }, [
    getLiveNode, getGlobalNodeNumber, reusedNodes, shouldShowUnlink,
    getParentLabel, isViewMode, graphState, schema, setPendingEdit, setValueAtPath,
    pendingEditsRef, pendingEditsVersion, nodeOptions, nodeIdToDisplay, setDeletingNodeId,
    handleUnlink, setHasUnsavedChanges
  ])

  // Early return after all hooks
  if (!data) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="rounded-md border bg-gray-50 px-2 py-1 text-xs text-gray-600">Loading...</div>
      </div>
    )
  }

  // Memoized Issue Section Component with custom comparison
  const IssueSection = React.memo(({ 
    entityData, 
    idx, 
    rootStructure,
    structureInfo,
    deletedNodeIds,
    orphanedNodeIds,
    isViewMode,
    edgesArray,
    nodesArray,
    schema,
    relationshipProps,
    handleAddNode,
    handleSelectNode,
    handleReliefTypeSelect,
    handleForumSelect,
    renderNodeCard,
    getLiveReliefType,
    getLiveForumAndJurisdiction
  }: any) => {
    // Find the root entity (the one with self: true in structure)
    const rootEntityKey = Object.entries(rootStructure).find(([, cfg]: [string, any]) => cfg.self)?.[0]
    const rootEntity = rootEntityKey ? entityData[rootEntityKey] : entityData[Object.keys(entityData)[0]]
    
    // Skip this entire entity if the root itself is deleted/orphaned
    if (!rootEntity || deletedNodeIds.has(rootEntity.temp_id) || orphanedNodeIds.has(rootEntity.temp_id)) {
      return null
    }
    
    // Extract nested entities from the structured data based on the actual structure
    const ruling = entityData.ruling && !deletedNodeIds.has(entityData.ruling.temp_id) ? entityData.ruling : null
    const reliefs = filterActiveNodes(ruling?.relief || [], deletedNodeIds, orphanedNodeIds)
    const issue = rootEntity
    const args = filterActiveNodes(ruling?.arguments || [], deletedNodeIds, orphanedNodeIds)
    
    // For Issue nodes, show "Issue {n}: {label}", otherwise use pickNodeName
    const issueLabel = rootEntity.label === 'Issue' && rootEntity.properties?.label 
      ? rootEntity.properties.label 
      : null
    const entityName = issueLabel 
      ? `${structureInfo.rootLabel} ${idx + 1}: ${issueLabel}`
      : pickNodeName(rootEntity) || `${structureInfo.rootLabel} ${idx + 1}`
    
    return (
      <div 
        key={rootEntity.temp_id} 
        id={`holding-${rootEntity.temp_id}`}
        className="scroll-mt-4 border-b pb-8 last:border-b-0"
      >
        {/* Root Entity Header */}
        <div className="mb-4">
          <h2 className="text-lg font-semibold text-gray-900">{entityName}</h2>
        </div>
        
        {/* Root Entity Details */}
        <div className="space-y-4">
          {renderNodeCard(rootEntity, `${structureInfo.rootLabel} Details`, { contextId: rootEntity.temp_id })}
          
          {/* Ruling */}
          {ruling && renderNodeCard(ruling, 'Ruling', {
            contextId: rootEntity.temp_id,
            statusBadge: (
              <RelationshipPropertyField
                sourceId={ruling.temp_id}
                targetId={rootEntity.temp_id}
                relLabel="SETS"
                propName="in_favor"
                sourceLabel="Ruling"
                isViewMode={isViewMode}
                label="In Favor"
                schema={schema}
                getValue={relationshipProps.getRulingInFavor}
                setValue={relationshipProps.setRulingInFavor}
              />
            ),
            children: (
              <>
                {/* Laws */}
                {(() => {
                  const rulingStructure = rootStructure?.ruling?.include || {}
                  const laws = filterActiveNodes(ruling?.law || [], deletedNodeIds, orphanedNodeIds)
                  const state = analyzeRelationship(ruling, 'law', rulingStructure, schema, { law: laws })
                  return (
                    <div className="mt-4">
                      <SectionHeader
                        title="Laws"
                        actionButton={!isViewMode && state && (
                          <RelationshipAction
                            state={state}
                            parentNodeLabel="Ruling"
                            position="inline"
                            onAdd={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleAddNode(type, rel, dir, ruling.temp_id)}
                            onSelect={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleSelectNode(type, rel, dir, ruling.temp_id)}
                          />
                        )}
                      />
                      <div className="space-y-4">
                        {laws.map((law: any, lawIdx: number) => 
                          renderNodeCard(law, 'Law', { 
                            index: lawIdx, 
                            depth: 1, 
                            parentId: ruling.temp_id,
                            contextId: rootEntity.temp_id
                          })
                        )}
                      </div>
                    </div>
                  )
                })()}
                
                {/* Relief (intermediate layer) */}
                {(() => {
                  const rulingStructure = rootStructure?.ruling?.include || {}
                  const state = analyzeRelationship(ruling, 'relief', rulingStructure, schema, { relief: reliefs })
                  return (
                    <div className="mt-4">
                      <SectionHeader
                        title="Relief"
                        actionButton={!isViewMode && state && (
                          <RelationshipAction
                            state={state}
                            parentNodeLabel="Ruling"
                            position="inline"
                            onAdd={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleAddNode(type, rel, dir, ruling.temp_id)}
                            onSelect={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleSelectNode(type, rel, dir, ruling.temp_id)}
                          />
                        )}
                      />
                      <div className="space-y-4">
                        {reliefs.map((relief: any, relIdx: number) => {
                          // Get live relief type from current graph state
                          const liveReliefType = getLiveReliefType(relief.temp_id)
                          const reliefStructure = rulingStructure?.relief?.include || {}
                          const reliefTypeState = analyzeRelationship(relief, 'reliefTypes', reliefStructure, schema, { reliefTypes: liveReliefType })
                          
                          return renderNodeCard(relief, 'Relief', {
                            index: relIdx,
                            depth: 1,
                            parentId: ruling.temp_id,
                            contextId: rootEntity.temp_id,
                            statusBadge: (
                              <RelationshipPropertyField
                                sourceId={ruling.temp_id}
                                targetId={relief.temp_id}
                                relLabel="RESULTS_IN"
                                propName="relief_status"
                                sourceLabel="Ruling"
                                isViewMode={isViewMode}
                                label="Relief Status"
                                schema={schema}
                                getValue={relationshipProps.getReliefStatus}
                                setValue={relationshipProps.setReliefStatus}
                              />
                            ),
                            children: (
                              <>
                                {/* Relief Type Selector (inline dropdown) */}
                                <ReliefTypeSelector
                                  reliefId={relief.temp_id}
                                  currentReliefType={liveReliefType}
                                  isViewMode={isViewMode}
                                  onSelect={(selectedNode: any) => handleReliefTypeSelect(relief.temp_id, selectedNode)}
                                />
                              </>
                            )
                          })
                        })}
                      </div>
                    </div>
                  )
                })()}
                
                {/* Arguments */}
                {(() => {
                  return (
                    <>
                      {args.length > 0 && (
                        <div className="mt-6 pt-6 border-t-2 border-gray-200 space-y-4">
                          {args.map((argData: any, argIdx: number) => {
                            // Backend returns structured argument data
                            const arg = argData.arguments || argData
                            const doctrines = filterActiveNodes(argData.doctrine || [], deletedNodeIds, orphanedNodeIds)
                            const policies = filterActiveNodes(argData.policy || [], deletedNodeIds, orphanedNodeIds)
                            const factPatterns = filterActiveNodes(argData.factPattern || [], deletedNodeIds, orphanedNodeIds)
                            const argumentStatus = relationshipProps.getArgumentStatus(arg.temp_id, ruling.temp_id)
                            
                            return renderNodeCard(arg, 'Argument', {
                              index: argIdx,
                              depth: 1,
                              parentId: ruling.temp_id,
                              contextId: rootEntity.temp_id,
                              statusBadge: isViewMode ? (
                                argumentStatus && (
                                  <span className={`px-2 py-1 rounded text-xs font-medium ${
                                    argumentStatus === 'Accepted' 
                                      ? 'bg-green-100 text-green-800' 
                                      : 'bg-red-100 text-red-800'
                                  }`}>
                                    {argumentStatus}
                                  </span>
                                )
                              ) : (
                                <select
                                  className="px-2 py-1 rounded border border-gray-300 text-xs font-medium focus:outline-none focus:ring-2 focus:ring-blue-500"
                                  value={argumentStatus || ''}
                                  onChange={(e) => relationshipProps.setArgumentStatus(arg.temp_id, ruling.temp_id, e.target.value)}
                                >
                                  <option value="">Select status...</option>
                                  <option value="Accepted">Accepted</option>
                                  <option value="Rejected">Rejected</option>
                                </select>
                              ),
                              children: (
                                <div className="mt-4 space-y-6">
                                  {/* Doctrines Section */}
                                  {(() => {
                                    const argStructure = rootStructure?.ruling?.include?.arguments?.include || {}
                                    const state = analyzeRelationship(arg, 'doctrine', argStructure, schema, argData)
                                    return (
                                      <div>
                                        <SectionHeader
                                          title="Doctrines"
                                          actionButton={!isViewMode && state && (
                                            <RelationshipAction
                                              state={state}
                                              parentNodeLabel="Argument"
                                              position="inline"
                                              onAdd={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleAddNode(type, rel, dir, arg.temp_id)}
                                              onSelect={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleSelectNode(type, rel, dir, arg.temp_id)}
                                            />
                                          )}
                                        />
                                        <div className="space-y-4">
                                          {doctrines.map((doc: any, docIdx: number) => 
                                            renderNodeCard(doc, 'Doctrine', { 
                                              index: docIdx, 
                                              depth: 2, 
                                              parentId: arg.temp_id,
                                              contextId: rootEntity.temp_id
                                            })
                                          )}
                                        </div>
                                      </div>
                                    )
                                  })()}
                                  
                                  {/* Policies Section */}
                                  {(() => {
                                    const argStructure = rootStructure?.ruling?.include?.arguments?.include || {}
                                    const state = analyzeRelationship(arg, 'policy', argStructure, schema, argData)
                                    return (
                                      <div>
                                        <SectionHeader
                                          title="Policies"
                                          actionButton={!isViewMode && state && (
                                            <RelationshipAction
                                              state={state}
                                              parentNodeLabel="Argument"
                                              position="inline"
                                              onAdd={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleAddNode(type, rel, dir, arg.temp_id)}
                                              onSelect={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleSelectNode(type, rel, dir, arg.temp_id)}
                                            />
                                          )}
                                        />
                                        <div className="space-y-4">
                                          {policies.map((pol: any, polIdx: number) => 
                                            renderNodeCard(pol, 'Policy', { 
                                              index: polIdx, 
                                              depth: 2, 
                                              parentId: arg.temp_id,
                                              contextId: rootEntity.temp_id
                                            })
                                          )}
                                        </div>
                                      </div>
                                    )
                                  })()}
                                  
                                  {/* Fact Patterns Section */}
                                  {(() => {
                                    const argStructure = rootStructure?.ruling?.include?.arguments?.include || {}
                                    const state = analyzeRelationship(arg, 'factPattern', argStructure, schema, argData)
                                    return (
                                      <div>
                                        <SectionHeader
                                          title="Fact Patterns"
                                          actionButton={!isViewMode && state && (
                                            <RelationshipAction
                                              state={state}
                                              parentNodeLabel="Argument"
                                              position="inline"
                                              onAdd={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleAddNode(type, rel, dir, arg.temp_id)}
                                              onSelect={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleSelectNode(type, rel, dir, arg.temp_id)}
                                            />
                                          )}
                                        />
                                        <div className="space-y-4">
                                          {factPatterns.map((fp: any, fpIdx: number) => 
                                            renderNodeCard(fp, 'Fact Pattern', { 
                                              index: fpIdx, 
                                              depth: 2, 
                                              parentId: arg.temp_id,
                                              contextId: rootEntity.temp_id
                                            })
                                          )}
                                        </div>
                                      </div>
                                    )
                                  })()}
                                </div>
                              )
                            })
                          })}
                        </div>
                      )}
                      {/* Add Argument button */}
                      {!isViewMode && (() => {
                        const rulingStructure = rootStructure?.ruling?.include || {}
                        const state = analyzeRelationship(ruling, 'arguments', rulingStructure, schema, { arguments: args })
                        if (!state) return null
                        return (
                          <div className={args.length > 0 ? "mt-3" : "mt-4"}>
                            <RelationshipAction
                              state={state}
                              parentNodeLabel="Ruling"
                              position={args.length === 0 ? 'centered' : 'inline'}
                              onAdd={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleAddNode(type, rel, dir, ruling.temp_id)}
                              onSelect={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleSelectNode(type, rel, dir, ruling.temp_id)}
                            />
                          </div>
                        )
                      })()}
                    </>
                  )
                })()}
              </>
            )
          })}
          {/* Add Ruling button if no ruling exists */}
          {!isViewMode && !ruling && issue && (() => {
            const state = analyzeRelationship(issue, 'ruling', rootStructure || {}, schema, { ruling: null })
            if (!state) return null
            return (
              <RelationshipAction
                state={state}
                parentNodeLabel="Issue"
                position="centered"
                onAdd={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleAddNode(type, rel, dir, issue.temp_id)}
                onSelect={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleSelectNode(type, rel, dir, issue.temp_id)}
              />
            )
          })()}
        </div>
      </div>
    )
  }, (prevProps, nextProps) => {
    // Custom comparison function - return true if props are equal (skip re-render)
    // Only re-render if the specific issue's data changed or view mode changed
    const rootEntityKey = Object.entries(prevProps.rootStructure).find(([, cfg]: [string, any]) => cfg.self)?.[0]
    const prevRootId = rootEntityKey ? prevProps.entityData[rootEntityKey]?.temp_id : prevProps.entityData[Object.keys(prevProps.entityData)[0]]?.temp_id
    const nextRootId = rootEntityKey ? nextProps.entityData[rootEntityKey]?.temp_id : nextProps.entityData[Object.keys(nextProps.entityData)[0]]?.temp_id
    
    // If root IDs are different, definitely re-render
    if (prevRootId !== nextRootId) return false
    
    // If view mode changed, re-render
    if (prevProps.isViewMode !== nextProps.isViewMode) return false
    
    // CRITICAL FIX: Check if IS_TYPE edges changed for reliefs in this issue
    // Extract all relief IDs from this issue's ruling
    const extractReliefIds = (entityData: any): string[] => {
      const ruling = entityData.ruling
      if (!ruling?.relief) return []
      return (Array.isArray(ruling.relief) ? ruling.relief : [])
        .map((r: any) => r?.temp_id)
        .filter((id: any): id is string => Boolean(id))
    }
    
    const reliefIds = extractReliefIds(prevProps.entityData)
    
    // If there are reliefs, check if their IS_TYPE edges changed
    if (reliefIds.length > 0) {
      const getReliefTypeEdgesHash = (edgesArray: any[], reliefIds: string[]): string => {
        return edgesArray
          .filter((e: any) => 
            e.label === 'IS_TYPE' && 
            e.status === 'active' && 
            reliefIds.includes(e.from)
          )
          .map((e: any) => `${e.from}:${e.to}`)
          .sort()
          .join('|')
      }
      
      const prevReliefTypeEdges = getReliefTypeEdgesHash(prevProps.edgesArray, reliefIds)
      const nextReliefTypeEdges = getReliefTypeEdgesHash(nextProps.edgesArray, reliefIds)
      
      // If relief type edges changed, re-render
      if (prevReliefTypeEdges !== nextReliefTypeEdges) return false
    }
    
    // Deep compare the entityData to see if THIS issue's data changed
    // This is the key optimization - we only care about this specific issue's data
    const prevEntityStr = JSON.stringify(prevProps.entityData)
    const nextEntityStr = JSON.stringify(nextProps.entityData)
    
    // If the specific entity data is the same, skip re-render (return true)
    // Ignore function prop changes - they're stable via useCallback
    return prevEntityStr === nextEntityStr
  })
  IssueSection.displayName = 'IssueSection'

  return (
    <div className="min-h-screen flex">
      {/* Sidebar Navigation */}
      <CaseSidebar
        isViewMode={isViewMode}
        setIsViewMode={setIsViewMode}
        caseNode={caseNode}
        proceedingNodes={proceedingNodes}
        forumNodes={forumNodes}
        partyNodes={partyNodes}
        holdingsData={rootEntities}
        structureInfo={structureInfo}
        rootStructure={rootStructure}
        activeHoldingId={activeHoldingId}
        activeNodeId={activeNodeId}
        activeNodeContext={activeNodeContext}
        partiesExpanded={partiesExpanded}
        setPartiesExpanded={setPartiesExpanded}
        partiesSectionExpanded={partiesSectionExpanded}
        setPartiesSectionExpanded={setPartiesSectionExpanded}
        expandedFacts={expandedFacts}
        deletedNodeIds={deletedNodeIds}
        orphanedNodeIds={orphanedNodeIds}
        reusedNodes={reusedNodes}
        globalNodeNumbering={globalNodeNumbering}
        scrollToHolding={scrollToHolding}
        scrollToNodeById={scrollToNodeById}
        toggleFact={toggleFact}
      />

      {/* Main Content */}
      <div className="flex-1 flex flex-col bg-gray-50">
        <div className="p-6 space-y-6 text-xs flex-1 overflow-y-auto">
          {/* Header with case name and domain */}
          <div className="flex items-center justify-between mb-4">
            <h1 className="text-2xl font-semibold tracking-tight">
              {caseNode ? pickNodeName(caseNode) || 'Case' : 'Case'}
            </h1>
            {isViewMode ? (
              <span className="px-3 py-1 bg-blue-500 text-white rounded-full text-sm font-medium">
                {domainName}
              </span>
            ) : (
              <select 
                value={(domainNode?.properties?.name as string) || ''}
                onChange={(e) => handleDomainChange(e.target.value)}
                className="px-3 py-1 border border-gray-300 rounded bg-white text-sm"
              >
                <option value="">Select Domain</option>
                {domainOptions.map((opt: string) => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
            )}
          </div>
          {error && (
            <div className="rounded-md border border-red-300 bg-red-50 px-4 py-3 text-xs text-red-700">
              {error.startsWith('Validation failed:') ? (
                <>
                  <div className="font-semibold mb-2">Validation Errors:</div>
                  <ul className="list-disc list-inside space-y-1">
                    {error.replace('Validation failed: ', '').split('; ').map((msg, idx) => (
                      <li key={idx}>{msg}</li>
                    ))}
                  </ul>
                </>
              ) : (
                error
              )}
            </div>
          )}

          {/* Top Section: Case, Proceedings, Forums, Parties */}
          <div className="space-y-4">
            <div className="border-b pb-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">Case Overview</h2>
              
              <div className="space-y-6">
                {/* Case Details */}
                {caseNode && renderNodeCard(caseNode, 'Case', { contextId: 'overview' })}
                
                {/* Proceedings Section */}
                {(() => {
                  const parentNode = getParentNodeFromConfig('proceedings')
                  const parentLabel = viewConfig?.topLevel?.proceedings?.from || 'Case'
                  const state = relationshipStates.proceedings
                  if (proceedingNodes.length === 0 && state) {
                    return !isViewMode ? (
                      <RelationshipAction
                        state={state}
                        parentNodeLabel={parentLabel}
                        position="centered"
                        onAdd={(type, rel, dir) => handleAddNode(type, rel, dir, parentNode?.temp_id)}
                        onSelect={(type, rel, dir) => handleSelectNode(type, rel, dir, parentNode?.temp_id)}
                      />
                    ) : null
                  }
                  return (
                    <div>
                      <SectionHeader
                        title="Proceedings"
                        actionButton={!isViewMode && state && (
                          <RelationshipAction
                            state={state}
                            parentNodeLabel={parentLabel}
                            position="inline"
                            onAdd={(type, rel, dir) => handleAddNode(type, rel, dir, parentNode?.temp_id)}
                            onSelect={(type, rel, dir) => handleSelectNode(type, rel, dir, parentNode?.temp_id)}
                          />
                        )}
                      />
                      <div className="space-y-4">
                        {proceedingNodes.map((proc: any, idx: number) => {
                          // Get live forum and jurisdiction for this proceeding
                          const { forum, jurisdiction } = getLiveForumAndJurisdiction(proc.temp_id)
                          
                          return renderNodeCard(proc, 'Proceeding', {
                            index: idx,
                            contextId: 'overview',
                            children: (
                              <div className="mt-4">
                                <ForumSelector
                                  proceedingId={proc.temp_id}
                                  currentForum={forum}
                                  currentJurisdiction={jurisdiction}
                                  isViewMode={isViewMode}
                                  onSelect={(forumNode: any, jurisdictionNode: any) => 
                                    handleForumSelect(proc.temp_id, forumNode, jurisdictionNode)
                                  }
                                />
                              </div>
                            )
                          })
                        })}
                      </div>
                    </div>
                  )
                })()}
                
                {/* Parties Section */}
                {(() => {
                  const parentNode = getParentNodeFromConfig('parties')
                  const parentLabel = viewConfig?.topLevel?.parties?.from || 'Proceeding'
                  const state = relationshipStates.parties
                  if (partyNodes.length === 0 && state) {
                    return !isViewMode ? (
                      <RelationshipAction
                        state={state}
                        parentNodeLabel={parentLabel}
                        position="centered"
                        onAdd={(type, rel, dir) => handleAddNode(type, rel, dir, parentNode?.temp_id)}
                        onSelect={(type, rel, dir) => handleSelectNode(type, rel, dir, parentNode?.temp_id)}
                      />
                    ) : null
                  }
                  return (
                    <div>
                      <div className="flex items-center justify-between mb-3">
                        <div 
                          onClick={() => setPartiesSectionExpanded(!partiesSectionExpanded)}
                          className="flex items-center gap-2 cursor-pointer hover:text-gray-900"
                        >
                          <span className="text-sm">{partiesSectionExpanded ? '▼' : '▶'}</span>
                          <h3 className="text-sm font-semibold text-gray-700">
                            Parties ({partyNodes.length})
                          </h3>
                        </div>
                        <div>
                          {!isViewMode && state && (
                            <RelationshipAction
                              state={state}
                              parentNodeLabel={parentLabel}
                              position="inline"
                              onAdd={(type, rel, dir) => handleAddNode(type, rel, dir, parentNode?.temp_id)}
                              onSelect={(type, rel, dir) => handleSelectNode(type, rel, dir, parentNode?.temp_id)}
                            />
                          )}
                        </div>
                      </div>
                      {partiesSectionExpanded && (
                        <div className="space-y-4">
                          {partyNodes.map((party: any, idx: number) => {
                            // Find the proceeding this party is connected to
                            const proceedingNode = parentNode || proceedingNodes[0]
                            const proceedingId = proceedingNode?.temp_id
                            
                            return renderNodeCard(party, 'Party', {
                              index: idx,
                              contextId: 'overview',
                              statusBadge: proceedingId ? (
                                <RelationshipPropertyField
                                  sourceId={proceedingId}
                                  targetId={party.temp_id}
                                  relLabel="INVOLVES"
                                  propName="role"
                                  sourceLabel="Proceeding"
                                  isViewMode={isViewMode}
                                  label="Role"
                                  schema={schema}
                                  getValue={relationshipProps.getPartyRole}
                                  setValue={relationshipProps.setPartyRole}
                                />
                              ) : undefined
                            })
                          })}
                        </div>
                      )}
                    </div>
                  )
                })()}
              </div>
            </div>

            {/* Root Entity Sections (Issues/Holdings) */}
            {rootEntities.map((entityData: any, idx: number) => (
              <IssueSection
                key={entityData[Object.keys(entityData)[0]]?.temp_id || idx}
                entityData={entityData}
                idx={idx}
                rootStructure={rootStructure}
                structureInfo={structureInfo}
                deletedNodeIds={deletedNodeIds}
                orphanedNodeIds={orphanedNodeIds}
                isViewMode={isViewMode}
                edgesArray={edgesArray}
                nodesArray={nodesArray}
                schema={schema}
                relationshipProps={relationshipProps}
                handleAddNode={handleAddNode}
                handleSelectNode={handleSelectNode}
                handleReliefTypeSelect={handleReliefTypeSelect}
                handleForumSelect={handleForumSelect}
                renderNodeCard={renderNodeCard}
                getLiveReliefType={getLiveReliefType}
                getLiveForumAndJurisdiction={getLiveForumAndJurisdiction}
              />
            ))}
            
            {/* Orphaned Nodes Section */}
            <OrphanedNodesSection orphanedNodes={orphanedNodes} graphState={graphState} />
          </div>
        </div>

        {/* Footer Save Button */}
        <CaseFooter
          isViewMode={isViewMode}
          hasUnsavedChanges={hasUnsavedChanges}
          orphanedNodesCount={orphanedNodes.length}
          scrollHistory={scrollHistory}
          saving={saving}
          submittingKg={submittingKg}
          error={error}
          onSave={onSave}
          onSubmitToKg={submitToKg}
          onBack={() => {
            if (typeof window === 'undefined') return
            setScrollHistory(prev => {
              const next = [...prev]
              const last = next.pop()
              if (typeof last === 'number') {
                window.scrollTo({ top: last, behavior: 'smooth' })
              }
              return next
            })
          }}
        />
      </div>

      {/* Delete Node Confirmation */}
      <DeleteNodeConfirmation
        nodeId={deletingNodeId}
        graphState={graphState}
        onCancel={() => setDeletingNodeId(null)}
        onConfirm={(nodeId) => {
          deleteNode(nodeId)
          setHasUnsavedChanges(true)
          setDeletingNodeId(null)
        }}
      />

      {/* Edit relationship modal */}
      <EditRelationshipModal
        edgeIndex={editingEdgeIdx}
        editToValue={editToValue}
        nodeOptions={nodeOptions}
        onCancel={() => setEditingEdgeIdx(null)}
        onSave={(edgeIdx, newValue) => {
          setValueAtPath(['edges', edgeIdx, 'to'], newValue)
          setEditingEdgeIdx(null)
        }}
        onEditToValueChange={setEditToValue}
      />

      {/* Delete relationship confirmation */}
      <DeleteRelationshipConfirmation
        edgeIndex={confirmDeleteIdx}
        onCancel={() => setConfirmDeleteIdx(null)}
        onConfirm={(idx) => {
          setGraphState((prev: any) => {
            const activeEdges = prev.edges.filter((e: any) => e.status === 'active')
            const edgeToDelete = activeEdges[idx!]
            if (!edgeToDelete) return prev
            
            return {
              ...prev,
              edges: prev.edges.map((e: any) => 
                e.from === edgeToDelete.from && 
                e.to === edgeToDelete.to && 
                e.label === edgeToDelete.label
                  ? { ...e, status: 'deleted' as const }
                  : e
              )
            }
          })
          setHasUnsavedChanges(true)
          setConfirmDeleteIdx(null)
        }}
      />
      
      {/* Add node modal */}
      <AddNodeModal
        open={addModalOpen}
        nodeType={addModalType}
        schema={schema}
        existingNodes={[...(catalogNodes[addModalType] || []), ...nodesArrayForModals]}
        parentContext={addModalContext?.parentId ? {
          parentId: addModalContext.parentId,
          parentLabel: getParentNodeLabel(addModalContext.parentId),
          relationship: addModalContext.relationship,
          direction: addModalContext.direction
        } : null}
        onCancel={() => {
          setAddModalOpen(false)
          setAddModalContext(null)
        }}
        onSubmit={({ node, edges }) => {
          setGraphState((prev: any) => {
            const nodes = [...prev.nodes]
            const nextEdges = [...prev.edges]

            const existingIndex = nodes.findIndex((n: any) => n.temp_id === node.temp_id)
            if (existingIndex >= 0) {
              const existing = nodes[existingIndex]
              if (existing.status !== 'active') {
                nodes[existingIndex] = { ...existing, status: 'active' as const }
              }
            } else {
              const newNode = {
                ...node,
                status: 'active' as const,
                source: 'user-created' as const
              }
              nodes.push(newNode)
            }

            const ensureActiveEdge = (from: string, to: string, label: string) => {
              const idx = nextEdges.findIndex((e: any) => e.from === from && e.to === to && e.label === label)
              if (idx >= 0) {
                if (nextEdges[idx].status !== 'active') {
                  nextEdges[idx] = { ...nextEdges[idx], status: 'active' as const }
                }
              } else {
                nextEdges.push({ from, to, label, status: 'active' as const })
              }
            }

            edges.forEach((e: any) => ensureActiveEdge(e.from, e.to, e.label))

            if (addModalContext?.parentId && addModalContext?.relationship) {
              const from = addModalContext.direction === 'outgoing' ? addModalContext.parentId : node.temp_id
              const to = addModalContext.direction === 'outgoing' ? node.temp_id : addModalContext.parentId
              ensureActiveEdge(from || '', to || '', addModalContext.relationship)
            }

            return { nodes, edges: nextEdges }
          })
          setHasUnsavedChanges(true)
          setAddModalOpen(false)
          setAddModalContext(null)
        }}
      />
      
      {/* Select node modal */}
      <SelectNodeModal
        open={selectModalOpen}
        nodeType={selectModalType}
        availableNodes={getAvailableNodesForSelection(selectModalType)}
        allNodes={nodesArrayForModals}
        allEdges={edgesArray}
        onCancel={() => {
          setSelectModalOpen(false)
          setSelectModalContext(null)
        }}
        onSubmit={handleSelectNodeSubmit}
      />
    </div>
  )
}

