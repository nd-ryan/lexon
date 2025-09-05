"use client";
import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'next/navigation'
import Button from '@/components/ui/button'

export default function CaseEditorPage() {
  const params = useParams()
  const id = params?.id as string
  const [data, setData] = useState<any>(null)
  const [formData, setFormData] = useState<any>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

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
      return (
        <div className="" style={indentStyle}>
          <label className="block text-xs font-medium text-gray-700 mt-2 mb-0.5">{formatLabel(label)}</label>
          {isLongText ? (
            <textarea
              className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs shadow-sm focus:border-gray-400 focus:outline-none"
              rows={Math.min(12, Math.max(3, Math.ceil((value?.length || 0) / 80)))}
              value={value ?? ''}
              onChange={e => setValueAtPath(path, e.target.value)}
            />
          ) : (
            <input
              className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs shadow-sm focus:border-gray-400 focus:outline-none"
              type={inputType}
              value={value === null ? '' : String(value)}
              onChange={e => {
                const v = inputType === 'number' ? (e.target.value === '' ? '' : Number(e.target.value)) : e.target.value
                setValueAtPath(path, v === '' ? '' : v)
              }}
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
      const entries = Object.entries(value as Record<string, any>)
      if (entries.length === 0) return null
      return (
        <div className="space-y-2" style={indentStyle}>
          {entries.map(([k, v]) => (
            <Field key={k} label={k} value={v} path={[...path, k]} depth={depth} />
          ))}
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
    })
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

        {/* Nodes with inline relationships */}
        {data && 'nodes' in (formData || {}) ? (
          <div className="space-y-2">
            <div className="text-xs font-semibold text-gray-900">Nodes</div>
            {Array.isArray(formData?.nodes) && formData.nodes.length > 0 ? (
              <div className="space-y-3">
                {formData.nodes.map((node: any, idx: number) => {
                  const nodeLabel = node?.label
                  const { label: _ignored, ...rest } = node || {}
                  const outgoingEdges = Array.isArray(formData?.edges)
                    ? (formData.edges as any[])
                        .map((e: any, eIdx: number) => ({ e, eIdx }))
                        .filter(({ e }) => e && e.from === node?.temp_id)
                    : []
                  return (
                    <div key={idx} className="rounded-md border bg-white p-3">
                      <div className="mb-2 text-xs font-semibold text-gray-700">{nodeLabel || `Node ${idx + 1}`}</div>
                      <ObjectFields obj={rest} path={['nodes', idx]} />
                      {outgoingEdges.length > 0 && (
                        <div className="mt-3 flex flex-col gap-2">
                          <div className="text-[11px] font-semibold text-gray-600">Relationships</div>
                          {outgoingEdges.map(({ e, eIdx }: any) => {
                            const toValueId = e?.to == null ? '' : String(e.to)
                            return (
                              <div key={eIdx} className="flex flex-row items-center gap-2 md:gap-3 flex-wrap">
                                <div className="text-xs text-gray-700 shrink-0">
                                  [{nodeLabel || 'Node'}] -- [{e?.label || 'RELATION'}] →
                                </div>
                                <div className="w-full sm:w-auto md:w-80">
                                  <select
                                    className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs shadow-sm focus:border-gray-400 focus:outline-none"
                                    value={toValueId}
                                    onChange={ev => setValueAtPath(['edges', eIdx, 'to'], ev.target.value)}
                                  >
                                    <option value="">Select node</option>
                                    {nodeOptions.map(opt => (
                                      <option key={opt.id} value={opt.id}>{opt.display}</option>
                                    ))}
                                    {!nodeIdToDisplay[toValueId] && toValueId !== '' && (
                                      <option value={toValueId}>{toValueId}</option>
                                    )}
                                  </select>
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
            ) : (
              <div className="text-xs text-gray-500">No nodes</div>
            )}
          </div>
        ) : null}

        {/* Fallback for unknown structures */}
        {!('nodes' in (formData || {})) && !('edges' in (formData || {})) && (
          <div className="rounded-lg border bg-white p-3">
            <ObjectFields obj={formData || {}} path={[]} />
          </div>
        )}
      </div>

      <div className="sticky bottom-0 z-10 border-t bg-white/80 backdrop-blur">
        <div className="mx-auto max-w-6xl px-6 py-3 flex items-center justify-end gap-2">
          <Button onClick={onSave} disabled={saving}>{saving ? 'Saving...' : 'Save'}</Button>
        </div>
      </div>
    </div>
  )
}


