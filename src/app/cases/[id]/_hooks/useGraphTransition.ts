import { useTransition, useCallback } from 'react'

/**
 * Hook to handle graph state updates with React transitions.
 * Provides a consistent pattern for non-blocking state updates that mark unsaved changes.
 */
export function useGraphTransition(
  setGraphState: (updater: (prev: any) => any) => void,
  setHasUnsavedChanges: (value: boolean) => void
) {
  const [, startTransition] = useTransition()
  
  /**
   * Update graph state with a non-blocking transition.
   * Automatically marks changes as unsaved.
   */
  const updateGraph = useCallback((updater: (prev: any) => any) => {
    // Mark unsaved changes immediately
    setHasUnsavedChanges(true)
    
    // Use transition to make the state update non-blocking
    startTransition(() => {
      setGraphState(updater)
    })
  }, [setGraphState, setHasUnsavedChanges, startTransition])
  
  return { updateGraph }
}

