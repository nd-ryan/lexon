/**
 * Validation utilities for case graph data
 */

import type { Schema, SchemaItem, SchemaPropertyDef } from '@/types/case-graph'
import type { GraphState } from '@/hooks/cases/useGraphState'
import { pickNodeName } from './formatting'

export interface ValidationError {
  nodeId?: string
  nodeLabel?: string
  propertyName: string
  propertyLabel?: string
  message: string
  edgeLabel?: string
  edgeFrom?: string
  edgeTo?: string
}

export interface ValidationResult {
  isValid: boolean
  errors: ValidationError[]
}

/**
 * Check if a value is empty (null, undefined, empty string, or empty array)
 * Also handles malformed object values like {citation: ''} by extracting nested value
 */
function isEmpty(value: any): boolean {
  if (value === null || value === undefined) return true
  if (typeof value === 'string' && !value.trim()) return true
  if (Array.isArray(value) && value.length === 0) return true
  
  // Handle malformed nested objects (e.g., {citation: ''} instead of '')
  // This can happen with data quality issues
  if (typeof value === 'object' && !Array.isArray(value)) {
    // If it's an object, check if it has any non-empty string values
    const values = Object.values(value)
    if (values.length === 0) return true
    
    // If all nested values are empty, treat the whole thing as empty
    return values.every(v => isEmpty(v))
  }
  
  return false
}

/**
 * Apply pending edits to a single node
 */
function applyPendingEditsToNode(node: any, pendingEdits: Record<string, any>): any {
  let updated = node
  let hasChanges = false
  
  Object.entries(pendingEdits).forEach(([key, value]) => {
    const parts = key.split('.')
    if (parts[0] === 'nodes' && parts[1] === node.temp_id) {
      if (!hasChanges) {
        updated = { ...node }
        hasChanges = true
      }
      
      let cursor: any = updated
      
      // Navigate to the nested property with proper null safety
      for (let i = 2; i < parts.length - 1; i++) {
        const k = parts[i]
        const current = cursor[k]
        
        // Create shallow copies or initialize if missing
        if (Array.isArray(current)) {
          cursor[k] = [...current]
        } else if (current && typeof current === 'object') {
          cursor[k] = { ...current }
        } else {
          cursor[k] = {}
        }
        cursor = cursor[k]
      }
      
      // Set the final property value
      const lastKey = parts[parts.length - 1]
      cursor[lastKey] = value
    }
  })
  
  return updated
}

/**
 * Get relationship definition from schema
 */
function getRelationshipDef(
  sourceLabel: string,
  relLabel: string,
  schema: Schema
): { target: string; properties?: Record<string, SchemaPropertyDef> } | null {
  const schemaItem = schema.find(item => item.label === sourceLabel)
  if (!schemaItem?.relationships) return null
  
  const relDef = schemaItem.relationships[relLabel]
  if (!relDef) return null
  
  // If it's just a string, return it wrapped as target
  if (typeof relDef === 'string') {
    return { target: relDef }
  }
  
  // If it's an object, return it (should have target and optional properties)
  if (typeof relDef === 'object' && relDef !== null) {
    return relDef as { target: string; properties?: Record<string, SchemaPropertyDef> }
  }
  
  return null
}

/**
 * Validate required fields in graph state
 * Applies pending edits before validation to check the actual state that will be saved
 */
export function validateRequiredFields(
  graphState: GraphState,
  schema: Schema | null,
  pendingEditsRef: React.MutableRefObject<Record<string, any>>
): ValidationResult {
  const errors: ValidationError[] = []
  
  if (!schema || schema.length === 0) {
    // Can't validate without schema, but don't block - might be loading
    return { isValid: true, errors: [] }
  }
  
  // Create schema lookup map for faster access
  const schemaByLabel = new Map<string, SchemaItem>()
  schema.forEach(item => {
    if (item.label) {
      schemaByLabel.set(item.label, item)
    }
  })
  
  // Apply pending edits to get current state with all changes
  const pendingEdits = pendingEditsRef.current
  const workingNodes = graphState.nodes.map(node => applyPendingEditsToNode(node, pendingEdits))
  
  // Validate active nodes only
  const activeNodes = workingNodes.filter(n => n.status === 'active')
  
  // Validate node properties
  activeNodes.forEach((node) => {
    const schemaItem = schemaByLabel.get(node.label)
    if (!schemaItem?.properties) return
    
    const nodeProps = node.properties || {}
    
    // Check each property in schema
    Object.entries(schemaItem.properties).forEach(([propName, propDef]) => {
      const ui = propDef.ui || {}
      
      // Skip hidden properties (upload codes, embeddings, etc.)
      if (ui.hidden) return
      
      // Check if required
      if (ui.required) {
        const value = nodeProps[propName]
        
        if (isEmpty(value)) {
          const nodeDisplayName = pickNodeName(node) || node.temp_id
          const fieldLabel = ui.label || propName
          errors.push({
            nodeId: node.temp_id,
            nodeLabel: node.label,
            propertyName: propName,
            propertyLabel: fieldLabel,
            message: `${node.label} "${nodeDisplayName}" requires "${fieldLabel}"`
          })
        }
      }
    })
  })
  
  // Validate relationship properties
  // Note: Relationship properties are updated directly in graphState.edges (not via pendingEdits)
  const activeEdges = graphState.edges.filter(e => e.status === 'active')
  
  activeEdges.forEach((edge) => {
    // Find source node to get its label
    const sourceNode = activeNodes.find(n => n.temp_id === edge.from)
    if (!sourceNode) return // Skip if source node not found
    
    // Get relationship definition from schema
    const relDef = getRelationshipDef(sourceNode.label, edge.label, schema)
    if (!relDef || !relDef.properties) return // No properties for this relationship
    
    const edgeProps = edge.properties || {}
    
    // Check required relationship properties
    Object.entries(relDef.properties).forEach(([propName, propDef]) => {
      const ui = propDef.ui || {}
      
      // Skip hidden properties
      if (ui.hidden) return
      
      // Check if required
      if (ui.required) {
        const value = edgeProps[propName]
        
        if (isEmpty(value)) {
          const fromNode = activeNodes.find(n => n.temp_id === edge.from)
          const toNode = activeNodes.find(n => n.temp_id === edge.to)
          const fromDisplayName = pickNodeName(fromNode) || edge.from
          const toDisplayName = pickNodeName(toNode) || edge.to
          const fieldLabel = ui.label || propName
          
          errors.push({
            edgeLabel: edge.label,
            edgeFrom: edge.from,
            edgeTo: edge.to,
            propertyName: propName,
            propertyLabel: fieldLabel,
            message: `Relationship "${edge.label}" from "${fromDisplayName}" to "${toDisplayName}" requires "${fieldLabel}"`
          })
        }
      }
    })
  })
  
  return {
    isValid: errors.length === 0,
    errors
  }
}

