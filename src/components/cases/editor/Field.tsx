/**
 * Field component for rendering and editing node properties
 */

import React, { useEffect, useMemo, useState } from 'react'
import { formatLabel } from '@/lib/cases/formatting'
import { getPropertySchema } from '@/lib/cases/schemaHelpers'
import { useAppStore } from '@/lib/store/appStore'
import type { Schema } from '@/types/case-graph'

interface FieldProps {
  label: string
  value: any
  path: (string | number)[]
  depth?: number
  isViewMode?: boolean
  graphState: any
  schema: Schema | null
  setPendingEdit: (path: (string | number)[], value: any) => void
  setValueAtPath: (path: (string | number)[], value: any) => void
  pendingEditsRef: React.MutableRefObject<Record<string, any>>
  nodeOptions?: { id: string; display: string }[]
  nodeIdToDisplay?: Record<string, string>
}

export function Field({
  label,
  value,
  path,
  depth = 0,
  isViewMode = false,
  graphState,
  schema,
  setPendingEdit,
  setValueAtPath,
  pendingEditsRef,
  nodeOptions = [],
  nodeIdToDisplay = {}
}: FieldProps) {
  // Subscribe directly to global store for pendingEditsVersion
  const pendingEditsVersion = useAppStore(s => s.pendingEditsVersion)
  
  const indentStyle = useMemo(() => ({ marginLeft: depth * 16 }), [depth])
  
  // Get schema definition for this property
  const propSchema = useMemo(() => getPropertySchema(path, label, graphState, schema), [path, label, graphState, schema])
  const uiConfig = propSchema?.ui
  const inputType = uiConfig?.input
  const options = uiConfig?.options
  const required = uiConfig?.required

  // Check for pending edits for this field (read fresh on every render)
  // Memoize the field path key to avoid creating new strings on every render
  const key = useMemo(() => path.join('.'), [path.join('.')])
  const currentValue = (key in pendingEditsRef.current) 
    ? pendingEditsRef.current[key] 
    : value

  // Local state for form inputs - always declare hooks at top level
  const [local, setLocal] = useState<string>(currentValue === null ? '' : String(currentValue))
  
  // Update local when currentValue changes (including from pending edits)
  // pendingEditsVersion triggers re-check when other instances are edited
  useEffect(() => {
    const freshValue = (key in pendingEditsRef.current)
      ? pendingEditsRef.current[key]
      : value
    const newValue = freshValue === null ? '' : String(freshValue)
    setLocal(newValue)
  }, [value, key, pendingEditsVersion])

  // Hide temp_id wherever it appears
  if (label === 'temp_id') return null
  
  // Hide properties marked as hidden in schema
  if (uiConfig?.hidden) return null

  // Edge endpoints: show node labels in a dropdown, store temp_id
  if ((label === 'from' || label === 'to') && nodeOptions.length > 0) {
    const valueId = value == null ? '' : String(value)
    
    // View mode: show as text
    if (isViewMode) {
      return (
        <div className="w-full mb-3" style={indentStyle}>
          <label className="block text-[10px] uppercase tracking-wide font-medium text-gray-500 mb-1">{formatLabel(label)}</label>
          <div className="text-sm text-gray-900">
            {nodeIdToDisplay[valueId] || valueId || <span className="text-gray-400 italic text-xs">Not set</span>}
          </div>
        </div>
      )
    }
    
    // Edit mode: show dropdown
    return (
      <div className="w-full" style={indentStyle}>
        <label className="block text-xs font-medium text-gray-700 mt-2 mb-0.5">
          {formatLabel(label)}{required ? ' *' : ''}
        </label>
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

  // Schema-based rendering for strings and numbers (including undefined)
  if (value === null || value === undefined || typeof value === 'string' || typeof value === 'number') {
    const displayLabel = uiConfig?.label || formatLabel(label)
    
    // Render dropdown for enums (select with options)
    if (inputType === 'select' && Array.isArray(options) && options.length > 0) {
      // View mode: show as text
      if (isViewMode) {
        return (
          <div className="w-full mb-3" style={indentStyle}>
            <label className="block text-[10px] uppercase tracking-wide font-medium text-gray-500 mb-1">
              {displayLabel}
            </label>
            <div className="text-sm text-gray-900">
              {local || <span className="text-gray-400 italic text-xs">Not selected</span>}
            </div>
          </div>
        )
      }
      
      // Edit mode: show dropdown
      return (
        <div className="w-full" style={indentStyle}>
          <label className="block text-xs font-medium text-gray-700 mt-2 mb-0.5">
            {displayLabel}{required ? ' *' : ''}
          </label>
          <select
            className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs shadow-sm focus:border-gray-400 focus:outline-none"
            value={local}
            onChange={e => {
              const newVal = e.target.value
              setLocal(newVal)
              setPendingEdit(path, newVal)
              setValueAtPath(path, newVal)
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
      // View mode: show as text
      if (isViewMode) {
        return (
          <div className="w-full mb-3" style={indentStyle}>
            <label className="block text-[10px] uppercase tracking-wide font-medium text-gray-500 mb-1">
              {displayLabel}
            </label>
            <div className="text-sm text-gray-900">
              {local || <span className="text-gray-400 italic text-xs">Not set</span>}
            </div>
          </div>
        )
      }
      
      // Edit mode: show date input
      return (
        <div className="w-full" style={indentStyle}>
          <label className="block text-xs font-medium text-gray-700 mt-2 mb-0.5">
            {displayLabel}{required ? ' *' : ''}
          </label>
          <input
            type="date"
            className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs shadow-sm focus:border-gray-400 focus:outline-none"
            value={local}
            onChange={e => {
              const newVal = e.target.value
              setLocal(newVal)
              setPendingEdit(path, newVal)
              setValueAtPath(path, newVal)
            }}
          />
        </div>
      )
    }
    
    // Render number input for numbers
    if (inputType === 'number' || typeof value === 'number') {
      // View mode: show as text
      if (isViewMode) {
        return (
          <div className="w-full mb-3" style={indentStyle}>
            <label className="block text-[10px] uppercase tracking-wide font-medium text-gray-500 mb-1">
              {displayLabel}
            </label>
            <div className="text-sm text-gray-900">
              {local || <span className="text-gray-400 italic text-xs">Not set</span>}
            </div>
          </div>
        )
      }
      
      // Edit mode: show number input
      return (
        <div className="w-full" style={indentStyle}>
          <label className="block text-xs font-medium text-gray-700 mt-2 mb-0.5">
            {displayLabel}{required ? ' *' : ''}
          </label>
          <input
            type="number"
            className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs shadow-sm focus:border-gray-400 focus:outline-none"
            value={local}
            onChange={e => {
              const newVal = e.target.value
              setLocal(newVal)
              const parsed = newVal === '' ? '' : Number(newVal)
              setPendingEdit(path, parsed)
              setValueAtPath(path, parsed)
            }}
          />
        </div>
      )
    }
    
    // Render textarea for long text or textarea input type
    const isLongText = inputType === 'textarea' || (typeof value === 'string' && (value.length > 120 || value.includes('\n')))
    
    // View mode: show as text
    if (isViewMode) {
      return (
        <div className="w-full mb-3" style={indentStyle}>
          <label className="block text-[10px] uppercase tracking-wide font-medium text-gray-500 mb-1">
            {displayLabel}
          </label>
          <div className="text-sm text-gray-900 whitespace-pre-wrap leading-relaxed">
            {local || <span className="text-gray-400 italic text-xs">Not set</span>}
          </div>
        </div>
      )
    }
    
    // Edit mode: show input/textarea
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
            onChange={e => {
              const newVal = e.target.value
              setLocal(newVal)
              setPendingEdit(path, newVal)
              setValueAtPath(path, newVal)
            }}
          />
        ) : (
          <input
            type="text"
            className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs shadow-sm focus:border-gray-400 focus:outline-none"
            value={local}
            onChange={e => {
              const newVal = e.target.value
              setLocal(newVal)
              setPendingEdit(path, newVal)
              setValueAtPath(path, newVal)
            }}
          />
        )}
      </div>
    )
  }

  if (typeof value === 'boolean') {
    const displayLabel = uiConfig?.label || formatLabel(label)
    
    // View mode: show as text
    if (isViewMode) {
      return (
        <div className="flex items-start justify-between mb-3" style={indentStyle}>
          <label className="text-[10px] uppercase tracking-wide font-medium text-gray-500">
            {displayLabel}
          </label>
          <span className="text-sm text-gray-900">
            {value ? 'Yes' : 'No'}
          </span>
        </div>
      )
    }
    
    // Edit mode: show checkbox
    return (
      <div className="flex items-center justify-between" style={indentStyle}>
        <label className="text-xs font-medium text-gray-700">
          {displayLabel}{required ? ' *' : ''}
        </label>
        <input
          className="h-3.5 w-3.5"
          type="checkbox"
          checked={value}
          onChange={e => {
            const newVal = e.target.checked
            setPendingEdit(path, newVal)
            setValueAtPath(path, newVal)
          }}
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
          <Field 
            key={idx} 
            label={`Item ${idx + 1}`} 
            value={item} 
            path={[...path, idx]} 
            depth={depth + 1} 
            isViewMode={isViewMode}
            graphState={graphState}
            schema={schema}
            setPendingEdit={setPendingEdit}
            setValueAtPath={setValueAtPath}
            pendingEditsRef={pendingEditsRef}
            nodeOptions={nodeOptions}
            nodeIdToDisplay={nodeIdToDisplay}
          />
        ))}
      </div>
    )
  }

  if (typeof value === 'object') {
    return (
      <div className="space-y-2" style={indentStyle}>
        <ObjectFields 
          obj={value as Record<string, any>} 
          path={path} 
          depth={depth} 
          isViewMode={isViewMode}
          graphState={graphState}
          schema={schema}
          setPendingEdit={setPendingEdit}
          setValueAtPath={setValueAtPath}
          pendingEditsRef={pendingEditsRef}
          nodeOptions={nodeOptions}
          nodeIdToDisplay={nodeIdToDisplay}
        />
      </div>
    )
  }

  return (
    <div className="" style={indentStyle}>
      <label className="block text-xs font-medium text-gray-700 mt-2 mb-0.5">{formatLabel(label)}</label>
      <input
        className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs shadow-sm focus:border-gray-400 focus:outline-none"
        value={local}
        onChange={e => {
          const newVal = e.target.value
          setLocal(newVal)
          setPendingEdit(path, newVal)
          setValueAtPath(path, newVal)
        }}
      />
    </div>
  )
}

