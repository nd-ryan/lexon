/**
 * Unified node card component for rendering case graph nodes
 */

import { ReusedNodeIcon } from './ReusedNodeIcon'
import { NodeActionMenu } from './NodeActionMenu'
import { ObjectFields } from './Field'
import type { Schema } from '@/types/case-graph'

interface NodeCardProps {
  node: any
  label: string
  index?: number
  depth?: number
  badge?: React.ReactNode
  statusBadge?: React.ReactNode
  children?: React.ReactNode
  parentId?: string
  contextId?: string
  isViewMode: boolean
  globalNodeNumber: number | null
  isReused: boolean
  shouldShowUnlink: boolean
  parentLabel: string
  onDelete: (nodeId: string) => void
  onUnlink: (nodeId: string, parentId: string) => void
  // Field rendering props
  graphState: any
  schema: Schema | null
  setPendingEdit: (path: (string | number)[], value: any) => void
  setValueAtPath: (path: (string | number)[], value: any) => void
  pendingEditsRef: React.MutableRefObject<Record<string, any>>
  pendingEditsVersion: number
  nodeOptions?: { id: string; display: string }[]
  nodeIdToDisplay?: Record<string, string>
}

export function NodeCard({
  node,
  label,
  index,
  depth = 0,
  badge,
  statusBadge,
  children,
  parentId,
  contextId,
  isViewMode,
  globalNodeNumber,
  isReused,
  shouldShowUnlink,
  parentLabel,
  onDelete,
  onUnlink,
  graphState,
  schema,
  setPendingEdit,
  setValueAtPath,
  pendingEditsRef,
  pendingEditsVersion,
  nodeOptions,
  nodeIdToDisplay
}: NodeCardProps) {
  const indentClass = depth === 0 ? '' : depth === 1 ? 'ml-6' : depth === 2 ? 'ml-12' : 'ml-18'
  
  // Use global numbering if available, otherwise fall back to local index
  const displayNumber = globalNodeNumber !== null ? globalNodeNumber : (index !== undefined ? index + 1 : null)
  const displayLabel = displayNumber !== null ? `${label} ${displayNumber}` : label
  
  // Different backgrounds for nodes with children to show containment
  const hasChildren = !!children
  const bgClass = hasChildren 
    ? (depth === 0 ? 'bg-blue-50' : depth === 1 ? 'bg-teal-50' : depth === 2 ? 'bg-gray-50' : 'bg-green-50')
    : 'bg-white'
  
  // Create unique ID using context to support reused nodes
  const nodeId = contextId ? `node-${contextId}-${node.temp_id}` : `node-${node.temp_id}`
  
  return (
    <div id={nodeId} className={`${bgClass} rounded-lg border border-gray-300 p-4 shadow-sm ${indentClass}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="text-sm font-semibold text-gray-900">{displayLabel}</div>
          {isReused && <ReusedNodeIcon />}
          {badge}
        </div>
        <div className="flex items-center gap-2">
          {statusBadge}
          {!isViewMode && (
            <NodeActionMenu 
              nodeId={node.temp_id}
              parentId={parentId}
              showUnlink={shouldShowUnlink}
              parentLabel={parentLabel}
              onDelete={onDelete}
              onUnlink={onUnlink}
            />
          )}
        </div>
      </div>
      <ObjectFields 
        obj={node.properties || {}} 
        path={['nodes', node.temp_id, 'properties']} 
        isViewMode={isViewMode}
        graphState={graphState}
        schema={schema}
        setPendingEdit={setPendingEdit}
        setValueAtPath={setValueAtPath}
        pendingEditsRef={pendingEditsRef}
        pendingEditsVersion={pendingEditsVersion}
        nodeOptions={nodeOptions}
        nodeIdToDisplay={nodeIdToDisplay}
      />
      {children}
    </div>
  )
}

