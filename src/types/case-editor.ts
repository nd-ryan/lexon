import { GraphNode, GraphEdge } from './case-graph'

// Node statuses
export type NodeStatus = 'active' | 'deleted' | 'orphaned'
export type NodeSource = 'initial' | 'user-created'

// Edge status
export type EdgeStatus = 'active' | 'deleted'

// Extended node with status
export interface NodeLike extends GraphNode {
  status: NodeStatus
  source: NodeSource
}

// Extended edge with status
export interface EdgeLike extends GraphEdge {
  status: EdgeStatus
  properties?: Record<string, any>
}

// Graph state
export interface GraphState {
  nodes: NodeLike[]
  edges: EdgeLike[]
}

// Pending edits
export interface PendingEdit {
  path: (string | number)[]
  value: any
  timestamp: number
}

export interface PendingEditsMap {
  [key: string]: PendingEdit
}

// Modal context types
export interface ModalContext {
  parentId?: string
  relationship: string
  direction: 'outgoing' | 'incoming'
}

// Node option for dropdowns
export interface NodeOption {
  id: string
  display: string
  label: string
}

// View config structure
export interface ViewConfig {
  topLevel?: Record<string, any>
  description?: string
  [key: string]: any
}

// Structure info extracted from view config
export interface StructureInfo {
  key: string | null
  rootLabel: string | null
  structure: Record<string, any>
}

// Relationship state from analyzeRelationship
export interface RelationshipState {
  canAdd: boolean
  canSelect: boolean
  targetLabel: string
  relationship: string
  direction: 'outgoing' | 'incoming'
  message?: string
}

// Relationship properties interface
export interface RelationshipProperties {
  getRulingInFavor: (rulingId: string, issueId: string) => string | null
  setRulingInFavor: (rulingId: string, issueId: string, value: string) => void
  getReliefStatus: (rulingId: string, reliefId: string) => string | null
  setReliefStatus: (rulingId: string, reliefId: string, value: string) => void
  getArgumentStatus: (argumentId: string, rulingId: string) => string | null
  setArgumentStatus: (argumentId: string, rulingId: string, value: string) => void
  getPartyRole: (proceedingId: string, partyId: string) => string | null
  setPartyRole: (proceedingId: string, partyId: string, value: string) => void
}

// Node lookup maps
export interface NodeLookups {
  edgesByFrom: Map<string, EdgeLike[]>
  edgesByTo: Map<string, EdgeLike[]>
  nodeById: Map<string, NodeLike>
  reliefTypeByReliefId: Record<string, NodeLike>
  forumAndJurisdictionByProceedingId: Record<string, { forum: NodeLike; jurisdiction: NodeLike | null }>
  getLiveReliefType: (reliefId: string) => NodeLike | null
  getLiveForumAndJurisdiction: (proceedingId: string) => { forum: NodeLike | null; jurisdiction: NodeLike | null }
}

// Global node numbering
export interface GlobalNodeNumbering {
  [nodeLabel: string]: {
    [nodeId: string]: number
  }
}

// Display data structure from backend
export interface DisplayData {
  [key: string]: any
}

// Catalog nodes by type
export interface CatalogNodes {
  [nodeType: string]: NodeLike[]
}

// Node card render options
export interface NodeCardOptions {
  index?: number
  depth?: number
  badge?: React.ReactNode
  statusBadge?: React.ReactNode
  children?: React.ReactNode
  parentId?: string
  contextId?: string
}

// Modal submission types
export interface AddNodeSubmission {
  node: NodeLike
  edges: EdgeLike[]
}

export interface ParentContext {
  parentId: string
  parentLabel: string
  relationship: string
  direction: 'outgoing' | 'incoming'
}

