/**
 * Footer with save buttons and status indicators
 */

import Button from '@/components/ui/button'

interface CaseFooterProps {
  isViewMode: boolean
  hasUnsavedChanges: boolean
  orphanedNodesCount: number
  scrollHistory: number[]
  saving: boolean
  submittingKg: boolean
  onSave: () => void
  onSubmitToKg: () => void
  onBack: () => void
}

export function CaseFooter({
  isViewMode,
  hasUnsavedChanges,
  orphanedNodesCount,
  scrollHistory,
  saving,
  submittingKg,
  onSave,
  onSubmitToKg,
  onBack
}: CaseFooterProps) {
  return (
    <div className="sticky bottom-0 z-10 border-t bg-white/80 backdrop-blur">
      <div className="mx-auto max-w-6xl px-6 py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {scrollHistory.length > 0 && (
              <Button
                variant="outline"
                onClick={onBack}
              >
                Back
              </Button>
            )}
          </div>
          {!isViewMode && (
            <div className="flex items-center gap-3">
              {hasUnsavedChanges && (
                <div className="flex items-center gap-2 text-amber-600 text-sm">
                  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                  </svg>
                  <span className="font-medium">Unsaved changes</span>
                </div>
              )}
              {orphanedNodesCount > 0 && (
                <div className="flex items-center gap-2 text-red-600 text-sm">
                  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                  </svg>
                  <span className="font-medium">{orphanedNodesCount} orphaned node{orphanedNodesCount !== 1 ? 's' : ''} will be deleted</span>
                </div>
              )}
              <Button onClick={onSave} disabled={saving || submittingKg}>{saving ? 'Saving...' : 'Save'}</Button>
              <Button onClick={onSubmitToKg} disabled={saving || submittingKg}>
                {submittingKg ? 'Submitting…' : 'Submit to KG'}
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

