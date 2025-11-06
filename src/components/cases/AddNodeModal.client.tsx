'use client'

import { useEffect, useMemo, useState } from 'react'
import type { GraphEdge, GraphNode, Schema, SchemaItem, PropertyUi } from '@/types/case-graph'

interface AddNodeModalProps {
  open: boolean
  nodeType: string
  schema: Schema | null
  existingNodes: GraphNode[]
  parentContext?: {
    parentId: string
    parentLabel: string
    relationship: string
    direction: 'outgoing' | 'incoming'
  } | null
  onCancel: () => void
  onSubmit: (payload: { node: GraphNode; edges: GraphEdge[] }) => void
}

export default function AddNodeModal({ open, nodeType, schema, existingNodes, parentContext, onCancel, onSubmit }: AddNodeModalProps) {
  const schemaArray: SchemaItem[] = useMemo(() => {
    if (!schema) return []
    if (Array.isArray(schema)) return schema as SchemaItem[]
    if (typeof schema === 'string') {
      try {
        const parsed = JSON.parse(schema)
        if (Array.isArray(parsed)) return parsed as SchemaItem[]
      } catch {
        // ignore
      }
    }
    return []
  }, [schema])

  const typeDef: SchemaItem | undefined = useMemo(
    () => schemaArray.find(s => (s?.label || '').toLowerCase() === (nodeType || '').toLowerCase()),
    [schemaArray, nodeType]
  )

  // Prefer new schema.properties shape; fall back to legacy attributes map
  const attributes: Record<string, string> = useMemo(() => {
    if (!typeDef) return {}
    if (typeDef.properties && typeof typeDef.properties === 'object') {
      const out: Record<string, string> = {}
      Object.entries(typeDef.properties).forEach(([key, def]) => {
        const t = (def && typeof def === 'object') ? (def.type || '') : ''
        out[key] = t || ''
      })
      return out
    }
    return typeDef.attributes || {}
  }, [typeDef])
  const propertyUi: Record<string, PropertyUi> = useMemo(() => {
    if (typeDef && typeDef.properties && typeof typeDef.properties === 'object') {
      const uiMap: Record<string, PropertyUi> = {}
      Object.entries(typeDef.properties).forEach(([key, def]) => {
        if (def && typeof def === 'object' && (def as any).ui) uiMap[key] = (def as any).ui
      })
      return uiMap
    }
    return {}
  }, [typeDef])
  const relationshipsMap: Record<string, string> = useMemo(() => {
    const rels = typeDef?.relationships || {}
    const out: Record<string, string> = {}
    Object.entries(rels).forEach(([label, def]) => {
      out[label] = typeof def === 'string' ? def : (def?.target || '')
    })
    return out
  }, [typeDef])

  // Build initial property state
  const [properties, setProperties] = useState<Record<string, any>>({})
  const [relSelections, setRelSelections] = useState<Array<{ targetTempId: string; relLabel: string | null }>>([])
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [mode, setMode] = useState<'new' | 'existing'>('new')
  const [searchTerm, setSearchTerm] = useState<string>('')
  const [selectedExistingId, setSelectedExistingId] = useState<string>('')

  // Determine which attributes to show:
  // Prefer properties seen in existing nodes of the same type; fallback to schema attributes.
  const sameTypeExistingNodes = useMemo(() => {
    const wanted = (nodeType || '').toLowerCase()
    return (existingNodes || []).filter(n => String(n?.label || '').toLowerCase() === wanted)
  }, [existingNodes, nodeType])

  // Build UI field metadata from per-property ui blocks in schema.properties
  const uiFieldMeta = useMemo(() => {
    const entries = Object.entries(propertyUi)
      .map(([key, ui]) => ({ key, ...ui }))
      .filter((f: any) => f && f.key && !f.hidden)
      .sort((a: any, b: any) => (a?.order || 0) - (b?.order || 0))
    return entries.length > 0 ? entries : null
  }, [propertyUi])

  const visibleAttributeKeys = useMemo(() => {
    // Strict: if per-property UI exists, it dictates which fields are shown
    const uiFields: string[] | null = uiFieldMeta ? uiFieldMeta.map((f: any) => String(f.key)) : null
    if (uiFields && uiFields.length > 0) return uiFields
    // Otherwise, infer from existing nodes then schema attributes as fallback
    const keys = new Set<string>()
    sameTypeExistingNodes.forEach(n => {
      const props = (n && typeof n === 'object') ? (n as any).properties || {} : {}
      Object.keys(props || {}).forEach(k => keys.add(k))
    })
    if (keys.size > 0) return Array.from(keys)
    // Fallback to schema attributes
    const schemaKeys = Object.keys(attributes || {})
    return schemaKeys
  }, [sameTypeExistingNodes, attributes, uiFieldMeta])

  useEffect(() => {
    // Initialize fields when modal opens or type changes
    if (!open) return
    setMode('new')
    setSearchTerm('')
    setSelectedExistingId('')
    const init: Record<string, any> = {}
    visibleAttributeKeys.forEach((key) => {
      const fieldCfg = Array.isArray(uiFieldMeta) ? uiFieldMeta.find((f: any) => f.key === key) : undefined
      const cfgInput = fieldCfg?.input
      const schemaType = attributes[key]
      const t = String(schemaType || '').toUpperCase()
      const input = cfgInput || (t.includes('BOOLEAN') ? 'checkbox' : t.includes('INTEGER') || t.includes('FLOAT') || t.includes('NUMBER') ? 'number' : t.includes('LIST') || t.includes('ARRAY') ? 'list' : 'text')
      if (input === 'checkbox') init[key] = false
      else init[key] = ''
    })
    setProperties(init)
    setRelSelections([])
    setErrors({})
  }, [open, attributes, visibleAttributeKeys])

  const handlePropChange = (key: string, value: any) => {
    setProperties(prev => ({ ...prev, [key]: value }))
  }

  const addRelationshipRow = () => {
    setRelSelections(prev => [...prev, { targetTempId: '', relLabel: null }])
  }

  const removeRelationshipRow = (idx: number) => {
    setRelSelections(prev => prev.filter((_, i) => i !== idx))
  }

  const onSelectTargetNode = (idx: number, targetTempId: string) => {
    setRelSelections(prev => {
      const next = [...prev]
      const row = next[idx]
      if (!row) return prev
      row.targetTempId = targetTempId
      // Auto-detect rel label based on selected node's label and source type relationships
      const targetNode = existingNodes.find(n => String(n?.temp_id) === targetTempId)
      const targetLabel = String(targetNode?.label || '')
      let rel: string | null = null
      for (const [relLabel, toLabel] of Object.entries(relationshipsMap)) {
        if (String(toLabel) === targetLabel) { rel = relLabel; break }
      }
      row.relLabel = rel
      return next
    })
  }

  const nodeOptionsByType = useMemo(() => {
    const truncate = (text: string, max = 60): string => {
      if (!text) return ''
      return text.length > max ? `${text.slice(0, max - 1)}…` : text
    }
    const byType: Record<string, Array<{ id: string; display: string }>> = {}
    existingNodes.forEach(n => {
      const id = String(n?.temp_id || '')
      if (!id) return
      const label = String(n?.label || 'Unknown')
      const name = (() => {
        const props = (n?.properties ?? {}) as Record<string, unknown>
        const candidates = ['name', 'title', 'text', 'case_name']
        for (const key of candidates) {
          const v = props[key]
          if (typeof v === 'string' && v.trim()) return v.trim()
        }
        return id
      })()
      const display = `[${label}] ${truncate(String(name))}`
      if (!byType[label]) byType[label] = []
      byType[label].push({ id, display })
    })
    return byType
  }, [existingNodes])

  const allNodeOptions = useMemo(() => {
    const arr: Array<{ id: string; display: string; label: string }> = []
    Object.entries(nodeOptionsByType).forEach(([label, opts]) => {
      opts.forEach(o => arr.push({ id: o.id, display: o.display, label }))
    })
    return arr
  }, [nodeOptionsByType])

  const sameTypeExistingOptions = useMemo(() => {
    const wanted = (nodeType || '').toLowerCase()
    const opts = (existingNodes || []).filter(n => String(n?.label || '').toLowerCase() === wanted)
      .map(n => {
        const id = String(n?.temp_id || '')
        const props = (n?.properties ?? {}) as Record<string, unknown>
        const candidates = ['name', 'title', 'text', 'case_name']
        let name = id
        for (const key of candidates) {
          const v = props[key]
          if (typeof v === 'string' && v.trim()) { name = v.trim(); break }
        }
        return { id, name }
      })
    if (!searchTerm.trim()) return opts
    const lower = searchTerm.toLowerCase()
    return opts.filter(o => o.name.toLowerCase().includes(lower) || o.id.toLowerCase().includes(lower))
  }, [existingNodes, nodeType, searchTerm])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ position: 'fixed', inset: 0, zIndex: 10000 }}>
      <div className="absolute inset-0 bg-black/50" onClick={onCancel} />
      <div className="relative z-50 w-full mx-auto rounded-lg border bg-white shadow-xl flex flex-col" style={{ maxHeight: 'min(70vh, 500px)', height: 'min(70vh, 500px)', width: 'min(60vw, 1000px)', maxWidth: '90vw' }}>
        <div className="flex-shrink-0 p-4 border-b">
          <div className="flex items-center justify-between">
            <div className="font-semibold text-sm">{`Add ${nodeType} Node`}</div>
            <button type="button" className="rounded border px-2 py-1 text-xs hover:bg-gray-50" onClick={onCancel}>Close</button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto px-4 py-3 text-sm" style={{ minHeight: 0, maxHeight: '100%' }}>
        {/* Mode Switch */}
        <div className="mb-3">
          <div className="inline-flex rounded-md border overflow-hidden">
            <button
              type="button"
              className={`px-3 py-1 text-xs ${mode === 'new' ? 'bg-blue-600 text-white' : 'bg-white text-gray-700'} hover:brightness-95`}
              onClick={() => setMode('new')}
            >
              Create new
            </button>
            <button
              type="button"
              className={`px-3 py-1 text-xs border-l ${mode === 'existing' ? 'bg-blue-600 text-white' : 'bg-white text-gray-700'} hover:brightness-95`}
              onClick={() => setMode('existing')}
            >
              Use existing
            </button>
          </div>
        </div>

        {/* Existing selector */}
        {mode === 'existing' && (
          <div className="space-y-2 mb-4">
            <div className="text-xs font-semibold text-gray-700">Select existing {nodeType}</div>
            <input
              type="text"
              placeholder="Search by name or ID..."
              value={searchTerm}
              onChange={e => setSearchTerm(e.target.value)}
              className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs"
            />
            <div className="max-h-56 overflow-y-auto space-y-1">
              {sameTypeExistingOptions.length === 0 ? (
                <div className="text-xs text-gray-500 py-4 text-center">No matching nodes</div>
              ) : (
                sameTypeExistingOptions.map(o => (
                  <div
                    key={o.id}
                    onClick={() => setSelectedExistingId(o.id)}
                    className={`p-2 rounded border cursor-pointer text-xs ${selectedExistingId === o.id ? 'border-blue-500 bg-blue-50' : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'}`}
                  >
                    <div className="font-medium">{o.name}</div>
                    <div className="text-[11px] text-gray-500">ID: {o.id}</div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {/* Properties */}
        {mode === 'new' && (
        <div className="space-y-1.5">
          <div className="text-xs font-semibold text-gray-700">Properties</div>
          {Object.keys(attributes).length === 0 && (
            <div className="text-xs text-gray-500">No attributes defined in schema for this node type.</div>
          )}
          {visibleAttributeKeys.map((key) => {
            const schemaType = attributes[key]
            const t = String(schemaType || '').toUpperCase()
            const value = properties[key]
            const fieldCfg = Array.isArray(uiFieldMeta) ? uiFieldMeta.find((f: any) => f.key === key) : undefined
            const input = fieldCfg?.input || (t.includes('BOOLEAN') ? 'checkbox' : t.includes('INTEGER') || t.includes('FLOAT') || t.includes('NUMBER') ? 'number' : t.includes('LIST') || t.includes('ARRAY') ? 'list' : 'text')
            const help = fieldCfg?.help
            const required = !!fieldCfg?.required
            const options = Array.isArray(fieldCfg?.options) ? fieldCfg.options : undefined
            const displayLabel = (fieldCfg && typeof fieldCfg.label === 'string' && fieldCfg.label.trim()) ? String(fieldCfg.label) : key

            if (input === 'checkbox') {
              return (
                <div key={key}>
                  <label className="flex items-center justify-between gap-2">
                    <span className="text-xs text-gray-700">{displayLabel}{required ? ' *' : ''}</span>
                    <input type="checkbox" className="h-4 w-4" checked={!!value} onChange={e => handlePropChange(key, e.target.checked)} />
                  </label>
                  {help && <div className="mt-0.5 text-[11px] text-gray-500">{help}</div>}
                  {errors[key] && <div className="mt-0.5 text-[11px] text-red-600">{errors[key]}</div>}
                </div>
              )
            }

            if (input === 'select' && options) {
              return (
                <div key={key}>
                  <label className="block text-xs text-gray-700 mb-0.5">{displayLabel}{required ? ' *' : ''}</label>
                  <select className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs" value={value ?? ''} onChange={e => handlePropChange(key, e.target.value)}>
                    <option value="">Select...</option>
                    {options.map((opt: any, i: number) => (
                      <option key={`${key}-${i}`} value={String(opt)}>{String(opt)}</option>
                    ))}
                  </select>
                  {help && <div className="mt-0.5 text-[11px] text-gray-500">{help}</div>}
                  {errors[key] && <div className="mt-0.5 text-[11px] text-red-600">{errors[key]}</div>}
                </div>
              )
            }

            if (input === 'date') {
              return (
                <div key={key}>
                  <label className="block text-xs text-gray-700 mb-0.5">{displayLabel}{required ? ' *' : ''}</label>
                  <input type="date" className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs" value={value || ''} onChange={e => handlePropChange(key, e.target.value)} />
                  {help && <div className="mt-0.5 text-[11px] text-gray-500">{help}</div>}
                  {errors[key] && <div className="mt-0.5 text-[11px] text-red-600">{errors[key]}</div>}
                </div>
              )
            }

            if (input === 'number') {
              return (
                <div key={key}>
                  <label className="block text-xs text-gray-700 mb-0.5">{displayLabel}{required ? ' *' : ''}</label>
                  <input type="number" className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs" value={value ?? ''} onChange={e => handlePropChange(key, e.target.value === '' ? '' : Number(e.target.value))} />
                  {help && <div className="mt-0.5 text-[11px] text-gray-500">{help}</div>}
                  {errors[key] && <div className="mt-0.5 text-[11px] text-red-600">{errors[key]}</div>}
                </div>
              )
            }

            if (input === 'list') {
              return (
                <div key={key}>
                  <label className="block text-xs text-gray-700 mb-0.5">{displayLabel}{required ? ' *' : ''} (comma-separated)</label>
                  <input className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs" value={value || ''} onChange={e => handlePropChange(key, e.target.value)} />
                  {help && <div className="mt-0.5 text-[11px] text-gray-500">{help}</div>}
                  {errors[key] && <div className="mt-0.5 text-[11px] text-red-600">{errors[key]}</div>}
                </div>
              )
            }

            if (input === 'textarea') {
              return (
                <div key={key}>
                  <label className="block text-xs text-gray-700 mb-0.5">{displayLabel}{required ? ' *' : ''}</label>
                  <textarea className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs" rows={3} value={value || ''} onChange={e => handlePropChange(key, e.target.value)} />
                  {help && <div className="mt-0.5 text-[11px] text-gray-500">{help}</div>}
                  {errors[key] && <div className="mt-0.5 text-[11px] text-red-600">{errors[key]}</div>}
                </div>
              )
            }

            const isLong = typeof value === 'string' && value.length > 120
            return (
              <div key={key}>
                <label className="block text-xs text-gray-700 mb-0.5">{displayLabel}{required ? ' *' : ''}</label>
                {isLong ? (
                  <textarea className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs" rows={3} value={value || ''} onChange={e => handlePropChange(key, e.target.value)} />
                ) : (
                  <input className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs" value={value || ''} onChange={e => handlePropChange(key, e.target.value)} />
                )}
                {help && <div className="mt-0.5 text-[11px] text-gray-500">{help}</div>}
                {errors[key] && <div className="mt-0.5 text-[11px] text-red-600">{errors[key]}</div>}
              </div>
            )
          })}
        </div>
        )}

        {/* Relationships */}
        {parentContext ? (
          // When context is provided, only show the auto-created relationship
          <div className="mt-3 space-y-1.5">
            <div className="text-xs font-semibold text-gray-700">Relationship</div>
            <div className="bg-blue-50 border border-blue-200 rounded-md px-3 py-2 text-xs">
              <div className="font-medium text-blue-900 mb-1">Auto-created</div>
              <div className="text-blue-700">
                {parentContext.direction === 'incoming' 
                  ? `← Connected from ${parentContext.parentLabel} via ${parentContext.relationship}`
                  : `→ Connected to ${parentContext.parentLabel} via ${parentContext.relationship}`
                }
              </div>
            </div>
          </div>
        ) : (
          // When no context, show relationship picker (for standalone node creation)
          <div className="mt-3 space-y-1.5">
            <div className="text-xs font-semibold text-gray-700">Relationships</div>
            
            {Object.keys(relationshipsMap).length === 0 && (
              <div className="text-xs text-gray-500">No relationships defined from this node type.</div>
            )}
            
            {relSelections.map((sel, idx) => {
              const hasMapping = !!sel.relLabel
              return (
                <div key={idx} className="flex items-center gap-2">
                  <select
                    className="w-80 max-w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs"
                    style={{ textOverflow: 'ellipsis', whiteSpace: 'nowrap', overflow: 'hidden' }}
                    value={sel.targetTempId}
                    onChange={e => onSelectTargetNode(idx, e.target.value)}
                  >
                    <option value="">Select node</option>
                    {allNodeOptions.map(o => (
                      <option key={o.id} value={o.id}>{o.display}</option>
                    ))}
                  </select>
                  <div className={`text-xs ${hasMapping ? 'text-gray-700' : 'text-red-600'}`}>
                    {sel.targetTempId ? (hasMapping ? sel.relLabel : 'No schema relationship for this pair') : 'Select a node'}
                  </div>
                  <button type="button" className="rounded border px-2 py-1 text-xs" onClick={() => removeRelationshipRow(idx)}>Remove</button>
                </div>
              )
            })}
            
            {Object.keys(relationshipsMap).length > 0 && (
              <button type="button" className="rounded border px-2 py-1 text-xs" onClick={addRelationshipRow}>
                Add relationship
              </button>
            )}
          </div>
        )}

        </div>
        {/* Actions */}
        <div className="flex-shrink-0 p-4 border-t bg-gray-50">
          <div className="flex items-center justify-end gap-2">
            <button type="button" className="rounded border px-3 py-1 min-w-[84px] hover:bg-gray-50" onClick={onCancel}>Cancel</button>
            <button
              type="button"
              className="rounded bg-blue-600 text-white text-center px-3 py-1 min-w-[84px] hover:brightness-95"
              onClick={() => {
              if (mode === 'existing') {
                if (!selectedExistingId) return
                const existing = existingNodes.find(n => String(n?.temp_id) === String(selectedExistingId))
                if (!existing) return
                console.log('AddNodeModal submitting existing node:', existing, 'is_existing:', existing.is_existing)
                const edges = relSelections
                  .filter(sel => sel.targetTempId && sel.relLabel)
                  .map<GraphEdge>(sel => ({ from: existing.temp_id, to: sel.targetTempId, label: sel.relLabel! }))
                onSubmit({ node: existing, edges })
                return
              }

              // Basic validation for new node
              const nextErr: Record<string, string> = {}
              const fieldsForValidation: any[] = Array.isArray(uiFieldMeta) ? uiFieldMeta : []
              fieldsForValidation.forEach((f: any) => {
                const key = f.key
                if (!visibleAttributeKeys.includes(key)) return
                const val = properties[key]
                if (f.required && (val === '' || val === undefined || val === null || (typeof val === 'string' && !val.trim()))) {
                  nextErr[key] = 'Required'
                }
                if (f.input === 'date' && val) {
                  const ok = /^\d{4}-\d{2}-\d{2}$/.test(String(val))
                  if (!ok) nextErr[key] = 'Use YYYY-MM-DD'
                }
              })
              setErrors(nextErr)
              if (Object.keys(nextErr).length > 0) return

              const tempId = (typeof crypto !== 'undefined' && (crypto as any).randomUUID)
                ? (crypto as any).randomUUID()
                : Math.random().toString(36).slice(2, 10) + Date.now().toString(36)
              const normalizedProps: Record<string, unknown> = {}
              Object.entries(properties).forEach(([k, v]) => {
                const t = String(attributes[k] || '').toUpperCase()
                if ((t.includes('LIST') || t.includes('ARRAY')) && typeof v === 'string') {
                  normalizedProps[k] = v.split(',').map(s => s.trim()).filter(Boolean)
                } else {
                  normalizedProps[k] = v
                }
              })

              const newNode: GraphNode = { label: nodeType, temp_id: tempId, properties: normalizedProps }
              const edges = relSelections
                .filter(sel => sel.targetTempId && sel.relLabel)
                .map<GraphEdge>(sel => ({ from: tempId, to: sel.targetTempId, label: sel.relLabel! }))
              onSubmit({ node: newNode, edges })
            }}
          >
              Save
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}


