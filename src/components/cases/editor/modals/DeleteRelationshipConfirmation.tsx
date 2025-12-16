/**
 * Confirmation modal for deleting a relationship
 */

interface DeleteRelationshipConfirmationProps {
  edgeIndex: number | null
  disabledReason?: string | null
  onCancel: () => void
  onConfirm: (edgeIndex: number) => void
}

export function DeleteRelationshipConfirmation({
  edgeIndex,
  disabledReason,
  onCancel,
  onConfirm
}: DeleteRelationshipConfirmationProps) {
  if (edgeIndex === null) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ position: 'fixed', inset: 0, zIndex: 9999 }}>
      <div className="absolute inset-0 bg-black/50" onClick={onCancel} />
      <div className="relative z-50 w-full max-w-md mx-4 rounded-lg border bg-white p-4 text-xs shadow-xl">
        <div className="font-semibold mb-2">Delete relationship?</div>
        <div className="text-xs text-gray-600">This action cannot be undone.</div>
        {disabledReason ? (
          <div className="mt-3 rounded border border-red-200 bg-red-50 px-2 py-1.5 text-red-800">
            <strong>Cannot delete:</strong> {disabledReason}
          </div>
        ) : null}
        <div className="mt-4 flex flex-wrap items-center justify-end gap-2">
          <button
            type="button"
            className="rounded border px-3 py-1 min-w-[84px] cursor-pointer"
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={Boolean(disabledReason)}
            className={`rounded px-3 py-1 min-w-[84px] transition-colors ${
              disabledReason
                ? 'bg-gray-300 text-gray-700 cursor-not-allowed'
                : '!bg-red-600 text-white hover:brightness-95 cursor-pointer'
            }`}
            onClick={() => onConfirm(edgeIndex)}
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  )
}

