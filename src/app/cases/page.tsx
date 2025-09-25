"use client";
import { useState, useEffect } from 'react';
import Link from 'next/link';

export default function CasesListPage() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [caseToDelete, setCaseToDelete] = useState<any>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  
  useEffect(() => {
    const fetchCases = async () => {
      try {
        const response = await fetch('/api/cases');
        const result = await response.json();
        setData(result);
        setIsLoading(false);
      } catch (err) {
        setError(err);
        setIsLoading(false);
      }
    };
    
    fetchCases();
  }, []);
  
  if (isLoading) return <div className="p-8">Loading...</div>
  if (error) return <div className="p-8 text-red-600">Error</div>
  const items = data?.items || []
  return (
    <div className="p-8 space-y-4">
      <div className="flex justify-between">
        <h1 className="text-2xl font-bold">Cases</h1>
        <Link className="text-blue-600 underline" href="/cases/upload">Upload</Link>
      </div>
      {deleteError && (
        <div className="text-red-600 text-sm">{deleteError}</div>
      )}
      <ul className="space-y-2">
        {items.map((c: any) => (
          <li key={c.id} className="border p-3 rounded">
            <div className="flex items-start justify-between gap-2">
              <div>
                <Link href={`/cases/${c.id}`} className="font-medium">{c.extracted?.case_name || c.filename}</Link>
                <div className="text-sm text-gray-600">{c.status}</div>
              </div>
              <button
                type="button"
                onClick={() => { setCaseToDelete(c); setDeleteError(null); setConfirmOpen(true); }}
                className="h-8 px-3 text-sm inline-flex items-center justify-center gap-2 rounded-md font-medium bg-red-600 text-white hover:bg-red-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-600"
              >
                Delete
              </button>
            </div>
          </li>
        ))}
      </ul>

      {confirmOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white rounded-md p-6 w-full max-w-sm shadow">
            <h2 className="text-lg font-semibold">Delete case?</h2>
            <p className="text-sm text-gray-600 mt-2">This action cannot be undone.</p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => { if (!deleting) { setConfirmOpen(false); setCaseToDelete(null); } }}
                disabled={deleting}
                className="h-9 px-4 text-sm inline-flex items-center justify-center gap-2 rounded-md font-medium border border-gray-300 bg-white text-gray-900 hover:bg-gray-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 disabled:opacity-50 disabled:pointer-events-none"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={async () => {
                  if (!caseToDelete) return
                  try {
                    setDeleting(true)
                    setDeleteError(null)
                    const res = await fetch(`/api/cases/${caseToDelete.id}`, { method: 'DELETE' })
                    if (!res.ok) {
                      let msg = 'Failed to delete case'
                      try {
                        const j = await res.json()
                        msg = j?.error || j?.detail || msg
                      } catch {}
                      throw new Error(msg)
                    }
                    setData((prev: any) => {
                      const prevItems = prev?.items || []
                      return { ...(prev || {}), items: prevItems.filter((it: any) => it.id !== caseToDelete.id) }
                    })
                    setConfirmOpen(false)
                    setCaseToDelete(null)
                  } catch (e: any) {
                    setDeleteError(e?.message || 'Failed to delete case')
                  } finally {
                    setDeleting(false)
                  }
                }}
                disabled={deleting}
                className="h-9 px-4 text-sm inline-flex items-center justify-center gap-2 rounded-md font-medium bg-red-600 text-white hover:bg-red-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-600 disabled:opacity-50 disabled:pointer-events-none"
              >
                {deleting ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

