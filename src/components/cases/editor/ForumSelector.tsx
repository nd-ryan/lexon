'use client'

import { useAppStore } from '@/lib/store/appStore'
import { useMemo } from 'react'

interface ForumSelectorProps {
  proceedingId: string
  currentForum: any // The currently selected Forum node (or null)
  currentJurisdiction: any // The Jurisdiction associated with current Forum (or null)
  isViewMode: boolean
  onSelect: (forumNode: any, jurisdictionNode: any) => void
}

export function ForumSelector({
  proceedingId,
  currentForum,
  currentJurisdiction,
  isViewMode,
  onSelect
}: ForumSelectorProps) {
  const catalogNodes = useAppStore(s => s.catalogNodes)
  
  const forumOptions = useMemo(() => {
    return catalogNodes['Forum'] || []
  }, [catalogNodes])
  
  const currentForumId = currentForum?.temp_id || ''
  
  if (isViewMode) {
    // View mode: show as badges
    if (!currentForum) {
      return (
        <div className="text-xs text-gray-500 italic">
          No forum selected
        </div>
      )
    }
    
    return (
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-gray-700">Forum:</span>
          <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded text-xs font-medium">
            {currentForum.properties?.name || 'Unknown Forum'}
          </span>
        </div>
        {currentJurisdiction && (
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-gray-700">Jurisdiction:</span>
            <span className="px-2 py-1 bg-purple-100 text-purple-800 rounded text-xs font-medium">
              {currentJurisdiction.properties?.name || 'Unknown Jurisdiction'}
            </span>
          </div>
        )}
      </div>
    )
  }
  
  // Edit mode: show dropdown
  if (forumOptions.length === 0) {
    return (
      <div className="text-xs text-red-600">
        No forums available. Please ensure the catalog is loaded.
      </div>
    )
  }
  
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <label htmlFor={`forum-select-${proceedingId}`} className="text-xs font-medium text-gray-700">
          Forum:
        </label>
        <select
          id={`forum-select-${proceedingId}`}
          value={currentForumId}
          onChange={(e) => {
            const selectedForumId = e.target.value
            if (!selectedForumId) return
            
            const selectedForum = forumOptions.find((f: any) => f.temp_id === selectedForumId)
            if (!selectedForum) return
            
            // Forum has embedded Jurisdiction in the 'related' field
            const selectedJurisdiction = selectedForum.related?.jurisdiction || null
            
            onSelect(selectedForum, selectedJurisdiction)
          }}
          className="flex-1 px-2 py-1 border border-gray-300 bg-white rounded text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">Select a forum...</option>
          {forumOptions.map((forum: any) => (
            <option key={forum.temp_id} value={forum.temp_id}>
              {forum.properties?.name || 'Unnamed Forum'}
            </option>
          ))}
        </select>
      </div>
      
      {currentJurisdiction && (
        <div className="flex items-center gap-2 pl-4 border-l-2 border-gray-200">
          <span className="text-xs font-medium text-gray-600">Jurisdiction:</span>
          <span className="px-2 py-1 bg-purple-50 text-purple-700 rounded text-xs">
            {currentJurisdiction.properties?.name || 'Unknown Jurisdiction'}
          </span>
        </div>
      )}
    </div>
  )
}

