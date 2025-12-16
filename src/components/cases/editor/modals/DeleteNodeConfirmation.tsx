/**
 * Confirmation modal for deleting a node
 */

import { pickNodeName } from '@/lib/cases/formatting'
import { findDescendants } from '@/lib/cases/graphHelpers'
import { HoverTooltip } from '@/components/ui/HoverTooltip'

interface DeleteNodeConfirmationProps {
  nodeId: string | null
  graphState: any
  disabledReason?: string | null
  onCancel: () => void
  onConfirm: (nodeId: string) => void
}

export function DeleteNodeConfirmation({
  nodeId,
  graphState,
  disabledReason,
  onCancel,
  onConfirm
}: DeleteNodeConfirmationProps) {
  if (!nodeId) return null

  const node = graphState.nodes.find((n: any) => n.temp_id === nodeId)
  if (!node) return null

  const nodeLabel = node.label || 'Node'
  const nodeName = pickNodeName(node) || nodeId
  const activeEdges = graphState.edges.filter((e: any) => e.status === 'active')
  const totalConnections = activeEdges.filter((e: any) => e.from === nodeId || e.to === nodeId).length
  
  // Find all descendants that will be orphaned
  const edges = graphState.edges.filter((e: any) => e.status === 'active')
  const descendants = findDescendants(nodeId, edges)
  const descendantNodes = descendants.map((id: string) => {
    const n = graphState.nodes.find((node: any) => node.temp_id === id)
    return n ? { id, label: n.label || 'Node', name: pickNodeName(n) || id } : null
  }).filter(Boolean)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ position: 'fixed', inset: 0, zIndex: 10000 }}>
      <div className="absolute inset-0 bg-black/50" onClick={onCancel} />
      <div className="relative z-50 w-full max-w-md mx-4 rounded-lg border bg-white p-4 shadow-xl">
        <div className="font-semibold mb-2 text-red-600">Delete Node?</div>
        <div className="text-sm text-gray-700 mb-2">
          Are you sure you want to delete <span className="font-medium">{nodeLabel}: {nodeName}</span>?
        </div>
        <div className="text-xs text-gray-600 mb-2">
          This will delete {totalConnections} connection{totalConnections !== 1 ? 's' : ''}.
        </div>
        {descendantNodes.length > 0 && (
          <div className="text-xs bg-amber-50 border border-amber-200 rounded px-2 py-1.5 mb-2">
            <div className="font-semibold text-amber-800 mb-1">
              {descendantNodes.length} child node{descendantNodes.length !== 1 ? 's' : ''} will be orphaned:
            </div>
            <div className="ml-2 space-y-0.5 max-h-24 overflow-y-auto">
              {descendantNodes.slice(0, 5).map((desc: any) => (
                <div key={desc.id} className="text-amber-700">
                  • [{desc.label}] {String(desc.name).slice(0, 40)}
                </div>
              ))}
              {descendantNodes.length > 5 && (
                <div className="text-amber-700 italic">... and {descendantNodes.length - 5} more</div>
              )}
            </div>
            <div className="mt-1 text-amber-700">
              These nodes will be available for reassignment before saving.
            </div>
          </div>
        )}
        <div className="text-xs text-gray-600 bg-gray-50 border border-gray-200 rounded px-2 py-1.5 mb-4">
          <strong>Note:</strong> The deletion will be persisted when you save the case.
        </div>
        {disabledReason ? (
          <div className="text-xs bg-red-50 border border-red-200 rounded px-2 py-1.5 mb-4 text-red-800">
            <strong>Cannot delete:</strong> {disabledReason}
          </div>
        ) : null}
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            className="rounded border px-3 py-1.5 text-sm cursor-pointer"
            onClick={onCancel}
          >
            Cancel
          </button>
          <HoverTooltip text={disabledReason} side="top" className="inline-flex">
            <button
              type="button"
              disabled={Boolean(disabledReason)}
              className={`rounded px-3 py-1.5 text-sm transition-colors ${
                disabledReason
                  ? 'bg-gray-300 text-gray-700 cursor-not-allowed'
                  : 'bg-red-600 text-white hover:bg-red-700 cursor-pointer'
              }`}
              onClick={() => onConfirm(nodeId)}
            >
              Delete Node
            </button>
          </HoverTooltip>
        </div>
      </div>
    </div>
  )
}

