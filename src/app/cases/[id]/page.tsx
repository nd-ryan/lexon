"use client";
import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'next/navigation'
import type { CaseGraph, GraphEdge, GraphNode, Schema } from '@/types/case-graph'
import Button from '@/components/ui/button'
import { Pencil, Trash2 } from 'lucide-react'
import { useAppStore } from '@/lib/store/appStore'
import AddNodeModal from '@/components/cases/AddNodeModal.client'
import SelectNodeModal from '@/components/cases/SelectNodeModal.client'
import RelationshipAction from '@/components/cases/RelationshipAction.client'
import { analyzeRelationship } from '@/lib/relationshipHelpers'

// Unified node/edge types with status tracking
type NodeStatus = 'active' | 'deleted' | 'orphaned'

interface UnifiedNode extends GraphNode {
  status: NodeStatus
  source: 'initial' | 'user-created'
}

interface UnifiedEdge extends GraphEdge {
  status: 'active' | 'deleted'
}

export default function CaseEditorPage() {
  const params = useParams()
  const id = params?.id as string
  const schema = useAppStore(s => s.schema as Schema | null)
  const catalogNodes = useAppStore(s => s.catalogNodes)
  const [data, setData] = useState<CaseGraph | null>(null)
  
  // Unified state: single source of truth for all nodes and edges
  const [graphState, setGraphState] = useState<{
    nodes: UnifiedNode[]
    edges: UnifiedEdge[]
  }>({ nodes: [], edges: [] })
  
  // displayData removed as a stateful dependency; we derive UI solely from graphState + viewConfig
  const [viewConfig, setViewConfig] = useState<any>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
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
  // Local edit widgets commit on blur to avoid full re-render per keystroke
  const [activeHoldingId, setActiveHoldingId] = useState<string | null>(null)
  const [expandedArgs, setExpandedArgs] = useState<Set<string>>(new Set())
  const [expandedFacts, setExpandedFacts] = useState<Set<string>>(new Set())
  const [viewingConnectionsNodeId, setViewingConnectionsNodeId] = useState<string | null>(null)
  const [deletingNodeId, setDeletingNodeId] = useState<string | null>(null)
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)

  useEffect(() => {
    // Debug: track when edit modal state changes
    // eslint-disable-next-line no-console
    console.debug('editingEdgeIdx changed:', editingEdgeIdx)
  }, [editingEdgeIdx])

  useEffect(() => {
    // Debug: track when delete modal state changes
    // eslint-disable-next-line no-console
    console.debug('confirmDeleteIdx changed:', confirmDeleteIdx)
  }, [confirmDeleteIdx])


  useEffect(() => {
    (async () => {
      // Fetch both raw and display data
      const [rawRes, displayRes] = await Promise.all([
        fetch(`/api/cases/${id}`),
        fetch(`/api/cases/${id}/display`)
      ])
      const rawData = await rawRes.json()
      const display = await displayRes.json()
      
      setData(rawData.case)
      setViewConfig(display.success ? display.viewConfig : null)
      
      // Use raw extracted graph directly - no need to extract from display!
      const extracted = rawData.case?.extracted || { nodes: [], edges: [] }
      
      setGraphState({
        nodes: extracted.nodes.map((n: any) => ({ 
          ...n, 
          status: 'active' as const, 
          source: 'initial' as const 
        })),
        edges: extracted.edges.map((e: any) => ({ 
          ...e, 
          status: 'active' as const 
        }))
      })
      
      setHasUnsavedChanges(false)
    })()
  }, [id])

  const onSave = async () => {
    try {
      setSaving(true); setError('')
      
      // Determine which nodes should be permanently deleted
      const activeEdges = graphState.edges.filter(e => e.status === 'active')
      const nodesToDelete = new Set<string>()
      
      // Mark deleted nodes
      graphState.nodes.forEach(n => {
        if (n.status === 'deleted') {
          nodesToDelete.add(n.temp_id)
        }
      })
      
      // Mark orphaned nodes that have no active parents
      graphState.nodes.forEach(n => {
        if (n.status === 'orphaned') {
          const hasActiveParent = activeEdges.some(e => 
            e.to === n.temp_id && 
            !nodesToDelete.has(e.from) &&
            graphState.nodes.find(p => p.temp_id === e.from && p.status === 'active')
          )
          if (!hasActiveParent) {
            nodesToDelete.add(n.temp_id)
          }
        }
      })
      
      // Build final payload with only active nodes and edges
      const finalData = {
        nodes: graphState.nodes
          .filter(n => n.status === 'active')
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
          .map(({ status, source, ...node }) => node), // Strip metadata
        edges: graphState.edges
          .filter(e => 
            e.status === 'active' && 
            !nodesToDelete.has(e.from) && 
            !nodesToDelete.has(e.to)
          )
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
          .map(({ status, ...edge }) => edge) // Strip metadata
      }
      
      const res = await fetch(`/api/cases/${id}`, { 
        method: 'PUT', 
        headers: { 'Content-Type': 'application/json' }, 
        body: JSON.stringify(finalData) 
      })
      
      const d = await res.json()
      setData(d.case)
      
      // Refetch display data after save for updated viewConfig
      const displayRes = await fetch(`/api/cases/${id}/display`)
      const display = await displayRes.json()
      setViewConfig(display.success ? display.viewConfig : null)
      
      // Rebuild unified state from fresh raw data
      const extracted = d.case?.extracted || { nodes: [], edges: [] }
      
      setGraphState({
        nodes: extracted.nodes.map((n: any) => ({ 
          ...n, 
          status: 'active' as const, 
          source: 'initial' as const 
        })),
        edges: extracted.edges.map((e: any) => ({ 
          ...e, 
          status: 'active' as const 
        }))
      })
      
      setHasUnsavedChanges(false)
    } catch (e: any) {
      setError(e?.message || 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  const formatLabel = (label: string) => {
    if (label === 'root') return 'Case'
    const spaced = label
      .replace(/[_-]/g, ' ')
      .replace(/([a-z])([A-Z])/g, '$1 $2')
      .replace(/\s+/g, ' ')
      .trim()
    return spaced.charAt(0).toUpperCase() + spaced.slice(1)
  }

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
  
  // Extract holdings structure from view config
  const holdingsStructure = useMemo(() => {
    return viewConfig?.holdings?.structure || {}
  }, [viewConfig])
  
  // Derive holdings structure purely from graphState + viewConfig
  const holdingsData = useMemo(() => {
    const holdingNodes = (nodesArray || []).filter((n: any) => n.label === 'Holding')
    
    const buildRelated = (
      nodeId: string, 
      relLabel: string, 
      direction: 'outgoing' | 'incoming' = 'outgoing'
    ) => {
      const relEdges = direction === 'outgoing'
        ? edgesArray.filter(e => e.from === nodeId && e.label === relLabel)
        : edgesArray.filter(e => e.to === nodeId && e.label === relLabel)
      return relEdges
        .map(edge => nodesArray.find(n => n.temp_id === (direction === 'outgoing' ? edge.to : edge.from)))
        .filter(Boolean)
    }
    
    return holdingNodes.map((holding: any) => {
      const rulings = buildRelated(holding.temp_id, 'SETS', 'incoming')
      const ruling = rulings[0] || null
      
      const issues = buildRelated(holding.temp_id, 'ON_ISSUE')
      const issue = issues[0] || null
      
      const args = buildRelated(holding.temp_id, 'EVALUATED_IN', 'incoming')
      
      return {
        holding,
        ruling: ruling ? {
          ...ruling,
          reliefTypes: buildRelated(ruling.temp_id, 'RESULTS_IN')
        } : null,
        issue: issue ? {
          ...issue,
          doctrines: buildRelated(issue.temp_id, 'RELATES_TO_DOCTRINE'),
          policies: buildRelated(issue.temp_id, 'RELATES_TO_POLICY'),
          factPatterns: buildRelated(issue.temp_id, 'RELATES_TO_FACTPATTERN')
        } : null,
        arguments: args.map((arg: any) => ({
          arguments: arg,
          laws: buildRelated(arg.temp_id, 'RELIES_ON_LAW'),
          facts: buildRelated(arg.temp_id, 'RELIES_ON_FACT').map((fact: any) => ({
            facts: fact,
            witnesses: buildRelated(fact.temp_id, 'SUPPORTED_BY_WITNESS'),
            evidence: buildRelated(fact.temp_id, 'SUPPORTED_BY_EVIDENCE'),
            judicialNotice: buildRelated(fact.temp_id, 'SUPPORTED_BY_JUDICIAL_NOTICE')
          }))
        }))
      }
    })
  }, [nodesArray, edgesArray])
  
  // Detect shared Issues across multiple Holdings
  const sharedIssues = useMemo(() => {
    const issueUsage: Record<string, string[]> = {} // issue temp_id -> holding temp_ids
    
    holdingsData.forEach((h: any) => {
      const issue = h.issue
      if (issue && issue.temp_id) {
        const issueId = issue.temp_id
        const holdingId = h.holding?.temp_id
        if (holdingId) {
        if (!issueUsage[issueId]) issueUsage[issueId] = []
          issueUsage[issueId].push(holdingId)
        }
      }
    })
    
    // Return only Issues used in multiple Holdings
    return Object.entries(issueUsage)
      .filter(([, holdingIds]) => holdingIds.length > 1)
      .reduce((acc, [issueId, holdingIds]) => {
        acc[issueId] = holdingIds
        return acc
      }, {} as Record<string, string[]>)
  }, [holdingsData])
  const pickNodeName = (node: GraphNode): string | undefined => {
    const props = (node?.properties ?? {}) as Record<string, unknown>
    const candidates = ['name', 'title', 'text', 'case_name']
    for (const key of candidates) {
      const v = props[key]
      if (typeof v === 'string' && v.trim()) return v.trim()
    }
    return undefined
  }
  const nodeOptions = useMemo(() => {
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
  }, [nodesArray])
  const nodeIdToDisplay = useMemo(() => {
    const map: Record<string, string> = {}
    nodeOptions.forEach(o => { map[o.id] = o.display })
    return map
  }, [nodeOptions])

  // Extract node types from schema (defensive against varying shapes)
  const extractNodeTypesFromSchema = (schemaPayload: any): string[] => {
    const labels = new Set<string>()
    const push = (val: any) => {
      if (typeof val === 'string' && val.trim()) labels.add(val.trim())
    }
    if (!schemaPayload) return []

    // Normalize string payloads
    let normalized: any = schemaPayload
    if (typeof normalized === 'string') {
      try {
        normalized = JSON.parse(normalized)
      } catch {
        // eslint-disable-next-line no-console
        console.warn('Schema was a string but could not be parsed as JSON')
        return []
      }
    }

    // Common shapes: array of { label, attributes, relationships }
    if (Array.isArray(normalized)) {
      for (const item of normalized) {
        if (!item) continue
        if (typeof item === 'string') push(item)
        else if (typeof item === 'object') push(item.label || item.name || item.type)
      }
    }

    // Alternative shapes: object with arrays of labels
    const candidates = [
      normalized?.nodeLabels,
      normalized?.labels,
      normalized?.node_types,
      normalized?.nodeTypes,
      normalized?.nodes,
    ].filter(Boolean)
    for (const arr of candidates) {
      if (Array.isArray(arr)) {
        for (const item of arr) {
          if (typeof item === 'string') push(item)
          else if (item && typeof item === 'object') push(item.label || item.name || item.type)
        }
      } else if (arr && typeof arr === 'object') {
        // Sometimes nodes can be an object map of label -> definition
        for (const key of Object.keys(arr)) push(key)
      }
    }

    return Array.from(labels).sort((a, b) => a.localeCompare(b))
  }

  const schemaNodeTypes = useMemo(() => extractNodeTypesFromSchema(schema), [schema])

  const groupedNodesByType = useMemo(() => {
    const groups: Record<string, GraphNode[]> = {}
    ;(nodesArray || []).forEach((node) => {
      const typeLabel = String(node?.label || 'Unknown')
      if (!groups[typeLabel]) groups[typeLabel] = []
      groups[typeLabel].push(node)
    })
    return groups
  }, [nodesArray])

  const allNodeTypes = useMemo(() => {
    const set = new Set<string>([...schemaNodeTypes, ...Object.keys(groupedNodesByType)])
    return Array.from(set).sort((a, b) => a.localeCompare(b))
  }, [schemaNodeTypes, groupedNodesByType])

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

  // Helper sets for filtering displayData nodes
  const deletedNodeIds = useMemo(() => 
    new Set(graphState.nodes.filter(n => n.status === 'deleted').map(n => n.temp_id)),
    [graphState]
  )
  const orphanedNodeIds = useMemo(() => 
    new Set(graphState.nodes.filter(n => n.status === 'orphaned').map(n => n.temp_id)),
    [graphState]
  )

  useEffect(() => {
    // eslint-disable-next-line no-console
    console.log('Case editor schema:', schema)
    // eslint-disable-next-line no-console
    console.log('Extracted schema node types:', schemaNodeTypes)
    // eslint-disable-next-line no-console
    console.log('Grouped node types (from case data):', Object.keys(groupedNodesByType))
    // eslint-disable-next-line no-console
    console.log('All node types to render:', allNodeTypes)
  }, [schema, schemaNodeTypes, groupedNodesByType, allNodeTypes])

  const setValueAtPath = (path: (string|number)[], value: any) => {
    // Path format: ['nodes', nodeIndex, 'properties', 'propName']
    // or ['edges', edgeIndex, 'to']
    
    if (path[0] === 'nodes' && typeof path[1] === 'number') {
      const nodeIdx = path[1]
      const activeNodes = graphState.nodes.filter(n => n.status === 'active')
      const node = activeNodes[nodeIdx]
      if (!node) return
      
      setGraphState(prev => ({
        ...prev,
        nodes: prev.nodes.map(n => {
          if (n.temp_id !== node.temp_id) return n
          
          // Deep clone and update property
          const updated = { ...n }
          let cursor: any = updated
          for (let i = 2; i < path.length - 1; i++) {
            const key = path[i]
            cursor[key] = Array.isArray(cursor[key]) ? [...cursor[key]] : { ...cursor[key] }
            cursor = cursor[key]
          }
          const lastKey = path[path.length - 1]
          cursor[lastKey] = value
          
          return updated
        })
      }))
    } else if (path[0] === 'edges' && typeof path[1] === 'number') {
      const edgeIdx = path[1]
      const activeEdges = graphState.edges.filter(e => e.status === 'active')
      const edge = activeEdges[edgeIdx]
      if (!edge) return
      
      setGraphState(prev => ({
        ...prev,
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        edges: prev.edges.map((e, idx) => {
          // Find the matching edge by comparing all properties
          if (e.from !== edge.from || e.to !== edge.to || e.label !== edge.label) return e
          
          // Update the property
          const lastKey = path[path.length - 1]
          return { ...e, [lastKey]: value }
        })
      }))
    }
    
    setHasUnsavedChanges(true)
  }



  // Helper to find schema definition for a property
  const getPropertySchema = (path: (string | number)[], propName: string): any => {
    // Determine node label from path (e.g., ['nodes', 0] -> check nodesArray[0].label)
    let nodeLabel: string | undefined
    if (path[0] === 'nodes' && typeof path[1] === 'number') {
      const nodeIdx = path[1]
      nodeLabel = nodesArray?.[nodeIdx]?.label
    }
    
    if (!nodeLabel || !schema) return null
    
    // Find label definition in schema
    const schemaArray = Array.isArray(schema) ? schema : []
    const labelDef = schemaArray.find((s: any) => s?.label === nodeLabel)
    if (!labelDef?.properties) return null
    
    return labelDef.properties[propName]
  }

  // Derive Case, Proceedings, Parties, Forums, Jurisdictions from graphState + viewConfig
  const caseNode = useMemo(() => {
    return (nodesArray || []).find((n: any) => n.label === 'Case') || null
  }, [nodesArray])
  
  const getRelatedNodes = (
    parentId: string | undefined,
    relLabel: string,
    direction: 'outgoing' | 'incoming' = 'outgoing'
  ) => {
    if (!parentId) return []
    const relEdges = direction === 'outgoing'
      ? edgesArray.filter(e => e.from === parentId && e.label === relLabel)
      : edgesArray.filter(e => e.to === parentId && e.label === relLabel)
    const ids = new Set<string>()
    const results: any[] = []
    relEdges.forEach(edge => {
      const targetId = direction === 'outgoing' ? edge.to : edge.from
      if (targetId && !ids.has(targetId)) {
        const node = nodesArray.find(n => n.temp_id === targetId)
        if (node) { ids.add(targetId); results.push(node) }
      }
    })
    return results
  }
  
  const proceedingNodes = useMemo(() => {
    return caseNode ? getRelatedNodes(caseNode.temp_id, 'HAS_PROCEEDING', 'outgoing') : []
  }, [caseNode, edgesArray, nodesArray])
  
  const forumNodes = useMemo(() => {
    const seen = new Set<string>()
    const results: any[] = []
    proceedingNodes.forEach((proc: any) => {
      getRelatedNodes(proc.temp_id, 'HEARD_IN', 'outgoing').forEach(n => {
        if (!seen.has(n.temp_id)) { seen.add(n.temp_id); results.push(n) }
      })
    })
    return results
  }, [proceedingNodes, edgesArray, nodesArray])
  
  const partyNodes = useMemo(() => {
    const seen = new Set<string>()
    const results: any[] = []
    proceedingNodes.forEach((proc: any) => {
      getRelatedNodes(proc.temp_id, 'INVOLVES', 'outgoing').forEach(n => {
        if (!seen.has(n.temp_id)) { seen.add(n.temp_id); results.push(n) }
      })
    })
    return results
  }, [proceedingNodes, edgesArray, nodesArray])
  
  const jurisdictionNodes = useMemo(() => {
    const seen = new Set<string>()
    const results: any[] = []
    forumNodes.forEach((forum: any) => {
      getRelatedNodes(forum.temp_id, 'PART_OF', 'outgoing').forEach(n => {
        if (!seen.has(n.temp_id)) { seen.add(n.temp_id); results.push(n) }
      })
    })
    return results
  }, [forumNodes, edgesArray, nodesArray])

  // Early return after all hooks to keep hook order stable
  if (!data) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="rounded-md border bg-gray-50 px-2 py-1 text-xs text-gray-600">Loading...</div>
      </div>
    )
  }

  const Field = ({ label, value, path, depth = 0 }: { label: string, value: any, path: (string|number)[], depth?: number }) => {
    const indentStyle = useMemo(() => ({ marginLeft: depth * 16 }), [depth])
    
    // Get schema definition for this property
    const propSchema = useMemo(() => getPropertySchema(path, label), [path, label])
    const uiConfig = propSchema?.ui
    const inputType = uiConfig?.input
    const options = uiConfig?.options
    const required = uiConfig?.required

    // Local state for form inputs - always declare hooks at top level
    const [local, setLocal] = useState<string>(value === null ? '' : String(value))
    useEffect(() => {
      setLocal(value === null ? '' : String(value))
    }, [value])

    // Hide temp_id wherever it appears
    if (label === 'temp_id') return null
    
    // Hide properties marked as hidden in schema
    if (uiConfig?.hidden) return null

    // Edge endpoints: show node labels in a dropdown, store temp_id
    if ((label === 'from' || label === 'to') && nodeOptions.length > 0) {
      const valueId = value == null ? '' : String(value)
      return (
        <div className="w-full" style={indentStyle}>
          <label className="block text-xs font-medium text-gray-700 mt-2 mb-0.5">{formatLabel(label)}</label>
          <select
            className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs shadow-sm focus:border-gray-400 focus:outline-none"
            value={valueId}
            onChange={e => setValueAtPath(path, e.target.value)}
          >
            <option value="">Select node</option>
            {nodeOptions.map(opt => (
              <option key={opt.id} value={opt.id}>{opt.display}</option>
            ))}
            {!nodeIdToDisplay[valueId] && valueId !== '' && (
              <option value={valueId}>{valueId}</option>
            )}
          </select>
        </div>
      )
    }

    // Schema-based rendering for strings and numbers
    if (value === null || typeof value === 'string' || typeof value === 'number') {
      const displayLabel = uiConfig?.label || formatLabel(label)
      
      // Render dropdown for enums (select with options)
      if (inputType === 'select' && Array.isArray(options) && options.length > 0) {
        return (
          <div className="w-full" style={indentStyle}>
            <label className="block text-xs font-medium text-gray-700 mt-2 mb-0.5">
              {displayLabel}{required ? ' *' : ''}
            </label>
            <select
              className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs shadow-sm focus:border-gray-400 focus:outline-none"
              value={local}
              onChange={e => {
                setLocal(e.target.value)
                setValueAtPath(path, e.target.value)
              }}
            >
              <option value="">Select...</option>
              {options.map((opt: any, i: number) => (
                <option key={i} value={String(opt)}>{String(opt)}</option>
              ))}
            </select>
          </div>
        )
      }
      
      // Render date picker for dates
      if (inputType === 'date') {
        const commit = () => setValueAtPath(path, local)
        return (
          <div className="w-full" style={indentStyle}>
            <label className="block text-xs font-medium text-gray-700 mt-2 mb-0.5">
              {displayLabel}{required ? ' *' : ''}
            </label>
            <input
              type="date"
              className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs shadow-sm focus:border-gray-400 focus:outline-none"
              value={local}
              onChange={e => setLocal(e.target.value)}
              onBlur={commit}
            />
          </div>
        )
      }
      
      // Render number input for numbers
      if (inputType === 'number' || typeof value === 'number') {
      const commit = () => {
          const parsed = local === '' ? '' : Number(local)
          setValueAtPath(path, parsed)
        }
        return (
          <div className="w-full" style={indentStyle}>
            <label className="block text-xs font-medium text-gray-700 mt-2 mb-0.5">
              {displayLabel}{required ? ' *' : ''}
            </label>
            <input
              type="number"
              className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs shadow-sm focus:border-gray-400 focus:outline-none"
              value={local}
              onChange={e => setLocal(e.target.value)}
              onBlur={commit}
            />
          </div>
        )
      }
      
      // Render textarea for long text or textarea input type
      const isLongText = inputType === 'textarea' || (typeof value === 'string' && (value.length > 120 || value.includes('\n')))
      const commit = () => setValueAtPath(path, local)
      
      return (
        <div className="w-full" style={indentStyle}>
          <label className="block text-xs font-medium text-gray-700 mt-2 mb-0.5">
            {displayLabel}{required ? ' *' : ''}
          </label>
          {isLongText ? (
            <textarea
              className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs shadow-sm focus:border-gray-400 focus:outline-none"
              rows={Math.min(12, Math.max(3, Math.ceil((local?.length || 0) / 80)))}
              value={local}
              onChange={e => setLocal(e.target.value)}
              onBlur={commit}
            />
          ) : (
            <input
              type="text"
              className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs shadow-sm focus:border-gray-400 focus:outline-none"
              value={local}
              onChange={e => setLocal(e.target.value)}
              onBlur={commit}
            />
          )}
        </div>
      )
    }

    if (typeof value === 'boolean') {
      const displayLabel = uiConfig?.label || formatLabel(label)
      return (
        <div className="flex items-center justify-between" style={indentStyle}>
          <label className="text-xs font-medium text-gray-700">
            {displayLabel}{required ? ' *' : ''}
          </label>
          <input
            className="h-3.5 w-3.5"
            type="checkbox"
            checked={value}
            onChange={e => setValueAtPath(path, e.target.checked)}
          />
        </div>
      )
    }

    if (Array.isArray(value)) {
      return (
        <div className="space-y-1.5" style={indentStyle}>
          <div className="text-xs font-medium text-gray-800">{formatLabel(label)}</div>
          {value.length === 0 && (
            <div className="text-xs text-gray-500" style={{ marginLeft: 16 }}>Empty array</div>
          )}
          {value.map((item, idx) => (
            <Field key={idx} label={`Item ${idx + 1}`} value={item} path={[...path, idx]} depth={depth + 1} />
          ))}
        </div>
      )
    }

    if (typeof value === 'object') {
      return (
        <div className="space-y-2" style={indentStyle}>
          <ObjectFields obj={value as Record<string, any>} path={path} depth={depth} />
        </div>
      )
    }

    return (
      <div className="" style={indentStyle}>
        <label className="block text-xs font-medium text-gray-700 mt-2 mb-0.5">{formatLabel(label)}</label>
        <input
          className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs shadow-sm focus:border-gray-400 focus:outline-none"
          value={String(value)}
          onChange={e => setValueAtPath(path, e.target.value)}
        />
      </div>
    )
  }

  const ObjectFields = ({ obj, path, depth = 0 }: { obj: Record<string, any>, path: (string | number)[], depth?: number }) => {
    const entries = Object.entries(obj || {}).filter(([k, v]) => {
      if (k === 'temp_id') return false
      // Hide empty nested objects like properties: {}
      if (v && typeof v === 'object' && !Array.isArray(v) && Object.keys(v).length === 0) return false
      return true
    }).sort(([a], [b]) => String(a).localeCompare(String(b)))
    if (entries.length === 0) return null
    return (
      <div className="space-y-2">
        {entries.map(([k, v]) => (
          <Field key={k} label={k} value={v} path={[...path, k]} depth={depth} />
        ))}
      </div>
    )
  }
  // Scroll to holding
  const scrollToHolding = (holdingId: string) => {
    setActiveHoldingId(holdingId)
    const el = document.getElementById(`holding-${holdingId}`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }
  
  // Scroll to any node in sidebar navigation
  const scrollToNodeById = (nodeId: string, holdingId?: string) => {
    if (holdingId) setActiveHoldingId(holdingId)
    const el = document.getElementById(`node-${nodeId}`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }

  // Get all edges related to a node (incoming and outgoing)
  const getNodeConnections = (nodeId: string) => {
    const edges = graphState.edges.filter(e => e.status === 'active')
    const outgoing = edges.map((e: any, idx: number) => ({ ...e, idx })).filter((e: any) => e.from === nodeId)
    const incoming = edges.map((e: any, idx: number) => ({ ...e, idx })).filter((e: any) => e.to === nodeId)
    return { outgoing, incoming }
  }

  // Get node display name helper
  const getNodeDisplayName = (nodeId: string) => {
    const node = graphState.nodes.find((n: any) => n.temp_id === nodeId)
    return node ? pickNodeName(node) : nodeId
  }

  // Get node type label helper
  const getNodeTypeLabel = (nodeId: string): string => {
    const node = graphState.nodes.find((n: any) => n.temp_id === nodeId)
    return node?.label || 'Node'
  }

  // Helper: Find all descendants (children, grandchildren, etc.) of a node
  const findDescendants = (nodeId: string, edges: any[]): string[] => {
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

  // Delete a node and orphan its descendants (only if they have no other active parents)
  const deleteNode = (nodeId: string) => {
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
    
    setHasUnsavedChanges(true)
    setDeletingNodeId(null)
    setViewingConnectionsNodeId(null)
  }
  
  // Restore an orphaned node (make it active again)
  const restoreOrphanedNode = (nodeId: string) => {
    setGraphState(prev => ({
      ...prev,
      nodes: prev.nodes.map(n => 
        n.temp_id === nodeId 
          ? { ...n, status: 'active' as const }
          : n
      )
    }))
    setHasUnsavedChanges(true)
  }
  
  // Helper: Filter out deleted and orphaned nodes from an array
  const filterActiveNodes = (nodes: any[]): any[] => {
    if (!Array.isArray(nodes)) return []
    return nodes.filter((n: any) => 
      n?.temp_id && !deletedNodeIds.has(n.temp_id) && !orphanedNodeIds.has(n.temp_id)
    )
  }

  // Handler for adding a new node
  const handleAddNode = (
    nodeType: string, 
    relationship: string, 
    direction: 'outgoing' | 'incoming',
    parentId?: string
  ) => {
    setAddModalType(nodeType)
    setAddModalContext({ parentId, relationship, direction })
    setAddModalOpen(true)
  }

  // Get parent node label for modal context
  const getParentNodeLabel = (parentId: string | undefined): string => {
    if (!parentId) return ''
    const parentNode = nodesArray.find(n => n.temp_id === parentId)
    return parentNode?.label || 'Node'
  }

  // Helper to get parent node for a top-level config entry
  const getParentNodeFromConfig = (configKey: string): any => {
    const config = viewConfig?.topLevel?.[configKey]
    const fromLabel = config?.from
    
    if (!fromLabel) {
      // No "from" field means it's directly on Case
      return caseNode
    }
    
    // Map label to actual node
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

  // Handler for selecting an existing catalog node
  const handleSelectNode = (
    nodeType: string, 
    relationship: string, 
    direction: 'outgoing' | 'incoming',
    parentId?: string
  ) => {
    setSelectModalType(nodeType)
    setSelectModalContext({ parentId, relationship, direction })
    setSelectModalOpen(true)
  }

  // Get nodes available for selection from catalog store
  const getAvailableNodesForSelection = (nodeType: string): GraphNode[] => {
    // Return catalog nodes from global store (for can_create_new=false types)
    return catalogNodes[nodeType] || []
  }

  // Handle submission from select modal
  const handleSelectNodeSubmit = (selectedNodeId: string) => {
    if (!selectModalContext) return

    const { parentId, relationship, direction } = selectModalContext
    
    // Find the selected node from available catalog nodes
    const selectedNode = getAvailableNodesForSelection(selectModalType).find(
      n => n.temp_id === selectedNodeId
    )
    
    if (!selectedNode) return

    setGraphState((prev) => {
      const nodes = [...prev.nodes]
      const edges = [...prev.edges]
      
      // Add the selected node if not already present
      if (!nodes.find(n => n.temp_id === selectedNode.temp_id)) {
        nodes.push({
          temp_id: selectedNode.temp_id,
          label: selectedNode.label,
          properties: selectedNode.properties,
          status: 'active' as const,
          source: 'user-created' as const
        })
      }
      
      // If Forum, also add its embedded Jurisdiction
      if (selectedNode.label === 'Forum' && selectedNode.related?.jurisdiction) {
        const jurisdiction = selectedNode.related.jurisdiction
        
        // Add jurisdiction node if not already present
        if (!nodes.find(n => n.temp_id === jurisdiction.temp_id)) {
          nodes.push({
            temp_id: jurisdiction.temp_id,
            label: 'Jurisdiction',
            properties: jurisdiction.properties,
            status: 'active' as const,
            source: 'user-created' as const
          })
        }
        
        // Add PART_OF edge from Forum to Jurisdiction if not present
        const partOfExists = edges.find(
          e => e.from === selectedNode.temp_id && 
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
      
      // Add relationship edge to parent
      const parentEdgeExists = edges.find(
        e => e.from === (direction === 'outgoing' ? (parentId || '') : selectedNodeId) &&
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

    // If the selected node was orphaned, restore it (since it now has a parent)
    if (orphanedNodeIds.has(selectedNodeId)) {
      restoreOrphanedNode(selectedNodeId)
    }

    setHasUnsavedChanges(true)
    setSelectModalOpen(false)
    setSelectModalContext(null)
  }

  // Helper: Find the edge connecting parent to child
  const findParentEdge = (parentId: string, nodeId: string) => {
    return edgesArray.find(e => e.from === parentId && e.to === nodeId)
  }

  // Helper: Get formatted parent label
  const getParentLabel = (parentId: string): string => {
    const parent = nodesArray.find(n => n.temp_id === parentId)
    return parent?.label ? formatLabel(parent.label) : 'parent'
  }

  // Helper: Check if a node should show "Unlink" instead of "Delete"
  const shouldShowUnlink = (nodeId: string, parentId?: string): boolean => {
    if (!parentId) return false
    
    const parentEdge = findParentEdge(parentId, nodeId)
    if (!parentEdge) return false
    
    // Count how many incoming edges of the same relationship type this node has
    const incomingEdgesOfType = edgesArray.filter(
      e => e.to === nodeId && e.label === parentEdge.label
    )
    
    return incomingEdgesOfType.length > 1
  }

  // Helper: Unlink a node from its parent (remove the edge only)
  const unlinkNode = (nodeId: string, parentId: string) => {
    const parentEdge = findParentEdge(parentId, nodeId)
    if (!parentEdge) return
    
    setGraphState(prev => ({
      ...prev,
      edges: prev.edges.map(e => 
        e.from === parentId && e.to === nodeId && e.label === parentEdge.label
          ? { ...e, status: 'deleted' as const }
          : e
      )
    }))
    setHasUnsavedChanges(true)
  }

  // Node Action Menu Component
  const NodeActionMenu = ({ 
    nodeId, 
    parentId
  }: { 
    nodeId: string
    parentId?: string
  }) => {
    const [menuOpen, setMenuOpen] = useState(false)
    const { outgoing, incoming } = getNodeConnections(nodeId)
    const totalConnections = outgoing.length + incoming.length
    const showUnlink = shouldShowUnlink(nodeId, parentId)
    const parentLabel = parentId ? getParentLabel(parentId) : ''

    return (
      <div className="relative">
        <button
          onClick={(e) => {
            e.stopPropagation()
            setMenuOpen(!menuOpen)
          }}
          className="p-1 rounded hover:bg-gray-200 text-gray-500 hover:text-gray-700 transition-colors cursor-pointer"
          title="Node actions"
        >
          <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 16 16">
            <circle cx="8" cy="2" r="1.5"/>
            <circle cx="8" cy="8" r="1.5"/>
            <circle cx="8" cy="14" r="1.5"/>
          </svg>
        </button>
        
        {menuOpen && (
          <>
            <div 
              className="fixed inset-0 z-10" 
              onClick={() => setMenuOpen(false)}
            />
            <div className="absolute right-0 top-full mt-1 w-56 bg-white rounded-lg shadow-lg border z-20 py-1">
              <button
                onClick={() => {
                  setViewingConnectionsNodeId(nodeId)
                  setMenuOpen(false)
                }}
                className="w-full px-4 py-2 text-left text-sm hover:bg-gray-50 flex items-center gap-2 cursor-pointer"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                </svg>
                <span>View connections</span>
                <span className="ml-auto text-xs text-gray-500">({totalConnections})</span>
              </button>
              {showUnlink ? (
                <button
                  onClick={() => {
                    if (parentId) {
                      unlinkNode(nodeId, parentId)
                    }
                    setMenuOpen(false)
                  }}
                  className="w-full px-4 py-2 text-left text-sm hover:bg-amber-50 text-amber-700 flex items-center gap-2 cursor-pointer"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                  </svg>
                  <span>Unlink from {parentLabel}</span>
                </button>
              ) : (
                <button
                  onClick={() => {
                    setDeletingNodeId(nodeId)
                    setMenuOpen(false)
                  }}
                  className="w-full px-4 py-2 text-left text-sm hover:bg-red-50 text-red-600 flex items-center gap-2 cursor-pointer"
                >
                  <Trash2 className="w-4 h-4" />
                  <span>Delete node</span>
                </button>
              )}
            </div>
          </>
        )}
      </div>
    )
  }
  
  // Toggle argument expansion
  const toggleArg = (argId: string) => {
    setExpandedArgs(prev => {
      const next = new Set(prev)
      if (next.has(argId)) {
        next.delete(argId)
      } else {
        next.add(argId)
      }
      return next
    })
  }
  
  // Toggle fact expansion
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

  // Section header with optional action button in top-right
  const SectionHeader = ({
    title,
    actionButton,
    className = ''
  }: {
    title: string
    actionButton?: React.ReactNode
    className?: string
  }) => {
    if (!actionButton) return null
    
    return (
      <div className={`flex items-center justify-between mb-3 ${className}`}>
        <h3 className="text-sm font-semibold text-gray-700">{title}</h3>
        <div>{actionButton}</div>
      </div>
    )
  }

  // Unified node card styling
  const NodeCard = ({ 
    node, 
    label, 
    index, 
    depth = 0, 
    badge,
    children,
    parentId
  }: { 
    node: any; 
    label: string; 
    index?: number; 
    depth?: number; 
    badge?: React.ReactNode;
    children?: React.ReactNode;
    parentId?: string;
  }) => {
    const indentClass = depth === 0 ? '' : depth === 1 ? 'ml-6' : depth === 2 ? 'ml-12' : 'ml-18'
    const displayLabel = index !== undefined ? `${label} ${index + 1}` : label
    
    // Different backgrounds for nodes with children to show containment
    const hasChildren = !!children
    const bgClass = hasChildren 
      ? (depth === 0 ? 'bg-blue-50' : depth === 1 ? 'bg-teal-50' : depth === 2 ? 'bg-gray-50' : 'bg-green-50')
      : 'bg-white'
    
    return (
      <div id={`node-${node.temp_id}`} className={`${bgClass} rounded-lg border border-gray-300 p-4 shadow-sm ${indentClass}`}>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <div className="text-sm font-semibold text-gray-900">{displayLabel}</div>
            {badge}
          </div>
          <NodeActionMenu 
            nodeId={node.temp_id}
            parentId={parentId}
          />
        </div>
        <ObjectFields 
          obj={node.properties || {}} 
          path={['nodes', nodesArray.findIndex(n => n.temp_id === node.temp_id), 'properties']} 
        />
        {children}
      </div>
    )
  }

  // Dynamic renderer for nested structures (sidebar)
  const renderNestedStructureSidebar = (
    data: any,
    structureConfig: Record<string, any>,
    holdingId?: string,
    depth: number = 0
  ): React.ReactElement[] => {
    const elements: React.ReactElement[] = []
    
    for (const [key, config] of Object.entries(structureConfig)) {
      if (config.self || key === 'holding') continue // Skip self-references
      
      const value = data[key]
      if (!value) continue
      
      // Filter out deleted and orphaned items to prevent showing removed nodes
      const itemsAll = Array.isArray(value) ? value : [value]
      // Handle nested structures: arguments have {arguments: node, ...}, facts have {facts: node, ...}
      const items = itemsAll.filter((item: any) => {
        // Extract the actual node from nested structure
        const node = (key === 'arguments' && item.arguments) || (key === 'facts' && item.facts) || item
        return node && node.temp_id && 
          !deletedNodeIds.has(node.temp_id) && 
          !orphanedNodeIds.has(node.temp_id)
      })
      const isCollapsible = ['arguments', 'facts'].includes(key)
      
      items.forEach((item: any, idx: number) => {
        // Extract the actual node from nested structure
        const node = (key === 'arguments' && item.arguments) || (key === 'facts' && item.facts) || item
        if (!node || !node.temp_id) return
        
        const expanded = isCollapsible && 
          (key === 'arguments' ? expandedArgs.has(node.temp_id) : expandedFacts.has(node.temp_id))
        
        const toggleFn = key === 'arguments' ? toggleArg : toggleFact
        
        elements.push(
          <div key={`${key}-${node.temp_id}`} className="space-y-1">
            <div className="flex items-center gap-1">
              {isCollapsible && (
                <div
                  onClick={() => toggleFn(node.temp_id)}
                  className="px-1 cursor-pointer text-gray-500 hover:text-gray-700"
                >
                  <span className="text-xs">{expanded ? '▼' : '▶'}</span>
                </div>
              )}
              <div
                onClick={() => scrollToNodeById(node.temp_id, holdingId)}
                className="flex-1 px-2 py-1 rounded text-xs hover:bg-gray-100 text-gray-600 cursor-pointer"
              >
                {formatLabel(key === 'arguments' ? 'argument' : key === 'facts' ? 'fact' : node.label || key)} {idx + 1}
              </div>
            </div>
            
            {(expanded || !isCollapsible) && config.include && (
              <div className="pl-5 space-y-1">
                {renderNestedStructureSidebar(item, config.include, holdingId, depth + 1)}
              </div>
            )}
          </div>
        )
      })
    }
    
    return elements
  }

  return (
    <div className="min-h-screen flex">
      {/* Sidebar Navigation */}
      <div className="w-64 border-r bg-gray-50 flex-shrink-0 sticky top-0 max-h-screen overflow-y-auto">
        <div className="p-4 space-y-4">
          <div>
            <h2 className="text-xs font-semibold text-gray-900 mb-3">Case Overview</h2>
            <div className="space-y-1 pl-2">
              {caseNode && (
                <div
                  onClick={() => scrollToNodeById(caseNode.temp_id)}
                  className="px-2 py-1 rounded text-xs hover:bg-gray-100 text-gray-600 cursor-pointer"
                >
                  Case
                </div>
              )}
              {proceedingNodes.map((proc: any, idx: number) => (
                <div key={proc.temp_id}>
                  <div
                    onClick={() => scrollToNodeById(proc.temp_id)}
                    className="px-2 py-1 rounded text-xs hover:bg-gray-100 text-gray-600 cursor-pointer"
                  >
                    Proceeding {idx + 1}
                  </div>
                </div>
              ))}
              {forumNodes.map((forum: any, idx: number) => (
                <div
                  key={forum.temp_id}
                  onClick={() => scrollToNodeById(forum.temp_id)}
                  className="px-2 py-1 rounded text-xs hover:bg-gray-100 text-gray-600 cursor-pointer"
                >
                  Forum {idx + 1}
                </div>
              ))}
              {partyNodes.map((party: any, idx: number) => (
                <div
                  key={party.temp_id}
                  onClick={() => scrollToNodeById(party.temp_id)}
                  className="px-2 py-1 rounded text-xs hover:bg-gray-100 text-gray-600 cursor-pointer"
                >
                  Party {idx + 1}
                </div>
              ))}
            </div>
          </div>
          
          <div>
            <h2 className="text-xs font-semibold text-gray-900 mb-3">
              Holdings ({holdingsData.length})
            </h2>
            <div className="space-y-3">
              {holdingsData.map((h: any, idx: number) => {
                const holding = h.holding
                if (!holding) return null
                
                const name = pickNodeName(holding) || `Holding ${idx + 1}`
                const isActive = activeHoldingId === holding.temp_id
                
                return (
                  <div key={holding.temp_id} className="space-y-1.5">
                    {/* Holding */}
                    <div
                      onClick={() => scrollToHolding(holding.temp_id)}
                      className={`px-2 py-1.5 rounded text-xs cursor-pointer ${
                        isActive ? 'bg-blue-100 text-blue-900 font-medium' : 'hover:bg-gray-100 text-gray-700'
                      }`}
                    >
                      <div className="truncate">{name}</div>
                    </div>
                    
                    {/* Dynamic content based on structure config */}
                    <div className="pl-4 space-y-1.5 border-l border-gray-300 ml-2">
                        <div
                        onClick={() => scrollToNodeById(holding.temp_id, holding.temp_id)}
                          className="px-2 py-1 rounded text-xs hover:bg-gray-100 text-gray-600 cursor-pointer"
                        >
                          Holding Details
                        </div>
                        
                      {holdingsStructure && renderNestedStructureSidebar(h, holdingsStructure, holding.temp_id)}
                            </div>
                                      </div>
                                      )
                                    })}
                                  </div>
                              </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col bg-gray-50">
        <div className="p-6 space-y-6 text-xs flex-1 overflow-y-auto">
          <h1 className="text-2xl font-semibold tracking-tight">Edit Case</h1>
        {error && (
          <div className="rounded-md border border-red-300 bg-red-50 px-2 py-1 text-xs text-red-700">{error}</div>
        )}

          {/* Top Section: Case, Proceeding, Parties */}
          <div className="space-y-4">
            <div className="border-b pb-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">Case Overview</h2>
              
              <div className="space-y-6">
                {/* Case Details */}
                {caseNode && <NodeCard node={caseNode} label="Case" depth={0} />}
                
                {/* Proceedings Section */}
                {(() => {
                  const parentNode = getParentNodeFromConfig('proceedings')
                  const parentLabel = viewConfig?.topLevel?.proceedings?.from || 'Case'
                  const state = analyzeRelationship(
                    parentNode,
                    'proceedings',
                    viewConfig?.topLevel || {},
                    schema,
                    { proceedings: proceedingNodes }
                  )
                  if (proceedingNodes.length === 0 && state) {
                    return (
                      <RelationshipAction
                        state={state}
                        parentNodeLabel={parentLabel}
                        position="centered"
                        onAdd={(type, rel, dir) => handleAddNode(type, rel, dir, parentNode?.temp_id)}
                        onSelect={(type, rel, dir) => handleSelectNode(type, rel, dir, parentNode?.temp_id)}
                      />
                    )
                  }
                  return (
                    <div>
                      <SectionHeader
                        title="Proceedings"
                        actionButton={state && (
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
                        {proceedingNodes.map((proc: any, idx: number) => (
                          <NodeCard key={proc.temp_id} node={proc} label="Proceeding" index={idx} depth={0} />
                        ))}
                      </div>
                    </div>
                  )
                })()}
                
                {/* Forums Section */}
                {(() => {
                  const parentNode = getParentNodeFromConfig('forums')
                  const parentLabel = viewConfig?.topLevel?.forums?.from || 'Proceeding'
                  const forumsForParent = parentNode ? getRelatedNodes(parentNode.temp_id, 'HEARD_IN', 'outgoing') : []
                  const state = analyzeRelationship(
                    parentNode,
                    'forums',
                    viewConfig?.topLevel || {},
                    schema,
                    { forums: forumsForParent }
                  )
                  if (forumNodes.length === 0 && state) {
                    return (
                      <RelationshipAction
                        state={state}
                        parentNodeLabel={parentLabel}
                        position="centered"
                        onAdd={(type, rel, dir) => handleAddNode(type, rel, dir, parentNode?.temp_id)}
                        onSelect={(type, rel, dir) => handleSelectNode(type, rel, dir, parentNode?.temp_id)}
                      />
                    )
                  }
                  return (
                    <div>
                      <SectionHeader
                        title="Forums"
                        actionButton={state && (
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
                        {forumNodes.map((forum: any, idx: number) => {
                          // Find the Jurisdiction for this Forum
                          const jurisdictionEdge = edgesArray.find(
                            e => e.from === forum.temp_id && e.label === 'PART_OF'
                          )
                          const jurisdiction = jurisdictionEdge 
                            ? jurisdictionNodes.find(j => j.temp_id === jurisdictionEdge.to)
                            : null
                          
                          return (
                            <NodeCard key={forum.temp_id} node={forum} label="Forum" index={idx} depth={0}>
                              {jurisdiction && (
                                <div className="mt-4">
                                  <NodeCard node={jurisdiction} label="Jurisdiction" depth={1} />
                                </div>
                              )}
                            </NodeCard>
                          )
                        })}
                      </div>
                    </div>
                  )
                })()}
                
                {/* Parties Section */}
                {(() => {
                  const parentNode = getParentNodeFromConfig('parties')
                  const parentLabel = viewConfig?.topLevel?.parties?.from || 'Proceeding'
                  const partiesForParent = parentNode ? getRelatedNodes(parentNode.temp_id, 'INVOLVES', 'outgoing') : []
                  const state = analyzeRelationship(
                    parentNode,
                    'parties',
                    viewConfig?.topLevel || {},
                    schema,
                    { parties: partiesForParent }
                  )
                  if (partyNodes.length === 0 && state) {
                    return (
                      <RelationshipAction
                        state={state}
                        parentNodeLabel={parentLabel}
                        position="centered"
                        onAdd={(type, rel, dir) => handleAddNode(type, rel, dir, parentNode?.temp_id)}
                        onSelect={(type, rel, dir) => handleSelectNode(type, rel, dir, parentNode?.temp_id)}
                      />
                    )
                  }
                  return (
                    <div>
                      <SectionHeader
                        title="Parties"
                        actionButton={state && (
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
                        {partyNodes.map((party: any, idx: number) => (
                          <NodeCard key={party.temp_id} node={party} label="Party" index={idx} depth={0} />
                        ))}
                      </div>
                    </div>
                  )
                })()}
              </div>
            </div>

            {/* Holdings Sections */}
            {holdingsData.map((holdingData: any, idx: number) => {
              const holding = holdingData.holding
              
              // Skip this entire holding if the holding itself is deleted/orphaned
              if (!holding || deletedNodeIds.has(holding.temp_id) || orphanedNodeIds.has(holding.temp_id)) {
                return null
              }
              
              // Filter out deleted/orphaned ruling and issue
              const ruling = holdingData.ruling && !deletedNodeIds.has(holdingData.ruling.temp_id) && !orphanedNodeIds.has(holdingData.ruling.temp_id) ? holdingData.ruling : null
              const reliefTypes = filterActiveNodes(holdingData.ruling?.reliefTypes || [])
              const issue = holdingData.issue && !deletedNodeIds.has(holdingData.issue.temp_id) && !orphanedNodeIds.has(holdingData.issue.temp_id) ? holdingData.issue : null
              const doctrines = filterActiveNodes(holdingData.issue?.doctrines || [])
              const policies = filterActiveNodes(holdingData.issue?.policies || [])
              const factPatterns = filterActiveNodes(holdingData.issue?.factPatterns || [])
              // Arguments have nested structure {arguments: node, laws: [...], facts: [...]}, filter by the nested node
              const args = (holdingData.arguments || []).filter((argData: any) => {
                const arg = argData.arguments || argData
                return arg?.temp_id && !deletedNodeIds.has(arg.temp_id) && !orphanedNodeIds.has(arg.temp_id)
              })
              
              const holdingName = pickNodeName(holding) || `Holding ${idx + 1}`
              const isShared = issue && sharedIssues[issue.temp_id]
              
              return (
                <div 
                  key={holding.temp_id} 
                  id={`holding-${holding.temp_id}`}
                  className="scroll-mt-4 border-b pb-8 last:border-b-0"
                >
                  {/* Holding Header */}
                  <div className="mb-4">
                    <h2 className="text-lg font-semibold text-gray-900">{holdingName}</h2>
                  </div>
                  
                  {/* Holding Details */}
          <div className="space-y-4">
                    <NodeCard node={holding} label="Holding Details" depth={0} />
                    
                    {/* Ruling */}
                    {ruling && (
                      <NodeCard node={ruling} label="Ruling" depth={0}>
                        {/* Relief Types */}
                        {(() => {
                          const rulingStructure = holdingsStructure?.ruling?.include || {}
                          const state = analyzeRelationship(ruling, 'reliefTypes', rulingStructure, schema, holdingData.ruling)
                          return (
                            <div className="mt-4">
                              <SectionHeader
                                title="Relief Types"
                                actionButton={state && (
                                  <RelationshipAction
                                    state={state}
                                    parentNodeLabel="Ruling"
                                    position="inline"
                                    onAdd={(type, rel, dir) => handleAddNode(type, rel, dir, ruling.temp_id)}
                                    onSelect={(type, rel, dir) => handleSelectNode(type, rel, dir, ruling.temp_id)}
                                  />
                                )}
                              />
                              <div className="space-y-4">
                                {reliefTypes.map((relief: any, relIdx: number) => (
                                  <NodeCard 
                                    key={relief.temp_id} 
                                    node={relief} 
                                    label="Relief Type" 
                                    index={relIdx} 
                                    depth={1}
                                    parentId={ruling.temp_id}
                                  />
                                ))}
                              </div>
                            </div>
                          )
                        })()}
                      </NodeCard>
                    )}
                    {/* Add Ruling button if no ruling exists */}
                    {!ruling && (() => {
                      const state = analyzeRelationship(holding, 'ruling', holdingsStructure || {}, schema, holdingData)
                      if (!state) return null
                      return (
                        <RelationshipAction
                          state={state}
                          parentNodeLabel="Holding"
                          position="centered"
                          onAdd={(type, rel, dir) => handleAddNode(type, rel, dir, holding.temp_id)}
                          onSelect={(type, rel, dir) => handleSelectNode(type, rel, dir, holding.temp_id)}
                        />
                      )
                    })()}
                    
                    {/* Issue */}
                    {issue && (
                      <NodeCard 
                        node={issue} 
                        label="Issue" 
                        depth={0}
                        badge={isShared && (
                              <div className="text-[10px] bg-amber-100 text-amber-800 px-2 py-0.5 rounded-full">
                                Shared across {sharedIssues[issue.temp_id].length} holdings
                              </div>
                            )}
                      >
                        {/* Doctrines, Policies, Fact Patterns */}
                        <div className="mt-4 space-y-6">
                          {/* Doctrines Section */}
                          {(() => {
                            const issueStructure = holdingsStructure?.issue?.include || {}
                            const state = analyzeRelationship(issue, 'doctrines', issueStructure, schema, holdingData.issue)
                            return (
                              <div>
                                <SectionHeader
                                  title="Doctrines"
                                  actionButton={state && (
                                    <RelationshipAction
                                      state={state}
                                      parentNodeLabel="Issue"
                                      position="inline"
                                      onAdd={(type, rel, dir) => handleAddNode(type, rel, dir, issue.temp_id)}
                                      onSelect={(type, rel, dir) => handleSelectNode(type, rel, dir, issue.temp_id)}
                                    />
                                  )}
                                />
                                <div className="space-y-4">
                                  {doctrines.map((doc: any, docIdx: number) => (
                                    <NodeCard 
                                      key={doc.temp_id} 
                                      node={doc} 
                                      label="Doctrine" 
                                      index={docIdx} 
                                      depth={1}
                                      parentId={issue.temp_id}
                                    />
                                  ))}
                                </div>
                              </div>
                            )
                          })()}
                          
                          {/* Policies Section */}
                          {(() => {
                            const issueStructure = holdingsStructure?.issue?.include || {}
                            const state = analyzeRelationship(issue, 'policies', issueStructure, schema, holdingData.issue)
                            return (
                              <div>
                                <SectionHeader
                                  title="Policies"
                                  actionButton={state && (
                                    <RelationshipAction
                                      state={state}
                                      parentNodeLabel="Issue"
                                      position="inline"
                                      onAdd={(type, rel, dir) => handleAddNode(type, rel, dir, issue.temp_id)}
                                      onSelect={(type, rel, dir) => handleSelectNode(type, rel, dir, issue.temp_id)}
                                    />
                                  )}
                                />
                                <div className="space-y-4">
                                  {policies.map((pol: any, polIdx: number) => (
                                    <NodeCard 
                                      key={pol.temp_id} 
                                      node={pol} 
                                      label="Policy" 
                                      index={polIdx} 
                                      depth={1}
                                      parentId={issue.temp_id}
                                    />
                                  ))}
                                </div>
                              </div>
                            )
                          })()}
                          
                          {/* Fact Patterns Section */}
                          {(() => {
                            const issueStructure = holdingsStructure?.issue?.include || {}
                            const state = analyzeRelationship(issue, 'factPatterns', issueStructure, schema, holdingData.issue)
                            return (
                              <div>
                                <SectionHeader
                                  title="Fact Patterns"
                                  actionButton={state && (
                                    <RelationshipAction
                                      state={state}
                                      parentNodeLabel="Issue"
                                      position="inline"
                                      onAdd={(type, rel, dir) => handleAddNode(type, rel, dir, issue.temp_id)}
                                      onSelect={(type, rel, dir) => handleSelectNode(type, rel, dir, issue.temp_id)}
                                    />
                                  )}
                                />
                                <div className="space-y-4">
                                  {factPatterns.map((fp: any, fpIdx: number) => (
                                    <NodeCard 
                                      key={fp.temp_id} 
                                      node={fp} 
                                      label="Fact Pattern" 
                                      index={fpIdx} 
                                      depth={1}
                                      parentId={issue.temp_id}
                                    />
                                  ))}
                                </div>
                              </div>
                            )
                          })()}
                        </div>
                      </NodeCard>
                    )}
                    {/* Add Issue button if no issue exists */}
                    {!issue && (() => {
                      const state = analyzeRelationship(holding, 'issue', holdingsStructure || {}, schema, holdingData)
                      if (!state) return null
                      return (
                        <RelationshipAction
                          state={state}
                          parentNodeLabel="Holding"
                          position="centered"
                          onAdd={(type, rel, dir) => handleAddNode(type, rel, dir, holding.temp_id)}
                          onSelect={(type, rel, dir) => handleSelectNode(type, rel, dir, holding.temp_id)}
                        />
                      )
                    })()}
                    
                    {/* Arguments */}
                    {args.length > 0 && (
                      <div className="mt-6 pt-6 border-t-2 border-gray-200 space-y-4">
                        {args.map((argData: any, argIdx: number) => {
                          // Backend returns: { arguments: node, laws: [...], facts: [...] }
                          const arg = argData.arguments || argData
                          const laws = filterActiveNodes(argData.laws || [])
                          // Facts have nested structure {facts: node, witnesses: [...], evidence: [...], judicialNotice: [...]}, filter by nested node
                          const facts = (argData.facts || []).filter((factData: any) => {
                            const fact = factData.facts || factData
                            return fact?.temp_id && !deletedNodeIds.has(fact.temp_id) && !orphanedNodeIds.has(fact.temp_id)
                          })
                          
                        return (
                          <NodeCard key={arg.temp_id} node={arg} label="Argument" index={argIdx} depth={0}>
                            <div className="mt-4 space-y-6">
                              {/* Laws Section */}
                              {(() => {
                                const argStructure = holdingsStructure?.arguments?.include || {}
                                const state = analyzeRelationship(arg, 'laws', argStructure, schema, argData)
                                return (
                                  <div>
                                    <SectionHeader
                                      title="Laws"
                                      actionButton={state && (
                                        <RelationshipAction
                                          state={state}
                                          parentNodeLabel="Argument"
                                          position="inline"
                                          onAdd={(type, rel, dir) => handleAddNode(type, rel, dir, arg.temp_id)}
                                          onSelect={(type, rel, dir) => handleSelectNode(type, rel, dir, arg.temp_id)}
                                        />
                                      )}
                                    />
                                    <div className="space-y-4">
                                      {laws.map((law: any, lawIdx: number) => (
                                        <NodeCard 
                                          key={law.temp_id} 
                                          node={law} 
                                          label="Law" 
                                          index={lawIdx} 
                                          depth={1}
                                          parentId={arg.temp_id}
                                        />
                                      ))}
                                    </div>
                                  </div>
                                )
                              })()}
                              
                              {/* Facts Section */}
                              {(() => {
                                const argStructure = holdingsStructure?.arguments?.include || {}
                                const state = analyzeRelationship(arg, 'facts', argStructure, schema, argData)
                                return (
                                  <div>
                                    <SectionHeader
                                      title="Facts"
                                      actionButton={state && (
                                        <RelationshipAction
                                          state={state}
                                          parentNodeLabel="Argument"
                                          position="inline"
                                          onAdd={(type, rel, dir) => handleAddNode(type, rel, dir, arg.temp_id)}
                                          onSelect={(type, rel, dir) => handleSelectNode(type, rel, dir, arg.temp_id)}
                                        />
                                      )}
                                    />
                                    <div className="space-y-4">
                                      {/* Facts with nested support */}
                                      {facts.map((factData: any, factIdx: number) => {
                                const fact = factData.facts || factData
                                const witnesses = filterActiveNodes(factData.witnesses || [])
                                const evidence = filterActiveNodes(factData.evidence || [])
                                const judicialNotice = filterActiveNodes(factData.judicialNotice || [])
                                
                                return (
                                  <NodeCard 
                                    key={fact.temp_id} 
                                    node={fact} 
                                    label="Fact" 
                                    index={factIdx} 
                                    depth={1}
                                    parentId={arg.temp_id}
                                  >
                                    <div className="mt-4 space-y-6">
                                      {/* Witnesses Section */}
                                      {(() => {
                                        const factStructure = holdingsStructure?.arguments?.include?.facts?.include || {}
                                        const state = analyzeRelationship(fact, 'witnesses', factStructure, schema, factData)
                                        return (
                                          <div>
                                            <SectionHeader
                                              title="Witnesses"
                                              actionButton={state && (
                                                <RelationshipAction
                                                  state={state}
                                                  parentNodeLabel="Fact"
                                                  position="inline"
                                                  onAdd={(type, rel, dir) => handleAddNode(type, rel, dir, fact.temp_id)}
                                                  onSelect={(type, rel, dir) => handleSelectNode(type, rel, dir, fact.temp_id)}
                                                />
                                              )}
                                            />
                                            <div className="space-y-4">
                                              {witnesses.map((wit: any, witIdx: number) => (
                                                <NodeCard 
                                                  key={wit.temp_id} 
                                                  node={wit} 
                                                  label="Witness" 
                                                  index={witIdx} 
                                                  depth={2}
                                                  parentId={fact.temp_id}
                                                />
                                              ))}
                                            </div>
                                          </div>
                                        )
                                      })()}
                                      
                                      {/* Evidence Section */}
                                      {(() => {
                                        const factStructure = holdingsStructure?.arguments?.include?.facts?.include || {}
                                        const state = analyzeRelationship(fact, 'evidence', factStructure, schema, factData)
                                        return (
                                          <div>
                                            <SectionHeader
                                              title="Evidence"
                                              actionButton={state && (
                                                <RelationshipAction
                                                  state={state}
                                                  parentNodeLabel="Fact"
                                                  position="inline"
                                                  onAdd={(type, rel, dir) => handleAddNode(type, rel, dir, fact.temp_id)}
                                                  onSelect={(type, rel, dir) => handleSelectNode(type, rel, dir, fact.temp_id)}
                                                />
                                              )}
                                            />
                                            <div className="space-y-4">
                                              {evidence.map((ev: any, evIdx: number) => (
                                                <NodeCard 
                                                  key={ev.temp_id} 
                                                  node={ev} 
                                                  label="Evidence" 
                                                  index={evIdx} 
                                                  depth={2}
                                                  parentId={fact.temp_id}
                                                />
                                              ))}
                                            </div>
                                          </div>
                                        )
                                      })()}
                                      
                                      {/* Judicial Notice Section */}
                                      {(() => {
                                        const factStructure = holdingsStructure?.arguments?.include?.facts?.include || {}
                                        const state = analyzeRelationship(fact, 'judicialNotice', factStructure, schema, factData)
                                        return (
                                          <div>
                                            <SectionHeader
                                              title="Judicial Notice"
                                              actionButton={state && (
                                                <RelationshipAction
                                                  state={state}
                                                  parentNodeLabel="Fact"
                                                  position="inline"
                                                  onAdd={(type, rel, dir) => handleAddNode(type, rel, dir, fact.temp_id)}
                                                  onSelect={(type, rel, dir) => handleSelectNode(type, rel, dir, fact.temp_id)}
                                                />
                                              )}
                                            />
                                            <div className="space-y-4">
                                              {judicialNotice.map((jn: any, jnIdx: number) => (
                                                <NodeCard 
                                                  key={jn.temp_id} 
                                                  node={jn} 
                                                  label="Judicial Notice" 
                                                  index={jnIdx} 
                                                  depth={2}
                                                  parentId={fact.temp_id}
                                                />
                                              ))}
                                            </div>
                                          </div>
                                        )
                                      })()}
                                    </div>
                                  </NodeCard>
                                )
                              })}
                            </div>
                                  </div>
                                )
                              })()}
                            </div>
                          </NodeCard>
                        )
                      })}
                      </div>
                    )}
                    {/* Add Argument button */}
                    {(() => {
                      const state = analyzeRelationship(holding, 'arguments', holdingsStructure || {}, schema, holdingData)
                      if (!state) return null
                      return (
                        <div className={args.length > 0 ? "mt-3" : ""}>
                          <RelationshipAction
                            state={state}
                            parentNodeLabel="Holding"
                            position={args.length === 0 ? 'centered' : 'inline'}
                            onAdd={(type, rel, dir) => handleAddNode(type, rel, dir, holding.temp_id)}
                            onSelect={(type, rel, dir) => handleSelectNode(type, rel, dir, holding.temp_id)}
                          />
                        </div>
                      )
                    })()}
                  </div>
                </div>
              )
            })}
            
            {/* Orphaned Nodes Section */}
            {orphanedNodes.length > 0 && (
              <div className="mt-8 border-t-4 border-red-200 pt-6">
                <div className="mb-4">
                  <h2 className="text-lg font-semibold text-red-700">
                    Orphaned Nodes ({orphanedNodes.length})
                  </h2>
                  <p className="text-xs text-gray-600 mt-1">
                    These nodes were disconnected when their parent was deleted. They will be permanently deleted when you save unless you reassign them.
                  </p>
                  <p className="text-xs text-gray-600 mt-1">
                    To keep a node, use the Add buttons above to connect it to an appropriate parent (you can add new or select an existing node in the modal).
                  </p>
                </div>
                
                <div className="space-y-3">
                  {orphanedNodes.map((node: any) => {
                    const nodeLabel = node.label || 'Unknown'
                    const nodeName = pickNodeName(node) || node.temp_id
                    const { outgoing, incoming } = getNodeConnections(node.temp_id)
                    
                    return (
                      <div key={node.temp_id} className="bg-red-50 border border-red-200 rounded-lg p-4">
                        <div className="flex items-start justify-between mb-2">
                          <div>
                            <div className="text-sm font-semibold text-gray-900">
                              [{nodeLabel}] {nodeName}
                            </div>
                            <div className="text-xs text-gray-600 mt-1">
                              {incoming.length} incoming · {outgoing.length} outgoing connections
                            </div>
                          </div>
                        </div>
                        
                        {/* Show a preview of properties */}
                        <div className="mt-2 text-xs text-gray-700">
                          {Object.entries(node.properties || {}).slice(0, 2).map(([key, value]) => (
                            <div key={key} className="truncate">
                              <span className="font-medium">{formatLabel(key)}:</span> {String(value).slice(0, 100)}
                            </div>
                          ))}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Footer Save Button */}
        <div className="sticky bottom-0 z-10 border-t bg-white/80 backdrop-blur">
          <div className="mx-auto max-w-6xl px-6 py-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                {scrollHistory.length > 0 && (
                  <Button
                    variant="outline"
                    onClick={() => {
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
                  >
                    Back
                  </Button>
                )}
              </div>
              <div className="flex items-center gap-3">
                {hasUnsavedChanges && (
                  <div className="flex items-center gap-2 text-amber-600 text-sm">
                    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                    </svg>
                    <span className="font-medium">Unsaved changes</span>
                  </div>
                )}
                {orphanedNodes.length > 0 && (
                  <div className="flex items-center gap-2 text-red-600 text-sm">
                    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                    </svg>
                    <span className="font-medium">{orphanedNodes.length} orphaned node{orphanedNodes.length !== 1 ? 's' : ''} will be deleted</span>
                  </div>
                )}
                <Button onClick={onSave} disabled={saving}>{saving ? 'Saving...' : 'Save'}</Button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* View Node Connections Modal */}
      {viewingConnectionsNodeId && (() => {
        const node = graphState.nodes.find((n: any) => n.temp_id === viewingConnectionsNodeId)
        if (!node) return null
        const { outgoing, incoming } = getNodeConnections(viewingConnectionsNodeId)
        const nodeLabel = node.label || 'Node'
        const nodeName = pickNodeName(node) || viewingConnectionsNodeId

        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ position: 'fixed', inset: 0, zIndex: 9999 }}>
            <div className="absolute inset-0 bg-black/50" onClick={() => setViewingConnectionsNodeId(null)} />
            <div className="relative z-50 w-full max-w-2xl mx-4 rounded-lg border bg-white p-6 shadow-xl max-h-[80vh] overflow-y-auto">
              <div className="flex items-start justify-between mb-4">
                <div>
                  <h3 className="text-lg font-semibold text-gray-900">{nodeLabel}: {nodeName}</h3>
                  <p className="text-xs text-gray-600 mt-1">View and manage all connections for this node</p>
                </div>
                <button
                  onClick={() => setViewingConnectionsNodeId(null)}
                  className="text-gray-400 hover:text-gray-600 cursor-pointer"
                >
                  ✕
                </button>
              </div>

              {/* Outgoing Relationships */}
              <div className="mb-6">
                <h4 className="text-sm font-semibold text-gray-700 mb-3">
                  Outgoing Connections ({outgoing.length})
                </h4>
                {outgoing.length === 0 ? (
                  <p className="text-xs text-gray-500 italic">No outgoing connections</p>
                ) : (
                  <div className="space-y-2">
                    {outgoing.map((edge: any) => (
                      <div key={edge.idx} className="flex items-center justify-between bg-gray-50 rounded p-3 text-xs">
                        <div className="flex-1">
                          <div className="font-medium text-gray-700">{edge.label}</div>
                          <div className="text-gray-600 mt-1">
                            → <span className="text-purple-600 font-medium">[{getNodeTypeLabel(edge.to)}]</span> {getNodeDisplayName(edge.to)}
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => {
                              setEditingEdgeIdx(edge.idx)
                              setEditToValue(edge.to)
                            }}
                            className="p-1.5 rounded hover:bg-gray-200 text-gray-600 cursor-pointer"
                            title="Edit relationship"
                          >
                            <Pencil className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => setConfirmDeleteIdx(edge.idx)}
                            className="p-1.5 rounded hover:bg-red-100 text-red-600 cursor-pointer"
                            title="Delete relationship"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Incoming Relationships */}
              <div className="mb-6">
                <h4 className="text-sm font-semibold text-gray-700 mb-3">
                  Incoming Connections ({incoming.length})
                </h4>
                {incoming.length === 0 ? (
                  <p className="text-xs text-gray-500 italic">No incoming connections</p>
                ) : (
                  <div className="space-y-2">
                    {incoming.map((edge: any) => (
                      <div key={edge.idx} className="flex items-center justify-between bg-gray-50 rounded p-3 text-xs">
                        <div className="flex-1">
                          <div className="font-medium text-gray-700">{edge.label}</div>
                          <div className="text-gray-600 mt-1">
                            ← <span className="text-purple-600 font-medium">[{getNodeTypeLabel(edge.from)}]</span> {getNodeDisplayName(edge.from)}
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => {
                              setEditingEdgeIdx(edge.idx)
                              setEditToValue(edge.to)
                            }}
                            className="p-1.5 rounded hover:bg-gray-200 text-gray-600 cursor-pointer"
                            title="Edit relationship"
                          >
                            <Pencil className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => setConfirmDeleteIdx(edge.idx)}
                            className="p-1.5 rounded hover:bg-red-100 text-red-600 cursor-pointer"
                            title="Delete relationship"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Actions */}
              <div className="flex items-center justify-between pt-4 border-t">
                <button
                  onClick={() => setDeletingNodeId(viewingConnectionsNodeId)}
                  className="px-4 py-2 rounded bg-red-600 text-white text-sm hover:bg-red-700 transition-colors cursor-pointer"
                >
                  Delete Node & All Connections
                </button>
                <button
                  onClick={() => setViewingConnectionsNodeId(null)}
                  className="px-4 py-2 rounded border text-sm hover:bg-gray-50 transition-colors cursor-pointer"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        )
      })()}

      {/* Delete Node Confirmation */}
      {deletingNodeId && (() => {
        const node = graphState.nodes.find((n: any) => n.temp_id === deletingNodeId)
        if (!node) return null
        const nodeLabel = node.label || 'Node'
        const nodeName = pickNodeName(node) || deletingNodeId
        const { outgoing, incoming } = getNodeConnections(deletingNodeId)
        const totalConnections = outgoing.length + incoming.length
        
        // Find all descendants that will be orphaned
        const edges = graphState.edges.filter(e => e.status === 'active')
        const descendants = findDescendants(deletingNodeId, edges)
        const descendantNodes = descendants.map(id => {
          const n = graphState.nodes.find((node: any) => node.temp_id === id)
          return n ? { id, label: n.label || 'Node', name: pickNodeName(n) || id } : null
        }).filter(Boolean)

        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ position: 'fixed', inset: 0, zIndex: 10000 }}>
            <div className="absolute inset-0 bg-black/50" onClick={() => setDeletingNodeId(null)} />
            <div className="relative z-50 w-full max-w-md mx-4 rounded-lg border bg-white p-4 shadow-xl">
              <div className="font-semibold mb-2 text-red-600">Delete Node?</div>
              <div className="text-sm text-gray-700 mb-2">
                Are you sure you want to delete <span className="font-medium">{nodeLabel}: {nodeName}</span>?
              </div>
              <div className="text-xs text-gray-600 mb-2">
                This will delete {totalConnections} connection{totalConnections !== 1 ? 's' : ''}.
              </div>
              {descendantNodes.length > 0 && (
                <div className="text-xs bg-amber-50 border border-amber-200 rounded px-2 py-1.5 mb-2">
                  <div className="font-semibold text-amber-800 mb-1">
                    {descendantNodes.length} child node{descendantNodes.length !== 1 ? 's' : ''} will be orphaned:
                  </div>
                  <div className="ml-2 space-y-0.5 max-h-24 overflow-y-auto">
                    {descendantNodes.slice(0, 5).map((desc: any) => (
                      <div key={desc.id} className="text-amber-700">
                        • [{desc.label}] {String(desc.name).slice(0, 40)}
                      </div>
                    ))}
                    {descendantNodes.length > 5 && (
                      <div className="text-amber-700 italic">... and {descendantNodes.length - 5} more</div>
                    )}
                  </div>
                  <div className="mt-1 text-amber-700">
                    These nodes will be available for reassignment before saving.
                  </div>
                </div>
              )}
              <div className="text-xs text-gray-600 bg-gray-50 border border-gray-200 rounded px-2 py-1.5 mb-4">
                <strong>Note:</strong> The deletion will be persisted when you save the case.
              </div>
              <div className="flex items-center justify-end gap-2">
                <button
                  type="button"
                  className="rounded border px-3 py-1.5 text-sm cursor-pointer"
                  onClick={() => setDeletingNodeId(null)}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="rounded bg-red-600 text-white px-3 py-1.5 text-sm hover:bg-red-700 transition-colors cursor-pointer"
                  onClick={() => deleteNode(deletingNodeId)}
                >
                  Delete Node
                </button>
              </div>
            </div>
          </div>
        )
      })()}

      {/* Edit relationship modal */}
      {editingEdgeIdx !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ position: 'fixed', inset: 0, zIndex: 9999 }}>
          <div className="absolute inset-0 bg-black/50" onClick={() => setEditingEdgeIdx(null)} />
          <div className="relative z-50 w-full max-w-md mx-4 rounded-lg border bg-white p-4 text-xs shadow-xl">
            <div className="font-semibold mb-2">Edit relationship destination</div>
            <select
              className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs shadow-sm focus:border-gray-400 focus:outline-none"
              value={editToValue}
              onChange={e => setEditToValue(e.target.value)}
            >
              <option value="">Select node</option>
              {nodeOptions.map(opt => (
                <option key={opt.id} value={opt.id}>{opt.display}</option>
              ))}
            </select>
            <div className="mt-4 flex flex-wrap items-center justify-end gap-2">
              <button
                type="button"
                className="rounded border px-3 py-1 min-w-[84px] cursor-pointer"
                onClick={() => setEditingEdgeIdx(null)}
              >
                Cancel
              </button>
              <div
                className="rounded bg-blue-600 text-white text-center px-3 py-1 min-w-[84px] transition-colors hover:brightness-95 cursor-pointer"
                onClick={() => {
                  if (editingEdgeIdx !== null) {
                    setValueAtPath(['edges', editingEdgeIdx, 'to'], editToValue)
                  }
                  setEditingEdgeIdx(null)
                }}
              >
                Save
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Delete relationship confirmation */}
      {confirmDeleteIdx !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ position: 'fixed', inset: 0, zIndex: 9999 }}>
          <div className="absolute inset-0 bg-black/50" onClick={() => setConfirmDeleteIdx(null)} />
          <div className="relative z-50 w-full max-w-md mx-4 rounded-lg border bg-white p-4 text-xs shadow-xl">
            <div className="font-semibold mb-2">Delete relationship?</div>
            <div className="text-xs text-gray-600">This action cannot be undone.</div>
            <div className="mt-4 flex flex-wrap items-center justify-end gap-2">
              <button
                type="button"
                className="rounded border px-3 py-1 min-w-[84px] cursor-pointer"
                onClick={() => setConfirmDeleteIdx(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="rounded !bg-red-600 text-white px-3 py-1 min-w-[84px] transition-colors hover:brightness-95 cursor-pointer"
                onClick={() => {
                  const idx = confirmDeleteIdx
                  setGraphState((prev) => {
                    const activeEdges = prev.edges.filter(e => e.status === 'active')
                    // Find the edge at the given index in active edges
                    const edgeToDelete = activeEdges[idx!]
                    if (!edgeToDelete) return prev
                    
                    // Mark that edge as deleted in the full edges array
                    return {
                      ...prev,
                      edges: prev.edges.map(e => 
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
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
      {/* Add node modal */}
      <AddNodeModal
        open={addModalOpen}
        nodeType={addModalType}
        schema={schema}
        existingNodes={nodesArrayForModals}
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
          setGraphState((prev) => {
            const nodes = [...prev.nodes]
            const nextEdges = [...prev.edges]

            // Ensure node exists and is active (avoid duplicates; revive orphaned/deleted)
            const existingIndex = nodes.findIndex(n => n.temp_id === node.temp_id)
            if (existingIndex >= 0) {
              const existing = nodes[existingIndex]
              if (existing.status !== 'active') {
                nodes[existingIndex] = { ...existing, status: 'active' as const }
              }
            } else {
              nodes.push({
                ...node,
                status: 'active' as const,
                source: 'user-created' as const
              })
            }

            // Helper to add or reactivate an edge
            const ensureActiveEdge = (from: string, to: string, label: string) => {
              const idx = nextEdges.findIndex(e => e.from === from && e.to === to && e.label === label)
              if (idx >= 0) {
                if (nextEdges[idx].status !== 'active') {
                  nextEdges[idx] = { ...nextEdges[idx], status: 'active' as const }
                }
              } else {
                nextEdges.push({ from, to, label, status: 'active' as const })
              }
            }

            // Add edges from the modal
            edges.forEach((e: any) => ensureActiveEdge(e.from, e.to, e.label))

            // Add edge to parent if context is provided
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


