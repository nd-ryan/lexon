"use client";
import { useState, useEffect, useCallback } from 'react'
import { useSession } from 'next-auth/react'
import { useRouter } from 'next/navigation'
import Button from '@/components/ui/button'

interface GraphEvent {
  id: string
  case_id: string
  entity_type: string
  entity_id: string
  entity_label: string
  action: string
  user_id: string
  content_hash: string | null
  property_changes: Record<string, unknown> | null
  created_at: string
}

interface EventStats {
  total: number
  by_action: Record<string, number>
  top_users: Record<string, number>
}

export default function EventLogsPage() {
  const { data: session, status: sessionStatus } = useSession()
  const router = useRouter()
  const [events, setEvents] = useState<GraphEvent[]>([])
  const [stats, setStats] = useState<EventStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  
  // Filters
  const [actionFilter, setActionFilter] = useState<string>('')
  const [entityTypeFilter, setEntityTypeFilter] = useState<string>('')
  const [userFilter, setUserFilter] = useState<string>('')
  const [limit, setLimit] = useState(100)

  const adminEmail = process.env.NEXT_PUBLIC_ADMIN_EMAIL

  // Protect the page
  useEffect(() => {
    if (sessionStatus === 'loading') return
    if (!session || !adminEmail || session.user?.email !== adminEmail) {
      router.replace('/cases')
    }
  }, [session, sessionStatus, router, adminEmail])

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch('/api/admin/graph-events/stats')
      const data = await res.json()
      if (data.success) {
        setStats(data.stats)
      }
    } catch (err) {
      console.error('Failed to fetch stats:', err)
    }
  }, [])

  const fetchEvents = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (actionFilter) params.set('action', actionFilter)
      if (entityTypeFilter) params.set('entity_type', entityTypeFilter)
      if (userFilter) params.set('user_id', userFilter)
      params.set('limit', limit.toString())
      
      const res = await fetch(`/api/admin/graph-events?${params.toString()}`)
      const data = await res.json()
      
      if (!res.ok) {
        throw new Error(data.error || 'Failed to fetch')
      }
      
      setEvents(data.items || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch events')
    } finally {
      setLoading(false)
    }
  }, [actionFilter, entityTypeFilter, userFilter, limit])

  useEffect(() => {
    if (sessionStatus === 'authenticated') {
      fetchStats()
      fetchEvents()
    }
  }, [sessionStatus, fetchStats, fetchEvents])

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString()
  }

  const getActionColor = (action: string) => {
    switch (action) {
      case 'ai_create':
        return 'bg-purple-100 text-purple-700'
      case 'create':
        return 'bg-green-100 text-green-700'
      case 'update':
        return 'bg-blue-100 text-blue-700'
      case 'delete':
        return 'bg-red-100 text-red-700'
      default:
        return 'bg-gray-100 text-gray-700'
    }
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
      <div className="max-w-7xl mx-auto p-6 space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold tracking-tight">Event Logs</h1>
          <Button variant="outline" onClick={() => { fetchStats(); fetchEvents() }} disabled={loading}>
            Refresh
          </Button>
        </div>

        {/* Stats Cards */}
        {stats && (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-white border rounded-lg p-4">
              <div className="text-sm text-gray-500">Total Events</div>
              <div className="text-2xl font-semibold">{stats.total.toLocaleString()}</div>
            </div>
            <div className="bg-white border rounded-lg p-4">
              <div className="text-sm text-gray-500 mb-2">By Action</div>
              <div className="flex flex-wrap gap-2">
                {Object.entries(stats.by_action).map(([action, count]) => (
                  <span key={action} className={`px-2 py-1 text-xs rounded-full ${getActionColor(action)}`}>
                    {action}: {count}
                  </span>
                ))}
              </div>
            </div>
            <div className="bg-white border rounded-lg p-4">
              <div className="text-sm text-gray-500 mb-2">Top Contributors</div>
              <div className="space-y-1">
                {Object.entries(stats.top_users).slice(0, 5).map(([user, count]) => (
                  <div key={user} className="flex justify-between text-sm">
                    <span className="text-gray-600 truncate">{user}</span>
                    <span className="font-medium">{count}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Filters */}
        <div className="bg-white border rounded-lg p-4">
          <div className="flex flex-wrap gap-4 items-end">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Action</label>
              <select
                value={actionFilter}
                onChange={(e) => setActionFilter(e.target.value)}
                className="text-sm border rounded px-3 py-1.5"
              >
                <option value="">All Actions</option>
                <option value="ai_create">AI Create</option>
                <option value="create">Create</option>
                <option value="update">Update</option>
                <option value="delete">Delete</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Entity Type</label>
              <select
                value={entityTypeFilter}
                onChange={(e) => setEntityTypeFilter(e.target.value)}
                className="text-sm border rounded px-3 py-1.5"
              >
                <option value="">All Types</option>
                <option value="node">Node</option>
                <option value="edge">Edge</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">User ID</label>
              <input
                type="text"
                value={userFilter}
                onChange={(e) => setUserFilter(e.target.value)}
                placeholder="Filter by user..."
                className="text-sm border rounded px-3 py-1.5 w-40"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Limit</label>
              <select
                value={limit}
                onChange={(e) => setLimit(Number(e.target.value))}
                className="text-sm border rounded px-3 py-1.5"
              >
                <option value={50}>50</option>
                <option value={100}>100</option>
                <option value={250}>250</option>
                <option value={500}>500</option>
              </select>
            </div>
            <Button onClick={fetchEvents} disabled={loading}>
              Apply Filters
            </Button>
          </div>
        </div>

        {error && (
          <div className="rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* Events Table */}
        {loading ? (
          <div className="text-center py-12 text-gray-500">Loading...</div>
        ) : events.length === 0 ? (
          <div className="text-center py-12 text-gray-500">
            No events found.
          </div>
        ) : (
          <div className="bg-white border rounded-lg overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Timestamp
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Action
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Entity
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    User
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Case
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {events.map((event) => (
                  <tr key={event.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm text-gray-600 whitespace-nowrap">
                      {formatDate(event.created_at)}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <span className={`px-2 py-1 text-xs font-medium rounded-full ${getActionColor(event.action)}`}>
                        {event.action}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <div className="font-medium text-gray-900">
                        {event.entity_label}
                      </div>
                      <div className="text-gray-500 text-xs">
                        {event.entity_type} 
                        <span className="ml-1 text-gray-400 truncate max-w-xs inline-block align-bottom" title={event.entity_id}>
                          ({event.entity_id.substring(0, 20)}...)
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {event.user_id === 'ai' ? (
                        <span className="px-2 py-0.5 text-xs bg-purple-100 text-purple-700 rounded">AI</span>
                      ) : (
                        <span className="truncate max-w-[120px] inline-block" title={event.user_id}>
                          {event.user_id.substring(0, 12)}...
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      <a 
                        href={`/cases/${event.case_id}`}
                        className="text-blue-600 hover:underline truncate max-w-[100px] inline-block"
                        title={event.case_id}
                      >
                        {event.case_id.substring(0, 8)}...
                      </a>
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
