'use client'

import React, { useState } from 'react'

type ComparisonStatus = 'match' | 'differ' | 'only_postgres' | 'only_neo4j'

interface Difference {
  field: string
  postgres_value: any
  neo4j_value: any
}

interface NodeComparison {
  node_id: string
  label: string
  status: ComparisonStatus
  differences: Difference[]
  postgres_properties?: Record<string, any>
  neo4j_properties?: Record<string, any>
}

interface EdgeComparison {
  edge_id: string
  label: string
  from: string
  to: string
  status: ComparisonStatus
  differences: Difference[]
  postgres_properties?: Record<string, any>
  neo4j_properties?: Record<string, any>
}

interface EmbeddingMissing {
  node_id: string
  label: string
  property: string
}

interface ComparisonSummary {
  nodes: {
    total_postgres: number
    total_neo4j: number
    match: number
    differ: number
    only_postgres: number
    only_neo4j: number
  }
  edges: {
    total_postgres: number
    total_neo4j: number
    match: number
    differ: number
    only_postgres: number
    only_neo4j: number
  }
  catalog_nodes_skipped?: {
    total: number
    by_label: Record<string, number>
    labels: string[]
  }
  embeddings?: {
    total_expected: number
    total_present: number
    total_missing: number
    all_present: boolean
    missing: EmbeddingMissing[]
  }
}

type ComparisonSource = 'fresh' | 'cached' | null

interface CachedComparisonInfo {
  exists: boolean
  is_stale?: boolean
  compared_at?: string
  postgres_updated_at?: string
  kg_submitted_at?: string
}

type SyncStatus = 'synced' | 'issues' | 'pending' | 'not_checked' | 'not_in_kg'

interface ComparisonResultsProps {
  loading: boolean
  error: string | null
  data: {
    all_match: boolean
    summary: ComparisonSummary
    node_comparisons: NodeComparison[]
    edge_comparisons: EdgeComparison[]
  } | null
  onCompare: () => void
  /** Whether this data came from cache or fresh comparison */
  source?: ComparisonSource
  /** Cached comparison metadata (when loaded from Postgres) */
  cachedInfo?: CachedComparisonInfo
  /** Computed sync status */
  syncStatus?: SyncStatus
  /** Whether the page is loading cached comparison */
  loadingCached?: boolean
}

