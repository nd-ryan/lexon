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

interface MissingRelationship {
  node_id: string
  label: string
  relationship: string
  direction: 'outgoing' | 'incoming'
  expected_min: number
  actual_count: number
}

interface MissingRelationshipProperty {
  edge_id: string
  relationship: string
  property: string
  from_id: string
  to_id: string
}

interface CardinalityViolation {
  source_id: string
  source_label: string
  relationship: string
  issue: 'source_multiple' | 'target_multiple'
  details: string
}

interface NodeStats {
  total_postgres: number
  total_neo4j: number
  match: number
  differ: number
  only_postgres: number
  only_neo4j: number
}

interface IntegrityChecks {
  all_valid: boolean
  required_properties?: {
    total_expected: number
    total_present: number
    total_missing: number
    all_present: boolean
    missing: EmbeddingMissing[]
  }
  required_relationships?: {
    total_expected: number
    total_present: number
    total_missing: number
    all_present: boolean
    missing: MissingRelationship[]
  }
  relationship_properties?: {
    total_expected: number
    total_present: number
    total_missing: number
    all_present: boolean
    missing: MissingRelationshipProperty[]
  }
  cardinality?: {
    total_violations: number
    all_valid: boolean
    violations: CardinalityViolation[]
  }
  embeddings?: {
    total_expected: number
    total_present: number
    total_missing: number
    all_present: boolean
    missing: EmbeddingMissing[]
  } | null
}

interface ComparisonSummary {
  // Sync status (Postgres ↔ Neo4j)
  sync: {
    all_synced: boolean
    nodes: NodeStats
    edges: NodeStats
    catalog_nodes_skipped?: {
      total: number
      by_label: Record<string, number>
      labels: string[]
    }
  }
  // Postgres integrity (source data - what admin edits)
  postgres_integrity: IntegrityChecks
  // Neo4j integrity (knowledge graph - the goal)
  neo4j_integrity: IntegrityChecks
}

type ComparisonSource = 'fresh' | 'cached' | null

interface CachedComparisonInfo {
  exists: boolean
  is_stale?: boolean
  compared_at?: string
  postgres_updated_at?: string
  kg_submitted_at?: string
}

type SyncStatus = 'synced' | 'issues' | 'pending' | 'not_checked' | 'not_in_kg' | 'needs_completion'

