'use client'

import { useState, useMemo } from 'react'
import type { GraphNode, GraphEdge } from '@/types/case-graph'

interface SelectNodeModalProps {
  open: boolean
  nodeType: string
  availableNodes: GraphNode[]  // Nodes available for selection
  allNodes?: GraphNode[]  // All nodes for jurisdiction lookup
  allEdges?: GraphEdge[]  // All edges for jurisdiction lookup
  onCancel: () => void
  onSubmit: (nodeId: string) => void
}

export default function SelectNodeModal({ 
  open, 
  nodeType, 
  availableNodes,
  allNodes,
  allEdges,
  onCancel, 
  onSubmit 
}: SelectNodeModalProps) {
  const [selectedId, setSelectedId] = useState<string>('')
  const [searchTerm, setSearchTerm] = useState<string>('')
  const [jurisdictionName, setJurisdictionName] = useState<string>('')
  
  // When Forum is selected, look up its Jurisdiction to display (but not create edge)
  const handleForumSelection = (forumId: string) => {
    if (nodeType === 'Forum' && allEdges && allNodes) {
      // Find PART_OF edge from this Forum to Jurisdiction
      const jurisdictionEdge = allEdges.find(
        e => e.from === forumId && e.label === 'PART_OF'
      )
      
      if (jurisdictionEdge?.to) {
        // Look up jurisdiction name
        const jurisdiction = allNodes.find(n => n.temp_id === jurisdictionEdge.to)
        if (jurisdiction) {
          const props = jurisdiction.properties as Record<string, unknown>
          const name = props?.name as string || 'Unknown Jurisdiction'
          setJurisdictionName(name)
        }
      } else {
        setJurisdictionName('')
      }
    }
  }
  
  const handleSelection = (nodeId: string) => {
    setSelectedId(nodeId)
    handleForumSelection(nodeId)
  }

  // Helper to pick display name from node
  const pickNodeName = (node: GraphNode): string => {
    const props = (node?.properties ?? {}) as Record<string, unknown>
    const candidates = ['name', 'title', 'text', 'label', 'case_name']
    for (const key of candidates) {
      const v = props[key]
      if (typeof v === 'string' && v.trim()) return v.trim()
    }
    return node?.temp_id || 'Unnamed'
  }

  // Build options for selection
  const nodeOptions = useMemo(() => {
    return availableNodes.map(n => ({
      id: n.temp_id,
      name: pickNodeName(n),
      node: n
    }))
  }, [availableNodes])

  // Filter by search term
  const filteredOptions = useMemo(() => {
    if (!searchTerm.trim()) return nodeOptions
    const lower = searchTerm.toLowerCase()
    return nodeOptions.filter(opt => 
      opt.name.toLowerCase().includes(lower) ||
      opt.id.toLowerCase().includes(lower)
    )
  }, [nodeOptions, searchTerm])

  const handleSubmit = () => {
    if (!selectedId) return
    onSubmit(selectedId)
    setSelectedId('')
    setSearchTerm('')
    setJurisdictionName('')
  }

  const handleCancel = () => {
    setSelectedId('')
    setSearchTerm('')
    setJurisdictionName('')
    onCancel()
  }

  if (!open) return null

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center p-4" 
      style={{ position: 'fixed', inset: 0, zIndex: 10000 }}
    >
      <div className="absolute inset-0 bg-black/50" onClick={handleCancel} />
      <div 
        className="relative z-50 w-full mx-auto rounded-lg border bg-white shadow-xl flex flex-col" 
        style={{ maxHeight: 'min(80vh, 600px)', width: 'min(90vw, 600px)' }}
      >
        {/* Header */}
        <div className="flex-shrink-0 p-4 border-b">
          <div className="flex items-center justify-between">
            <div className="font-semibold text-sm">Select {nodeType}</div>
            <button 
              type="button" 
              className="rounded border px-2 py-1 text-xs hover:bg-gray-50 transition-colors" 
              onClick={handleCancel}
            >
              Close
            </button>
          </div>
        </div>

        {/* Search */}
        <div className="flex-shrink-0 p-4 border-b bg-gray-50">
          <input
            type="text"
            placeholder="Search by name..."
            value={searchTerm}
            onChange={e => setSearchTerm(e.target.value)}
            className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          />
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto p-4" style={{ minHeight: 0 }}>
          {filteredOptions.length === 0 ? (
            <div className="text-sm text-gray-500 text-center py-8">
              {searchTerm ? 'No matching nodes found' : 'No nodes available'}
            </div>
          ) : (
            <div className="space-y-2">
              {filteredOptions.map(opt => (
                <div
                  key={opt.id}
                  onClick={() => handleSelection(opt.id)}
                  className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                    selectedId === opt.id
                      ? 'border-blue-500 bg-blue-50'
                      : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                  }`}
                >
                  <div className="font-medium text-sm">{opt.name}</div>
                  <div className="text-xs text-gray-500 mt-1">ID: {opt.id}</div>
                </div>
              ))}
            </div>
          )}
          
          {/* Show Jurisdiction info for Forum selection */}
          {jurisdictionName && (
            <div className="mt-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
              <div className="text-xs font-semibold text-blue-900 mb-1">
                Jurisdiction
              </div>
              <div className="text-xs text-blue-700">
                ✓ This forum is in: <span className="font-medium">{jurisdictionName}</span>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex-shrink-0 p-4 border-t bg-gray-50">
          <div className="flex items-center justify-end gap-2">
            <button 
              type="button" 
              className="rounded border px-4 py-2 text-sm hover:bg-gray-50 transition-colors" 
              onClick={handleCancel}
            >
              Cancel
            </button>
            <button
              type="button"
              className="rounded bg-blue-600 text-white px-4 py-2 text-sm hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              onClick={handleSubmit}
              disabled={!selectedId}
            >
              Select
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

