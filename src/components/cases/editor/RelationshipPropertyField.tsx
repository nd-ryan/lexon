/**
 * Component for rendering and editing relationship edge properties
 */

import { getRelationshipPropertySchema } from '@/lib/cases/schemaHelpers'
import { capitalizeFirst } from '@/lib/cases/formatting'
import type { Schema } from '@/types/case-graph'

interface RelationshipPropertyFieldProps {
  sourceId: string
  targetId: string
  relLabel: string
  propName: string
  sourceLabel: string
  isViewMode: boolean
  label: string
  schema: Schema | null
  getValue: (sourceId: string, targetId: string) => string | null
  setValue: (sourceId: string, targetId: string, value: string) => void
}

export function RelationshipPropertyField({
  sourceId,
  targetId,
  relLabel,
  propName,
  sourceLabel,
  isViewMode,
  label,
  schema,
  getValue,
  setValue
}: RelationshipPropertyFieldProps) {
  // Get property schema
  const propSchema = getRelationshipPropertySchema(sourceLabel, relLabel, propName, schema)
  const options = propSchema?.ui?.options || []
  const displayLabel = propSchema?.ui?.label || label
  
  // Get current value
  const currentValue = getValue(sourceId, targetId)
  
  // Capitalize first letter of value for display
  const displayValue = capitalizeFirst(currentValue)
  
  if (isViewMode) {
    if (!currentValue) return null
    
    // Determine badge color based on relationship and value
    let badgeColorClass = 'bg-blue-100 text-blue-800'
    if (relLabel === 'SETS' || propName === 'in_favor') {
      // Mustard yellow for in_favor (ruling card has blue background)
      badgeColorClass = 'bg-yellow-200 text-yellow-900'
    } else if (relLabel === 'RESULTS_IN' || propName === 'relief_status') {
      // Color based on relief_status value
      const statusLower = currentValue.toLowerCase()
      if (statusLower === 'granted') {
        badgeColorClass = 'bg-green-100 text-green-800'
      } else if (statusLower === 'denied') {
        badgeColorClass = 'bg-red-100 text-red-800'
      } else if (statusLower === 'partially granted') {
        badgeColorClass = 'bg-amber-100 text-amber-800'
      }
    }
    
    // For SETS (in_favor), show label with badge
    if (relLabel === 'SETS' || propName === 'in_favor') {
      return (
        <span className="flex items-center gap-2">
          <span className="text-xs text-gray-600">{displayLabel}:</span>
          <span className={`px-2 py-1 rounded text-xs font-medium ${badgeColorClass}`}>
            {displayValue}
          </span>
        </span>
      )
    }
    
    return (
      <span className={`px-2 py-1 rounded text-xs font-medium ${badgeColorClass}`}>
        {displayValue}
      </span>
    )
  }
  
  // Edit mode: return form field - for SETS and RESULTS_IN, place in statusBadge position (top right), otherwise inside card
  if (relLabel === 'SETS' || relLabel === 'RESULTS_IN') {
    // For SETS (in_favor) and RESULTS_IN (relief_status), show as dropdown with label in top right corner
    return (
      <span className="flex items-center gap-2">
        <label className="text-xs text-gray-600">{displayLabel}:</label>
        <select
          className="px-2 py-1 rounded border border-gray-300 text-xs font-medium focus:outline-none focus:ring-2 focus:ring-blue-500"
          value={currentValue || ''}
          onChange={(e) => setValue(sourceId, targetId, e.target.value)}
        >
          <option value="">Select...</option>
          {options.map((opt: string) => (
            <option key={opt} value={opt}>{capitalizeFirst(opt)}</option>
          ))}
        </select>
      </span>
    )
  }
  
  // For other relationships, return form field to be placed inside card
  return (
    <div className="mb-2">
      <label className="block text-xs font-medium text-gray-700 mb-1">
        {displayLabel}
      </label>
      <select
        className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs shadow-sm focus:border-gray-400 focus:outline-none"
        value={currentValue || ''}
        onChange={(e) => setValue(sourceId, targetId, e.target.value)}
      >
        <option value="">Select {displayLabel}...</option>
        {options.map((opt: string) => (
          <option key={opt} value={opt}>{capitalizeFirst(opt)}</option>
        ))}
      </select>
    </div>
  )
}

