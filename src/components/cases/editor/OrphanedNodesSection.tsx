/**
 * Section displaying orphaned nodes that will be deleted on save
 */

import { formatLabel, pickNodeName } from '@/lib/cases/formatting'
import { getNodeConnections } from '@/lib/cases/graphHelpers'

interface OrphanedNodesSectionProps {
  orphanedNodes: any[]
  graphState: any
}

export function OrphanedNodesSection({ orphanedNodes, graphState }: OrphanedNodesSectionProps) {
  // Filter out special node types handled by dedicated selectors (e.g., ReliefType)
  const EXCLUDED_NODE_TYPES = new Set(['ReliefType'])
  const displayedOrphanedNodes = orphanedNodes.filter((n: any) => !EXCLUDED_NODE_TYPES.has(n?.label))
  
  if (displayedOrphanedNodes.length === 0) return null

  return (
    <div className="mt-8 border-t-4 border-red-200 pt-6">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-red-700">
          Orphaned Nodes ({displayedOrphanedNodes.length})
        </h2>
        <p className="text-xs text-gray-600 mt-1">
          These nodes were disconnected when their parent was deleted. They will be permanently deleted when you save unless you reassign them.
        </p>
        <p className="text-xs text-gray-600 mt-1">
          To keep a node, use the Add buttons above to connect it to an appropriate parent (you can add new or select an existing node in the modal).
        </p>
      </div>
      
      <div className="space-y-3">
        {displayedOrphanedNodes.map((node: any) => {
          const nodeLabel = node.label || 'Unknown'
          const nodeName = pickNodeName(node) || node.temp_id
          const { outgoing, incoming } = getNodeConnections(node.temp_id, graphState)
          
          return (
            <div key={node.temp_id} className="bg-red-50 border border-red-200 rounded-lg p-4">
              <div className="flex items-start justify-between mb-2">
                <div>
                  <div className="text-sm font-semibold text-gray-900">
                    [{nodeLabel}] {nodeName}
                  </div>
                  <div className="text-xs text-gray-600 mt-1">
                    {incoming.length} incoming · {outgoing.length} outgoing connections
                  </div>
                </div>
              </div>
              
              {/* Show a preview of properties */}
              <div className="mt-2 text-xs text-gray-700">
                {Object.entries(node.properties || {}).slice(0, 2).map(([key, value]) => (
                  <div key={key} className="truncate">
                    <span className="font-medium">{formatLabel(key)}:</span> {String(value).slice(0, 100)}
                  </div>
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

