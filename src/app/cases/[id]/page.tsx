"use client";
import { useEffect, useMemo, useState, useLayoutEffect, useRef } from 'react'
import { useParams } from 'next/navigation'
import Button from '@/components/ui/button'
import { Pencil, Trash2 } from 'lucide-react'
import { useAppStore } from '@/lib/store/appStore'
import AddNodeModal from '@/components/cases/AddNodeModal.client'

export default function CaseEditorPage() {
  const params = useParams()
  const id = params?.id as string
  const schema = useAppStore(s => s.schema)
  const [data, setData] = useState<any>(null)
  const [formData, setFormData] = useState<any>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [editingEdgeIdx, setEditingEdgeIdx] = useState<number | null>(null)
  const [editToValue, setEditToValue] = useState<string>('')
  const [confirmDeleteIdx, setConfirmDeleteIdx] = useState<number | null>(null)
  const [scrollHistory, setScrollHistory] = useState<number[]>([])
  const [addModalOpen, setAddModalOpen] = useState(false)
  const [addModalType, setAddModalType] = useState<string>('')
  // Local edit widgets commit on blur to avoid full re-render per keystroke
  const [activeInputPath, setActiveInputPath] = useState<string | null>(null)
  const selectionRef = useRef<{ start: number | null; end: number | null }>({ start: null, end: null })
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

  // Track expanded/collapsed paths for objects/arrays
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(() => new Set(['']))

  useEffect(() => {
    (async () => {
      const res = await fetch(`/api/cases/${id}`)
      const d = await res.json()
      setData(d.case)
      setFormData(d.case?.extracted || {})
    })()
  }, [id])

  const onSave = async () => {
    try {
      setSaving(true); setError('')
      const res = await fetch(`/api/cases/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(formData) })
      const d = await res.json()
      setData(d.case)
    } catch (e: any) {
      setError(e?.message || 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  // Don't early-return before hooks to keep hook order stable

  const pathToKey = (path: (string | number)[]) => path.join('.')

  const formatLabel = (label: string) => {
    if (label === 'root') return 'Case'
    const spaced = label
      .replace(/[_-]/g, ' ')
      .replace(/([a-z])([A-Z])/g, '$1 $2')
      .replace(/\s+/g, ' ')
      .trim()
    return spaced.charAt(0).toUpperCase() + spaced.slice(1)
  }

  // Build node lookup to show labels and names for edge endpoints
  const nodesArray = useMemo(() => (Array.isArray(formData?.nodes) ? formData.nodes : []), [formData])
  const edgesArray = useMemo(() => (Array.isArray(formData?.edges) ? formData.edges : []), [formData])
  
  // Build relationship map from schema to determine direction
  const relationshipMap = useMemo(() => {
    if (!schema || !Array.isArray(schema)) return {}
    const map: Record<string, { from: string; to: string; label: string }> = {}
    
    schema.forEach((labelDef: any) => {
      const sourceLabel = labelDef?.label
      if (!sourceLabel) return
      
      const relationships = labelDef?.relationships || {}
      Object.entries(relationships).forEach(([relLabel, relDef]: [string, any]) => {
        const targetLabel = typeof relDef === 'string' ? relDef : relDef?.target
        if (targetLabel) {
          // Create a key that uniquely identifies this relationship
          const key = `${sourceLabel}->${relLabel}->${targetLabel}`
          map[key] = { from: sourceLabel, to: targetLabel, label: relLabel }
        }
      })
    })
    
    return map
  }, [schema])
  
  // Helper to find relationship label between two node types from schema
  const findRelationship = (fromLabel: string, toLabel: string): string | null => {
    const matches = Object.values(relationshipMap).filter(
      (rel) => rel.from === fromLabel && rel.to === toLabel
    )
    return matches.length > 0 ? matches[0].label : null
  }
  
  // Helper to find nodes by label
  const getNodesByLabel = (label: string) => 
    nodesArray.filter((n: any) => n?.label === label)
  
  // Helper to find edges by relationship
  const getEdgesByLabel = (relLabel: string) =>
    edgesArray.filter((e: any) => e?.label === relLabel)
  
  // Schema-aware helper to get related nodes
  const getRelatedNodesByType = (nodeTempId: string, nodeLabel: string, targetLabel: string): any[] => {
    // Find the relationship from schema
    const relLabel = findRelationship(nodeLabel, targetLabel)
    if (!relLabel) return []
    
    // Get edges using this relationship
    const edges = edgesArray.filter((e: any) => 
      e?.from === nodeTempId && e?.label === relLabel
    )
    return edges.map((e: any) => nodesArray.find((n: any) => n?.temp_id === e?.to)).filter(Boolean)
  }
  
  // Schema-aware helper for reverse relationships (incoming edges)
  const getRelatedNodesByTypeReverse = (nodeTempId: string, sourceLabel: string, nodeLabel: string): any[] => {
    // Find the relationship from schema (sourceLabel -> nodeLabel)
    const relLabel = findRelationship(sourceLabel, nodeLabel)
    if (!relLabel) return []
    
    // Get edges using this relationship (coming TO this node)
    const edges = edgesArray.filter((e: any) => 
      e?.to === nodeTempId && e?.label === relLabel
    )
    return edges.map((e: any) => nodesArray.find((n: any) => n?.temp_id === e?.from)).filter(Boolean)
  }
  
  // Organize data by Holdings
  const holdingsData = useMemo(() => {
    const holdings = getNodesByLabel('Holding')
    
    return holdings.map((holding: any) => {
      const holdingId = holding?.temp_id
      
      // Get Ruling for this Holding (Ruling -> Holding)
      const rulings = getRelatedNodesByTypeReverse(holdingId, 'Ruling', 'Holding')
      const ruling = rulings[0] // Should be one Ruling per Holding
      
      // Get ReliefTypes from Ruling (Ruling -> ReliefType)
      const reliefTypes = ruling ? getRelatedNodesByType(ruling.temp_id, 'Ruling', 'ReliefType') : []
      
      // Get Issue for this Holding (Holding -> Issue)
      const issues = getRelatedNodesByType(holdingId, 'Holding', 'Issue')
      const issue = issues[0] // Should be one Issue per Holding
      
      // Get Doctrines, Policies, FactPatterns from Issue
      const doctrines = issue ? getRelatedNodesByType(issue.temp_id, 'Issue', 'Doctrine') : []
      const policies = issue ? getRelatedNodesByType(issue.temp_id, 'Issue', 'Policy') : []
      const factPatterns = issue ? getRelatedNodesByType(issue.temp_id, 'Issue', 'FactPattern') : []
      
      // Get Arguments for this Holding (Argument -> Holding)
      const argumentNodes = getRelatedNodesByTypeReverse(holdingId, 'Argument', 'Holding')
      
      // For each Argument, get Laws and Facts
      const argumentsWithDetails = argumentNodes.map((arg: any) => {
        const laws = getRelatedNodesByType(arg.temp_id, 'Argument', 'Law')
        const facts = getRelatedNodesByType(arg.temp_id, 'Argument', 'Fact')
        
        // For each Fact, get Witnesses, Evidence, JudicialNotice
        const factsWithSupport = facts.map((fact: any) => {
          const witnesses = getRelatedNodesByType(fact.temp_id, 'Fact', 'Witness')
          const evidence = getRelatedNodesByType(fact.temp_id, 'Fact', 'Evidence')
          const judicialNotice = getRelatedNodesByType(fact.temp_id, 'Fact', 'JudicialNotice')
          
          return {
            node: fact,
            witnesses,
            evidence,
            judicialNotice
          }
        })
        
        return {
          node: arg,
          laws,
          facts: factsWithSupport
        }
      })
      
      return {
        holding,
        ruling,
        reliefTypes,
        issue,
        doctrines,
        policies,
        factPatterns,
        arguments: argumentsWithDetails
      }
    })
  }, [nodesArray, edgesArray])
  
  // Detect shared Issues across multiple Holdings
  const sharedIssues = useMemo(() => {
    const issueUsage: Record<string, string[]> = {} // issue temp_id -> holding temp_ids
    
    holdingsData.forEach((h: any) => {
      if (h.issue) {
        const issueId = h.issue.temp_id
        if (!issueUsage[issueId]) issueUsage[issueId] = []
        issueUsage[issueId].push(h.holding.temp_id)
      }
    })
    
    // Return only Issues used in multiple Holdings
    return Object.entries(issueUsage)
      .filter(([_, holdingIds]) => holdingIds.length > 1)
      .reduce((acc, [issueId, holdingIds]) => {
        acc[issueId] = holdingIds
        return acc
      }, {} as Record<string, string[]>)
  }, [holdingsData])
  const pickNodeName = (node: any): string | undefined => {
    const p = (node && typeof node === 'object') ? (node.properties || node) : undefined
    const candidates = ['name', 'title', 'text', 'case_name']
    for (const key of candidates) {
      const v = p?.[key]
      if (typeof v === 'string' && v.trim()) return v.trim()
    }
    return undefined
  }
  const nodeOptions = useMemo(() => {
    return (nodesArray || [])
      .map((n: any) => {
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
    const groups: Record<string, any[]> = {}
    ;(nodesArray || []).forEach((node: any) => {
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

  const formatNodeTypeHeading = (type: string) => `${formatLabel(type)} Nodes`

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

  const addNodeOfType = (type: string) => {
    setAddModalType(type)
    setAddModalOpen(true)
  }

  const scrollToNode = (targetId?: string) => {
    if (!targetId) return
    // Save current scroll position so we can return
    if (typeof window !== 'undefined') {
      setScrollHistory(prev => [...prev, window.scrollY])
    }
    const el = document.getElementById(`node-${targetId}`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }

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

  const ToggleIcon = ({ open }: { open: boolean }) => (
    <svg
      className={`h-4 w-4 text-gray-500 transition-transform ${open ? 'rotate-90' : ''}`}
      viewBox="0 0 20 20"
      fill="currentColor"
      aria-hidden="true"
    >
      <path fillRule="evenodd" d="M6 6l6 4-6 4V6z" clipRule="evenodd" />
    </svg>
  )

  const SectionHeader = ({
    label,
    count,
    depth,
    path,
  }: {
    label: string
    count?: number
    depth: number
    path: (string | number)[]
  }) => {
    const key = pathToKey(path)
    const isOpen = expandedPaths.has(key)
    const toggle = () => {
      setExpandedPaths(prev => {
        const next = new Set(prev)
        if (next.has(key)) next.delete(key)
        else next.add(key)
        return next
      })
    }
    return (
      <button
        type="button"
        onClick={toggle}
        className="w-full flex items-center justify-between rounded-md bg-gray-50 hover:bg-gray-100 px-3 py-2 border text-left"
        style={{ marginLeft: depth * 16 }}
      >
        <div className="flex items-center gap-2">
          <ToggleIcon open={isOpen} />
          <span className="text-sm font-medium text-gray-800">{formatLabel(label)}</span>
        </div>
        {typeof count === 'number' && (
          <span className="inline-flex items-center rounded-full bg-gray-200 px-2 py-0.5 text-xs text-gray-700">{count}</span>
        )}
      </button>
    )
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

  const Field = ({ label, value, path, depth = 0 }: { label: string, value: any, path: (string|number)[], depth?: number }) => {
    const indentStyle = useMemo(() => ({ marginLeft: depth * 16 }), [depth])
    
    // Get schema definition for this property
    const propSchema = useMemo(() => getPropertySchema(path, label), [path, label])
    const uiConfig = propSchema?.ui
    const inputType = uiConfig?.input
    const options = uiConfig?.options
    const required = uiConfig?.required

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
      const [local, setLocal] = useState<string>(value === null ? '' : String(value))
      useEffect(() => {
        setLocal(value === null ? '' : String(value))
      }, [value])
      
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

  // Get Case, Proceeding, Parties for top section
  const caseNode = getNodesByLabel('Case')[0]
  const proceedingNodes = getNodesByLabel('Proceeding')
  const partyNodes = getNodesByLabel('Party')
  const forumNodes = getNodesByLabel('Forum')
  const jurisdictionNodes = getNodesByLabel('Jurisdiction')
  
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
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
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
              {jurisdictionNodes.map((juris: any, idx: number) => (
                <div
                  key={juris.temp_id}
                  onClick={() => scrollToNodeById(juris.temp_id)}
                  className="px-2 py-1 rounded text-xs hover:bg-gray-100 text-gray-600 cursor-pointer"
                >
                  Jurisdiction {idx + 1}
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
                const name = pickNodeName(h.holding) || `Holding ${idx + 1}`
                const isActive = activeHoldingId === h.holding.temp_id
                
                return (
                  <div key={h.holding.temp_id} className="space-y-1.5">
                    {/* Holding */}
                    <div
                      onClick={() => scrollToHolding(h.holding.temp_id)}
                      className={`px-2 py-1.5 rounded text-xs cursor-pointer ${
                        isActive ? 'bg-blue-100 text-blue-900 font-medium' : 'hover:bg-gray-100 text-gray-700'
                      }`}
                    >
                      <div className="truncate">{name}</div>
                    </div>
                    
                    {/* Always show content */}
                    <div className="pl-4 space-y-1.5 border-l border-gray-300 ml-2">
                        {/* Holding Details */}
                        <div
                          onClick={() => scrollToNodeById(h.holding.temp_id, h.holding.temp_id)}
                          className="px-2 py-1 rounded text-xs hover:bg-gray-100 text-gray-600 cursor-pointer"
                        >
                          Holding Details
                        </div>
                        
                        {/* Ruling and Relief Types */}
                        {h.ruling && (
                          <div className="space-y-1">
                            <div
                              onClick={() => scrollToNodeById(h.ruling.temp_id, h.holding.temp_id)}
                              className="px-2 py-1 rounded text-xs hover:bg-gray-100 text-gray-600 cursor-pointer"
                            >
                              Ruling
                            </div>
                            {h.reliefTypes.length > 0 && (
                              <div className="pl-4 space-y-1">
                                {h.reliefTypes.map((relief: any, rIdx: number) => (
                                  <div
                                    key={relief.temp_id}
                                    onClick={() => scrollToNodeById(relief.temp_id, h.holding.temp_id)}
                                    className="px-2 py-1 rounded text-xs hover:bg-gray-100 text-gray-500 cursor-pointer"
                                  >
                                    Relief Type {rIdx + 1}
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        )}
                        
                        {/* Issue and its sub-nodes */}
                        {h.issue && (
                          <div className="space-y-1">
                            <div
                              onClick={() => scrollToNodeById(h.issue.temp_id, h.holding.temp_id)}
                              className="px-2 py-1 rounded text-xs hover:bg-gray-100 text-gray-600 cursor-pointer"
                            >
                              Issue
                            </div>
                            <div className="pl-4 space-y-1">
                              {h.doctrines.length > 0 && (
                                <div className="space-y-1">
                                  <div className="text-xs font-semibold text-gray-600 px-2">Doctrines</div>
                                  {h.doctrines.map((doc: any, docIdx: number) => (
                                    <div
                                      key={doc.temp_id}
                                      onClick={() => scrollToNodeById(doc.temp_id, h.holding.temp_id)}
                                      className="px-2 py-1 rounded text-xs hover:bg-gray-100 text-gray-500 cursor-pointer"
                                    >
                                      Doctrine {docIdx + 1}
                                    </div>
                                  ))}
                                </div>
                              )}
                              {h.policies.length > 0 && (
                                <div className="space-y-1">
                                  <div className="text-xs font-semibold text-gray-600 px-2">Policies</div>
                                  {h.policies.map((pol: any, polIdx: number) => (
                                    <div
                                      key={pol.temp_id}
                                      onClick={() => scrollToNodeById(pol.temp_id, h.holding.temp_id)}
                                      className="px-2 py-1 rounded text-xs hover:bg-gray-100 text-gray-500 cursor-pointer"
                                    >
                                      Policy {polIdx + 1}
                                    </div>
                                  ))}
                                </div>
                              )}
                              {h.factPatterns.length > 0 && (
                                <div className="space-y-1">
                                  <div className="text-xs font-semibold text-gray-600 px-2">Fact Patterns</div>
                                  {h.factPatterns.map((fp: any, fpIdx: number) => (
                                    <div
                                      key={fp.temp_id}
                                      onClick={() => scrollToNodeById(fp.temp_id, h.holding.temp_id)}
                                      className="px-2 py-1 rounded text-xs hover:bg-gray-100 text-gray-500 cursor-pointer"
                                    >
                                      Fact Pattern {fpIdx + 1}
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          </div>
                        )}
                        
                        {/* Arguments */}
                        {h.arguments.map((argData: any, argIdx: number) => {
                          const isArgExpanded = expandedArgs.has(argData.node.temp_id)
                          
                          return (
                          <div key={argData.node.temp_id} className="space-y-1">
                            <div className="flex items-center gap-1">
                              <div
                                onClick={() => toggleArg(argData.node.temp_id)}
                                className="px-1 cursor-pointer text-gray-500 hover:text-gray-700"
                              >
                                <span className="text-xs">{isArgExpanded ? '▼' : '▶'}</span>
                              </div>
                              <div
                                onClick={() => scrollToNodeById(argData.node.temp_id, h.holding.temp_id)}
                                className="flex-1 px-2 py-1 rounded text-xs hover:bg-gray-100 text-gray-600 cursor-pointer"
                              >
                                Argument {argIdx + 1}
                              </div>
                            </div>
                            
                            {/* Show content if expanded */}
                            {isArgExpanded && (
                              <div className="pl-5 space-y-1">
                                {/* Laws under this argument */}
                                {argData.laws.length > 0 && (
                                  <div className="space-y-1">
                                    {argData.laws.map((law: any, lawIdx: number) => (
                                      <div
                                        key={law.temp_id}
                                        onClick={() => scrollToNodeById(law.temp_id, h.holding.temp_id)}
                                        className="px-2 py-1 rounded text-xs hover:bg-gray-100 text-gray-500 cursor-pointer"
                                      >
                                        Law {lawIdx + 1}
                                      </div>
                                    ))}
                                  </div>
                                )}
                                
                                {/* Facts under this argument */}
                                {argData.facts.length > 0 && (
                                  <div className="space-y-1">
                                    {argData.facts.map((factData: any, factIdx: number) => {
                                      const isFactExpanded = expandedFacts.has(factData.node.temp_id)
                                      
                                      return (
                                      <div key={factData.node.temp_id} className="space-y-1">
                                        <div className="flex items-center gap-1">
                                          <div
                                            onClick={() => toggleFact(factData.node.temp_id)}
                                            className="px-1 cursor-pointer text-gray-500 hover:text-gray-700"
                                          >
                                            <span className="text-xs">{isFactExpanded ? '▼' : '▶'}</span>
                                          </div>
                                          <div
                                            onClick={() => scrollToNodeById(factData.node.temp_id, h.holding.temp_id)}
                                            className="flex-1 px-2 py-1 rounded text-xs hover:bg-gray-100 text-gray-500 cursor-pointer"
                                          >
                                            Fact {factIdx + 1}
                                          </div>
                                        </div>
                                        
                                        {/* Show fact content if expanded */}
                                        {isFactExpanded && (
                                          <div className="pl-5 space-y-1">
                                            {/* Witnesses under this fact */}
                                            {factData.witnesses.length > 0 && (
                                              <div className="space-y-1">
                                                {factData.witnesses.map((wit: any, witIdx: number) => (
                                                  <div
                                                    key={wit.temp_id}
                                                    onClick={() => scrollToNodeById(wit.temp_id, h.holding.temp_id)}
                                                    className="px-2 py-1 rounded text-xs hover:bg-gray-100 text-gray-400 cursor-pointer"
                                                  >
                                                    Witness {witIdx + 1}
                                                  </div>
                                                ))}
                                              </div>
                                            )}
                                            
                                            {/* Evidence under this fact */}
                                            {factData.evidence.length > 0 && (
                                              <div className="space-y-1">
                                                {factData.evidence.map((ev: any, evIdx: number) => (
                                                  <div
                                                    key={ev.temp_id}
                                                    onClick={() => scrollToNodeById(ev.temp_id, h.holding.temp_id)}
                                                    className="px-2 py-1 rounded text-xs hover:bg-gray-100 text-gray-400 cursor-pointer"
                                                  >
                                                    Evidence {evIdx + 1}
                                                  </div>
                                                ))}
                                              </div>
                                            )}
                                            
                                            {/* Judicial Notice under this fact */}
                                            {factData.judicialNotice.length > 0 && (
                                              <div className="space-y-1">
                                                {factData.judicialNotice.map((jn: any, jnIdx: number) => (
                                                  <div
                                                    key={jn.temp_id}
                                                    onClick={() => scrollToNodeById(jn.temp_id, h.holding.temp_id)}
                                                    className="px-2 py-1 rounded text-xs hover:bg-gray-100 text-gray-400 cursor-pointer"
                                                  >
                                                    Judicial Notice {jnIdx + 1}
                                                  </div>
                                                ))}
                                              </div>
                                            )}
                                          </div>
                                        )}
                                      </div>
                                      )
                                    })}
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                          )
                        })}
                      </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col">
        <div className="p-6 space-y-6 text-xs flex-1 overflow-y-auto">
          <h1 className="text-2xl font-semibold tracking-tight">Edit Case</h1>
        {!data && (
          <div className="rounded-md border bg-gray-50 px-2 py-1 text-xs text-gray-600">Loading...</div>
        )}
        {error && (
          <div className="rounded-md border border-red-300 bg-red-50 px-2 py-1 text-xs text-red-700">{error}</div>
        )}

          {/* Top Section: Case, Proceeding, Parties */}
          <div className="space-y-6">
            <div className="border-b pb-4">
              <h2 className="text-lg font-semibold text-gray-900 mb-3">Case Overview</h2>
              
              {/* Case Details */}
              {caseNode && (
                <div id={`node-${caseNode.temp_id}`} className="bg-white rounded-lg border p-4 mb-4">
                  <div className="flex items-center justify-between mb-2">
                    <div className="text-sm font-semibold text-gray-700">Case</div>
                    <NodeActionMenu nodeId={caseNode.temp_id} />
                  </div>
                  <ObjectFields 
                    obj={caseNode.properties || {}} 
                    path={['nodes', nodesArray.indexOf(caseNode), 'properties']} 
                  />
                </div>
              )}
              
              {/* Proceeding Details */}
              {proceedingNodes.length > 0 && (
                <div className="bg-white rounded-lg border p-4 mb-4">
                  <div className="text-sm font-semibold text-gray-700 mb-2">Proceeding</div>
                  {proceedingNodes.map((proc: any, idx: number) => (
                    <div key={proc.temp_id} id={`node-${proc.temp_id}`} className="mb-3 last:mb-0 bg-gray-50 rounded p-3 relative">
                      <div className="absolute top-2 right-2">
                        <NodeActionMenu nodeId={proc.temp_id} />
                      </div>
                      <ObjectFields 
                        obj={proc.properties || {}} 
                        path={['nodes', nodesArray.indexOf(proc), 'properties']} 
                      />
                    </div>
                  ))}
                </div>
              )}
              
              {/* Forum & Jurisdiction */}
              {(forumNodes.length > 0 || jurisdictionNodes.length > 0) && (
                <div className="bg-white rounded-lg border p-4 mb-4">
                  <div className="text-sm font-semibold text-gray-700 mb-2">Forum & Jurisdiction</div>
                  {forumNodes.map((forum: any) => (
                    <div key={forum.temp_id} id={`node-${forum.temp_id}`} className="mb-3 bg-gray-50 rounded p-3 relative">
                      <div className="flex items-center justify-between mb-1">
                        <div className="text-xs font-medium text-gray-600">Forum</div>
                        <NodeActionMenu nodeId={forum.temp_id} />
                      </div>
                      <ObjectFields 
                        obj={forum.properties || {}} 
                        path={['nodes', nodesArray.indexOf(forum), 'properties']} 
                      />
                    </div>
                  ))}
                  {jurisdictionNodes.map((jur: any) => (
                    <div key={jur.temp_id} id={`node-${jur.temp_id}`} className="mb-3 last:mb-0 bg-gray-50 rounded p-3 relative">
                      <div className="flex items-center justify-between mb-1">
                        <div className="text-xs font-medium text-gray-600">Jurisdiction</div>
                        <NodeActionMenu nodeId={jur.temp_id} />
                      </div>
                      <ObjectFields 
                        obj={jur.properties || {}} 
                        path={['nodes', nodesArray.indexOf(jur), 'properties']} 
                      />
                    </div>
                  ))}
                </div>
              )}
              
              {/* Parties */}
              {partyNodes.length > 0 && (
                <div className="bg-white rounded-lg border p-4">
                  <div className="text-sm font-semibold text-gray-700 mb-4">
                    Parties ({partyNodes.length})
                  </div>
                  <div className="space-y-4">
                    {partyNodes.map((party: any, partyIdx: number) => (
                      <div key={party.temp_id} id={`node-${party.temp_id}`} className={`bg-gray-50 rounded p-2 pl-3 border-l-2 border-gray-200 relative ${partyIdx > 0 ? 'mt-4 pt-4 border-t border-gray-200' : ''}`}>
                        <div className="flex items-start justify-between mb-1">
                          <div className="text-[9px] font-bold text-gray-400 uppercase tracking-wide">
                            Party {partyIdx + 1}
                          </div>
                          <NodeActionMenu nodeId={party.temp_id} />
                        </div>
                        <ObjectFields 
                          obj={party.properties || {}} 
                          path={['nodes', nodesArray.indexOf(party), 'properties']} 
                        />
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Holdings Sections */}
            {holdingsData.map((holdingData: any, idx: number) => {
              const { holding, ruling, reliefTypes, issue, doctrines, policies, factPatterns, arguments: args } = holdingData
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
                    <div id={`node-${holding.temp_id}`} className="bg-white rounded-lg border p-4">
                      <div className="flex items-center justify-between mb-2">
                        <div className="text-sm font-semibold text-gray-700">Holding Details</div>
                        <NodeActionMenu nodeId={holding.temp_id} />
                      </div>
                      <ObjectFields 
                        obj={holding.properties || {}} 
                        path={['nodes', nodesArray.indexOf(holding), 'properties']} 
                      />
                    </div>
                    
                    {/* Ruling */}
                    {ruling && (
                      <div id={`node-${ruling.temp_id}`} className="bg-white rounded-lg border p-4">
                        <div className="flex items-center justify-between mb-2">
                          <div className="text-sm font-semibold text-gray-700">Ruling</div>
                          <NodeActionMenu nodeId={ruling.temp_id} />
                        </div>
                        <ObjectFields 
                          obj={ruling.properties || {}} 
                          path={['nodes', nodesArray.indexOf(ruling), 'properties']} 
                        />
                        
                        {/* Relief Types */}
                        {reliefTypes.length > 0 && (
                          <div className="mt-3 pl-4 border-l-2 border-blue-200">
                            <div className="text-xs font-semibold text-gray-600 mb-3">
                              Relief Types ({reliefTypes.length})
                            </div>
                            <div className="space-y-3">
                              {reliefTypes.map((relief: any, relIdx: number) => (
                                <div key={relief.temp_id} id={`node-${relief.temp_id}`} className={`bg-gray-50 rounded p-2 text-xs relative ${relIdx > 0 ? 'mt-3 pt-3 border-t border-gray-200' : ''}`}>
                                  <div className="flex items-start justify-between mb-1">
                                    <div className="text-[9px] font-bold text-gray-400 uppercase tracking-wide">
                                      Relief Type {relIdx + 1}
                                    </div>
                                    <NodeActionMenu nodeId={relief.temp_id} />
                                  </div>
                                  <ObjectFields 
                                    obj={relief.properties || {}} 
                                    path={['nodes', nodesArray.indexOf(relief), 'properties']} 
                                  />
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                    
                    {/* Issue */}
                    {issue && (
                      <div id={`node-${issue.temp_id}`} className={`bg-white rounded-lg border p-4 ${isShared ? 'border-amber-300 bg-amber-50/30' : ''}`}>
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <div className="text-sm font-semibold text-gray-700">Issue</div>
                            {isShared && (
                              <div className="text-[10px] bg-amber-100 text-amber-800 px-2 py-0.5 rounded-full">
                                Shared across {sharedIssues[issue.temp_id].length} holdings
                              </div>
                            )}
                          </div>
                          <NodeActionMenu nodeId={issue.temp_id} />
                        </div>
                        <ObjectFields 
                          obj={issue.properties || {}} 
                          path={['nodes', nodesArray.indexOf(issue), 'properties']} 
                        />
                        
                        {/* Doctrines, Policies, Fact Patterns */}
                        <div className="mt-3 space-y-3">
                          {doctrines.length > 0 && (
                            <div className="pl-4 border-l-2 border-purple-200">
                              <div className="text-xs font-semibold text-gray-600 mb-3">
                                Doctrines ({doctrines.length})
                              </div>
                              <div className="space-y-3">
                                {doctrines.map((doc: any, docIdx: number) => (
                                  <div key={doc.temp_id} id={`node-${doc.temp_id}`} className={`bg-gray-50 rounded p-2 text-xs relative ${docIdx > 0 ? 'mt-3 pt-3 border-t border-gray-200' : ''}`}>
                                    <div className="flex items-start justify-between mb-1">
                                      <div className="text-[9px] font-bold text-gray-400 uppercase tracking-wide">
                                        Doctrine {docIdx + 1}
                                      </div>
                                      <NodeActionMenu nodeId={doc.temp_id} />
                                    </div>
                                    <ObjectFields 
                                      obj={doc.properties || {}} 
                                      path={['nodes', nodesArray.indexOf(doc), 'properties']} 
                                    />
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                          
                          {policies.length > 0 && (
                            <div className="pl-4 border-l-2 border-green-200">
                              <div className="text-xs font-semibold text-gray-600 mb-3">
                                Policies ({policies.length})
                              </div>
                              <div className="space-y-3">
                                {policies.map((pol: any, polIdx: number) => (
                                  <div key={pol.temp_id} id={`node-${pol.temp_id}`} className={`bg-gray-50 rounded p-2 text-xs relative ${polIdx > 0 ? 'mt-3 pt-3 border-t border-gray-200' : ''}`}>
                                    <div className="flex items-start justify-between mb-1">
                                      <div className="text-[9px] font-bold text-gray-400 uppercase tracking-wide">
                                        Policy {polIdx + 1}
                                      </div>
                                      <NodeActionMenu nodeId={pol.temp_id} />
                                    </div>
                                    <ObjectFields 
                                      obj={pol.properties || {}} 
                                      path={['nodes', nodesArray.indexOf(pol), 'properties']} 
                                    />
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                          
                          {factPatterns.length > 0 && (
                            <div className="pl-4 border-l-2 border-indigo-200">
                              <div className="text-xs font-semibold text-gray-600 mb-3">
                                Fact Patterns ({factPatterns.length})
                              </div>
                              <div className="space-y-3">
                                {factPatterns.map((fp: any, fpIdx: number) => (
                                  <div key={fp.temp_id} id={`node-${fp.temp_id}`} className={`bg-gray-50 rounded p-2 text-xs relative ${fpIdx > 0 ? 'mt-3 pt-3 border-t border-gray-200' : ''}`}>
                                    <div className="flex items-start justify-between mb-1">
                                      <div className="text-[9px] font-bold text-gray-400 uppercase tracking-wide">
                                        Fact Pattern {fpIdx + 1}
                                      </div>
                                      <NodeActionMenu nodeId={fp.temp_id} />
                                    </div>
                                    <ObjectFields 
                                      obj={fp.properties || {}} 
                                      path={['nodes', nodesArray.indexOf(fp), 'properties']} 
                                    />
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                    
                    {/* Arguments */}
                    {args.length > 0 && (
                      <div className="mt-6 pt-6 border-t-2 border-gray-200 space-y-5">
                        <div className="text-sm font-semibold text-gray-700 mb-4">
                          Arguments ({args.length})
                        </div>
                        {args.map((argData: any, argIdx: number) => {
                          const { node: arg, laws, facts } = argData
                          
                        return (
                            <div key={arg.temp_id} id={`node-${arg.temp_id}`} className="bg-white rounded-lg border p-4 relative">
                              <div className="flex items-start justify-between mb-3">
                                <div className="text-[10px] font-bold text-gray-400 uppercase tracking-wide">
                                  Arg {argIdx + 1}
                                </div>
                                <NodeActionMenu nodeId={arg.temp_id} />
                              </div>
                              <ObjectFields 
                                obj={arg.properties || {}} 
                                path={['nodes', nodesArray.indexOf(arg), 'properties']} 
                              />
                              
                              {/* Laws */}
                              {laws.length > 0 && (
                                <div className="mt-3 pl-4 border-l-2 border-red-200">
                                  <div className="text-xs font-semibold text-gray-600 mb-3">
                                    Laws ({laws.length})
                                  </div>
                                  <div className="space-y-3">
                                    {laws.map((law: any, lawIdx: number) => (
                                      <div key={law.temp_id} id={`node-${law.temp_id}`} className={`bg-gray-50 rounded p-2 text-xs relative ${lawIdx > 0 ? 'mt-3 pt-3 border-t border-gray-200' : ''}`}>
                                        <div className="flex items-start justify-between mb-1">
                                          <div className="text-[9px] font-bold text-gray-400 uppercase tracking-wide">
                                            Law {lawIdx + 1}
                                          </div>
                                          <NodeActionMenu nodeId={law.temp_id} />
                                        </div>
                                        <ObjectFields 
                                          obj={law.properties || {}} 
                                          path={['nodes', nodesArray.indexOf(law), 'properties']} 
                                        />
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              )}
                              
                              {/* Facts */}
                              {facts.length > 0 && (
                                <div className="mt-3 pl-4 border-l-2 border-blue-200">
                                  <div className="text-xs font-semibold text-gray-600 mb-3">
                                    Facts ({facts.length})
                                  </div>
                                  <div className="space-y-4">
                                    {facts.map((factData: any, factIdx: number) => {
                                      const { node: fact, witnesses, evidence, judicialNotice } = factData
                                      
                        return (
                                        <div key={fact.temp_id} id={`node-${fact.temp_id}`} className={`bg-gray-50 rounded p-2 relative ${factIdx > 0 ? 'mt-4 pt-3 border-t border-gray-200' : ''}`}>
                                          <div className="flex items-start justify-between mb-1">
                                            <div className="text-[9px] font-bold text-gray-400 uppercase tracking-wide">
                                              Fact {factIdx + 1}
                                            </div>
                                            <NodeActionMenu nodeId={fact.temp_id} />
                                          </div>
                                          <ObjectFields 
                                            obj={fact.properties || {}} 
                                            path={['nodes', nodesArray.indexOf(fact), 'properties']} 
                                          />
                                          
                                          {/* Witnesses */}
                                          {witnesses.length > 0 && (
                                            <div className="mt-2 pl-3 border-l border-gray-300">
                                              <div className="text-[10px] font-semibold text-gray-500 mb-2">
                                                Witnesses ({witnesses.length})
                                      </div>
                                              <div className="space-y-2">
                                                {witnesses.map((wit: any, witIdx: number) => (
                                                  <div key={wit.temp_id} id={`node-${wit.temp_id}`} className={`bg-white rounded p-2 text-[10px] relative ${witIdx > 0 ? 'mt-2 pt-2 border-t border-gray-200' : ''}`}>
                                                    <div className="flex items-start justify-between mb-0.5">
                                                      <div className="text-[8px] font-bold text-gray-400 uppercase tracking-wide">
                                                        Witness {witIdx + 1}
                                                      </div>
                                                      <NodeActionMenu nodeId={wit.temp_id} />
                                                    </div>
                                                    <ObjectFields 
                                                      obj={wit.properties || {}} 
                                                      path={['nodes', nodesArray.indexOf(wit), 'properties']} 
                                                    />
                                      </div>
                                                ))}
                                    </div>
                                            </div>
                                          )}
                                          
                                          {/* Evidence */}
                                          {evidence.length > 0 && (
                                            <div className="mt-2 pl-3 border-l border-gray-300">
                                              <div className="text-[10px] font-semibold text-gray-500 mb-2">
                                                Evidence ({evidence.length})
                                              </div>
                                              <div className="space-y-2">
                                                {evidence.map((ev: any, evIdx: number) => (
                                                  <div key={ev.temp_id} id={`node-${ev.temp_id}`} className={`bg-white rounded p-2 text-[10px] relative ${evIdx > 0 ? 'mt-2 pt-2 border-t border-gray-200' : ''}`}>
                                                    <div className="flex items-start justify-between mb-0.5">
                                                      <div className="text-[8px] font-bold text-gray-400 uppercase tracking-wide">
                                                        Evidence {evIdx + 1}
                                                      </div>
                                                      <NodeActionMenu nodeId={ev.temp_id} />
                                                    </div>
                                                    <ObjectFields 
                                                      obj={ev.properties || {}} 
                                                      path={['nodes', nodesArray.indexOf(ev), 'properties']} 
                                                    />
                                                  </div>
                                                ))}
                                              </div>
                                            </div>
                                          )}
                                          
                                          {/* Judicial Notice */}
                                          {judicialNotice.length > 0 && (
                                            <div className="mt-2 pl-3 border-l border-gray-300">
                                              <div className="text-[10px] font-semibold text-gray-500 mb-2">
                                                Judicial Notice ({judicialNotice.length})
                                              </div>
                                              <div className="space-y-2">
                                                {judicialNotice.map((jn: any, jnIdx: number) => (
                                                  <div key={jn.temp_id} id={`node-${jn.temp_id}`} className={`bg-white rounded p-2 text-[10px] relative ${jnIdx > 0 ? 'mt-2 pt-2 border-t border-gray-200' : ''}`}>
                                                    <div className="flex items-start justify-between mb-0.5">
                                                      <div className="text-[8px] font-bold text-gray-400 uppercase tracking-wide">
                                                        Judicial Notice {jnIdx + 1}
                                                      </div>
                                                      <NodeActionMenu nodeId={jn.temp_id} />
                                                    </div>
                                                    <ObjectFields 
                                                      obj={jn.properties || {}} 
                                                      path={['nodes', nodesArray.indexOf(jn), 'properties']} 
                                                    />
                                                  </div>
                                                ))}
                                              </div>
                              </div>
                            )}
                          </div>
                        )
                      })}
                                  </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
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
        onCancel={() => setAddModalOpen(false)}
        onSubmit={({ node, edges }) => {
          setFormData((prev: any) => {
            const next = prev ? { ...prev } : {}
            const nodes = Array.isArray(next.nodes) ? [...next.nodes] : []
            nodes.push(node)
            const nextEdges = Array.isArray(next.edges) ? [...next.edges] : []
            edges.forEach((e: any) => nextEdges.push(e))
            next.nodes = nodes
            if (nextEdges.length > 0) next.edges = nextEdges
            return next
          })
          setAddModalOpen(false)
        }}
      />
    </div>
  )
}


