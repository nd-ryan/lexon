/**
 * Inline dropdown selector for ReliefType nodes
 * Shows a simple dropdown of the 6 relief types instead of opening a modal
 */

'use client'

import React, { useMemo } from 'react'
import { useAppStore } from '@/lib/store/appStore'
import type { GraphNode } from '@/types/case-graph'

interface ReliefTypeSelectorProps {
  reliefId: string
  currentReliefType: GraphNode | null
  isViewMode: boolean
  onSelect: (reliefTypeNode: GraphNode) => void
}

// Stable empty array to avoid infinite loop
const EMPTY_ARRAY: GraphNode[] = []

export function ReliefTypeSelector({
  reliefId,
  currentReliefType,
  isViewMode,
  onSelect
}: ReliefTypeSelectorProps) {
  // Only subscribe to ReliefType catalog, not all catalog nodes (performance optimization)
  const reliefTypes = useAppStore(s => s.catalogNodes['ReliefType']) || EMPTY_ARRAY

  // Initialize optimistic value from currentReliefType prop - use function form for proper initialization
  // Match by relief_type_id or type property, then find corresponding catalog temp_id
  const [optimisticValue, setOptimisticValue] = React.useState<string>(() => {
    if (!currentReliefType) return ''
    
    // Try to find matching catalog node by relief_type_id or type
    const reliefTypeId = currentReliefType.properties?.relief_type_id
    const reliefType = currentReliefType.properties?.type
    
    const matchingCatalogNode = reliefTypes.find((rt: GraphNode) => {
      if (reliefTypeId && rt.properties?.relief_type_id === reliefTypeId) return true
      if (reliefType && rt.properties?.type === reliefType) return true
      return false
    })
    
    return matchingCatalogNode?.temp_id || currentReliefType.temp_id || ''
  })

  // Sync with prop when it changes (after parent re-render)
  // This ensures the dropdown shows the correct value even if currentReliefType loads later
  // Use a ref to track the last synced value to avoid unnecessary updates
  const lastSyncedRef = React.useRef<string | undefined>(currentReliefType?.temp_id)
  
  React.useEffect(() => {
    const currentTempId = currentReliefType?.temp_id || ''
    const lastSynced = lastSyncedRef.current || ''
    
    // Only sync if the prop value actually changed (not just a re-render)
    if (currentTempId !== lastSynced) {
      // Find matching catalog node by relief_type_id or type
      const reliefTypeId = currentReliefType?.properties?.relief_type_id
      const reliefType = currentReliefType?.properties?.type
      
      const matchingCatalogNode = reliefTypes.find((rt: GraphNode) => {
        if (reliefTypeId && rt.properties?.relief_type_id === reliefTypeId) return true
        if (reliefType && rt.properties?.type === reliefType) return true
        return false
      })
      
      const catalogTempId = matchingCatalogNode?.temp_id || currentTempId
      setOptimisticValue(catalogTempId)
      lastSyncedRef.current = currentTempId
    }
  }, [currentReliefType?.temp_id, currentReliefType?.properties, reliefId, reliefTypes])

  // Memoize formatted options to avoid recalculating on every render
  const reliefTypeOptions = useMemo(() => {
    return reliefTypes.map((rt: GraphNode) => {
      const type = String(rt.properties?.type || 'Unknown')
      const description = rt.properties?.description
      let displayName: string = type
      if (description && typeof description === 'string') {
        const shortDesc = description.length > 50 ? description.slice(0, 50) + '...' : description
        displayName = `${type} - ${shortDesc}`
      }
      return {
        tempId: rt.temp_id,
        displayName,
        node: rt
      }
    })
  }, [reliefTypes])

  if (reliefTypes.length === 0) {
    return (
      <div className="text-xs text-gray-500 italic">
        No relief types available. Please ensure the catalog is loaded.
      </div>
    )
  }

  // View mode: show current selection
  if (isViewMode) {
    if (!currentReliefType) {
      return <div className="text-xs text-gray-400 italic">No relief type selected</div>
    }
    return (
      <div className="mt-4 ml-12">
        <div className="rounded-lg border border-gray-300 p-4 bg-gray-50 shadow-sm">
          <div className="text-sm font-semibold text-gray-900 mb-3">Relief Type</div>
          <div className="space-y-1">
            <div className="flex items-start">
              <span className="text-[10px] uppercase tracking-wide font-medium text-gray-500 mr-2">Type:</span>
              <span className="text-sm text-gray-900">{String(currentReliefType.properties?.type || 'N/A')}</span>
            </div>
            {currentReliefType.properties?.description ? (
              <div className="flex items-start">
                <span className="text-[10px] uppercase tracking-wide font-medium text-gray-500 mr-2">Description:</span>
                <span className="text-sm text-gray-900">{String(currentReliefType.properties.description)}</span>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    )
  }

  // Edit mode: show dropdown
  return (
    <div className="mt-4 ml-12">
      <div className="rounded-lg border border-gray-300 p-4 bg-white shadow-sm">
        <label className="block text-sm font-semibold text-gray-900 mb-2">
          Select Relief Type
        </label>
        <select
          value={optimisticValue}
          onChange={(e) => {
            const selectedId = e.target.value
            // Update local state immediately for instant feedback
            setOptimisticValue(selectedId)
            
            const selected = reliefTypeOptions.find(opt => opt.tempId === selectedId)
            if (selected) {
              // This triggers parent state update which may be slow
              onSelect(selected.node)
            }
          }}
          className="w-full px-2 py-1 border border-gray-300 bg-white rounded text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">-- Select a relief type --</option>
          {reliefTypeOptions.map((opt) => (
            <option key={opt.tempId} value={opt.tempId}>
              {opt.displayName}
            </option>
          ))}
        </select>
        {optimisticValue && (() => {
          // Show the selected relief type info using optimistic value
          const selectedOption = reliefTypeOptions.find(opt => opt.tempId === optimisticValue)
          if (!selectedOption) return null
          
          return (
            <div className="mt-3 p-2 bg-blue-50 rounded border border-blue-200">
              <div className="text-xs text-blue-900">
                <span className="font-medium">Selected:</span> {String(selectedOption.node.properties?.type || '')}
                {selectedOption.node.properties?.description ? (
                  <div className="mt-1 text-blue-700">{String(selectedOption.node.properties.description)}</div>
                ) : null}
              </div>
            </div>
          )
        })()}
      </div>
    </div>
  )
}

