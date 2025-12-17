/**
 * Confirmation modal for deleting a node with cascade plan display
 */

import { HoverTooltip } from '@/components/ui/HoverTooltip'
import type { CascadePlan, CascadeValidation } from '@/lib/cases/cascadeDelete'

interface DeleteNodeConfirmationProps {
  /** The cascade plan (null if no node selected) */
  cascadePlan: CascadePlan | null
  /** Validation result for min_per_case check */
  validation: CascadeValidation
  /** Called when user cancels */
  onCancel: () => void
  /** Called when user confirms deletion */
  onConfirm: () => void
}

export function DeleteNodeConfirmation({
  cascadePlan,
  validation,
  onCancel,
  onConfirm
}: DeleteNodeConfirmationProps) {
  if (!cascadePlan) return null

  const { primaryNode, toDelete, toDetachOnly, edgesToRemove } = cascadePlan
  const disabledReason = validation.valid ? null : validation.reason

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ position: 'fixed', inset: 0, zIndex: 10000 }}>
      <div className="absolute inset-0 bg-black/50" onClick={onCancel} />
      <div className="relative z-50 w-full max-w-md mx-4 rounded-lg border bg-white p-4 shadow-xl max-h-[90vh] overflow-y-auto">
        <div className="font-semibold mb-2 text-red-600">Delete Node?</div>
        <div className="text-sm text-gray-700 mb-2">
          Are you sure you want to delete <span className="font-medium">{primaryNode.label}: {primaryNode.name}</span>?
        </div>
        <div className="text-xs text-gray-600 mb-2">
          This will remove {edgesToRemove.length} connection{edgesToRemove.length !== 1 ? 's' : ''}.
        </div>
        
        {/* Cascade deletions - nodes that will be removed from this case */}
        {toDelete.length > 0 && (
          <div className="text-xs bg-red-50 border border-red-200 rounded px-2 py-1.5 mb-2">
            <div className="font-semibold text-red-800 mb-1">
              {toDelete.length} item{toDelete.length !== 1 ? 's' : ''} will also be removed:
            </div>
            <div className="ml-2 space-y-0.5 max-h-48 overflow-y-auto">
              {toDelete.map((node) => (
                <div key={node.nodeId} className="text-red-700">
                  • [{node.label}] {String(node.name).slice(0, 50)}
                  {!node.caseUnique && <span className="text-red-500 text-[10px] ml-1">(shared)</span>}
                </div>
              ))}
            </div>
            <div className="mt-1 text-red-600 text-[10px]">
              Items marked (shared) will be preserved in the knowledge graph.
            </div>
          </div>
        )}
        
        {/* Detach-only nodes - nodes that have other parents and will just have their edge removed */}
        {toDetachOnly.length > 0 && (
          <div className="text-xs bg-blue-50 border border-blue-200 rounded px-2 py-1.5 mb-2">
            <div className="font-semibold text-blue-800 mb-1">
              {toDetachOnly.length} item{toDetachOnly.length !== 1 ? 's' : ''} will be unlinked (used elsewhere):
            </div>
            <div className="ml-2 space-y-0.5 max-h-48 overflow-y-auto">
              {toDetachOnly.map((node) => (
                <div key={node.nodeId} className="text-blue-700">
                  • [{node.label}] {String(node.name).slice(0, 50)}
                </div>
              ))}
            </div>
            <div className="mt-1 text-blue-600 text-[10px]">
              These items have other connections in this case and will remain visible.
            </div>
          </div>
        )}
        
        <div className="text-xs text-gray-600 bg-gray-50 border border-gray-200 rounded px-2 py-1.5 mb-4">
          <strong>Note:</strong> The deletion will be persisted when you save the case.
        </div>
        
        {/* min_per_case violation warning */}
        {disabledReason && (
          <div className="text-xs bg-red-50 border border-red-200 rounded px-2 py-1.5 mb-4 text-red-800">
            <strong>Cannot delete:</strong> {disabledReason}
          </div>
        )}
        
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
              onClick={onConfirm}
            >
              Delete Node
            </button>
          </HoverTooltip>
        </div>
      </div>
    </div>
  )
}
