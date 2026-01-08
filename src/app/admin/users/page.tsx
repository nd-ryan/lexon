'use client'

import React, { useEffect, useMemo, useState } from 'react'
import { useSession } from 'next-auth/react'
import type { Session } from 'next-auth'
import { useRouter } from 'next/navigation'
import Button from '@/components/ui/button'
import Card from '@/components/ui/card'
import { hasAtLeastRole, type Role } from '@/lib/rbac'

type UserRow = {
  id: string
  name: string | null
  email: string
  role: Role
  createdAt: string
  updatedAt: string
}

const ROLES: readonly Role[] = ['user', 'editor', 'developer', 'admin'] as const

export default function AdminUsersPage() {
  const { data: session, status } = useSession()
  const router = useRouter()
  const role = (session?.user as Session['user'])?.role
  const isAdmin = hasAtLeastRole(role, 'admin')

  const [users, setUsers] = useState<UserRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyUserId, setBusyUserId] = useState<string | null>(null)

  useEffect(() => {
    if (status === 'unauthenticated') router.replace('/auth/signin')
    if (status === 'authenticated' && !isAdmin) router.replace('/cases')
  }, [status, isAdmin, router])

  const currentUserId = (session?.user as Session['user'])?.id

  const sortedUsers = useMemo(() => {
    return [...users].sort((a, b) => b.createdAt.localeCompare(a.createdAt))
  }, [users])

  const fetchUsers = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/admin/users', { cache: 'no-store' })
      const data = await res.json()
      if (!res.ok) throw new Error(data?.error || 'Failed to load users')
      setUsers((data?.users || []) as UserRow[])
    } catch (e: any) {
      setError(e?.message || 'Failed to load users')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (status !== 'authenticated' || !isAdmin) return
    fetchUsers()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, isAdmin])

  const updateRole = async (userId: string, role: Role) => {
    setBusyUserId(userId)
    setError(null)
    try {
      const res = await fetch(`/api/admin/users/${encodeURIComponent(userId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data?.error || 'Failed to update role')
      setUsers((prev) => prev.map((u) => (u.id === userId ? { ...u, role: data.user.role } : u)))
    } catch (e: any) {
      setError(e?.message || 'Failed to update role')
    } finally {
      setBusyUserId(null)
    }
  }

  const deleteUser = async (userId: string) => {
    if (!confirm('Delete this user? This cannot be undone.')) return
    setBusyUserId(userId)
    setError(null)
    try {
      const res = await fetch(`/api/admin/users/${encodeURIComponent(userId)}`, {
        method: 'DELETE',
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data?.error || 'Failed to delete user')
      setUsers((prev) => prev.filter((u) => u.id !== userId))
    } catch (e: any) {
      setError(e?.message || 'Failed to delete user')
    } finally {
      setBusyUserId(null)
    }
  }

  if (status === 'loading' || (status === 'authenticated' && !isAdmin)) return null

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="mx-auto max-w-5xl px-4 py-8">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Users</h1>
            <p className="text-sm text-gray-600">Assign roles and delete users.</p>
          </div>
          <Button variant="outline" onClick={fetchUsers} disabled={loading}>
            Refresh
          </Button>
        </div>

        {error && (
          <div className="mb-4 rounded border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            {error}
          </div>
        )}

        <Card>
          <div className="p-4">
            {loading ? (
              <div className="text-sm text-gray-600">Loading…</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200 text-sm">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium text-gray-600">Name</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-600">Email</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-600">Role</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-600">Created</th>
                      <th className="px-3 py-2 text-right font-medium text-gray-600">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 bg-white">
                    {sortedUsers.map((u) => {
                      const isSelf = Boolean(currentUserId && u.id === currentUserId)
                      const busy = busyUserId === u.id
                      return (
                        <tr key={u.id}>
                          <td className="px-3 py-2 whitespace-nowrap">{u.name || '—'}</td>
                          <td className="px-3 py-2 whitespace-nowrap">{u.email}</td>
                          <td className="px-3 py-2 whitespace-nowrap">
                            <select
                              className="h-9 rounded border border-gray-300 bg-white px-2"
                              value={u.role}
                              disabled={busy || isSelf}
                              onChange={(e) => updateRole(u.id, e.target.value as Role)}
                              title={isSelf ? 'You cannot change your own role' : undefined}
                            >
                              {ROLES.map((r) => (
                                <option key={r} value={r}>
                                  {r}
                                </option>
                              ))}
                            </select>
                            {isSelf && <span className="ml-2 text-xs text-gray-500">(you)</span>}
                          </td>
                          <td className="px-3 py-2 whitespace-nowrap">
                            {new Date(u.createdAt).toLocaleString()}
                          </td>
                          <td className="px-3 py-2 whitespace-nowrap text-right">
                            <Button
                              variant="outline"
                              className="border-red-300 text-red-700 hover:bg-red-50"
                              disabled={busy || isSelf}
                              onClick={() => deleteUser(u.id)}
                              title={isSelf ? 'You cannot delete your own user' : undefined}
                            >
                              Delete
                            </Button>
                          </td>
                        </tr>
                      )
                    })}
                    {sortedUsers.length === 0 && (
                      <tr>
                        <td className="px-3 py-6 text-center text-gray-500" colSpan={5}>
                          No users found.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </Card>
      </div>
    </div>
  )
}

