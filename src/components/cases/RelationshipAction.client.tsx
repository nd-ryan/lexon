'use client'

import { formatLabel, type RelationshipState } from '@/lib/relationshipHelpers'

interface RelationshipActionProps {
  state: RelationshipState
  parentNodeLabel?: string
  position: 'inline' | 'centered'
  onAdd: (nodeType: string, relationshipLabel: string, direction: 'outgoing' | 'incoming') => void
  onSelect: (nodeType: string, relationshipLabel: string, direction: 'outgoing' | 'incoming') => void
}

export default function RelationshipAction({ 
  state, 
  parentNodeLabel,
  position, 
  onAdd, 
  onSelect 
}: RelationshipActionProps) {
  // Case 1: Max reached due to cardinality
  if (state.maxReached) {
    const message = `Only one ${formatLabel(state.targetNodeType)} allowed${parentNodeLabel ? ` per ${formatLabel(parentNodeLabel)}` : ''}`
    
    if (position === 'centered') {
      return (
        <div className="flex justify-center py-8">
          <div className="text-sm text-gray-500 italic text-center bg-gray-50 px-6 py-4 rounded-lg border border-gray-200">
            {message}
          </div>
        </div>
      )
    }
    
    return (
      <div className="text-xs text-gray-500 italic mt-2">
        {message}
      </div>
    )
  }
  
  // Case 2: Button to add/select
  const buttonText = state.canCreateNew 
    ? `Add ${formatLabel(state.targetNodeType)}`
    : `Select ${formatLabel(state.targetNodeType)}`
  
  const handleClick = () => {
    if (state.canCreateNew) {
      onAdd(state.targetNodeType, state.relationshipLabel, state.direction)
    } else {
      onSelect(state.targetNodeType, state.relationshipLabel, state.direction)
    }
  }
  
  if (position === 'centered') {
    return (
      <div className="flex justify-center py-8">
        <button 
          onClick={handleClick}
          className="px-6 py-3 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors shadow-sm"
        >
          {buttonText}
        </button>
      </div>
    )
  }
  
  // Inline position - small button
  return (
    <button 
      onClick={handleClick}
      className="px-3 py-1.5 bg-blue-600 text-white rounded text-xs font-medium hover:bg-blue-700 transition-colors shadow-sm"
    >
      {buttonText}
    </button>
  )
}

