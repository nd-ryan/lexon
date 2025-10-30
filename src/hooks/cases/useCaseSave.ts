/**
 * Hook for saving case data
 */

import { useState } from 'react'
import type { GraphState } from './useGraphState'

export function useCaseSave(
  id: string,
  graphState: GraphState,
  pendingEditsRef: React.MutableRefObject<Record<string, any>>,
  versionTimerRef: React.MutableRefObject<NodeJS.Timeout | null>,
  setData: (data: any) => void,
  setDisplayData: (data: any) => void,
  setViewConfig: (config: any) => void,
  setGraphState: (updater: (prev: GraphState) => GraphState) => void
) {
  const [saving, setSaving] = useState(false)
  const [submittingKg, setSubmittingKg] = useState(false)
  const [error, setError] = useState('')

  const onSave = async () => {
    try {
      setSaving(true); setError('')
      
      // Apply pending edits to get current state with all changes
      const edits = pendingEditsRef.current
      const workingNodes = graphState.nodes.map(node => {
        let updated = node
        let hasChanges = false
        
        // Apply edits to this node
        Object.entries(edits).forEach(([key, value]) => {
          const parts = key.split('.')
          if (parts[0] === 'nodes' && parts[1] === node.temp_id) {
            if (!hasChanges) {
              updated = { ...node }
              hasChanges = true
            }
            
            // Navigate to the property and update it
            let cursor: any = updated
            for (let i = 2; i < parts.length - 1; i++) {
              const k = parts[i]
              cursor[k] = Array.isArray(cursor[k]) ? [...cursor[k]] : { ...cursor[k] }
              cursor = cursor[k]
            }
            const lastKey = parts[parts.length - 1]
            cursor[lastKey] = value
          }
        })
        
        return updated
      })
      
      // Determine which nodes should be permanently deleted
      const activeEdges = graphState.edges.filter(e => e.status === 'active')
      const nodesToDelete = new Set<string>()
      
      // Mark deleted nodes
      workingNodes.forEach(n => {
        if (n.status === 'deleted') {
          nodesToDelete.add(n.temp_id)
        }
      })
      
      // Mark orphaned nodes that have no active parents
      workingNodes.forEach(n => {
        if (n.status === 'orphaned') {
          const hasActiveParent = activeEdges.some(e => 
            e.to === n.temp_id && 
            !nodesToDelete.has(e.from) &&
            workingNodes.find(p => p.temp_id === e.from && p.status === 'active')
          )
          if (!hasActiveParent) {
            nodesToDelete.add(n.temp_id)
          }
        }
      })
      
      // Build final payload with only active nodes and edges
      const finalData = {
        nodes: workingNodes
          .filter(n => n.status === 'active')
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
          .map(({ status, source, ...node }) => node), // Strip metadata
        edges: graphState.edges
          .filter(e => 
            e.status === 'active' && 
            !nodesToDelete.has(e.from) && 
            !nodesToDelete.has(e.to)
          )
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
          .map(({ status, ...edge }) => edge) // Strip metadata
      }
      
      const res = await fetch(`/api/cases/${id}`, { 
        method: 'PUT', 
        headers: { 'Content-Type': 'application/json' }, 
        body: JSON.stringify(finalData) 
      })
      
      const d = await res.json()
      setData(d.case)
      
      // Refetch display data after save for updated viewConfig and structured data
      const displayRes = await fetch(`/api/cases/${id}/display`)
      const display = await displayRes.json()
      setViewConfig(display.success ? display.viewConfig : null)
      if (display.success && display.data) {
        setDisplayData(display.data)
      }
      
      // Rebuild unified state from fresh raw data
      const extracted = d.case?.extracted || { nodes: [], edges: [] }
      
      setGraphState(() => ({
        nodes: extracted.nodes.map((n: any) => ({ 
          ...n, 
          status: 'active' as const, 
          source: 'initial' as const 
        })),
        edges: extracted.edges.map((e: any) => ({ 
          ...e, 
          status: 'active' as const 
        }))
      }))
      
      // Clear pending edits and debounce timer after successful save
      pendingEditsRef.current = {}
      if (versionTimerRef.current) {
        clearTimeout(versionTimerRef.current)
        versionTimerRef.current = null
      }
      
      return true
    } catch (e: any) {
      setError(e?.message || 'Failed to save')
      return false
    } finally {
      setSaving(false)
    }
  }

  const submitToKg = async () => {
    try {
      setSubmittingKg(true)
      // Ensure latest changes are saved first
      await onSave()
      // Call secure API to trigger backend KG flow with case id
      const res = await fetch('/api/kg/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id })
      })
      if (!res.ok) {
        const txt = await res.text()
        throw new Error(txt || 'Failed to submit to KG')
      }
    } catch (e: any) {
      setError(e?.message || 'Submit to KG failed')
    } finally {
      setSubmittingKg(false)
    }
  }

  return {
    saving,
    submittingKg,
    error,
    setError,
    onSave,
    submitToKg
  }
}

