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
  kgDiverged: boolean
  error?: string
  kgEmbeddingWarning?: {
    missing: number
    total: number
    details: string[]
  } | null
  onSave: () => void
  onSubmitToKg: () => void
  onDismissEmbeddingWarning?: () => void
  onBack: () => void
}

export function CaseFooter({
  isViewMode,
  hasUnsavedChanges,
  orphanedNodesCount,
  scrollHistory,
  saving,
  submittingKg,
  kgDiverged,
  error,
  kgEmbeddingWarning,
  onSave,
  onSubmitToKg,
  onDismissEmbeddingWarning,
  onBack
}: CaseFooterProps) {
  return (
    <div className="sticky bottom-0 z-10 border-t bg-white/80 backdrop-blur">
      {/* Embedding Warning Banner */}
      {kgEmbeddingWarning && kgEmbeddingWarning.missing > 0 && (
        <div className="bg-amber-50 border-b border-amber-200 px-6 py-3">
          <div className="mx-auto max-w-6xl flex items-center justify-between">
            <div className="flex items-center gap-3">
              <svg className="w-5 h-5 text-amber-600 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
              </svg>
              <div className="text-sm text-amber-800">
                <span className="font-semibold">KG uploaded with missing embeddings: </span>
                <span>{kgEmbeddingWarning.missing} of {kgEmbeddingWarning.total} embeddings missing. </span>
                <span className="text-amber-700">Click &quot;Submit to KG&quot; again to retry embedding generation.</span>
              </div>
            </div>
            {onDismissEmbeddingWarning && (
              <button 
                onClick={onDismissEmbeddingWarning}
                className="text-amber-600 hover:text-amber-800 p-1"
                aria-label="Dismiss warning"
              >
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                </svg>
              </button>
            )}
          </div>
        </div>
      )}
      
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
              {error && (
                <div className="flex items-center gap-2 text-red-600 text-sm">
                  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                  </svg>
                  <span className="font-medium">{error}</span>
                </div>
              )}
              {!error && hasUnsavedChanges && (
                <div className="flex items-center gap-2 text-amber-600 text-sm">
                  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                  </svg>
                  <span className="font-medium">Unsaved changes</span>
                </div>
              )}
              {!error && orphanedNodesCount > 0 && (
                <div className="flex items-center gap-2 text-red-600 text-sm">
                  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                  </svg>
                  <span className="font-medium">{orphanedNodesCount} orphaned node{orphanedNodesCount !== 1 ? 's' : ''} will be deleted</span>
                </div>
              )}
              {!error && !hasUnsavedChanges && kgDiverged && (
                <div className="flex items-center gap-2 text-blue-600 text-sm">
                  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
                  </svg>
                  <span className="font-medium">KG out of date</span>
                </div>
              )}
              <Button onClick={onSave} disabled={saving || submittingKg}>{saving ? 'Saving...' : 'Save'}</Button>
              <Button 
                onClick={onSubmitToKg} 
                disabled={saving || submittingKg || hasUnsavedChanges}
                className={kgDiverged && !hasUnsavedChanges ? 'ring-2 ring-blue-500 ring-offset-2' : ''}
              >
                {submittingKg ? 'Submitting…' : 'Submit to KG'}
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

