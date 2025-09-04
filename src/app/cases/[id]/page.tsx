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

  if (!data) return <div className="p-8">Loading...</div>

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

  const Field = ({ label, value, path, depth = 0 }: { label: string, value: any, path: (string|number)[], depth?: number }) => {
    const indentStyle = useMemo(() => ({ marginLeft: depth * 16 }), [depth])

    if (value === null || typeof value === 'string' || typeof value === 'number') {
      const inputType = typeof value === 'number' ? 'number' : 'text'
      return (
        <div className="flex items-center gap-2" style={indentStyle}>
          <label className="w-56 text-sm text-gray-700">{label}</label>
          <input
            className="flex-1 border rounded px-2 py-1"
            type={inputType}
            value={value === null ? '' : String(value)}
            onChange={e => {
              const v = inputType === 'number' ? (e.target.value === '' ? '' : Number(e.target.value)) : e.target.value
              setValueAtPath(path, v === '' ? '' : v)
            }}
          />
        </div>
      )
    }

    if (typeof value === 'boolean') {
      return (
        <div className="flex items-center gap-2" style={indentStyle}>
          <label className="w-56 text-sm text-gray-700">{label}</label>
          <input
            type="checkbox"
            checked={value}
            onChange={e => setValueAtPath(path, e.target.checked)}
          />
        </div>
      )
    }

    if (Array.isArray(value)) {
      return (
        <div className="space-y-2" style={indentStyle}>
          <div className="text-sm font-medium text-gray-800">{label} (array)</div>
          {value.map((item, idx) => (
            <Field key={idx} label={`${label}[${idx}]`} value={item} path={[...path, idx]} depth={depth + 1} />
          ))}
        </div>
      )
    }

    if (typeof value === 'object') {
      const entries = Object.entries(value as Record<string, any>)
      return (
        <div className="space-y-2" style={indentStyle}>
          <div className="text-sm font-medium text-gray-800">{label} (object)</div>
          {entries.length === 0 && (
            <div className="text-sm text-gray-500" style={{ marginLeft: 16 }}>Empty object</div>
          )}
          {entries.map(([k, v]) => (
            <Field key={k} label={k} value={v} path={[...path, k]} depth={depth + 1} />
          ))}
        </div>
      )
    }

    return (
      <div className="flex items-center gap-2" style={indentStyle}>
        <label className="w-56 text-sm text-gray-700">{label}</label>
        <input className="flex-1 border rounded px-2 py-1" value={String(value)} onChange={e => setValueAtPath(path, e.target.value)} />
      </div>
    )
  }

  return (
    <div className="p-8 space-y-4">
      <h1 className="text-2xl font-bold">Edit Case</h1>
      {error && <div className="text-red-600">{error}</div>}
      <div className="space-y-3">
        <Field label="root" value={formData} path={[]} depth={0} />
      </div>
      <div className="flex gap-2">
        <Button onClick={onSave} disabled={saving}>{saving ? 'Saving...' : 'Save'}</Button>
      </div>
    </div>
  )
}


