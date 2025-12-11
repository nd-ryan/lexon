"use client";
import { useState, useEffect, useCallback } from 'react'
import { useSession } from 'next-auth/react'
import { useRouter } from 'next/navigation'
import Button from '@/components/ui/button'

interface DeletionRequest {
  id: string
  case_id: string
  node_label: string
  node_id: string
  node_name: string | null
  requested_by: string
  requested_at: string
  status: string
  resolved_by: string | null
  resolved_at: string | null
}

export default function PendingDeletionsPage() {
  const { data: session, status: sessionStatus } = useSession()
  const router = useRouter()
  const [requests, setRequests] = useState<DeletionRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [processingId, setProcessingId] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<string>('pending')

  const adminEmail = process.env.NEXT_PUBLIC_ADMIN_EMAIL

  // Protect the page - only allow admin email
  useEffect(() => {
    if (sessionStatus === 'loading') return
    if (!session || !adminEmail || session.user?.email !== adminEmail) {
      router.replace('/cases')
    }
  }, [session, sessionStatus, router, adminEmail])

  const fetchRequests = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const url = statusFilter 
        ? `/api/admin/pending-deletions?status=${statusFilter}`
        : '/api/admin/pending-deletions'
      const res = await fetch(url)
      const data = await res.json()
      
      if (!res.ok) {
        throw new Error(data.error || 'Failed to fetch')
      }
      
      setRequests(data.items || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch pending deletions')
    } finally {
      setLoading(false)
    }
  }, [statusFilter])

  useEffect(() => {
    if (sessionStatus === 'authenticated') {
      fetchRequests()
    }
  }, [sessionStatus, fetchRequests])

  const handleApprove = async (id: string) => {
    if (processingId) return
    setProcessingId(id)
    setError(null)
    
    try {
      const res = await fetch(`/api/admin/pending-deletions/${id}/approve`, {
        method: 'POST',
      })
      
      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.error || 'Failed to approve')
      }
      
      // Refresh the list
      await fetchRequests()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to approve deletion')
    } finally {
      setProcessingId(null)
    }
  }

  const handleReject = async (id: string) => {
    if (processingId) return
    setProcessingId(id)
    setError(null)
    
    try {
      const res = await fetch(`/api/admin/pending-deletions/${id}/reject`, {
        method: 'POST',
      })
      
      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.error || 'Failed to reject')
      }
      
      // Refresh the list
      await fetchRequests()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reject deletion')
    } finally {
      setProcessingId(null)
    }
  }

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString()
  }

  if (sessionStatus === 'loading' || !session) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-gray-600">Loading...</div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-6xl mx-auto p-6 space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold tracking-tight">Pending KG Deletions</h1>
          <div className="flex items-center gap-4">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="text-sm border rounded px-3 py-1.5"
            >
              <option value="pending">Pending</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
              <option value="">All</option>
            </select>
            <Button variant="outline" onClick={fetchRequests} disabled={loading}>
              Refresh
            </Button>
          </div>
        </div>

        {error && (
          <div className="rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {loading ? (
          <div className="text-center py-12 text-gray-500">Loading...</div>
        ) : requests.length === 0 ? (
          <div className="text-center py-12 text-gray-500">
            No {statusFilter || ''} deletion requests found.
          </div>
        ) : (
          <div className="bg-white border rounded-lg overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Node
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Type
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Requested By
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Date
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {requests.map((req) => (
                  <tr key={req.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm">
                      <div className="font-medium text-gray-900">
                        {req.node_name || 'Unnamed'}
                      </div>
                      <div className="text-gray-500 text-xs truncate max-w-xs" title={req.node_id}>
                        {req.node_id}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <span className="px-2 py-1 text-xs font-medium rounded-full bg-blue-100 text-blue-700">
                        {req.node_label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {req.requested_by}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {formatDate(req.requested_at)}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <span className={`px-2 py-1 text-xs font-medium rounded-full ${
                        req.status === 'pending' 
                          ? 'bg-yellow-100 text-yellow-700'
                          : req.status === 'approved'
                          ? 'bg-green-100 text-green-700'
                          : 'bg-red-100 text-red-700'
                      }`}>
                        {req.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-right">
                      {req.status === 'pending' && (
                        <div className="flex items-center justify-end gap-2">
                          <Button
                            variant="outline"
                            onClick={() => handleApprove(req.id)}
                            disabled={processingId === req.id}
                            className="text-green-600 border-green-300 hover:bg-green-50"
                          >
                            {processingId === req.id ? '...' : 'Approve'}
                          </Button>
                          <Button
                            variant="outline"
                            onClick={() => handleReject(req.id)}
                            disabled={processingId === req.id}
                            className="text-red-600 border-red-300 hover:bg-red-50"
                          >
                            {processingId === req.id ? '...' : 'Reject'}
                          </Button>
                        </div>
                      )}
                      {req.status !== 'pending' && req.resolved_by && (
                        <div className="text-xs text-gray-500">
                          by {req.resolved_by}
                          {req.resolved_at && (
                            <span className="block">{formatDate(req.resolved_at)}</span>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
