"use client";
import { useState, useEffect, useMemo } from 'react';
import Link from 'next/link';
import { useAppStore } from '@/lib/store/appStore';
import { DocumentDownloadButton } from '@/components/cases/DocumentDownloadButton';

export default function CasesListPage() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [caseToDelete, setCaseToDelete] = useState<any>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [selectedDomain, setSelectedDomain] = useState<string>('all')
  const catalogNodes = useAppStore(s => s.catalogNodes)
  
  // Helper to get domain name from domain_id
  const getDomainName = (domainId: string | null | undefined): string | null => {
    if (!domainId) {
      return null;
    }
    const domains = catalogNodes?.Domain || [];
    const domain = domains.find((d: any) => d.properties?.domain_id === domainId);
    const name = domain?.properties?.name;
    return typeof name === 'string' ? name : null;
  }
  
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
  
  // Get unique domains with their IDs and names
  const domains = useMemo(() => {
    const items = data?.items || [];
    const domainMap = new Map<string, string>();
    
    items.forEach((item: any) => {
      if (item.domain_id) {
        const name = getDomainName(item.domain_id);
        if (name) {
          domainMap.set(item.domain_id, name);
        }
      }
    });
    
    return Array.from(domainMap.entries())
      .map(([id, name]) => ({ id, name }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [data, catalogNodes]);
  
  // Filter items by selected domain
  const filteredItems = useMemo(() => {
    const items = data?.items || [];
    if (selectedDomain === 'all') {
      return items;
    }
    return items.filter((item: any) => item.domain_id === selectedDomain);
  }, [data, selectedDomain]);
  
  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-gray-600">Loading cases...</div>
      </div>
    );
  }
  
  if (error) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-red-600">Error loading cases</div>
      </div>
    );
  }
  
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="p-6 space-y-6 text-xs">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-2xl font-semibold tracking-tight">Cases</h1>
          <Link 
            href="/cases/upload"
            className="text-blue-600 underline text-sm hover:text-blue-700"
          >
            Upload
          </Link>
        </div>

        {deleteError && (
          <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700">
            {deleteError}
          </div>
        )}

        {/* Domain Tabs */}
        <div className="border-b border-gray-200">
          <nav className="-mb-px flex space-x-6 overflow-x-auto text-xs" aria-label="Tabs">
            <button
              onClick={() => setSelectedDomain('all')}
              className={`whitespace-nowrap py-2 px-1 border-b-2 font-medium ${
                selectedDomain === 'all'
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              All
              <span className={`ml-2 py-0.5 px-2 rounded-full text-xs ${
                selectedDomain === 'all'
                  ? 'bg-blue-100 text-blue-700'
                  : 'bg-gray-100 text-gray-600'
              }`}>
                {data?.items?.length || 0}
              </span>
            </button>
            {domains.map((domain) => {
              const count = data?.items?.filter((item: any) => item.domain_id === domain.id).length || 0;
              return (
                <button
                  key={domain.id}
                  onClick={() => setSelectedDomain(domain.id)}
                  className={`whitespace-nowrap py-2 px-1 border-b-2 font-medium ${
                    selectedDomain === domain.id
                      ? 'border-blue-500 text-blue-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                  }`}
                >
                  {domain.name}
                  <span className={`ml-2 py-0.5 px-2 rounded-full text-xs ${
                    selectedDomain === domain.id
                      ? 'bg-blue-100 text-blue-700'
                      : 'bg-gray-100 text-gray-600'
                  }`}>
                    {count}
                  </span>
                </button>
              );
            })}
          </nav>
        </div>

        {/* Cases List */}
        {filteredItems.length === 0 ? (
          <div className="text-center py-12 text-sm text-gray-500">
            <p>
              {selectedDomain === 'all' 
                ? 'No cases yet. Get started by uploading a case.' 
                : 'No cases found in this domain.'}
            </p>
            {selectedDomain === 'all' && (
              <div className="mt-4">
                <Link
                  href="/cases/upload"
                  className="text-blue-600 underline hover:text-blue-700"
                >
                  Upload Case
                </Link>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-2">
            {filteredItems.map((c: any) => {
              const domainName = getDomainName(c.domain_id);
              return (
                <div key={c.id} className="border rounded bg-white p-3 hover:bg-gray-50 transition-colors">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <Link href={`/cases/${c.id}`} className="block">
                        <h3 className="font-medium text-sm text-gray-900 hover:text-blue-600">
                          {c.extracted?.case_name || c.filename}
                        </h3>
                        <div className="flex items-center gap-3 mt-1 text-xs text-gray-600">
                          <span className="capitalize">{c.status}</span>
                          {domainName && (
                            <>
                              <span className="text-gray-300">•</span>
                              <span className="px-2 py-0.5 bg-blue-500 text-white rounded-full">
                                {domainName}
                              </span>
                            </>
                          )}
                        </div>
                      </Link>
                    </div>
                    <div className="flex items-center gap-2">
                      <DocumentDownloadButton caseId={c.id} hasFile={c.has_file} />
                      <button
                        type="button"
                        onClick={() => { setCaseToDelete(c); setDeleteError(null); setConfirmOpen(true); }}
                        className="text-xs text-red-600 hover:text-red-700 hover:underline"
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Delete Confirmation Modal */}
        {confirmOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50 px-4">
            <div className="bg-white rounded border shadow-lg max-w-sm w-full p-4">
              <h3 className="text-sm font-semibold text-gray-900 mb-2">Delete case?</h3>
              <p className="text-xs text-gray-600 mb-4">
                This action cannot be undone.
              </p>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => { if (!deleting) { setConfirmOpen(false); setCaseToDelete(null); } }}
                  disabled={deleting}
                  className="px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50"
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
                  className="px-3 py-1.5 text-xs font-medium text-white bg-red-600 border border-transparent rounded hover:bg-red-700 disabled:opacity-50"
                >
                  {deleting ? 'Deleting...' : 'Delete'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

