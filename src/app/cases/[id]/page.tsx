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

export default function CaseEditorPage() {
  const params = useParams()
  const id = params?.id as string
  const schema = useAppStore(s => s.schema as Schema | null)
  const [data, setData] = useState<CaseGraph | null>(null)
  const [formData, setFormData] = useState<CaseGraph>({ nodes: [], edges: [] })
  const [displayData, setDisplayData] = useState<any>(null)
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
      setFormData(rawData.case?.extracted || {})
      setDisplayData(display.success ? display.data : null)
      setViewConfig(display.success ? display.viewConfig : null)
    })()
  }, [id])

  const onSave = async () => {
    try {
      setSaving(true); setError('')
      const res = await fetch(`/api/cases/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(formData) })
      const d = await res.json()
      setData(d.case)
      
      // Refetch display data after save
      const displayRes = await fetch(`/api/cases/${id}/display`)
      const display = await displayRes.json()
      setDisplayData(display.success ? display.data : null)
      setViewConfig(display.success ? display.viewConfig : null)
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

  // Build node lookup for editing operations
  const nodesArray = useMemo<GraphNode[]>(() => (Array.isArray(formData?.nodes) ? formData.nodes : []), [formData])
  const edgesArray = useMemo<GraphEdge[]>(() => (Array.isArray(formData?.edges) ? formData.edges : []), [formData])
  
  // Extract holdings structure from view config
  const holdingsStructure = useMemo(() => {
    return viewConfig?.holdings?.structure || {}
  }, [viewConfig])
  
  const holdingsData = useMemo(() => {
    return displayData?.holdings || []
  }, [displayData])
  
  // Helper: Get nested field value from structured data
  const getNestedValue = (obj: any, key: string): any => {
    if (!obj) return null
    // Try direct key first
    if (obj[key] !== undefined) return obj[key]
    // Try finding a node with this key
    for (const k of Object.keys(obj)) {
      const val = obj[k]
      if (val && typeof val === 'object' && !Array.isArray(val) && val.temp_id) {
        // This is likely a node, check if key matches
        if (k === key) return val
      }
    }
    return null
  }
  
  // Helper: Get all nested collections from structured data
  const getNestedCollections = (obj: any, structureKeys: string[]): Record<string, any[]> => {
    const collections: Record<string, any[]> = {}
    for (const key of structureKeys) {
      const val = obj[key]
      if (Array.isArray(val)) {
        collections[key] = val
      } else if (val && typeof val === 'object') {
        // Single item, treat as array of one
        collections[key] = [val]
      }
    }
    return collections
  }
  
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
    setFormData((prev: any) => {
      const clone = Array.isArray(prev) ? [...prev] : { ...prev }
      let cursor: any = clone
      for (let i = 0; i < path.length - 1; i++) {
        const key = path[i]
        const nextKey = path[i + 1]
        const isNextIndex = typeof nextKey === 'number'
        if (cursor[key] === undefined || cursor[key] === null) {
          cursor[key] = isNextIndex ? [] : {}
        } else {
          cursor[key] = Array.isArray(cursor[key]) ? [...cursor[key]] : { ...cursor[key] }
        }
        cursor = cursor[key]
      }
      const lastKey = path[path.length - 1]
      cursor[lastKey] = value
      return clone
    })
  }



  // Helper to find schema definition for a property
  const getPropertySchema = (path: (string | number)[], propName: string): any => {
    // Determine node label from path (e.g., ['nodes', 0] -> check formData.nodes[0].label)
    let nodeLabel: string | undefined
    if (path[0] === 'nodes' && typeof path[1] === 'number') {
      const nodeIdx = path[1]
      nodeLabel = formData?.nodes?.[nodeIdx]?.label
    }
    
    if (!nodeLabel || !schema) return null
    
    // Find label definition in schema
    const schemaArray = Array.isArray(schema) ? schema : []
    const labelDef = schemaArray.find((s: any) => s?.label === nodeLabel)
    if (!labelDef?.properties) return null
    
    return labelDef.properties[propName]
  }

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

  // Get Case, Proceeding, Parties for top section from backend-structured data
  const caseNode = displayData?.case
  const proceedingNodes = displayData?.proceedings || []
  const partyNodes = displayData?.parties || []
  const forumNodes = displayData?.forums || []
  const jurisdictionNodes = displayData?.jurisdictions || []
  
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
    const edges = formData?.edges || []
    const outgoing = edges.map((e: any, idx: number) => ({ ...e, idx })).filter((e: any) => e.from === nodeId)
    const incoming = edges.map((e: any, idx: number) => ({ ...e, idx })).filter((e: any) => e.to === nodeId)
    return { outgoing, incoming }
  }

  // Get node display name helper
  const getNodeDisplayName = (nodeId: string) => {
    const node = nodesArray.find((n: any) => n.temp_id === nodeId)
    return node ? pickNodeName(node) : nodeId
  }

  // Get node type label helper
  const getNodeTypeLabel = (nodeId: string): string => {
    const node = nodesArray.find((n: any) => n.temp_id === nodeId)
    return node?.label || 'Node'
  }

  // Delete a node and all its relationships
  const deleteNode = (nodeId: string) => {
    setFormData((prev: any) => {
      const nodes = Array.isArray(prev?.nodes) ? prev.nodes.filter((n: any) => n.temp_id !== nodeId) : []
      const edges = Array.isArray(prev?.edges) ? prev.edges.filter((e: any) => e.from !== nodeId && e.to !== nodeId) : []
      return { ...prev, nodes, edges }
    })
    setDeletingNodeId(null)
    setViewingConnectionsNodeId(null)
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

  // Get nodes available for selection (filter by type from existing nodes)
  const getAvailableNodesForSelection = (nodeType: string): GraphNode[] => {
    return nodesArray.filter(n => n.label === nodeType)
  }

  // Handle submission from select modal
  const handleSelectNodeSubmit = (selectedNodeId: string) => {
    if (!selectModalContext) return

    const { parentId, relationship, direction } = selectModalContext

    // Create edge between parent and selected node
    const newEdge: GraphEdge = {
      from: direction === 'outgoing' ? (parentId || '') : selectedNodeId,
      to: direction === 'outgoing' ? selectedNodeId : (parentId || ''),
      label: relationship
    }

    setFormData((prev: any) => {
      const edges = Array.isArray(prev?.edges) ? [...prev.edges, newEdge] : [newEdge]
      return { ...prev, edges }
    })

    setSelectModalOpen(false)
    setSelectModalContext(null)
  }

  // Node Action Menu Component
  const NodeActionMenu = ({ nodeId }: { nodeId: string }) => {
    const [menuOpen, setMenuOpen] = useState(false)
    const { outgoing, incoming } = getNodeConnections(nodeId)
    const totalConnections = outgoing.length + incoming.length

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
    children 
  }: { 
    node: any; 
    label: string; 
    index?: number; 
    depth?: number; 
    badge?: React.ReactNode;
    children?: React.ReactNode 
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
          <NodeActionMenu nodeId={node.temp_id} />
        </div>
        <ObjectFields 
          obj={node.properties || {}} 
          path={['nodes', nodesArray.indexOf(node), 'properties']} 
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
      
      const items = Array.isArray(value) ? value : [value]
      const isCollapsible = ['arguments', 'facts'].includes(key)
      
      items.forEach((item: any, idx: number) => {
        if (!item || !item.temp_id) return
        
        const expanded = isCollapsible && 
          (key === 'arguments' ? expandedArgs.has(item.temp_id) : expandedFacts.has(item.temp_id))
        
        const toggleFn = key === 'arguments' ? toggleArg : toggleFact
        
        elements.push(
          <div key={`${key}-${item.temp_id}`} className="space-y-1">
            <div className="flex items-center gap-1">
              {isCollapsible && (
                <div
                  onClick={() => toggleFn(item.temp_id)}
                  className="px-1 cursor-pointer text-gray-500 hover:text-gray-700"
                >
                  <span className="text-xs">{expanded ? '▼' : '▶'}</span>
                </div>
              )}
              <div
                onClick={() => scrollToNodeById(item.temp_id, holdingId)}
                className="flex-1 px-2 py-1 rounded text-xs hover:bg-gray-100 text-gray-600 cursor-pointer"
              >
                {formatLabel(key === 'arguments' ? 'argument' : key === 'facts' ? 'fact' : item.label || key)} {idx + 1}
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
                  const state = analyzeRelationship(parentNode, 'proceedings', viewConfig?.topLevel || {}, schema, displayData)
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
                  const state = analyzeRelationship(parentNode, 'forums', viewConfig?.topLevel || {}, schema, displayData)
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
                        {forumNodes.map((forum: any, idx: number) => (
                          <NodeCard key={forum.temp_id} node={forum} label="Forum" index={idx} depth={0} />
                        ))}
                      </div>
                    </div>
                  )
                })()}
                
                {/* Parties Section */}
                {(() => {
                  const parentNode = getParentNodeFromConfig('parties')
                  const parentLabel = viewConfig?.topLevel?.parties?.from || 'Proceeding'
                  const state = analyzeRelationship(parentNode, 'parties', viewConfig?.topLevel || {}, schema, displayData)
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
              const ruling = holdingData.ruling
              const reliefTypes = holdingData.ruling?.reliefTypes || []
              const issue = holdingData.issue
              const doctrines = holdingData.issue?.doctrines || []
              const policies = holdingData.issue?.policies || []
              const factPatterns = holdingData.issue?.factPatterns || []
              const args = holdingData.arguments || []
              
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
                                  <NodeCard key={relief.temp_id} node={relief} label="Relief Type" index={relIdx} depth={1} />
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
                                    <NodeCard key={doc.temp_id} node={doc} label="Doctrine" index={docIdx} depth={1} />
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
                                    <NodeCard key={pol.temp_id} node={pol} label="Policy" index={polIdx} depth={1} />
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
                                    <NodeCard key={fp.temp_id} node={fp} label="Fact Pattern" index={fpIdx} depth={1} />
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
                          const laws = argData.laws || []
                          const facts = argData.facts || []
                          
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
                                        <NodeCard key={law.temp_id} node={law} label="Law" index={lawIdx} depth={1} />
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
                                const witnesses = factData.witnesses || []
                                const evidence = factData.evidence || []
                                const judicialNotice = factData.judicialNotice || []
                                
                                return (
                                  <NodeCard key={fact.temp_id} node={fact} label="Fact" index={factIdx} depth={1}>
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
                                                <NodeCard key={wit.temp_id} node={wit} label="Witness" index={witIdx} depth={2} />
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
                                                <NodeCard key={ev.temp_id} node={ev} label="Evidence" index={evIdx} depth={2} />
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
                                                <NodeCard key={jn.temp_id} node={jn} label="Judicial Notice" index={jnIdx} depth={2} />
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
              <div className="flex items-center gap-2">
                <Button onClick={onSave} disabled={saving}>{saving ? 'Saving...' : 'Save'}</Button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* View Node Connections Modal */}
      {viewingConnectionsNodeId && (() => {
        const node = nodesArray.find((n: any) => n.temp_id === viewingConnectionsNodeId)
        if (!node) return null
        const { outgoing, incoming } = getNodeConnections(viewingConnectionsNodeId)
        const nodeLabel = node.label || 'Node'
        const nodeName = getNodeDisplayName(viewingConnectionsNodeId)

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
        const node = nodesArray.find((n: any) => n.temp_id === deletingNodeId)
        if (!node) return null
        const nodeLabel = node.label || 'Node'
        const nodeName = getNodeDisplayName(deletingNodeId)
        const { outgoing, incoming } = getNodeConnections(deletingNodeId)
        const totalConnections = outgoing.length + incoming.length

        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ position: 'fixed', inset: 0, zIndex: 10000 }}>
            <div className="absolute inset-0 bg-black/50" onClick={() => setDeletingNodeId(null)} />
            <div className="relative z-50 w-full max-w-md mx-4 rounded-lg border bg-white p-4 shadow-xl">
              <div className="font-semibold mb-2 text-red-600">Delete Node?</div>
              <div className="text-sm text-gray-700 mb-2">
                Are you sure you want to delete <span className="font-medium">{nodeLabel}: {nodeName}</span>?
              </div>
              <div className="text-xs text-gray-600 mb-4">
                This will also delete {totalConnections} connection{totalConnections !== 1 ? 's' : ''}. This action cannot be undone.
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
                className="rounded border px-3 py-1 min-w-[84px]"
                onClick={() => setEditingEdgeIdx(null)}
              >
                Cancel
              </button>
              <div
                className="rounded bg-blue-600 text-white text-center px-3 py-1 min-w-[84px] transition-colors hover:brightness-95"
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
                className="rounded border px-3 py-1 min-w-[84px]"
                onClick={() => setConfirmDeleteIdx(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="rounded !bg-red-600 text-white px-3 py-1 min-w-[84px] transition-colors hover:brightness-95"
                onClick={() => {
                  const idx = confirmDeleteIdx
                  setFormData((prev: any) => {
                    const next = Array.isArray(prev?.edges) ? { ...prev, edges: prev.edges.filter((_: any, i: number) => i !== idx) } : prev
                    return next
                  })
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
        existingNodes={nodesArray}
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
          setFormData((prev: any) => {
            const next = prev ? { ...prev } : {}
            const nodes = Array.isArray(next.nodes) ? [...next.nodes] : []
            nodes.push(node)
            const nextEdges = Array.isArray(next.edges) ? [...next.edges] : []
            
            // Add edges from the modal
            edges.forEach((e: any) => nextEdges.push(e))
            
            // Add edge to parent if context is provided
            if (addModalContext?.parentId && addModalContext?.relationship) {
              const parentEdge: GraphEdge = {
                from: addModalContext.direction === 'outgoing' 
                  ? addModalContext.parentId 
                  : node.temp_id,
                to: addModalContext.direction === 'outgoing' 
                  ? node.temp_id 
                  : addModalContext.parentId,
                label: addModalContext.relationship
              }
              nextEdges.push(parentEdge)
            }
            
            next.nodes = nodes
            if (nextEdges.length > 0) next.edges = nextEdges
            return next
          })
          setAddModalOpen(false)
          setAddModalContext(null)
        }}
      />
      
      {/* Select node modal */}
      <SelectNodeModal
        open={selectModalOpen}
        nodeType={selectModalType}
        availableNodes={getAvailableNodesForSelection(selectModalType)}
        allNodes={nodesArray}
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


