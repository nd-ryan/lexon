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

  const Field = ({ label, value, path, depth = 0 }: { label: string, value: any, path: (string|number)[], depth?: number }) => {
    const indentStyle = useMemo(() => ({ marginLeft: depth * 16 }), [depth])
    // const pathKey = pathToKey(path)

    // Hide temp_id wherever it appears
    if (label === 'temp_id') return null

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

    if (value === null || typeof value === 'string' || typeof value === 'number') {
      const inputType = typeof value === 'number' ? 'number' : 'text'
      const isLongText = typeof value === 'string' && (value.length > 120 || value.includes('\n'))
      const [local, setLocal] = useState<string>(value === null ? '' : String(value))
      useEffect(() => {
        setLocal(value === null ? '' : String(value))
      }, [value])
      const commit = () => {
        if (inputType === 'number') {
          const parsed = local === '' ? '' : Number(local)
          setValueAtPath(path, parsed)
        } else {
          setValueAtPath(path, local)
        }
      }
      return (
        <div className="" style={indentStyle}>
          <label className="block text-xs font-medium text-gray-700 mt-2 mb-0.5">{formatLabel(label)}</label>
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
              className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs shadow-sm focus:border-gray-400 focus:outline-none"
              type={inputType}
              value={local}
              onChange={e => setLocal(e.target.value)}
              onBlur={commit}
            />
          )}
        </div>
      )
    }

    if (typeof value === 'boolean') {
      return (
        <div className="flex items-center justify-between" style={indentStyle}>
          <label className="text-xs font-medium text-gray-700">{formatLabel(label)}</label>
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

  return (
    <div className="min-h-screen flex flex-col">
      <div className="p-4 space-y-4 text-xs">
        <h1 className="text-xl font-semibold tracking-tight">Edit Case</h1>
        {!data && (
          <div className="rounded-md border bg-gray-50 px-2 py-1 text-xs text-gray-600">Loading...</div>
        )}
        {error && (
          <div className="rounded-md border border-red-300 bg-red-50 px-2 py-1 text-xs text-red-700">{error}</div>
        )}

        {/* Nodes grouped by type with headings including schema-defined types */}
        {(allNodeTypes.length > 0 || Array.isArray(formData?.nodes)) && (
          <div className="space-y-4">
            <div className="text-xs font-semibold text-gray-900">Nodes</div>
            {allNodeTypes.map((type) => {
              const nodesForType = groupedNodesByType[type] || []
              return (
                <div key={type} className="space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="text-base font-semibold text-gray-900">{formatNodeTypeHeading(type)}</div>
                    <Button variant="outline" onClick={() => addNodeOfType(type)}>
                      {`Add ${formatLabel(type)} Node`}
                    </Button>
                  </div>
                  <div className="border-b" />
                  {nodesForType.length === 0 ? (
                    <div className="text-xs text-gray-500 ml-6 pl-3 border-l border-gray-200">No case data for this node type</div>
                  ) : (
                    <div className="space-y-3 ml-6 pl-3 border-l border-gray-200">
                      {nodesForType.map((node: any, localIdx: number) => {
                        const idx = (nodesArray || []).indexOf(node)
                        const nodeLabel = node?.label
                        const { label: _ignored, ...rest } = node || {}
                        const outgoingEdges = Array.isArray(formData?.edges)
                          ? (formData.edges as any[])
                              .map((e: any, eIdx: number) => ({ e, eIdx }))
                              .filter(({ e }) => e && e.from === node?.temp_id)
                          : []
                        return (
                          <div key={localIdx} id={`node-${node?.temp_id ?? idx}`} className="rounded-md border bg-white p-3">
                            <div className="mb-2 text-xs font-semibold text-gray-700">{nodeLabel || `Node ${idx + 1}`}</div>
                            <ObjectFields obj={rest} path={['nodes', idx]} />
                            {outgoingEdges.length > 0 && (
                              <div className="mt-3 flex flex-col gap-2">
                                <div className="text-[11px] font-semibold text-gray-600">Relationships</div>
                                {outgoingEdges.map(({ e, eIdx }: any) => {
                                  const toValueId = e?.to == null ? '' : String(e.to)
                                  const toDisplay = nodeIdToDisplay[toValueId] || toValueId || 'Unknown'
                                  return (
                                    <div key={eIdx} className="flex flex-row items-center gap-2 md:gap-3 flex-wrap">
                                      <div className="text-xs text-gray-700 shrink-0">
                                        [{nodeLabel || 'Node'}] -- [{e?.label || 'RELATION'}] →
                                      </div>
                                      <button
                                        type="button"
                                        className="text-xs text-blue-600 hover:underline cursor-pointer"
                                        onClick={() => scrollToNode(toValueId)}
                                      >
                                        {toDisplay}
                                      </button>
                                      <div className="flex items-center gap-1 ml-1">
                                        <button
                                          type="button"
                                          aria-label="Edit relationship"
                                          className="inline-flex items-center justify-center p-1 rounded text-gray-600 hover:text-gray-800 hover:bg-gray-100 cursor-pointer"
                                          onClick={(ev) => {
                                            ev.preventDefault();
                                            ev.stopPropagation();
                                            // eslint-disable-next-line no-console
                                            console.debug('Edit click for edge index:', eIdx)
                                            setEditingEdgeIdx(eIdx);
                                            setEditToValue(toValueId)
                                          }}
                                        >
                                          <Pencil className="h-4 w-4" />
                                        </button>
                                        <button
                                          type="button"
                                          aria-label="Delete relationship"
                                          className="inline-flex items-center justify-center p-1 rounded text-gray-600 hover:text-red-600 hover:bg-gray-100 cursor-pointer"
                                          onClick={(ev) => {
                                            ev.preventDefault();
                                            ev.stopPropagation();
                                            // eslint-disable-next-line no-console
                                            console.debug('Delete click for edge index:', eIdx)
                                            setConfirmDeleteIdx(eIdx)
                                          }}
                                        >
                                          <Trash2 className="h-4 w-4" />
                                        </button>
                                      </div>
                                    </div>
                                  )
                                })}
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}

        {/* Fallback for unknown structures */}
        {!('nodes' in (formData || {})) && !('edges' in (formData || {})) && (
          <div className="rounded-lg border bg-white p-3">
            <ObjectFields obj={formData || {}} path={[]} />
          </div>
        )}
      </div>

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


