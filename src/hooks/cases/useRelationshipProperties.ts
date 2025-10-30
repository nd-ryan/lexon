/**
 * Hook for managing relationship edge properties
 */

import { useCallback } from 'react'
import type { GraphState } from './useGraphState'

export function useRelationshipProperties(
  graphState: GraphState,
  setGraphState: (updater: (prev: GraphState) => GraphState) => void,
  setHasUnsavedChanges: (value: boolean) => void
) {
  // Get argument status from EVALUATED_IN edge
  const getArgumentStatus = useCallback((argumentId: string, rulingId: string): string | null => {
    const edge = graphState.edges.find(
      (e: any) => e.from === argumentId && e.to === rulingId && e.label === 'EVALUATED_IN' && e.status === 'active'
    )
    return edge?.properties?.status || null
  }, [graphState])

  // Update argument status on EVALUATED_IN edge
  const setArgumentStatus = useCallback((argumentId: string, rulingId: string, status: string) => {
    setGraphState(prev => ({
      ...prev,
      edges: prev.edges.map(e => {
        if (e.from === argumentId && e.to === rulingId && e.label === 'EVALUATED_IN') {
          return {
            ...e,
            properties: { ...e.properties, status }
          }
        }
        return e
      })
    }))
    setHasUnsavedChanges(true)
  }, [setGraphState, setHasUnsavedChanges])

  // Get INVOLVES role property
  const getPartyRole = useCallback((proceedingId: string, partyId: string): string | null => {
    const edge = graphState.edges.find(
      (e: any) => e.from === proceedingId && e.to === partyId && e.label === 'INVOLVES' && e.status === 'active'
    )
    return edge?.properties?.role || null
  }, [graphState])

  // Set INVOLVES role property
  const setPartyRole = useCallback((proceedingId: string, partyId: string, role: string) => {
    setGraphState(prev => ({
      ...prev,
      edges: prev.edges.map(e => {
        if (e.from === proceedingId && e.to === partyId && e.label === 'INVOLVES') {
          return { ...e, properties: { ...e.properties, role } }
        }
        return e
      })
    }))
    setHasUnsavedChanges(true)
  }, [setGraphState, setHasUnsavedChanges])

  // Get SETS in_favor property
  const getRulingInFavor = useCallback((rulingId: string, issueId: string): string | null => {
    const edge = graphState.edges.find(
      (e: any) => e.from === rulingId && e.to === issueId && e.label === 'SETS' && e.status === 'active'
    )
    return edge?.properties?.in_favor || null
  }, [graphState])

  // Set SETS in_favor property
  const setRulingInFavor = useCallback((rulingId: string, issueId: string, inFavor: string) => {
    setGraphState(prev => ({
      ...prev,
      edges: prev.edges.map(e => {
        if (e.from === rulingId && e.to === issueId && e.label === 'SETS') {
          return { ...e, properties: { ...e.properties, in_favor: inFavor } }
        }
        return e
      })
    }))
    setHasUnsavedChanges(true)
  }, [setGraphState, setHasUnsavedChanges])

  // Get RESULTS_IN relief_status property
  const getReliefStatus = useCallback((rulingId: string, reliefId: string): string | null => {
    const edge = graphState.edges.find(
      (e: any) => e.from === rulingId && e.to === reliefId && e.label === 'RESULTS_IN' && e.status === 'active'
    )
    return edge?.properties?.relief_status || null
  }, [graphState])

  // Set RESULTS_IN relief_status property
  const setReliefStatus = useCallback((rulingId: string, reliefId: string, status: string) => {
    setGraphState(prev => ({
      ...prev,
      edges: prev.edges.map(e => {
        if (e.from === rulingId && e.to === reliefId && e.label === 'RESULTS_IN') {
          return { ...e, properties: { ...e.properties, relief_status: status } }
        }
        return e
      })
    }))
    setHasUnsavedChanges(true)
  }, [setGraphState, setHasUnsavedChanges])

  return {
    getArgumentStatus,
    setArgumentStatus,
    getPartyRole,
    setPartyRole,
    getRulingInFavor,
    setRulingInFavor,
    getReliefStatus,
    setReliefStatus
  }
}

