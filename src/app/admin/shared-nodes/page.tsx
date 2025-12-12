'use client'

import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { useSession } from 'next-auth/react'
import { useRouter } from 'next/navigation'

interface SchemaNode {
  label: string
  case_unique: boolean
  can_create_new: boolean
  properties: Record<string, any>
}

interface SharedNode {
  label: string
  id: string
  name: string
  properties: Record<string, any>
  connectionCount: number
  isOrphaned: boolean
}

interface ConnectedCase {
  case_id: string
  case_name: string
  citation?: string
  currentCount?: number
  status?: string
}

interface NodeDetail {
  node: SharedNode
  connectedCases: ConnectedCase[]
  minPerCase: number
}

type ModalState = 
  | { type: 'none' }
  | { type: 'edit'; node: SharedNode; detail: NodeDetail | null; loading: boolean }
  | { type: 'delete'; node: SharedNode; detail: NodeDetail | null; loading: boolean }
  | { type: 'delete-confirm'; node: SharedNode; detail: NodeDetail; blockedCases: ConnectedCase[]; deletableCases: ConnectedCase[] }

export default function SharedNodesPage() {
  const { data: session, status } = useSession()
  const router = useRouter()
  const [nodes, setNodes] = useState<SharedNode[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedLabel, setSelectedLabel] = useState<string>('')
  const [showOrphanedOnly, setShowOrphanedOnly] = useState(false)
  const [sharedLabels, setSharedLabels] = useState<string[]>([])
  const [searchQuery, setSearchQuery] = useState<string>('')
  const [modal, setModal] = useState<ModalState>({ type: 'none' })
  const [editForm, setEditForm] = useState<Record<string, any>>({})
  const [actionResult, setActionResult] = useState<{ success: boolean; message: string } | null>(null)
  const [deletedCases, setDeletedCases] = useState<Set<string>>(new Set())
  
  const adminEmail = process.env.NEXT_PUBLIC_ADMIN_EMAIL
  
  useEffect(() => {
    if (status === 'loading') return
    if (!session || session.user?.email !== adminEmail) {
      router.push('/')
    }
  }, [session, status, adminEmail, router])
  
  // Fetch schema to get shared node labels
  useEffect(() => {
    async function fetchSchema() {
      try {
        const res = await fetch('/api/schema')
        if (res.ok) {
          const data = await res.json()
          const schema: SchemaNode[] = data.schema || []
          const labels = schema
            .filter(node => node.case_unique === false)
            .map(node => node.label)
          setSharedLabels(labels)
          // Default to 'all' for initial load to show all shared nodes
          if (labels.length > 0 && !selectedLabel) {
            setSelectedLabel('all')
          }
        }
      } catch (e) {
        console.error('Failed to fetch schema:', e)
      }
    }
    fetchSchema()
  }, [selectedLabel])
  
  // Fetch nodes
  const fetchNodes = useCallback(async () => {
    if (!selectedLabel) return // Wait for label to be set
    
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (selectedLabel !== 'all') params.set('label', selectedLabel)
      if (showOrphanedOnly) params.set('orphaned_only', 'true')
      
      const res = await fetch(`/api/admin/shared-nodes?${params}`)
      if (res.ok) {
        const data = await res.json()
        setNodes(data.nodes || [])
      } else {
        const data = await res.json()
        setError(data.error || 'Failed to fetch nodes')
      }
    } catch (e) {
      setError('Failed to fetch nodes')
    } finally {
      setLoading(false)
    }
  }, [selectedLabel, showOrphanedOnly])
  
  useEffect(() => {
    if (sharedLabels.length > 0 && selectedLabel) {
      fetchNodes()
    }
  }, [sharedLabels, selectedLabel, fetchNodes])
  
  // Filter nodes by search query (client-side)
  const filteredNodes = useMemo(() => {
    if (!searchQuery.trim()) return nodes
    const query = searchQuery.toLowerCase()
    return nodes.filter(node => 
      node.name.toLowerCase().includes(query) ||
      node.id.toLowerCase().includes(query)
    )
  }, [nodes, searchQuery])
  
  // Fetch node detail for modal
  const fetchNodeDetail = async (node: SharedNode): Promise<NodeDetail | null> => {
    try {
      const res = await fetch(`/api/admin/shared-nodes/${node.label}/${node.id}`)
      if (res.ok) {
        const data = await res.json()
        return {
          node: data.node,
          connectedCases: data.connectedCases || [],
          minPerCase: data.minPerCase || 0,
        }
      }
    } catch (e) {
      console.error('Failed to fetch node detail:', e)
    }
    return null
  }
  
  // Open edit modal
  const openEditModal = async (node: SharedNode) => {
    setModal({ type: 'edit', node, detail: null, loading: true })
    setEditForm({ ...node.properties })
    setActionResult(null)
    const detail = await fetchNodeDetail(node)
    setModal({ type: 'edit', node, detail, loading: false })
  }
  
  // Open delete modal
  const openDeleteModal = async (node: SharedNode) => {
    setModal({ type: 'delete', node, detail: null, loading: true })
    setActionResult(null)
    setDeletedCases(new Set())
    const detail = await fetchNodeDetail(node)
    setModal({ type: 'delete', node, detail, loading: false })
  }
  
  // Handle edit submit
  const handleEditSubmit = async () => {
    if (modal.type !== 'edit' || !modal.node) return
    
    setModal({ ...modal, loading: true })
    setActionResult(null)
    
    try {
      const res = await fetch(`/api/admin/shared-nodes/${modal.node.label}/${modal.node.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ properties: editForm }),
      })
      const data = await res.json()
      
      if (data.success) {
        setActionResult({ success: true, message: 'Node updated successfully' })
        // Refresh the list after a short delay
        setTimeout(() => {
          setModal({ type: 'none' })
          fetchNodes()
        }, 1500)
      } else {
        setActionResult({ success: false, message: data.error || 'Failed to update node' })
        setModal({ ...modal, loading: false })
      }
    } catch (e) {
      setActionResult({ success: false, message: 'Failed to update node' })
      setModal({ ...modal, loading: false })
    }
  }
  
  // Handle delete submit
  const handleDeleteSubmit = async (forcePartial: boolean = false) => {
    if (modal.type !== 'delete' || !modal.node) return
    
    setModal({ ...modal, loading: true })
    setActionResult(null)
    
    try {
      const url = `/api/admin/shared-nodes/${modal.node.label}/${modal.node.id}?force_partial=${forcePartial}`
      const res = await fetch(url, { method: 'DELETE' })
      const data = await res.json()
      
      if (data.success) {
        // Mark deleted cases
        if (data.deletedFromCases) {
          const deleted = new Set<string>()
          data.deletedFromCases.forEach((c: ConnectedCase) => {
            if (c.status === 'deleted') deleted.add(c.case_id)
          })
          setDeletedCases(deleted)
        }
        
        setActionResult({ 
          success: true, 
          message: data.partial 
            ? `Node partially deleted. ${data.message}` 
            : 'Node deleted successfully from all cases'
        })
        
        // Refresh the list after a short delay
        setTimeout(() => {
          setModal({ type: 'none' })
          fetchNodes()
        }, 2000)
      } else if (data.error === 'min_per_case_violation') {
        // Show confirmation with blocked/deletable cases
        setModal({
          type: 'delete-confirm',
          node: modal.node,
          detail: modal.detail!,
          blockedCases: data.blockedCases || [],
          deletableCases: data.deletableCases || [],
        })
      } else {
        setActionResult({ success: false, message: data.message || data.error || 'Failed to delete node' })
        setModal({ ...modal, loading: false })
      }
    } catch (e) {
      setActionResult({ success: false, message: 'Failed to delete node' })
      setModal({ ...modal, loading: false })
    }
  }
  
  if (status === 'loading') {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-gray-600">Loading...</div>
      </div>
    )
  }
  
  if (!session || session.user?.email !== adminEmail) {
    return null
  }
  
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 py-8">
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-gray-900">Shared Nodes</h1>
          <p className="text-gray-600 mt-1">
            Manage non-case-unique nodes in the Knowledge Graph.
            {!loading && nodes.length > 0 && (
              <span className="ml-2 text-gray-500">
                ({filteredNodes.length}{searchQuery ? ` of ${nodes.length}` : ''} nodes)
              </span>
            )}
          </p>
        </div>
        
        {/* Filters */}
        <div className="bg-white rounded-lg shadow p-4 mb-6">
          <div className="flex flex-wrap gap-4 items-center">
            <div>
              <label htmlFor="node-type-select" className="block text-sm font-medium text-gray-700 mb-1">Node Type</label>
              <select
                id="node-type-select"
                value={selectedLabel}
                onChange={(e) => setSelectedLabel(e.target.value)}
                className="border rounded px-3 py-2 text-sm min-w-[140px]"
              >
                {sharedLabels.length === 0 && <option value="">Loading...</option>}
                <option value="all">All Types</option>
                {sharedLabels.map(label => (
                  <option key={label} value={label}>{label}</option>
                ))}
              </select>
            </div>
            
            <div>
              <label htmlFor="search-input" className="block text-sm font-medium text-gray-700 mb-1">Search</label>
              <input
                id="search-input"
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Filter by name or ID..."
                className="border rounded px-3 py-2 text-sm w-64"
              />
            </div>
            
            <div className="flex items-center gap-2 self-end pb-2">
              <input
                type="checkbox"
                id="orphaned"
                checked={showOrphanedOnly}
                onChange={(e) => setShowOrphanedOnly(e.target.checked)}
                className="rounded"
              />
              <label htmlFor="orphaned" className="text-sm text-gray-700">
                Orphaned only
              </label>
            </div>
            
            <button
              onClick={fetchNodes}
              disabled={!selectedLabel}
              className="ml-auto px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50 self-end"
            >
              Refresh
            </button>
          </div>
        </div>
        
        {/* Error Message */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
            <p className="text-red-800 text-sm">{error}</p>
          </div>
        )}
        
        {/* Loading */}
        {loading && (
          <div className="text-center py-8 text-gray-500">Loading nodes...</div>
        )}
        
        {/* Nodes Table */}
        {!loading && filteredNodes.length > 0 && (
          <div className="bg-white rounded-lg shadow overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">ID</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Connections</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {filteredNodes.map((node) => (
                  <tr key={`${node.label}-${node.id}`} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded text-xs font-medium">
                        {node.label}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="text-sm text-gray-900 max-w-xs truncate">{node.name}</div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <code className="text-xs text-gray-500">{node.id.slice(0, 8)}...</code>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {node.connectionCount}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {node.isOrphaned ? (
                        <span className="px-2 py-1 bg-yellow-100 text-yellow-800 rounded text-xs">
                          Orphaned
                        </span>
                      ) : (
                        <span className="px-2 py-1 bg-green-100 text-green-800 rounded text-xs">
                          Connected
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm">
                      <button
                        onClick={() => openEditModal(node)}
                        className="text-blue-600 hover:text-blue-800 mr-3"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => openDeleteModal(node)}
                        className="text-red-600 hover:text-red-800"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        
        {/* Empty State */}
        {!loading && filteredNodes.length === 0 && !error && (
          <div className="bg-white rounded-lg shadow p-8 text-center text-gray-500">
            {nodes.length > 0 && searchQuery 
              ? `No nodes match "${searchQuery}"`
              : 'No nodes found matching your filters.'}
          </div>
        )}
      </div>
      
      {/* Edit Modal */}
      {modal.type === 'edit' && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-hidden flex flex-col">
            <div className="px-6 py-4 border-b">
              <h2 className="text-lg font-semibold">Edit {modal.node.label}</h2>
              <p className="text-sm text-gray-500">{modal.node.name}</p>
            </div>
            
            <div className="px-6 py-4 overflow-y-auto flex-1">
              {modal.loading && !modal.detail ? (
                <div className="text-center py-8">
                  <div className="animate-spin h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full mx-auto"></div>
                  <p className="mt-2 text-gray-500">Loading node details...</p>
                </div>
              ) : (
                <>
                  {/* Connected Cases */}
                  {modal.detail && modal.detail.connectedCases.length > 0 && (
                    <div className="mb-4">
                      <h3 className="text-sm font-medium text-gray-700 mb-2">
                        Connected Cases ({modal.detail.connectedCases.length})
                      </h3>
                      <div className="max-h-32 overflow-y-auto border rounded p-2 bg-gray-50">
                        {modal.detail.connectedCases.map((c) => (
                          <div key={c.case_id} className="text-sm text-gray-600 py-1">
                            {c.case_name || c.case_id}
                            {c.citation && <span className="text-gray-400 ml-2">({c.citation})</span>}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  
                  {/* Edit Form */}
                  <div className="space-y-4">
                    {Object.entries(editForm)
                      .filter(([key]) => !key.endsWith('_id') && !key.endsWith('_embedding') && !key.endsWith('_upload_code'))
                      .map(([key, value]) => (
                        <div key={key}>
                          <label className="block text-sm font-medium text-gray-700 mb-1 capitalize">
                            {key.replace(/_/g, ' ')}
                          </label>
                          {typeof value === 'string' && value.length > 100 ? (
                            <textarea
                              value={editForm[key] || ''}
                              onChange={(e) => setEditForm({ ...editForm, [key]: e.target.value })}
                              className="w-full border rounded px-3 py-2 text-sm"
                              rows={3}
                            />
                          ) : (
                            <input
                              type="text"
                              value={editForm[key] || ''}
                              onChange={(e) => setEditForm({ ...editForm, [key]: e.target.value })}
                              className="w-full border rounded px-3 py-2 text-sm"
                            />
                          )}
                        </div>
                      ))}
                  </div>
                  
                  {/* Result Message */}
                  {actionResult && (
                    <div className={`mt-4 p-3 rounded ${actionResult.success ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'}`}>
                      {actionResult.success && (
                        <svg className="inline w-5 h-5 mr-2" fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                        </svg>
                      )}
                      {actionResult.message}
                    </div>
                  )}
                </>
              )}
            </div>
            
            <div className="px-6 py-4 border-t flex justify-end gap-3">
              <button
                onClick={() => setModal({ type: 'none' })}
                disabled={modal.loading && actionResult?.success}
                className="px-4 py-2 border rounded text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleEditSubmit}
                disabled={modal.loading}
                className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 flex items-center gap-2"
              >
                {modal.loading && (
                  <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full"></div>
                )}
                Save Changes
              </button>
            </div>
          </div>
        </div>
      )}
      
      {/* Delete Modal */}
      {modal.type === 'delete' && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-hidden flex flex-col">
            <div className="px-6 py-4 border-b">
              <h2 className="text-lg font-semibold text-red-600">Delete {modal.node.label}</h2>
              <p className="text-sm text-gray-500">{modal.node.name}</p>
            </div>
            
            <div className="px-6 py-4 overflow-y-auto flex-1">
              {modal.loading && !modal.detail ? (
                <div className="text-center py-8">
                  <div className="animate-spin h-8 w-8 border-4 border-red-600 border-t-transparent rounded-full mx-auto"></div>
                  <p className="mt-2 text-gray-500">Loading node details...</p>
                </div>
              ) : (
                <>
                  {/* Warning message - different for catalog vs regular nodes */}
                  {(() => {
                    const catalogNodes = ['Domain', 'Forum', 'Jurisdiction']
                    const isCatalogNode = catalogNodes.includes(modal.node.label)
                    const hasConnections = modal.detail && modal.detail.connectedCases.length > 0
                    
                    return (
                      <div className={`border rounded p-4 mb-4 ${isCatalogNode && hasConnections ? 'bg-blue-50 border-blue-200' : 'bg-red-50 border-red-200'}`}>
                        <p className={`text-sm ${isCatalogNode && hasConnections ? 'text-blue-800' : 'text-red-800'}`}>
                          {isCatalogNode && hasConnections ? (
                            <>
                              <strong>ℹ️ Catalog Node Detachment:</strong> This is a catalog node (Domain, Forum, or Jurisdiction). 
                              It will be <strong>detached from all connected cases</strong> but <strong>preserved in the Knowledge Graph</strong> for future use.
                            </>
                          ) : isCatalogNode && !hasConnections ? (
                            <>
                              <strong>⚠️ Orphaned Catalog Node:</strong> This catalog node has no case connections. 
                              It will be <strong>permanently deleted</strong> from the Knowledge Graph.
                            </>
                          ) : hasConnections ? (
                            <>
                              <strong>⚠️ Permanent Deletion:</strong> This node will be <strong>permanently deleted</strong> from the Knowledge Graph and removed from all connected cases.
                            </>
                          ) : (
                            <>
                              <strong>⚠️ Orphaned Node:</strong> This orphaned node will be <strong>permanently deleted</strong> from the Knowledge Graph.
                            </>
                          )}
                        </p>
                      </div>
                    );
                  })()}
                  
                  {/* Connected Cases */}
                  {modal.detail && modal.detail.connectedCases.length > 0 && (
                    <div className="mb-4">
                      <h3 className="text-sm font-medium text-gray-700 mb-2">
                        Will be removed from {modal.detail.connectedCases.length} case(s):
                      </h3>
                      <div className="max-h-48 overflow-y-auto border rounded p-2 bg-gray-50">
                        {modal.detail.connectedCases.map((c) => (
                          <div key={c.case_id} className="text-sm text-gray-600 py-1 flex items-center gap-2">
                            {deletedCases.has(c.case_id) && (
                              <svg className="w-4 h-4 text-green-600" fill="currentColor" viewBox="0 0 20 20">
                                <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                              </svg>
                            )}
                            <span>{c.case_name || c.case_id}</span>
                            {c.citation && <span className="text-gray-400">({c.citation})</span>}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  
                  {modal.detail && modal.detail.connectedCases.length === 0 && (
                    <div className="mb-4 text-sm text-gray-500">
                      This node is not connected to any cases (orphaned).
                    </div>
                  )}
                  
                  {/* Result Message */}
                  {actionResult && (
                    <div className={`mt-4 p-3 rounded ${actionResult.success ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'}`}>
                      {actionResult.success && (
                        <svg className="inline w-5 h-5 mr-2" fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                        </svg>
                      )}
                      {actionResult.message}
                    </div>
                  )}
                </>
              )}
            </div>
            
            <div className="px-6 py-4 border-t flex justify-end gap-3">
              <button
                onClick={() => setModal({ type: 'none' })}
                disabled={modal.loading && actionResult?.success}
                className="px-4 py-2 border rounded text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={() => handleDeleteSubmit(false)}
                disabled={modal.loading}
                className="px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50 flex items-center gap-2"
              >
                {modal.loading && (
                  <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full"></div>
                )}
                Delete Node
              </button>
            </div>
          </div>
        </div>
      )}
      
      {/* Delete Confirmation Modal (min_per_case violation) */}
      {modal.type === 'delete-confirm' && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-hidden flex flex-col">
            <div className="px-6 py-4 border-b">
              <h2 className="text-lg font-semibold text-yellow-600">Cannot Delete Completely</h2>
              <p className="text-sm text-gray-500">{modal.node.name}</p>
            </div>
            
            <div className="px-6 py-4 overflow-y-auto flex-1">
              <div className="bg-yellow-50 border border-yellow-200 rounded p-4 mb-4">
                <p className="text-yellow-800 text-sm">
                  Some cases require at least one {modal.node.label} node. Deleting this node would violate that constraint.
                </p>
              </div>
              
              {/* Blocked Cases */}
              {modal.blockedCases.length > 0 && (
                <div className="mb-4">
                  <h3 className="text-sm font-medium text-red-700 mb-2">
                    Cannot delete from ({modal.blockedCases.length} case(s) - would violate minimum):
                  </h3>
                  <div className="max-h-32 overflow-y-auto border border-red-200 rounded p-2 bg-red-50">
                    {modal.blockedCases.map((c) => (
                      <div key={c.case_id} className="text-sm text-red-700 py-1">
                        {c.case_name || c.case_id}
                        <span className="text-red-400 ml-2">(has {c.currentCount} {modal.node.label})</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              
              {/* Deletable Cases */}
              {modal.deletableCases.length > 0 && (
                <div className="mb-4">
                  <h3 className="text-sm font-medium text-green-700 mb-2">
                    Can delete from ({modal.deletableCases.length} case(s)):
                  </h3>
                  <div className="max-h-32 overflow-y-auto border border-green-200 rounded p-2 bg-green-50">
                    {modal.deletableCases.map((c) => (
                      <div key={c.case_id} className="text-sm text-green-700 py-1">
                        {c.case_name || c.case_id}
                        <span className="text-green-400 ml-2">(has {c.currentCount} {modal.node.label})</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
            
            <div className="px-6 py-4 border-t flex justify-end gap-3">
              <button
                onClick={() => setModal({ type: 'none' })}
                className="px-4 py-2 border rounded text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              {modal.deletableCases.length > 0 && (
                <button
                  onClick={() => {
                    setModal({ type: 'delete', node: modal.node, detail: modal.detail, loading: true })
                    handleDeleteSubmit(true)
                  }}
                  className="px-4 py-2 bg-yellow-600 text-white rounded hover:bg-yellow-700"
                >
                  Delete from {modal.deletableCases.length} case(s) only
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
