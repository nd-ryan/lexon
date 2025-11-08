import { useReducer, useCallback } from 'react'
import { ModalContext } from '@/types/case-editor'

// UI State type
export interface UIState {
  // Modal states
  addModal: {
    open: boolean
    type: string
    context: ModalContext | null
  }
  selectModal: {
    open: boolean
    type: string
    context: ModalContext | null
  }
  editRelationship: {
    edgeIdx: number | null
    toValue: string
  }
  confirmDelete: {
    edgeIdx: number | null
  }
  deletingNode: {
    nodeId: string | null
  }
  
  // Active/scroll states
  activeHoldingId: string | null
  activeNodeId: string | null
  activeNodeContext: string | null
  scrollHistory: number[]
  expandedFacts: Set<string>
  
  // UI flags
  partiesExpanded: boolean
  partiesSectionExpanded: boolean
}

// Action types
type UIAction =
  | { type: 'OPEN_ADD_MODAL'; payload: { nodeType: string; context: ModalContext } }
  | { type: 'CLOSE_ADD_MODAL' }
  | { type: 'OPEN_SELECT_MODAL'; payload: { nodeType: string; context: ModalContext } }
  | { type: 'CLOSE_SELECT_MODAL' }
  | { type: 'START_EDIT_RELATIONSHIP'; payload: { edgeIdx: number; toValue: string } }
  | { type: 'CANCEL_EDIT_RELATIONSHIP' }
  | { type: 'UPDATE_EDIT_TO_VALUE'; payload: string }
  | { type: 'START_CONFIRM_DELETE'; payload: number }
  | { type: 'CANCEL_CONFIRM_DELETE' }
  | { type: 'START_DELETE_NODE'; payload: string }
  | { type: 'CANCEL_DELETE_NODE' }
  | { type: 'SET_ACTIVE_HOLDING'; payload: string | null }
  | { type: 'SET_ACTIVE_NODE'; payload: { nodeId: string | null; context: string | null } }
  | { type: 'PUSH_SCROLL_HISTORY'; payload: number }
  | { type: 'POP_SCROLL_HISTORY' }
  | { type: 'TOGGLE_FACT'; payload: string }
  | { type: 'SET_PARTIES_EXPANDED'; payload: boolean }
  | { type: 'SET_PARTIES_SECTION_EXPANDED'; payload: boolean }

// Initial state
const initialState: UIState = {
  addModal: {
    open: false,
    type: '',
    context: null
  },
  selectModal: {
    open: false,
    type: '',
    context: null
  },
  editRelationship: {
    edgeIdx: null,
    toValue: ''
  },
  confirmDelete: {
    edgeIdx: null
  },
  deletingNode: {
    nodeId: null
  },
  activeHoldingId: null,
  activeNodeId: null,
  activeNodeContext: null,
  scrollHistory: [],
  expandedFacts: new Set(),
  partiesExpanded: false,
  partiesSectionExpanded: false
}

// Reducer
function uiReducer(state: UIState, action: UIAction): UIState {
  switch (action.type) {
    case 'OPEN_ADD_MODAL':
      return {
        ...state,
        addModal: {
          open: true,
          type: action.payload.nodeType,
          context: action.payload.context
        }
      }
    
    case 'CLOSE_ADD_MODAL':
      return {
        ...state,
        addModal: {
          open: false,
          type: '',
          context: null
        }
      }
    
    case 'OPEN_SELECT_MODAL':
      return {
        ...state,
        selectModal: {
          open: true,
          type: action.payload.nodeType,
          context: action.payload.context
        }
      }
    
    case 'CLOSE_SELECT_MODAL':
      return {
        ...state,
        selectModal: {
          open: false,
          type: '',
          context: null
        }
      }
    
    case 'START_EDIT_RELATIONSHIP':
      return {
        ...state,
        editRelationship: {
          edgeIdx: action.payload.edgeIdx,
          toValue: action.payload.toValue
        }
      }
    
    case 'CANCEL_EDIT_RELATIONSHIP':
      return {
        ...state,
        editRelationship: {
          edgeIdx: null,
          toValue: ''
        }
      }
    
    case 'UPDATE_EDIT_TO_VALUE':
      return {
        ...state,
        editRelationship: {
          ...state.editRelationship,
          toValue: action.payload
        }
      }
    
    case 'START_CONFIRM_DELETE':
      return {
        ...state,
        confirmDelete: {
          edgeIdx: action.payload
        }
      }
    
    case 'CANCEL_CONFIRM_DELETE':
      return {
        ...state,
        confirmDelete: {
          edgeIdx: null
        }
      }
    
    case 'START_DELETE_NODE':
      return {
        ...state,
        deletingNode: {
          nodeId: action.payload
        }
      }
    
    case 'CANCEL_DELETE_NODE':
      return {
        ...state,
        deletingNode: {
          nodeId: null
        }
      }
    
    case 'SET_ACTIVE_HOLDING':
      return {
        ...state,
        activeHoldingId: action.payload
      }
    
    case 'SET_ACTIVE_NODE':
      return {
        ...state,
        activeNodeId: action.payload.nodeId,
        activeNodeContext: action.payload.context
      }
    
    case 'PUSH_SCROLL_HISTORY':
      return {
        ...state,
        scrollHistory: [...state.scrollHistory, action.payload]
      }
    
    case 'POP_SCROLL_HISTORY':
      return {
        ...state,
        scrollHistory: state.scrollHistory.slice(0, -1)
      }
    
    case 'TOGGLE_FACT': {
      const newExpandedFacts = new Set(state.expandedFacts)
      if (newExpandedFacts.has(action.payload)) {
        newExpandedFacts.delete(action.payload)
      } else {
        newExpandedFacts.add(action.payload)
      }
      return {
        ...state,
        expandedFacts: newExpandedFacts
      }
    }
    
    case 'SET_PARTIES_EXPANDED':
      return {
        ...state,
        partiesExpanded: action.payload
      }
    
    case 'SET_PARTIES_SECTION_EXPANDED':
      return {
        ...state,
        partiesSectionExpanded: action.payload
      }
    
    default:
      return state
  }
}

