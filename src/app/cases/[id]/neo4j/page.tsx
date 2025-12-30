'use client'

import React, { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { useParams, useRouter, useSearchParams } from 'next/navigation'
import { useSession } from 'next-auth/react'

import type { Schema } from '@/types/case-graph'
import { useAppStore } from '@/lib/store/appStore'
import { isAdminEmail } from '@/lib/admin'

import { useGraphState } from '@/hooks/cases/useGraphState'
import { useNodeLookups } from '@/app/cases/[id]/_hooks/useNodeLookups'
import { useUIState } from '@/app/cases/[id]/_hooks/useUIState'
import { useRelationshipProperties } from '@/hooks/cases/useRelationshipProperties'

import { pickNodeName } from '@/lib/cases/formatting'
import { buildNodeOptions, buildGlobalNodeNumbering } from '@/lib/cases/graphHelpers'
import { detectReusedNodes } from '@/lib/cases/graphHelpers'
import { formatLabel } from '@/lib/cases/formatting'

import { NodeCard } from '@/components/cases/editor/NodeCard'
import { CaseSidebar } from '@/components/cases/editor/CaseSidebar'
import { SectionHeader } from '@/components/cases/editor/SectionHeader'
import { ForumSelector } from '@/components/cases/editor/ForumSelector'
import { IssueSection } from '@/app/cases/[id]/_components/IssueSection'
import { ComparisonResults } from '@/components/cases/ComparisonResults'

type Neo4jCaseViewResponse = {
  success: boolean
  extracted?: any
  data?: any
  viewConfig?: any
  error?: string
  detail?: string
}

export default function Neo4jCaseViewPage() {
  const params = useParams()
  const router = useRouter()
  const searchParams = useSearchParams()
  const { data: session, status: sessionStatus } = useSession()

  const id = params?.id as string
  // Get the Neo4j case_id from query params (passed from the case page)
  const neo4jCaseId = searchParams.get('neo4j_case_id')
  
  const schema = useAppStore((s) => s.schema as Schema | null)

  const isAdmin = isAdminEmail(session?.user?.email)
  const isViewMode = true

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [extracted, setExtracted] = useState<any>(null)
  const [displayData, setDisplayData] = useState<any>(null)
  const [viewConfig, setViewConfig] = useState<any>(null)
  
  // Comparison state
  const [comparisonLoading, setComparisonLoading] = useState(false)
  const [comparisonError, setComparisonError] = useState<string | null>(null)
  const [comparisonData, setComparisonData] = useState<any>(null)

  // Protect route
  useEffect(() => {
    if (sessionStatus === 'loading') return
    if (!session || !isAdmin) {
      router.replace(`/cases/${id}`)
    }
  }, [session, sessionStatus, isAdmin, router, id])

  // Fetch Neo4j-backed view payload
  useEffect(() => {
    if (!id) return
    if (!neo4jCaseId) {
      setError('Missing Neo4j case ID. Please access this page from the case view.')
      setLoading(false)
      return
    }
    if (sessionStatus !== 'authenticated') return
    if (!isAdmin) return

    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        // Pass the Neo4j case_id directly to the backend
        const res = await fetch(`/api/admin/neo4j-cases/${encodeURIComponent(neo4jCaseId)}/view?view=holdingsCentric`)
        const data = (await res.json()) as Neo4jCaseViewResponse
        if (!res.ok || !data?.success) {
          throw new Error(data?.error || data?.detail || 'Failed to load Neo4j case view')
        }
        setExtracted(data.extracted || null)
        setDisplayData(data.data || null)
        setViewConfig(data.viewConfig || null)
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load Neo4j case view')
      } finally {
        setLoading(false)
      }
    })()
  }, [id, neo4jCaseId, sessionStatus, isAdmin])

  // Graph state
  const { graphState, setGraphState, nodesArray, edgesArray, deletedNodeIds, orphanedNodeIds } = useGraphState(
    [],
    []
  )

  // Initialize graph state directly from extracted data (simpler than useCatalogEnrichment)
  // Neo4j data is already complete - no need for catalog enrichment
  const [graphInitialized, setGraphInitialized] = useState(false)
  
  useEffect(() => {
    if (extracted && !graphInitialized) {
      const nodes = extracted.nodes || []
      const edges = extracted.edges || []
      
      const initialNodes = nodes.map((n: any) => ({ 
        ...n, 
        status: 'active' as const, 
        source: 'initial' as const 
      }))
      const initialEdges = edges.map((e: any) => ({ 
        ...e, 
        status: 'active' as const,
        properties: e.properties || {}
      }))
      
      setGraphState({
        nodes: initialNodes,
        edges: initialEdges
      })
      setGraphInitialized(true)
    }
  }, [extracted, graphInitialized, setGraphState])

  // Node/edge lookups
  const { edgesByFrom, edgesByTo, nodeById, getLiveReliefType, getLiveForumAndJurisdiction } = useNodeLookups(
    nodesArray as any[],
    edgesArray as any[],
    graphState as any
  )

  const relationshipProps = useRelationshipProperties(graphState as any, setGraphState as any, () => {})

  const { uiState, uiActions } = useUIState()

  const nodeOptions = useMemo(() => buildNodeOptions(nodesArray as any[], pickNodeName), [nodesArray])
  const nodeIdToDisplay = useMemo(() => {
    const map: Record<string, string> = {}
    nodeOptions.forEach((o: any) => {
      map[o.id] = o.display
    })
    return map
  }, [nodeOptions])

  const globalNodeNumbering = useMemo(
    () => buildGlobalNodeNumbering(graphState as any, displayData),
    [graphState, displayData]
  )

  const reusedNodes = useMemo(() => detectReusedNodes(graphState as any), [graphState])

  // Extract structure key and root label from view config
  const structureInfo = useMemo(() => {
    if (!viewConfig) return { key: null, rootLabel: null, structure: {} }
    for (const [key, value] of Object.entries(viewConfig)) {
      if (key === 'topLevel' || key === 'description') continue
      if (typeof value === 'object' && value !== null && 'root' in value) {
        return {
          key,
          rootLabel: (value as any).root,
          structure: (value as any).structure || {},
        }
      }
    }
    return { key: null, rootLabel: null, structure: {} }
  }, [viewConfig])

  const rootStructure = useMemo(() => structureInfo.structure, [structureInfo])

  const rootEntities = useMemo(() => {
    if (!displayData || !structureInfo.key) return []
    const rootCollection = displayData[structureInfo.key]
    if (!Array.isArray(rootCollection)) return []
    return rootCollection
  }, [displayData, structureInfo])

  const caseNode = useMemo(() => {
    return (nodesArray || []).find((n: any) => n.label === 'Case') || null
  }, [nodesArray])

  const domainNode = useMemo(() => {
    return (graphState as any).nodes?.find((n: any) => n.label === 'Domain' && n.status === 'active') || null
  }, [graphState])

  const domainName = String(domainNode?.properties?.name || 'Unknown')

  const getRelatedNodes = useCallback(
    (parentId: string | undefined, relLabel: string, direction: 'outgoing' | 'incoming' = 'outgoing') => {
      if (!parentId) return []
      const edges =
        direction === 'outgoing'
          ? (edgesByFrom.get(parentId) || []).filter((e) => e.label === relLabel)
          : (edgesByTo.get(parentId) || []).filter((e) => e.label === relLabel)
      const ids = new Set<string>()
      const results: any[] = []
      edges.forEach((edge: any) => {
        const targetId = direction === 'outgoing' ? edge.to : edge.from
        if (targetId && !ids.has(targetId)) {
          const node = nodeById.get(targetId)
          if (node) {
            ids.add(targetId)
            results.push(node)
          }
        }
      })
      return results
    },
    [edgesByFrom, edgesByTo, nodeById]
  )

  const proceedingNodes = useMemo(() => {
    return caseNode ? getRelatedNodes(caseNode.temp_id, 'HAS_PROCEEDING', 'outgoing') : []
  }, [caseNode, getRelatedNodes])

  const forumNodes = useMemo(() => {
    const seen = new Set<string>()
    const results: any[] = []
    proceedingNodes.forEach((proc: any) => {
      getRelatedNodes(proc.temp_id, 'HEARD_IN', 'outgoing').forEach((n: any) => {
        if (!seen.has(n.temp_id)) {
          seen.add(n.temp_id)
          results.push(n)
        }
      })
    })
    return results
  }, [proceedingNodes, getRelatedNodes])

  const partyNodes = useMemo(() => {
    const seen = new Set<string>()
    const results: any[] = []
    proceedingNodes.forEach((proc: any) => {
      getRelatedNodes(proc.temp_id, 'INVOLVES', 'outgoing').forEach((n: any) => {
        if (!seen.has(n.temp_id)) {
          seen.add(n.temp_id)
          results.push(n)
        }
      })
    })
    return results
  }, [proceedingNodes, getRelatedNodes])

  const pendingEditsRef = useRef<Record<string, any>>({})
  const setPendingEdit = useCallback(() => {}, [])
  const setValueAtPath = useCallback(() => {}, [])
  const noop = useCallback(() => {}, [])

  const getGlobalNodeNumber = useCallback(
    (nodeId: string, nodeLabel: string) => globalNodeNumbering[nodeLabel]?.[nodeId] ?? null,
    [globalNodeNumbering]
  )

  const renderNodeCard = useCallback(
    (
      node: any,
      label: string,
      options: {
        index?: number
        depth?: number
        badge?: React.ReactNode
        statusBadge?: React.ReactNode
        children?: React.ReactNode
        parentId?: string
        contextId?: string
      } = {}
    ) => {
      const liveNode = nodeById.get(node.temp_id) || node
      const globalNum = getGlobalNodeNumber(node.temp_id, node.label)
      const isReused = reusedNodes.has(node.temp_id)
      const parentLabel = options.parentId ? formatLabel(nodeById.get(options.parentId)?.label || 'parent') : ''

      // Include parentId and index in key to handle shared/reused nodes and duplicates
      const keyParts = [options.contextId || 'ctx']
      if (options.parentId) keyParts.push(options.parentId)
      keyParts.push(node.temp_id)
      // Add index to handle duplicate nodes in the same list
      if (options.index !== undefined) keyParts.push(String(options.index))
      const uniqueKey = keyParts.join('-')

      return (
        <NodeCard
          key={uniqueKey}
          node={liveNode}
          label={label}
          index={options.index}
          depth={options.depth || 0}
          badge={options.badge}
          statusBadge={options.statusBadge}
          parentId={options.parentId}
          contextId={options.contextId}
          isViewMode={true}
          globalNodeNumber={globalNum}
          isReused={isReused}
          isExistingNode={false}
          shouldShowUnlink={false}
          parentLabel={parentLabel}
          onDelete={noop}
          onUnlink={noop as any}
          graphState={graphState}
          schema={schema}
          setPendingEdit={setPendingEdit as any}
          setValueAtPath={setValueAtPath as any}
          pendingEditsRef={pendingEditsRef}
          nodeOptions={nodeOptions as any}
          nodeIdToDisplay={nodeIdToDisplay}
        >
          {options.children}
        </NodeCard>
      )
    },
    [
      nodeById,
      reusedNodes,
      getGlobalNodeNumber,
      noop,
      graphState,
      schema,
      setPendingEdit,
      setValueAtPath,
      nodeOptions,
      nodeIdToDisplay,
    ]
  )

  const scrollToHolding = (holdingId: string) => {
    uiActions.setActiveHolding(holdingId)
    uiActions.setActiveNode(holdingId, holdingId)
    const el = document.getElementById(`holding-${holdingId}`)
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const scrollToNodeById = (nodeId: string, holdingId?: string, context?: string) => {
    if (holdingId) uiActions.setActiveHolding(holdingId)
    uiActions.setActiveNode(nodeId, context || holdingId || null)
    const elementId = context ? `node-${context}-${nodeId}` : `node-${nodeId}`
    const el = document.getElementById(elementId)
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const toggleFact = (factId: string) => uiActions.toggleFact(factId)

  // Comparison handler
  const handleCompare = useCallback(async () => {
    if (!neo4jCaseId || !id) return
    
    setComparisonLoading(true)
    setComparisonError(null)
    
    try {
      const res = await fetch(
        `/api/admin/neo4j-cases/${encodeURIComponent(neo4jCaseId)}/compare?postgres_case_id=${encodeURIComponent(id)}`
      )
      const data = await res.json()
      
      if (!res.ok || !data?.success) {
        throw new Error(data?.error || data?.detail || 'Comparison failed')
      }
      
      setComparisonData(data)
    } catch (e) {
      setComparisonError(e instanceof Error ? e.message : 'Comparison failed')
    } finally {
      setComparisonLoading(false)
    }
  }, [neo4jCaseId, id])

  if (sessionStatus === 'loading' || !session) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-gray-600">Loading...</div>
      </div>
    )
  }

  if (!isAdmin) return null

  // Check for errors FIRST (before loading check)
  if (error) {
    return (
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-3xl mx-auto px-4 py-10">
          <div className="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-800">
            {error}
          </div>
        </div>
      </div>
    )
  }

  // Show loading state while fetching or while graph state is being initialized
  if (loading || !extracted || (graphState as any).nodes.length === 0) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="rounded-md border bg-gray-50 px-2 py-1 text-xs text-gray-600">
          Loading Neo4j view...
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex">
      <CaseSidebar
        isViewMode={true}
        setIsViewMode={() => {}}
        hideModeToggle={true}
        caseNode={caseNode}
        proceedingNodes={proceedingNodes}
        forumNodes={forumNodes}
        partyNodes={partyNodes}
        holdingsData={rootEntities}
        structureInfo={structureInfo as any}
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

      <div className="flex-1 flex flex-col bg-gray-50">
        <div className="p-6 space-y-6 text-xs flex-1 overflow-y-auto">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-semibold tracking-tight">
                {caseNode ? pickNodeName(caseNode) || 'Case' : 'Case'}
              </h1>
              <span className="text-xs text-gray-500">(Neo4j view — read-only)</span>
            </div>
            <span className="px-3 py-1 bg-blue-500 text-white rounded-full text-sm font-medium">
              {domainName}
            </span>
          </div>

          {/* Comparison Section */}
          <ComparisonResults
            loading={comparisonLoading}
            error={comparisonError}
            data={comparisonData}
            onCompare={handleCompare}
          />

          {/* Top Section */}
          <div className="space-y-4">
            <div className="border-b pb-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">Case Overview</h2>

              <div className="space-y-6">
                {caseNode && renderNodeCard(caseNode, 'Case', { contextId: 'overview' })}

                {/* Proceedings */}
                <div>
                  <SectionHeader title="Proceedings" actionButton={null} />
                  <div className="space-y-4">
                    {proceedingNodes.map((proc: any, idx: number) => {
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
                              isViewMode={true}
                              onSelect={() => {}}
                            />
                          </div>
                        ),
                      })
                    })}
                  </div>
                </div>
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
                isViewMode={true}
                edgesArray={edgesArray as any[]}
                schema={schema}
                relationshipProps={relationshipProps}
                handleAddNode={() => {}}
                handleSelectNode={() => {}}
                handleReliefTypeSelect={() => {}}
                renderNodeCard={renderNodeCard}
                getLiveReliefType={getLiveReliefType}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}


