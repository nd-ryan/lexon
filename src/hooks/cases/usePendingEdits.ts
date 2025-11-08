/**
 * Hook for managing pending edits with debouncing
 * Allows fast typing without triggering full re-renders
 */

import { useCallback, useRef } from 'react'
import { useAppStore } from '@/lib/store/appStore'

export function usePendingEdits() {
  const pendingEditsRef = useRef<Record<string, any>>({})
  const versionTimerRef = useRef<NodeJS.Timeout | null>(null)
  const incrementVersion = useAppStore(s => s.incrementPendingEditsVersion)
  
  // Store pending edit without triggering re-render (fast!)
  const setPendingEdit = useCallback((path: (string|number)[], value: any) => {
    // Path format: ['nodes', temp_id, 'properties', 'propName']
    const key = path.join('.')
    pendingEditsRef.current[key] = value
    
    // Debounce version increment to batch updates for reused nodes
    // This allows typing without lag while still syncing across instances
    if (versionTimerRef.current) {
      clearTimeout(versionTimerRef.current)
    }
    versionTimerRef.current = setTimeout(() => {
      incrementVersion() // Increment in global store
    }, 300) // 300ms debounce
    
    return true // Indicates change was made
  }, [incrementVersion])
  
  // Get value with pending edits applied (check edits first, then graphState)
  const getValueWithEdits = useCallback((path: (string|number)[], graphState: any) => {
    const key = path.join('.')
    if (key in pendingEditsRef.current) {
      return pendingEditsRef.current[key]
    }
    
    // Fall back to graphState
    if (path[0] === 'nodes' && typeof path[1] === 'string') {
      const nodeId = path[1]
      const node = graphState.nodes.find((n: any) => n.temp_id === nodeId)
      if (!node) return undefined
      
      let cursor: any = node
      for (let i = 2; i < path.length; i++) {
        cursor = cursor?.[path[i]]
        if (cursor === undefined) return undefined
      }
      return cursor
    }
    return undefined
  }, [])
  
  const clearPendingEdits = useCallback(() => {
    pendingEditsRef.current = {}
    if (versionTimerRef.current) {
      clearTimeout(versionTimerRef.current)
      versionTimerRef.current = null
    }
  }, [])
  
  return {
    pendingEditsRef,
    setPendingEdit,
    getValueWithEdits,
    clearPendingEdits,
    versionTimerRef
  }
}

