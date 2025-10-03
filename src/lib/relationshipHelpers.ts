/**
 * Helpers for analyzing relationships and determining what actions are available
 */

import type { Schema, GraphNode } from '@/types/case-graph'

export interface RelationshipState {
  key: string                    // e.g., "ruling", "arguments", "doctrines"
  relationshipLabel: string      // e.g., "SETS", "EVALUATED_IN"
  targetNodeType: string         // e.g., "Ruling", "Argument"
  cardinality: 'single' | 'multiple'
  canCreateNew: boolean          // from schema
  currentCount: number           // how many exist in data
  maxReached: boolean            // true if single and count >= 1
  exists: boolean                // true if currentCount > 0
  direction: 'outgoing' | 'incoming'
}

/**
 * Get can_create_new flag from schema for a node type
 */
export const getCanCreateNew = (nodeType: string, schema: Schema | null): boolean => {
  if (!schema) return true // Default to true if no schema
  const schemaArray = Array.isArray(schema) ? schema : []
  const schemaDef = schemaArray.find((s: any) => s?.label === nodeType)
  return schemaDef?.can_create_new ?? true
}

/**
 * Get cardinality from views.json structure config
 */
export const getCardinality = (config: any): 'single' | 'multiple' => {
  return config?.single === true ? 'single' : 'multiple'
}

/**
 * Get direction from views.json structure config
 */
export const getDirection = (config: any): 'outgoing' | 'incoming' => {
  return config?.direction === 'incoming' ? 'incoming' : 'outgoing'
}

/**
 * Analyze a relationship to determine its current state and available actions
 */
export const analyzeRelationship = (
  parentNode: any,
  structureKey: string,
  structureConfig: any,
  schema: Schema | null,
  currentData: any
): RelationshipState | null => {
  const config = structureConfig?.[structureKey]
  if (!config) return null
  
  const targetNodeType = config?.label || structureKey
  const cardinality = getCardinality(config)
  const canCreateNew = getCanCreateNew(targetNodeType, schema)
  const relationshipLabel = config?.via || ''
  const direction = getDirection(config)
  
  // Check current data
  const dataValue = currentData?.[structureKey]
  const currentCount = Array.isArray(dataValue) 
    ? dataValue.length 
    : (dataValue ? 1 : 0)
  
  return {
    key: structureKey,
    relationshipLabel,
    targetNodeType,
    cardinality,
    canCreateNew,
    currentCount,
    maxReached: cardinality === 'single' && currentCount >= 1,
    exists: currentCount > 0,
    direction
  }
}

/**
 * Format label for display (Case -> Case, holding -> Holding, etc.)
 */
export const formatLabel = (label: string): string => {
  if (!label) return ''
  if (label === 'root') return 'Case'
  const spaced = label
    .replace(/[_-]/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/\s+/g, ' ')
    .trim()
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