interface ComparisonResultsProps {
  loading: boolean
  error: string | null
  data: {
    all_match: boolean
    needs_completion?: boolean
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

// Helper component for integrity check details
function IntegritySection({ 
  title, 
  integrity, 
  colorScheme = 'orange',
  showEmbeddings = false
}: { 
  title: string
  integrity: IntegrityChecks
  colorScheme?: 'orange' | 'purple'
  showEmbeddings?: boolean
}) {
  const colors = colorScheme === 'orange' 
    ? { bg: 'bg-orange-50', border: 'border-orange-200', text: 'text-orange-800', accent: 'text-orange-600', item: 'bg-orange-100' }
    : { bg: 'bg-purple-50', border: 'border-purple-200', text: 'text-purple-800', accent: 'text-purple-600', item: 'bg-purple-100' }
  
  const isValid = integrity.all_valid

  return (
    <div className={`border rounded p-3 ${isValid ? 'bg-green-50 border-green-200' : `${colors.bg} ${colors.border}`}`}>
      <div className="font-medium text-sm mb-3 flex items-center gap-2">
        <span className={isValid ? 'text-green-600' : colors.accent}>
          {isValid ? '✓' : '⚠️'}
        </span>
        <span className={isValid ? 'text-green-800' : colors.text}>
          {title} {!isValid && '(Issues Found)'}
        </span>
      </div>
      
      <div className="space-y-3 text-xs">
        {/* Required Properties */}
        {integrity.required_properties && (
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className={integrity.required_properties.all_present ? 'text-green-600' : colors.accent}>
                {integrity.required_properties.all_present ? '✓' : '○'}
              </span>
              <span>Required Properties: {integrity.required_properties.total_present}/{integrity.required_properties.total_expected}</span>
            </div>
            {integrity.required_properties.missing.length > 0 && (
              <div className="ml-5 max-h-24 overflow-y-auto space-y-1">
                {integrity.required_properties.missing.map((m, idx) => (
                  <div key={idx} className={`${colors.item} ${colors.text} px-2 py-0.5 rounded text-[11px]`}>
                    {m.label}.{m.property}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Required Relationships */}
        {integrity.required_relationships && (
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className={integrity.required_relationships.all_present ? 'text-green-600' : colors.accent}>
                {integrity.required_relationships.all_present ? '✓' : '○'}
              </span>
              <span>Required Relationships: {integrity.required_relationships.total_present}/{integrity.required_relationships.total_expected}</span>
            </div>
            {integrity.required_relationships.missing.length > 0 && (
              <div className="ml-5 max-h-24 overflow-y-auto space-y-1">
                {integrity.required_relationships.missing.map((m, idx) => (
                  <div key={idx} className={`${colors.item} ${colors.text} px-2 py-0.5 rounded text-[11px]`}>
                    {m.label} {m.direction === 'outgoing' ? '→' : '←'} {m.relationship}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Relationship Properties */}
        {integrity.relationship_properties && (
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className={integrity.relationship_properties.all_present ? 'text-green-600' : colors.accent}>
                {integrity.relationship_properties.all_present ? '✓' : '○'}
              </span>
              <span>Relationship Properties: {integrity.relationship_properties.total_present}/{integrity.relationship_properties.total_expected}</span>
            </div>
            {integrity.relationship_properties.missing.length > 0 && (
              <div className="ml-5 max-h-24 overflow-y-auto space-y-1">
                {integrity.relationship_properties.missing.map((m, idx) => (
                  <div key={idx} className={`${colors.item} ${colors.text} px-2 py-0.5 rounded text-[11px]`}>
                    {m.relationship}.{m.property}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Cardinality */}
        {integrity.cardinality && (
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className={integrity.cardinality.all_valid ? 'text-green-600' : 'text-red-600'}>
                {integrity.cardinality.all_valid ? '✓' : '○'}
              </span>
              <span>Cardinality: {integrity.cardinality.all_valid ? 'Valid' : `${integrity.cardinality.total_violations} violation(s)`}</span>
            </div>
            {integrity.cardinality.violations.length > 0 && (
              <div className="ml-5 max-h-24 overflow-y-auto space-y-1">
                {integrity.cardinality.violations.map((v, idx) => (
                  <div key={idx} className="bg-red-100 text-red-800 px-2 py-0.5 rounded text-[11px]">
                    {v.source_label}→{v.relationship}: {v.details}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Embeddings (Neo4j only) */}
        {showEmbeddings && integrity.embeddings && (
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className={integrity.embeddings.all_present ? 'text-green-600' : 'text-amber-600'}>
                {integrity.embeddings.all_present ? '✓' : '○'}
              </span>
              <span>Embeddings: {integrity.embeddings.total_present}/{integrity.embeddings.total_expected}</span>
            </div>
            {integrity.embeddings.missing.length > 0 && (
              <div className="ml-5 max-h-24 overflow-y-auto space-y-1">
                {integrity.embeddings.missing.map((m, idx) => (
                  <div key={idx} className="bg-amber-100 text-amber-800 px-2 py-0.5 rounded text-[11px]">
                    {m.label}.{m.property}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// Migrate old summary format to new three-part structure
function migrateSummary(summary: any): ComparisonSummary {
  // If already has new structure, return as-is
  if (summary.sync && summary.postgres_integrity && summary.neo4j_integrity) {
    return summary as ComparisonSummary
  }
  
  // Migrate old flat structure to new nested structure
  const nodes = summary.nodes || { total_postgres: 0, total_neo4j: 0, match: 0, differ: 0, only_postgres: 0, only_neo4j: 0 }
  const edges = summary.edges || { total_postgres: 0, total_neo4j: 0, match: 0, differ: 0, only_postgres: 0, only_neo4j: 0 }
  
  const all_synced = nodes.differ === 0 && nodes.only_postgres === 0 && nodes.only_neo4j === 0 &&
                     edges.differ === 0 && edges.only_postgres === 0 && edges.only_neo4j === 0
  
  const integrityChecks: IntegrityChecks = {
    all_valid: (summary.required_properties?.all_present ?? true) &&
               (summary.required_relationships?.all_present ?? true) &&
               (summary.relationship_properties?.all_present ?? true) &&
               (summary.cardinality?.all_valid ?? true),
    required_properties: summary.required_properties,
    required_relationships: summary.required_relationships,
    relationship_properties: summary.relationship_properties,
    cardinality: summary.cardinality,
    embeddings: summary.embeddings,
  }
  
  return {
    sync: {
      all_synced,
      nodes,
      edges,
      catalog_nodes_skipped: summary.catalog_nodes_skipped,
    },
    postgres_integrity: integrityChecks,
    neo4j_integrity: integrityChecks,
  }
}

function SummaryStats({ summary: rawSummary }: { summary: ComparisonSummary }) {
  const summary = migrateSummary(rawSummary)
  const { sync, postgres_integrity, neo4j_integrity } = summary
  const catalogSkipped = sync.catalog_nodes_skipped
  
  return (
    <div className="space-y-4 mb-4">
      {/* SYNC STATUS */}
      <div className={`border rounded p-3 ${sync.all_synced ? 'bg-green-50 border-green-200' : 'bg-amber-50 border-amber-200'}`}>
        <div className="font-medium text-sm mb-3 flex items-center gap-2">
          <span className={sync.all_synced ? 'text-green-600' : 'text-amber-600'}>
            {sync.all_synced ? '✓' : '⚠'}
          </span>
          <span className={sync.all_synced ? 'text-green-800' : 'text-amber-800'}>
            Sync Status (Postgres ↔ Neo4j) {!sync.all_synced && '- Re-submit to KG'}
          </span>
        </div>
        
        <div className="grid grid-cols-2 gap-4">
          <div className="text-xs">
            <div className="font-medium mb-1">Nodes</div>
            <div className="grid grid-cols-2 gap-1">
              <div>Postgres: {sync.nodes.total_postgres}</div>
              <div>Neo4j: {sync.nodes.total_neo4j}</div>
              <div className="text-green-600">Match: {sync.nodes.match}</div>
              <div className={sync.nodes.differ > 0 ? 'text-amber-600 font-medium' : ''}>Differ: {sync.nodes.differ}</div>
              <div className={sync.nodes.only_postgres > 0 ? 'text-blue-600' : ''}>Only PG: {sync.nodes.only_postgres}</div>
              <div className={sync.nodes.only_neo4j > 0 ? 'text-purple-600' : ''}>Only Neo4j: {sync.nodes.only_neo4j}</div>
            </div>
          </div>
          <div className="text-xs">
            <div className="font-medium mb-1">Edges</div>
            <div className="grid grid-cols-2 gap-1">
              <div>Postgres: {sync.edges.total_postgres}</div>
              <div>Neo4j: {sync.edges.total_neo4j}</div>
              <div className="text-green-600">Match: {sync.edges.match}</div>
              <div className={sync.edges.differ > 0 ? 'text-amber-600 font-medium' : ''}>Differ: {sync.edges.differ}</div>
              <div className={sync.edges.only_postgres > 0 ? 'text-blue-600' : ''}>Only PG: {sync.edges.only_postgres}</div>
              <div className={sync.edges.only_neo4j > 0 ? 'text-purple-600' : ''}>Only Neo4j: {sync.edges.only_neo4j}</div>
            </div>
          </div>
        </div>

        {/* Catalog nodes info */}
        {catalogSkipped && catalogSkipped.total > 0 && (
          <div className="mt-3 pt-3 border-t border-gray-200 text-xs text-gray-600">
            <span className="font-medium">Catalog nodes skipped:</span>{' '}
            {Object.entries(catalogSkipped.by_label).map(([label, count]) => (
              <span key={label} className="ml-2">{label}: {count}</span>
            ))}
          </div>
        )}
      </div>

      {/* POSTGRES INTEGRITY */}
      <IntegritySection
        title="Postgres Integrity (Source Data)"
        integrity={postgres_integrity}
        colorScheme="orange"
      />

      {/* NEO4J INTEGRITY */}
      <IntegritySection
        title="Neo4j Integrity (Knowledge Graph)"
        integrity={neo4j_integrity}
        colorScheme="purple"
        showEmbeddings={true}
      />
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
  allMatch,
  needsCompletion 
}: { 
  syncStatus?: SyncStatus
  source?: ComparisonSource
  cachedInfo?: CachedComparisonInfo
  allMatch?: boolean
  needsCompletion?: boolean
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
  
  // Needs completion: data synced but missing required properties
  if (syncStatus === 'needs_completion' || needsCompletion) {
    const timeAgo = cachedInfo?.compared_at ? formatRelativeTime(cachedInfo.compared_at) : null
    const isStale = cachedInfo?.is_stale
    
    return (
      <div className="p-3 rounded mb-4 bg-orange-50 border border-orange-200">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg text-orange-600">📝</span>
            <div>
              <span className="font-medium text-orange-800">Needs manual completion</span>
              <p className="text-xs text-orange-600 mt-0.5">
                Data synced correctly but some required properties are missing. 
                Edit the case to fill in the missing fields.
              </p>
            </div>
          </div>
          {timeAgo && (
            <span className={`text-xs ${isStale ? 'text-orange-600' : 'text-gray-500'}`}>
              {isStale && '⚠ Stale — '}Checked {timeAgo}
            </span>
          )}
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
        needsCompletion={data?.needs_completion}
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

