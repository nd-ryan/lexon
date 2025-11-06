/**
 * Helper functions for working with nodes
 */

/**
 * Determines if a node is an existing node from the Neo4j catalog
 * The backend sets `is_existing: true` on nodes that come from the catalog
 */
export function isExistingNode(node: any): boolean {
  return node?.is_existing === true
}

