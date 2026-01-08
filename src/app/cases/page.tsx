"use client";
import { useState, useEffect, useMemo, useCallback } from 'react';
import Link from 'next/link';
import { useSession } from 'next-auth/react';
import type { Session } from 'next-auth';
import { useAppStore } from '@/lib/store/appStore';
import { DocumentDownloadButton } from '@/components/cases/DocumentDownloadButton';
import { hasAtLeastRole } from '@/lib/rbac';

type ComparisonStatus = 'all' | 'issues' | 'synced' | 'pending' | 'not_checked' | 'not_in_kg' | 'needs_completion';

interface BatchProgress {
  completed: number;
  total: number;
  currentCase: string;
  status: 'running' | 'complete' | 'error';
  successCount?: number;
  failCount?: number;
}

export default function CasesListPage() {
  const { data: session } = useSession();
  const role = (session?.user as Session['user'])?.role
  const isAdmin = hasAtLeastRole(role, 'admin');
  
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [caseToDelete, setCaseToDelete] = useState<any>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [selectedDomain, setSelectedDomain] = useState<string>('all')
  const [selectedComparisonStatus, setSelectedComparisonStatus] = useState<ComparisonStatus>('all')
  const catalogNodes = useAppStore(s => s.catalogNodes)
  
  // Batch comparison state
  const [batchProgress, setBatchProgress] = useState<BatchProgress | null>(null);
  const [batchRunning, setBatchRunning] = useState(false);
  
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
  
  const fetchCases = useCallback(async () => {
      try {
        const response = await fetch('/api/cases');
        const result = await response.json();
        setData(result);
        setIsLoading(false);
      } catch (err) {
        setError(err);
        setIsLoading(false);
      }
  }, []);
    
  useEffect(() => {
    fetchCases();
  }, [fetchCases]);
  
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
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, catalogNodes]);
  
  // Get comparison status counts
  const comparisonStatusCounts = useMemo(() => {
    const items = data?.items || [];
    const counts: Record<ComparisonStatus, number> = {
      all: items.length,
      issues: 0,
      synced: 0,
      pending: 0,
      not_checked: 0,
      not_in_kg: 0,
      needs_completion: 0,
    };
    
    items.forEach((item: any) => {
      const status = item.comparison_status as ComparisonStatus;
      if (status && counts[status] !== undefined) {
        counts[status]++;
      }
    });
    
    return counts;
  }, [data]);
  
  // Filter items by selected domain and comparison status
  const filteredItems = useMemo(() => {
    let items = data?.items || [];
    
    // Filter by domain
    if (selectedDomain !== 'all') {
      items = items.filter((item: any) => item.domain_id === selectedDomain);
    }
    
    // Filter by comparison status (admin only)
    if (isAdmin && selectedComparisonStatus !== 'all') {
      items = items.filter((item: any) => item.comparison_status === selectedComparisonStatus);
    }
    
      return items;
  }, [data, selectedDomain, selectedComparisonStatus, isAdmin]);
  
  // Start batch comparison
  const startBatchComparison = async (force: boolean = false) => {
    if (batchRunning) return;
    
    setBatchRunning(true);
    setBatchProgress(null);
    
    try {
      // Start the batch job
      const res = await fetch('/api/admin/comparisons/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force }),
      });
      
      const result = await res.json();
      
      if (!res.ok || !result.job_id) {
        throw new Error(result.error || 'Failed to start batch comparison');
      }
      
      const jobId = result.job_id;
      const total = result.queued_count;
      
      if (total === 0) {
        setBatchProgress({
          completed: 0,
          total: 0,
          currentCase: '',
          status: 'complete',
          successCount: 0,
          failCount: 0,
        });
        setBatchRunning(false);
        return;
      }
      
      // Connect to SSE progress stream
      const eventSource = new EventSource(`/api/admin/comparisons/progress/${jobId}`);
      
      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          
          if (data.type === 'progress') {
            setBatchProgress({
              completed: data.completed,
              total: data.total,
              currentCase: data.current_case || '',
              status: data.status === 'complete' ? 'complete' : 'running',
            });
          } else if (data.type === 'complete') {
            setBatchProgress({
              completed: data.total,
              total: data.total,
              currentCase: '',
              status: 'complete',
              successCount: data.success_count,
              failCount: data.fail_count,
            });
            eventSource.close();
            setBatchRunning(false);
            // Refresh cases to get updated comparison data
            fetchCases();
          } else if (data.type === 'error') {
            setBatchProgress(prev => prev ? { ...prev, status: 'error' } : null);
            eventSource.close();
            setBatchRunning(false);
          } else if (data.type === 'end') {
            eventSource.close();
            setBatchRunning(false);
          }
        } catch (e) {
          console.error('Failed to parse SSE event:', e);
        }
      };
      
      eventSource.onerror = () => {
        eventSource.close();
        setBatchRunning(false);
      };
      
    } catch (e: any) {
      console.error('Failed to start batch comparison:', e);
      setBatchRunning(false);
    }
  };
  
  // Render comparison status badge
  const renderComparisonBadge = (item: any) => {
    if (!isAdmin) return null;
    
    const status = item.comparison_status;
    const comparison = item.comparison;
    
    switch (status) {
      case 'not_in_kg':
        return (
          <span className="text-xs text-gray-400">Not in KG</span>
        );
      case 'pending':
        return (
          <span className="text-xs text-blue-500">Pending sync</span>
        );
      case 'not_checked':
        return (
          <span className="text-xs text-gray-400">Not checked</span>
        );
      case 'synced':
        return (
          <span className="text-xs text-green-600">✓ Synced</span>
        );
      case 'needs_completion':
        return (
          <Link
            href={`/cases/${item.id}/neo4j`}
            className="text-xs text-orange-500 hover:text-orange-600 hover:underline"
            onClick={(e) => e.stopPropagation()}
          >
            📝 {comparison?.required_missing_count || ''} required fields missing
          </Link>
        );
      case 'issues':
        const issues: string[] = [];
        if (comparison?.nodes_differ_count) issues.push(`${comparison.nodes_differ_count} fields`);
        if (comparison?.edges_differ_count) issues.push(`${comparison.edges_differ_count} edges`);
        if (comparison?.embeddings_missing_count) issues.push(`${comparison.embeddings_missing_count} embeddings`);
        
        return (
          <Link
            href={`/cases/${item.id}/neo4j`}
            className="text-xs text-amber-600 hover:text-amber-700 hover:underline"
            onClick={(e) => e.stopPropagation()}
          >
            ⚠ {issues.join(', ') || 'Issues'}
          </Link>
        );
      default:
        return null;
    }
  };
  
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
          <div className="flex items-center gap-4">
            {isAdmin && (
              <button
                onClick={() => startBatchComparison(false)}
                disabled={batchRunning}
                className="text-xs px-3 py-1.5 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded border border-gray-300 disabled:opacity-50"
              >
                {batchRunning ? 'Running...' : 'Run Comparisons'}
              </button>
            )}
            {isAdmin && (
              <Link 
                href="/cases/upload"
                className="text-blue-600 underline text-sm hover:text-blue-700"
              >
                Upload
              </Link>
            )}
          </div>
        </div>

        {deleteError && (
          <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700">
            {deleteError}
          </div>
        )}

        {/* Admin: Comparison Status Filter */}
        {isAdmin && (
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-gray-500">Filter by status:</span>
            {[
              { key: 'all' as ComparisonStatus, label: 'All' },
              { key: 'issues' as ComparisonStatus, label: '⚠ Issues', color: 'text-amber-600' },
              { key: 'needs_completion' as ComparisonStatus, label: '📝 Needs completion', color: 'text-orange-500' },
              { key: 'synced' as ComparisonStatus, label: '✓ Synced', color: 'text-green-600' },
              { key: 'pending' as ComparisonStatus, label: 'Pending', color: 'text-blue-500' },
              { key: 'not_checked' as ComparisonStatus, label: 'Not checked', color: 'text-gray-400' },
              { key: 'not_in_kg' as ComparisonStatus, label: 'Not in KG', color: 'text-gray-400' },
            ].map(({ key, label, color }) => (
              <button
                key={key}
                onClick={() => setSelectedComparisonStatus(key)}
                className={`text-xs px-2 py-1 rounded ${
                  selectedComparisonStatus === key
                    ? 'bg-gray-800 text-white'
                    : `bg-gray-100 hover:bg-gray-200 ${color || 'text-gray-700'}`
                }`}
              >
                {label}
                {key !== 'all' && (
                  <span className="ml-1 opacity-70">({comparisonStatusCounts[key]})</span>
                )}
              </button>
            ))}
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
              {selectedDomain === 'all' && selectedComparisonStatus === 'all'
                ? (isAdmin ? 'No cases yet. Get started by uploading a case.' : 'No cases yet.')
                : 'No cases found with the selected filters.'}
            </p>
            {isAdmin && selectedDomain === 'all' && selectedComparisonStatus === 'all' && (
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
                      </Link>
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
                        {/* Comparison status badge (admin only) */}
                        {renderComparisonBadge(c)}
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <DocumentDownloadButton caseId={c.id} hasFile={c.has_file} />
                      {isAdmin && (
                        <button
                          type="button"
                          onClick={() => { setCaseToDelete(c); setDeleteError(null); setConfirmOpen(true); }}
                          className="text-xs text-red-600 hover:text-red-700 hover:underline"
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Batch Comparison Progress Modal */}
        {batchProgress && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50 px-4">
            <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">
                {batchProgress.status === 'complete' ? 'Comparison Complete' : 'Running Comparisons'}
              </h3>
              
              {batchProgress.status === 'running' && (
                <>
                  <div className="mb-2 text-sm text-gray-600">
                    Comparing case {batchProgress.completed + 1} of {batchProgress.total}
                  </div>
                  {batchProgress.currentCase && (
                    <div className="mb-3 text-xs text-gray-500 truncate">
                      {batchProgress.currentCase}
                    </div>
                  )}
                  <div className="w-full bg-gray-200 rounded-full h-2 mb-4">
                    <div
                      className="h-full bg-blue-500 rounded-full transition-all duration-300"
                      style={{ width: `${(batchProgress.completed / batchProgress.total) * 100}%` }}
                    />
                  </div>
                </>
              )}
              
              {batchProgress.status === 'complete' && (
                <div className="space-y-2 mb-4">
                  <div className="text-sm text-gray-700">
                    <span className="text-green-600 font-medium">{batchProgress.successCount || 0}</span> comparisons completed successfully
                  </div>
                  {(batchProgress.failCount || 0) > 0 && (
                    <div className="text-sm text-gray-700">
                      <span className="text-red-600 font-medium">{batchProgress.failCount}</span> comparisons failed
                    </div>
                  )}
                </div>
              )}
              
              <div className="flex justify-end gap-2">
                {batchProgress.status === 'complete' && (
                  <>
                    <button
                      onClick={() => startBatchComparison(true)}
                      className="px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-300 rounded hover:bg-gray-50"
                    >
                      Force Re-run All
                    </button>
                    <button
                      onClick={() => setBatchProgress(null)}
                      className="px-3 py-1.5 text-xs font-medium text-white bg-blue-600 rounded hover:bg-blue-700"
                    >
                      Done
                    </button>
                  </>
                )}
              </div>
            </div>
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