interface ObjectFieldsProps {
  obj: Record<string, any>
  path: (string | number)[]
  depth?: number
  isViewMode?: boolean
  graphState: any
  schema: Schema | null
  setPendingEdit: (path: (string | number)[], value: any) => void
  setValueAtPath: (path: (string | number)[], value: any) => void
  pendingEditsRef: React.MutableRefObject<Record<string, any>>
  nodeOptions?: { id: string; display: string }[]
  nodeIdToDisplay?: Record<string, string>
}

export function ObjectFields({
  obj,
  path,
  depth = 0,
  isViewMode = false,
  graphState,
  schema,
  setPendingEdit,
  setValueAtPath,
  pendingEditsRef,
  nodeOptions,
  nodeIdToDisplay
}: ObjectFieldsProps) {
  // Filter out unwanted properties but preserve the order from backend
  // Backend orders properties according to schema ui.order
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
        <Field 
          key={k} 
          label={k} 
          value={v} 
          path={[...path, k]} 
          depth={depth} 
          isViewMode={isViewMode}
          graphState={graphState}
          schema={schema}
          setPendingEdit={setPendingEdit}
          setValueAtPath={setValueAtPath}
          pendingEditsRef={pendingEditsRef}
          nodeOptions={nodeOptions}
          nodeIdToDisplay={nodeIdToDisplay}
        />
      ))}
    </div>
  )
}

