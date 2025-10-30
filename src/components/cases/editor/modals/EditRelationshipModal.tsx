/**
 * Modal for editing relationship destination
 */

interface EditRelationshipModalProps {
  edgeIndex: number | null
  editToValue: string
  nodeOptions: { id: string; display: string }[]
  onCancel: () => void
  onSave: (edgeIndex: number, newToValue: string) => void
  onEditToValueChange: (value: string) => void
}

export function EditRelationshipModal({
  edgeIndex,
  editToValue,
  nodeOptions,
  onCancel,
  onSave,
  onEditToValueChange
}: EditRelationshipModalProps) {
  if (edgeIndex === null) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ position: 'fixed', inset: 0, zIndex: 9999 }}>
      <div className="absolute inset-0 bg-black/50" onClick={onCancel} />
      <div className="relative z-50 w-full max-w-md mx-4 rounded-lg border bg-white p-4 text-xs shadow-xl">
        <div className="font-semibold mb-2">Edit relationship destination</div>
        <select
          className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-xs shadow-sm focus:border-gray-400 focus:outline-none"
          value={editToValue}
          onChange={e => onEditToValueChange(e.target.value)}
        >
          <option value="">Select node</option>
          {nodeOptions.map(opt => (
            <option key={opt.id} value={opt.id}>{opt.display}</option>
          ))}
        </select>
        <div className="mt-4 flex flex-wrap items-center justify-end gap-2">
          <button
            type="button"
            className="rounded border px-3 py-1 min-w-[84px] cursor-pointer"
            onClick={onCancel}
          >
            Cancel
          </button>
          <div
            className="rounded bg-blue-600 text-white text-center px-3 py-1 min-w-[84px] transition-colors hover:brightness-95 cursor-pointer"
            onClick={() => onSave(edgeIndex, editToValue)}
          >
            Save
          </div>
        </div>
      </div>
    </div>
  )
}

