import { renderHook, act } from '@testing-library/react'
import { useUIState } from './useUIState'
import { ModalContext } from '@/types/case-editor'

const context: ModalContext = {
  relationship: 'RELATES_TO',
  direction: 'outgoing'
}

describe('useUIState', () => {
  it('initializes with expected defaults', () => {
    const { result } = renderHook(() => useUIState())
    const { uiState } = result.current

    expect(uiState.addModal.open).toBe(false)
    expect(uiState.selectModal.open).toBe(false)
    expect(uiState.editRelationship.edgeIdx).toBeNull()
    expect(uiState.expandedFacts instanceof Set).toBe(true)
    expect(uiState.expandedFacts.size).toBe(0)
  })

  it('opens and closes the add modal', () => {
    const { result } = renderHook(() => useUIState())

    act(() => result.current.uiActions.openAddModal('Person', context))
    expect(result.current.uiState.addModal).toEqual({
      open: true,
      type: 'Person',
      context
    })

    act(() => result.current.uiActions.closeAddModal())
    expect(result.current.uiState.addModal.open).toBe(false)
  })

  it('tracks edit relationship state and toggles facts', () => {
    const { result } = renderHook(() => useUIState())

    act(() => result.current.uiActions.startEditRelationship(2, 'target-1'))
    expect(result.current.uiState.editRelationship).toEqual({
      edgeIdx: 2,
      toValue: 'target-1'
    })

    act(() => result.current.uiActions.updateEditToValue('target-2'))
    expect(result.current.uiState.editRelationship.toValue).toBe('target-2')

    act(() => result.current.uiActions.toggleFact('fact-1'))
    expect(result.current.uiState.expandedFacts.has('fact-1')).toBe(true)

    act(() => result.current.uiActions.toggleFact('fact-1'))
    expect(result.current.uiState.expandedFacts.has('fact-1')).toBe(false)
  })
})