// Custom hook
export function useUIState() {
  const [state, dispatch] = useReducer(uiReducer, initialState)
  
  // Action creators for better API
  const actions = {
    openAddModal: useCallback((nodeType: string, context: ModalContext) => {
      dispatch({ type: 'OPEN_ADD_MODAL', payload: { nodeType, context } })
    }, []),
    
    closeAddModal: useCallback(() => {
      dispatch({ type: 'CLOSE_ADD_MODAL' })
    }, []),
    
    openSelectModal: useCallback((nodeType: string, context: ModalContext) => {
      dispatch({ type: 'OPEN_SELECT_MODAL', payload: { nodeType, context } })
    }, []),
    
    closeSelectModal: useCallback(() => {
      dispatch({ type: 'CLOSE_SELECT_MODAL' })
    }, []),
    
    startEditRelationship: useCallback((edgeIdx: number, toValue: string) => {
      dispatch({ type: 'START_EDIT_RELATIONSHIP', payload: { edgeIdx, toValue } })
    }, []),
    
    cancelEditRelationship: useCallback(() => {
      dispatch({ type: 'CANCEL_EDIT_RELATIONSHIP' })
    }, []),
    
    updateEditToValue: useCallback((value: string) => {
      dispatch({ type: 'UPDATE_EDIT_TO_VALUE', payload: value })
    }, []),
    
    startConfirmDelete: useCallback((edgeIdx: number) => {
      dispatch({ type: 'START_CONFIRM_DELETE', payload: edgeIdx })
    }, []),
    
    cancelConfirmDelete: useCallback(() => {
      dispatch({ type: 'CANCEL_CONFIRM_DELETE' })
    }, []),
    
    startDeleteNode: useCallback((nodeId: string) => {
      dispatch({ type: 'START_DELETE_NODE', payload: nodeId })
    }, []),
    
    cancelDeleteNode: useCallback(() => {
      dispatch({ type: 'CANCEL_DELETE_NODE' })
    }, []),
    
    setActiveHolding: useCallback((holdingId: string | null) => {
      dispatch({ type: 'SET_ACTIVE_HOLDING', payload: holdingId })
    }, []),
    
    setActiveNode: useCallback((nodeId: string | null, context: string | null) => {
      dispatch({ type: 'SET_ACTIVE_NODE', payload: { nodeId, context } })
    }, []),
    
    pushScrollHistory: useCallback((scrollY: number) => {
      dispatch({ type: 'PUSH_SCROLL_HISTORY', payload: scrollY })
    }, []),
    
    popScrollHistory: useCallback(() => {
      dispatch({ type: 'POP_SCROLL_HISTORY' })
    }, []),
    
    toggleFact: useCallback((factId: string) => {
      dispatch({ type: 'TOGGLE_FACT', payload: factId })
    }, []),
    
    setPartiesExpanded: useCallback((expanded: boolean) => {
      dispatch({ type: 'SET_PARTIES_EXPANDED', payload: expanded })
    }, []),
    
    setPartiesSectionExpanded: useCallback((expanded: boolean) => {
      dispatch({ type: 'SET_PARTIES_SECTION_EXPANDED', payload: expanded })
    }, [])
  }
  
  return { uiState: state, uiActions: actions }
}

