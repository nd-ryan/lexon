"use client";
import React, { useMemo, useState, useCallback } from 'react'
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
import { buildNodeOptions, buildGlobalNodeNumbering, detectReusedNodes } from '@/lib/cases/graphHelpers'
import { isExistingNode } from '@/lib/cases/nodeHelpers'
import { validateRequiredFields } from '@/lib/cases/validation'
import { useNodeLookups } from './_hooks/useNodeLookups'
import { useUIState } from './_hooks/useUIState'
import { useCatalogEnrichment } from './_hooks/useCatalogEnrichment'
import { useGraphTransition } from './_hooks/useGraphTransition'

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
import { ForumSelector } from '@/components/cases/editor/ForumSelector'
import { IssueSection } from './_components/IssueSection'

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
  const { pendingEditsRef, setPendingEdit, clearPendingEdits, versionTimerRef } = usePendingEdits()
  
  // Relationship properties
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
  
  // Catalog enrichment - automatically add catalog nodes referenced by edges
  // NOTE: This hook also initializes graphState from data, so we don't need a separate useEffect
  useCatalogEnrichment(data, catalogNodes as any, graphState, setGraphState, setHasUnsavedChanges)
  
  // Graph transitions for non-blocking updates
  const { updateGraph } = useGraphTransition(setGraphState, setHasUnsavedChanges)
  
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
  const { uiState, uiActions } = useUIState()

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
  
  // Node and edge lookups
  const {
    edgesByFrom,
    edgesByTo,
    nodeById,
    getLiveReliefType,
    getLiveForumAndJurisdiction
  } = useNodeLookups(nodesArray as any[], edgesArray as any[], graphState)
  
  // Domain state
  const domainNode = useMemo(() => {
    return graphState.nodes.find((n: any) => n.label === 'Domain' && n.status === 'active')
  }, [graphState])
  
  const domainName = String(domainNode?.properties?.name || 'Unknown')
  
  const domainOptions = useMemo(() => {
    const domainLabel = schema?.find((l: any) => l.label === 'Domain')
    return domainLabel?.properties?.name?.ui?.options || ['Free Speech', 'Antitrust']
  }, [schema])
  
  // Deduplicated existing nodes for AddNodeModal (combines catalog and case nodes)
  const deduplicatedExistingNodes = useMemo(() => {
    const catalog = catalogNodes[uiState.addModal.type] || []
    const all = [...catalog, ...nodesArrayForModals]
    // Deduplicate by temp_id
    const seen = new Set<string>()
    return all.filter(node => {
      if (seen.has(node.temp_id)) return false
      seen.add(node.temp_id)
      return true
    })
  }, [catalogNodes, uiState.addModal.type, nodesArrayForModals])
  
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
    uiActions.setActiveHolding(holdingId)
    uiActions.setActiveNode(holdingId, holdingId)
    const el = document.getElementById(`holding-${holdingId}`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }
  
  const scrollToNodeById = (nodeId: string, holdingId?: string, context?: string) => {
    if (holdingId) uiActions.setActiveHolding(holdingId)
    uiActions.setActiveNode(nodeId, context || holdingId || null)
    // Use context-specific ID if context is provided, otherwise fallback to basic ID
    const elementId = context ? `node-${context}-${nodeId}` : `node-${nodeId}`
    const el = document.getElementById(elementId)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }

  const toggleFact = (factId: string) => {
    uiActions.toggleFact(factId)
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
    uiActions.openAddModal(nodeType, { parentId, relationship, direction })
  }, [uiActions])

  const handleSelectNode = useCallback((
    nodeType: string, 
    relationship: string, 
    direction: 'outgoing' | 'incoming',
    parentId?: string
  ) => {
    uiActions.openSelectModal(nodeType, { parentId, relationship, direction })
  }, [uiActions])

  const getAvailableNodesForSelection = (nodeType: string) => {
    return catalogNodes[nodeType] || []
  }

  const handleSelectNodeSubmit = (selectedNodeId: string) => {
    if (!uiState.selectModal.context) return

    const { parentId, relationship, direction } = uiState.selectModal.context
    const selectedNode = getAvailableNodesForSelection(uiState.selectModal.type).find(
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
    uiActions.closeSelectModal()
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
    
    // Remove the node from its parent in displayData so it disappears immediately
    if (displayData && nodeId && parentId) {
      setDisplayData((prevDisplayData: any) => {
        if (!prevDisplayData) return prevDisplayData
        
        // Helper to recursively find parent and remove child
        const removeChildFromParent = (obj: any): any => {
          if (!obj || typeof obj !== 'object') return obj
          
          // If this is the parent node, remove child from all arrays
          if (obj.temp_id === parentId) {
            const updated: any = {}
            for (const [key, value] of Object.entries(obj)) {
              if (Array.isArray(value)) {
                // Remove the unlinked node from this array
                updated[key] = value.filter((item: any) => item?.temp_id !== nodeId)
              } else {
                updated[key] = value
              }
            }
            return updated
          }
          
          // Recursively search in nested objects/arrays
          if (Array.isArray(obj)) {
            return obj.map(removeChildFromParent)
          } else {
            const updated: any = {}
            for (const [key, value] of Object.entries(obj)) {
              updated[key] = removeChildFromParent(value)
            }
            return updated
          }
        }
        
        return removeChildFromParent(prevDisplayData)
      })
    }
  }

  const handleReliefTypeSelect = useCallback((reliefId: string, reliefTypeNode: any) => {
    updateGraph((prev: any) => {
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
  }, [updateGraph])
  
  const handleForumSelect = useCallback((proceedingId: string, forumNode: any, jurisdictionNode: any | null) => {
    updateGraph((prev: any) => {
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
  }, [updateGraph])

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
        onDelete={uiActions.startDeleteNode}
        onUnlink={handleUnlink}
        graphState={graphState}
        schema={schema}
        setPendingEdit={(path, value) => {
          setPendingEdit(path, value)
          setHasUnsavedChanges(true)
        }}
        setValueAtPath={setValueAtPath}
        pendingEditsRef={pendingEditsRef}
        nodeOptions={nodeOptions}
        nodeIdToDisplay={nodeIdToDisplay}
      >
        {options.children}
      </NodeCard>
    )
  }, [
    getLiveNode, getGlobalNodeNumber, reusedNodes, shouldShowUnlink,
    getParentLabel, isViewMode, graphState, schema, setPendingEdit, setValueAtPath,
    pendingEditsRef, nodeOptions, nodeIdToDisplay, uiActions.startDeleteNode,
    handleUnlink, setHasUnsavedChanges
  ])

  // Early return after all hooks
  // Wait for both data AND graph state to be initialized
  if (!data || graphState.nodes.length === 0) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="rounded-md border bg-gray-50 px-2 py-1 text-xs text-gray-600">Loading...</div>
      </div>
    )
  }

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
        activeHoldingId={uiState.activeHoldingId}
        activeNodeId={uiState.activeNodeId}
        activeNodeContext={uiState.activeNodeContext}
        partiesExpanded={uiState.partiesExpanded}
        setPartiesExpanded={uiActions.setPartiesExpanded}
        partiesSectionExpanded={uiState.partiesSectionExpanded}
        setPartiesSectionExpanded={uiActions.setPartiesSectionExpanded}
        expandedFacts={uiState.expandedFacts}
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
                          onClick={() => uiActions.setPartiesSectionExpanded(!uiState.partiesSectionExpanded)}
                          className="flex items-center gap-2 cursor-pointer hover:text-gray-900"
                        >
                          <span className="text-sm">{uiState.partiesSectionExpanded ? '▼' : '▶'}</span>
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
                      {uiState.partiesSectionExpanded && (
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
                schema={schema}
                relationshipProps={relationshipProps}
                handleAddNode={handleAddNode}
                handleSelectNode={handleSelectNode}
                handleReliefTypeSelect={handleReliefTypeSelect}
                renderNodeCard={renderNodeCard}
                getLiveReliefType={getLiveReliefType}
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
          scrollHistory={uiState.scrollHistory}
          saving={saving}
          submittingKg={submittingKg}
          error={error}
          onSave={onSave}
          onSubmitToKg={submitToKg}
          onBack={() => {
            if (typeof window === 'undefined') return
            const last = uiState.scrollHistory[uiState.scrollHistory.length - 1]
            if (typeof last === 'number') {
              window.scrollTo({ top: last, behavior: 'smooth' })
            }
            uiActions.popScrollHistory()
          }}
        />
      </div>

      {/* Delete Node Confirmation */}
      <DeleteNodeConfirmation
        nodeId={uiState.deletingNode.nodeId}
        graphState={graphState}
        onCancel={uiActions.cancelDeleteNode}
        onConfirm={(nodeId) => {
          deleteNode(nodeId)
          setHasUnsavedChanges(true)
          
          // Remove the node from displayData so it disappears immediately
          if (displayData && nodeId) {
            setDisplayData((prevDisplayData: any) => {
              if (!prevDisplayData) return prevDisplayData
              
              // Helper to recursively remove node from display data
              const removeNodeFromStructure = (obj: any): any => {
                if (!obj || typeof obj !== 'object') return obj
                
                if (Array.isArray(obj)) {
                  // Filter out the deleted node from arrays
                  return obj
                    .filter((item: any) => item?.temp_id !== nodeId)
                    .map(removeNodeFromStructure)
                } else {
                  const updated: any = {}
                  for (const [key, value] of Object.entries(obj)) {
                    // Skip if this node is the one being deleted
                    if (key === 'temp_id' && value === nodeId) {
                      return null // Mark for removal
                    }
                    updated[key] = removeNodeFromStructure(value)
                  }
                  return updated
                }
              }
              
              const result = removeNodeFromStructure(prevDisplayData)
              return result === null ? prevDisplayData : result
            })
          }
          
          uiActions.cancelDeleteNode()
        }}
      />

      {/* Edit relationship modal */}
      <EditRelationshipModal
        edgeIndex={uiState.editRelationship.edgeIdx}
        editToValue={uiState.editRelationship.toValue}
        nodeOptions={nodeOptions}
        onCancel={uiActions.cancelEditRelationship}
        onSave={(edgeIdx, newValue) => {
          setValueAtPath(['edges', edgeIdx, 'to'], newValue)
          uiActions.cancelEditRelationship()
        }}
        onEditToValueChange={uiActions.updateEditToValue}
      />

      {/* Delete relationship confirmation */}
      <DeleteRelationshipConfirmation
        edgeIndex={uiState.confirmDelete.edgeIdx}
        onCancel={uiActions.cancelConfirmDelete}
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
          uiActions.cancelConfirmDelete()
        }}
      />
      
      {/* Add node modal */}
      <AddNodeModal
        open={uiState.addModal.open}
        nodeType={uiState.addModal.type}
        schema={schema}
        existingNodes={deduplicatedExistingNodes}
        parentContext={uiState.addModal.context?.parentId ? {
          parentId: uiState.addModal.context.parentId,
          parentLabel: getParentNodeLabel(uiState.addModal.context.parentId),
          relationship: uiState.addModal.context.relationship,
          direction: uiState.addModal.context.direction
        } : null}
        onCancel={uiActions.closeAddModal}
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

            if (uiState.addModal.context?.parentId && uiState.addModal.context?.relationship) {
              const from = uiState.addModal.context.direction === 'outgoing' ? uiState.addModal.context.parentId : node.temp_id
              const to = uiState.addModal.context.direction === 'outgoing' ? node.temp_id : uiState.addModal.context.parentId
              ensureActiveEdge(from || '', to || '', uiState.addModal.context.relationship)
            }

            return { nodes, edges: nextEdges }
          })
          setHasUnsavedChanges(true)
          
          // Insert the new node into displayData so it appears immediately
          if (uiState.addModal.context?.parentId && uiState.addModal.context?.relationship && displayData && structureInfo.key) {
            setDisplayData((prevDisplayData: any) => {
              if (!prevDisplayData) return prevDisplayData
              
              const relationship = uiState.addModal.context?.relationship
              
              // Find the key in the viewConfig structure that corresponds to this relationship
              const findKeyForRelationship = (structure: any): string | null => {
                if (!structure || typeof structure !== 'object') return null
                
                for (const [key, config] of Object.entries(structure)) {
                  const cfg = config as any
                  if (cfg.via === relationship || cfg.from?.relationship === relationship) {
                    return key
                  }
                  // Also check nested include structures
                  if (cfg.include) {
                    const nestedKey = findKeyForRelationship(cfg.include)
                    if (nestedKey) return nestedKey
                  }
                }
                return null
              }
              
              const childKey = findKeyForRelationship(rootStructure) || node.label.toLowerCase() + 's'
              
              // Helper to recursively find and update parent node in display data
              const insertNodeIntoParent = (obj: any): any => {
                if (!obj || typeof obj !== 'object') return obj
                
                // If this is the parent node, add child to appropriate relationship
                if (obj.temp_id === uiState.addModal.context?.parentId) {
                  const updated = { ...obj }
                  
                  // Add node to the collection (create array if needed)
                  if (!updated[childKey]) {
                    updated[childKey] = []
                  } else if (!Array.isArray(updated[childKey])) {
                    updated[childKey] = [updated[childKey]]
                  }
                  
                  // Check if node already exists in the array
                  const existingIdx = updated[childKey].findIndex((n: any) => n?.temp_id === node.temp_id)
                  if (existingIdx === -1) {
                    updated[childKey] = [...updated[childKey], node]
                  }
                  
                  return updated
                }
                
                // Recursively search in nested objects/arrays
                if (Array.isArray(obj)) {
                  return obj.map(insertNodeIntoParent)
                } else {
                  const updated: any = {}
                  for (const [key, value] of Object.entries(obj)) {
                    updated[key] = insertNodeIntoParent(value)
                  }
                  return updated
                }
              }
              
              return insertNodeIntoParent(prevDisplayData)
            })
          }
          
          uiActions.closeAddModal()
        }}
      />
      
      {/* Select node modal */}
      <SelectNodeModal
        open={uiState.selectModal.open}
        nodeType={uiState.selectModal.type}
        availableNodes={getAvailableNodesForSelection(uiState.selectModal.type)}
        allNodes={nodesArrayForModals}
        allEdges={edgesArray}
        onCancel={uiActions.closeSelectModal}
        onSubmit={handleSelectNodeSubmit}
      />
    </div>
  )
}

