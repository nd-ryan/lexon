"use client";
import { useEffect, useState } from 'react'
import Button from '@/components/ui/button'
import { useRouter } from 'next/navigation'
import { useSession } from 'next-auth/react'
import type { Session } from 'next-auth'
import { hasAtLeastRole } from '@/lib/rbac'

export default function CaseUploadPage() {
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const router = useRouter()
  const { status, data: session } = useSession()
  const role = (session?.user as Session['user'])?.role
  const isAdmin = hasAtLeastRole(role, 'admin')

  useEffect(() => {
    if (status === 'unauthenticated') {
      router.push('/auth/signin')
    } else if (status === 'authenticated' && !isAdmin) {
      router.push('/cases')
    }
  }, [status, isAdmin, router])

  if (status === 'loading') return null
  if (status === 'unauthenticated') return null
  if (!isAdmin) return null

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!file) return
    setLoading(true); setError('')
    const fd = new FormData(); fd.append('file', file)
    const res = await fetch('/api/cases/upload', { method: 'POST', body: fd })
    const data = await res.json()
    setLoading(false)
    if (!res.ok || !data.success) { setError(data.detail || data.error || 'Upload failed'); return }
    // Redirect to progress page to track extraction
    router.push(`/cases/upload/progress?jobId=${data.jobId}&caseId=${data.caseId}`)
  }

  return (
    <div className="p-8 max-w-xl mx-auto space-y-4">
      <h1 className="text-2xl font-bold">Upload Legal Case</h1>
      {error && <div className="text-red-600">{error}</div>}
      <form onSubmit={onSubmit} className="space-y-4">
        <input type="file" onChange={e => setFile(e.target.files?.[0] || null)} accept=".docx,.pdf" />
        <Button type="submit" disabled={!file || loading}>{loading ? 'Processing...' : 'Upload & Extract'}</Button>
      </form>
    </div>
  )
}