function StatusBadge({ status }: { status: ComparisonStatus }) {
  const styles: Record<ComparisonStatus, string> = {
    match: 'bg-green-100 text-green-800',
    differ: 'bg-amber-100 text-amber-800',
    only_postgres: 'bg-blue-100 text-blue-800',
    only_neo4j: 'bg-purple-100 text-purple-800',
  }
  const labels: Record<ComparisonStatus, string> = {
    match: '✓ Match',
    differ: '≠ Differs',
    only_postgres: 'Only in Postgres',
    only_neo4j: 'Only in Neo4j',
  }
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${styles[status]}`}>
      {labels[status]}
    </span>
  )
}

function formatValue(value: any): string {
  if (value === null || value === undefined) return '(empty)'
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}

function DiffTable({ differences }: { differences: Difference[] }) {
  if (differences.length === 0) return null
  
  return (
    <table className="w-full text-xs mt-2 border-collapse">
      <thead>
        <tr className="bg-gray-100">
          <th className="text-left p-2 border">Field</th>
          <th className="text-left p-2 border">Postgres</th>
          <th className="text-left p-2 border">Neo4j</th>
        </tr>
      </thead>
      <tbody>
        {differences.map((diff, idx) => (
          <tr key={idx} className="border-b">
            <td className="p-2 border font-medium">{diff.field}</td>
            <td className="p-2 border bg-blue-50">
              <pre className="whitespace-pre-wrap break-words max-w-xs">
                {formatValue(diff.postgres_value)}
              </pre>
            </td>
            <td className="p-2 border bg-purple-50">
              <pre className="whitespace-pre-wrap break-words max-w-xs">
                {formatValue(diff.neo4j_value)}
              </pre>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ComparisonItem({ 
  title, 
  status, 
  differences,
  postgresProperties,
  neo4jProperties 
}: { 
  title: string
  status: ComparisonStatus
  differences: Difference[]
  postgresProperties?: Record<string, any>
  neo4jProperties?: Record<string, any>
}) {
  const [expanded, setExpanded] = useState(false)
  const hasDetails = differences.length > 0 || postgresProperties || neo4jProperties
  
  return (
    <div className="border rounded mb-2">
      <div 
        className={`flex items-center justify-between p-2 ${hasDetails ? 'cursor-pointer hover:bg-gray-50' : ''}`}
        onClick={() => hasDetails && setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2">
          {hasDetails && (
            <span className="text-gray-400 text-xs">{expanded ? '▼' : '▶'}</span>
          )}
          <span className="text-sm font-medium">{title}</span>
        </div>
        <StatusBadge status={status} />
      </div>
      
      {expanded && hasDetails && (
        <div className="p-2 pt-0 border-t bg-gray-50">
          {differences.length > 0 && <DiffTable differences={differences} />}
          
          {postgresProperties && (
            <div className="mt-2">
              <div className="text-xs font-medium text-blue-700 mb-1">Postgres Properties:</div>
              <pre className="text-xs bg-blue-50 p-2 rounded overflow-auto max-h-40">
                {JSON.stringify(postgresProperties, null, 2)}
              </pre>
            </div>
          )}
          
          {neo4jProperties && (
            <div className="mt-2">
              <div className="text-xs font-medium text-purple-700 mb-1">Neo4j Properties:</div>
              <pre className="text-xs bg-purple-50 p-2 rounded overflow-auto max-h-40">
                {JSON.stringify(neo4jProperties, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function SummaryStats({ summary }: { summary: ComparisonSummary }) {
  const catalogSkipped = summary.catalog_nodes_skipped
  
  return (
    <div className="space-y-4 mb-4">
      <div className="grid grid-cols-2 gap-4">
        <div className="border rounded p-3">
          <div className="font-medium text-sm mb-2">Nodes</div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div>Postgres: {summary.nodes.total_postgres}</div>
            <div>Neo4j: {summary.nodes.total_neo4j}</div>
            <div className="text-green-600">Match: {summary.nodes.match}</div>
            <div className="text-amber-600">Differ: {summary.nodes.differ}</div>
            <div className="text-blue-600">Only PG: {summary.nodes.only_postgres}</div>
            <div className="text-purple-600">Only Neo4j: {summary.nodes.only_neo4j}</div>
          </div>
        </div>
        <div className="border rounded p-3">
          <div className="font-medium text-sm mb-2">Edges</div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div>Postgres: {summary.edges.total_postgres}</div>
            <div>Neo4j: {summary.edges.total_neo4j}</div>
            <div className="text-green-600">Match: {summary.edges.match}</div>
            <div className="text-amber-600">Differ: {summary.edges.differ}</div>
            <div className="text-blue-600">Only PG: {summary.edges.only_postgres}</div>
            <div className="text-purple-600">Only Neo4j: {summary.edges.only_neo4j}</div>
          </div>
        </div>
      </div>
      
      {/* Catalog nodes info */}
      {catalogSkipped && catalogSkipped.total > 0 && (
        <div className="border rounded p-3 bg-gray-50">
          <div className="font-medium text-sm mb-2 text-gray-700">
            Catalog Nodes (skipped from comparison)
          </div>
          <div className="text-xs text-gray-600">
            <p className="mb-1">
              {catalogSkipped.total} catalog node{catalogSkipped.total !== 1 ? 's' : ''} exist only in Neo4j by design 
              (shared/immutable entities not stored in Postgres).
            </p>
            <div className="flex flex-wrap gap-2 mt-2">
              {Object.entries(catalogSkipped.by_label).map(([label, count]) => (
                <span key={label} className="px-2 py-0.5 bg-gray-200 rounded text-gray-700">
                  {label}: {count}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}
      
      {/* Embeddings validation */}
      {summary.embeddings && (
        <div className={`border rounded p-3 ${summary.embeddings.all_present ? 'bg-green-50 border-green-200' : 'bg-amber-50 border-amber-200'}`}>
          <div className="font-medium text-sm mb-2 flex items-center gap-2">
            <span className={summary.embeddings.all_present ? 'text-green-600' : 'text-amber-600'}>
              {summary.embeddings.all_present ? '✓' : '⚠'}
            </span>
            <span className={summary.embeddings.all_present ? 'text-green-800' : 'text-amber-800'}>
              Neo4j Embeddings
            </span>
          </div>
          <div className="text-xs">
            <div className="grid grid-cols-3 gap-2 mb-2">
              <div>Expected: {summary.embeddings.total_expected}</div>
              <div className="text-green-600">Present: {summary.embeddings.total_present}</div>
              <div className={summary.embeddings.total_missing > 0 ? 'text-amber-600' : ''}>
                Missing: {summary.embeddings.total_missing}
              </div>
            </div>
            {summary.embeddings.missing.length > 0 && (
              <div className="mt-2">
                <div className="font-medium text-amber-700 mb-1">Missing embeddings:</div>
                <div className="max-h-32 overflow-y-auto">
                  {summary.embeddings.missing.map((m, idx) => (
                    <div key={idx} className="text-amber-800 py-0.5">
                      {m.label}.{m.property} (node: {m.node_id.substring(0, 8)}...)
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function formatRelativeTime(dateString: string): string {
  const date = new Date(dateString)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMins / 60)
  const diffDays = Math.floor(diffHours / 24)
  
  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 7) return `${diffDays}d ago`
  return date.toLocaleDateString()
}

function SyncStatusBanner({ 
  syncStatus, 
  source, 
  cachedInfo,
  allMatch 
}: { 
  syncStatus?: SyncStatus
  source?: ComparisonSource
  cachedInfo?: CachedComparisonInfo
  allMatch?: boolean
}) {
  // Pending sync: postgres was updated after KG submit, so mismatch is expected
  if (syncStatus === 'pending') {
    return (
      <div className="p-3 rounded mb-4 bg-blue-50 border border-blue-200">
        <div className="flex items-center gap-2">
          <span className="text-lg text-blue-600">⏳</span>
          <div>
            <span className="font-medium text-blue-800">Pending sync</span>
            <p className="text-xs text-blue-600 mt-0.5">
              Postgres data was updated after the last KG submission. 
              Differences are expected until the case is re-submitted to the Knowledge Graph.
            </p>
          </div>
        </div>
      </div>
    )
  }
  
  // Not in KG yet
  if (syncStatus === 'not_in_kg') {
    return (
      <div className="p-3 rounded mb-4 bg-gray-50 border border-gray-200">
        <div className="flex items-center gap-2">
          <span className="text-lg text-gray-500">—</span>
          <div>
            <span className="font-medium text-gray-700">Not in Knowledge Graph</span>
            <p className="text-xs text-gray-500 mt-0.5">
              This case has not been submitted to the Knowledge Graph yet.
            </p>
          </div>
        </div>
      </div>
    )
  }
  
  // Show cached data indicator when we have results from cache
  if (source === 'cached' && cachedInfo?.compared_at) {
    const timeAgo = formatRelativeTime(cachedInfo.compared_at)
    const isStale = cachedInfo.is_stale
    
    return (
      <div className={`p-3 rounded mb-4 ${allMatch ? 'bg-green-50 border border-green-200' : 'bg-amber-50 border border-amber-200'}`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className={`text-lg ${allMatch ? 'text-green-600' : 'text-amber-600'}`}>
              {allMatch ? '✓' : '⚠'}
            </span>
            <span className={`font-medium ${allMatch ? 'text-green-800' : 'text-amber-800'}`}>
              {allMatch ? 'All data matches!' : 'Differences found'}
            </span>
          </div>
          <span className={`text-xs ${isStale ? 'text-amber-600' : 'text-gray-500'}`}>
            {isStale && '⚠ Stale — '}Checked {timeAgo}
          </span>
        </div>
      </div>
    )
  }
  
  // Fresh comparison result (no cache metadata)
  if (allMatch !== undefined) {
    return (
      <div className={`p-3 rounded mb-4 ${allMatch ? 'bg-green-50 border border-green-200' : 'bg-amber-50 border border-amber-200'}`}>
        <div className="flex items-center gap-2">
          <span className={`text-lg ${allMatch ? 'text-green-600' : 'text-amber-600'}`}>
            {allMatch ? '✓' : '⚠'}
          </span>
          <span className={`font-medium ${allMatch ? 'text-green-800' : 'text-amber-800'}`}>
            {allMatch ? 'All data matches!' : 'Differences found'}
          </span>
        </div>
      </div>
    )
  }
  
  return null
}

export function ComparisonResults({ 
  loading, 
  error, 
  data, 
  onCompare,
  source,
  cachedInfo,
  syncStatus,
  loadingCached 
}: ComparisonResultsProps) {
  const [showMatches, setShowMatches] = useState(false)
  const [activeTab, setActiveTab] = useState<'nodes' | 'edges'>('nodes')
  
  // Determine button text based on state
  const getButtonText = () => {
    if (loading) return 'Comparing...'
    if (source === 'cached' && cachedInfo?.is_stale) return 'Re-run Comparison (stale)'
    if (source === 'cached') return 'Re-run Comparison'
    return 'Run Comparison'
  }
  
  return (
    <div className="border rounded-lg bg-white p-4 mb-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold">Postgres ↔ Neo4j Comparison</h3>
        <button
          onClick={onCompare}
          disabled={loading || loadingCached}
          className="px-3 py-1.5 bg-blue-600 text-white text-xs rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {getButtonText()}
        </button>
      </div>
      
      {error && (
        <div className="text-red-600 text-sm bg-red-50 p-2 rounded mb-4">
          {error}
        </div>
      )}
      
      {loadingCached && (
        <div className="text-center text-gray-500 text-sm py-4">
          Loading comparison status...
        </div>
      )}
      
      {/* Sync status banner */}
      <SyncStatusBanner 
        syncStatus={syncStatus}
        source={source}
        cachedInfo={cachedInfo}
        allMatch={data?.all_match}
      />
      
      {data && (
        <>
          {/* Summary stats */}
          <SummaryStats summary={data.summary} />
          
          {/* Filter toggle */}
          <div className="flex items-center gap-4 mb-4">
            <label className="flex items-center gap-2 text-xs">
              <input
                type="checkbox"
                checked={showMatches}
                onChange={(e) => setShowMatches(e.target.checked)}
                className="rounded"
              />
              Show matching items
            </label>
          </div>
          
          {/* Tabs */}
          <div className="flex border-b mb-4">
            <button
              className={`px-4 py-2 text-sm ${activeTab === 'nodes' ? 'border-b-2 border-blue-600 text-blue-600' : 'text-gray-500'}`}
              onClick={() => setActiveTab('nodes')}
            >
              Nodes ({data.node_comparisons.length})
            </button>
            <button
              className={`px-4 py-2 text-sm ${activeTab === 'edges' ? 'border-b-2 border-blue-600 text-blue-600' : 'text-gray-500'}`}
              onClick={() => setActiveTab('edges')}
            >
              Edges ({data.edge_comparisons.length})
            </button>
          </div>
          
          {/* Comparison list */}
          <div className="max-h-96 overflow-y-auto">
            {activeTab === 'nodes' && (
              <>
                {data.node_comparisons
                  .filter(n => showMatches || n.status !== 'match')
                  .map((node) => (
                    <ComparisonItem
                      key={node.node_id}
                      title={`${node.label}: ${node.node_id.substring(0, 8)}...`}
                      status={node.status}
                      differences={node.differences}
                      postgresProperties={node.postgres_properties}
                      neo4jProperties={node.neo4j_properties}
                    />
                  ))}
                {!showMatches && data.node_comparisons.every(n => n.status === 'match') && (
                  <div className="text-center text-gray-500 text-sm py-4">
                    All nodes match! Enable &quot;Show matching items&quot; to see details.
                  </div>
                )}
              </>
            )}
            
            {activeTab === 'edges' && (
              <>
                {data.edge_comparisons
                  .filter(e => showMatches || e.status !== 'match')
                  .map((edge) => (
                    <ComparisonItem
                      key={edge.edge_id}
                      title={`${edge.label}`}
                      status={edge.status}
                      differences={edge.differences}
                      postgresProperties={edge.postgres_properties}
                      neo4jProperties={edge.neo4j_properties}
                    />
                  ))}
                {!showMatches && data.edge_comparisons.every(e => e.status === 'match') && (
                  <div className="text-center text-gray-500 text-sm py-4">
                    All edges match! Enable &quot;Show matching items&quot; to see details.
                  </div>
                )}
              </>
            )}
          </div>
        </>
      )}
      
      {!data && !loading && !error && (
        <div className="text-center text-gray-500 text-sm py-4">
          Click &quot;Run Comparison&quot; to compare Postgres and Neo4j data.
        </div>
      )}
    </div>
  )
}

