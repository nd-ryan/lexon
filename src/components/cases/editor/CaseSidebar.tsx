/**
 * Sidebar navigation for case editor
 */

import { formatLabel, pickNodeName } from '@/lib/cases/formatting'
import { ReusedNodeIcon } from './ReusedNodeIcon'

interface CaseSidebarProps {
  isViewMode: boolean
  setIsViewMode: (mode: boolean) => void
  hideModeToggle?: boolean
  caseNode: any
  proceedingNodes: any[]
  forumNodes: any[]
  partyNodes: any[]
  holdingsData: any[]
  structureInfo: { key: string | null; rootLabel: string | null; structure: any }
  rootStructure: any
  activeHoldingId: string | null
  activeNodeId: string | null
  activeNodeContext: string | null
  partiesExpanded: boolean
  setPartiesExpanded: (expanded: boolean) => void
  partiesSectionExpanded: boolean
  setPartiesSectionExpanded: (expanded: boolean) => void
  expandedFacts: Set<string>
  deletedNodeIds: Set<string>
  orphanedNodeIds: Set<string>
  reusedNodes: Set<string>
  globalNodeNumbering: Record<string, Record<string, number>>
  scrollToHolding: (holdingId: string) => void
  scrollToNodeById: (nodeId: string, holdingId?: string, context?: string) => void
  toggleFact: (factId: string) => void
}

export function CaseSidebar({
  isViewMode,
  setIsViewMode,
  hideModeToggle = false,
  caseNode,
  proceedingNodes,
  forumNodes,
  partyNodes,
  holdingsData,
  structureInfo,
  rootStructure,
  activeHoldingId,
  activeNodeId,
  activeNodeContext,
  partiesExpanded,
  setPartiesExpanded,
  setPartiesSectionExpanded,
  expandedFacts,
  deletedNodeIds,
  orphanedNodeIds,
  reusedNodes,
  globalNodeNumbering,
  scrollToHolding,
  scrollToNodeById,
  toggleFact
}: CaseSidebarProps) {
  // Get global number for a node
  const getGlobalNodeNumber = (nodeId: string, nodeLabel: string): number | null => {
    return globalNodeNumbering[nodeLabel]?.[nodeId] ?? null
  }

  // Dynamic renderer for nested structures (sidebar)
  const renderNestedStructureSidebar = (
    data: any,
    structureConfig: Record<string, any>,
    rootId?: string,
    depth: number = 0
  ): React.ReactElement[] => {
    const elements: React.ReactElement[] = []
    
    for (const [key, config] of Object.entries(structureConfig)) {
      if (config.self) continue // Skip self-references
      
      const value = data[key]
      if (!value) continue
      
      // Handle both single and array values
      const itemsAll = Array.isArray(value) ? value : [value]
      
      // Generic filtering - just check if it's a node object with temp_id
      const items = itemsAll.filter((item: any) => {
        return item && item.temp_id && 
          !deletedNodeIds.has(item.temp_id) && 
          !orphanedNodeIds.has(item.temp_id)
      })
      
      // Make collapsible if it's a multiple (arrays have multiple items)
      const isCollapsible = Array.isArray(value)
      
      items.forEach((item: any, idx: number) => {
        if (!item || !item.temp_id) return
        
        // Check if this node has any children to show
        const hasChildren = config.include && Object.keys(config.include).length > 0 && 
          Object.entries(config.include).some(([childKey, childConfig]: [string, any]) => {
            if (childConfig.self) return false
            const childValue = item[childKey]
            if (!childValue) return false
            const childItems = Array.isArray(childValue) ? childValue : [childValue]
            return childItems.some((child: any) => 
              child && child.temp_id && 
              !deletedNodeIds.has(child.temp_id) && 
              !orphanedNodeIds.has(child.temp_id)
            )
          })
        
        // Check if this node is expanded using a generic key
        const isExpanded = isCollapsible && expandedFacts.has(item.temp_id)
        
        const isActiveNode = activeNodeId === item.temp_id
        const isSelectedInThisContext = isActiveNode && activeNodeContext === rootId
        const isAlsoHere = isActiveNode && activeNodeContext !== rootId
        const isReused = reusedNodes.has(item.temp_id)
        
        // Get global number for this node
        const globalNum = getGlobalNodeNumber(item.temp_id, item.label || key)
        const displayNumber = globalNum !== null ? globalNum : idx + 1
        
        elements.push(
          <div key={`${key}-${item.temp_id}`} className="space-y-1">
            <div className="flex items-center gap-1">
              {isCollapsible && hasChildren && (
                <div
                  onClick={() => toggleFact(item.temp_id)}
                  className="w-4 flex-shrink-0 cursor-pointer text-gray-500 hover:text-gray-700"
                >
                  <span className="text-xs">{isExpanded ? '▼' : '▶'}</span>
                </div>
              )}
              {(!isCollapsible || !hasChildren) && <div className="w-4 flex-shrink-0" />}
              <div
                onClick={() => scrollToNodeById(item.temp_id, rootId, rootId)}
                className={`flex-1 px-2 py-1 rounded text-xs hover:bg-gray-100 cursor-pointer break-words flex items-center gap-1.5 ${
                  isSelectedInThisContext 
                    ? 'bg-blue-100 text-blue-900 font-medium' 
                    : isAlsoHere
                    ? 'bg-purple-50 text-purple-700 font-medium'
                    : 'text-gray-600'
                }`}
              >
                <span>{formatLabel(item.label || key)} {displayNumber}</span>
                {isReused && <ReusedNodeIcon />}
              </div>
            </div>
            
            {(isExpanded || !isCollapsible) && hasChildren && (
              <div className="pl-5 space-y-1">
                {renderNestedStructureSidebar(item, config.include, rootId, depth + 1)}
              </div>
            )}
          </div>
        )
      })
    }
    
    return elements
  }

  return (
    <div className="w-64 border-r bg-gray-50 flex-shrink-0 sticky top-0 max-h-screen overflow-y-auto">
      {!hideModeToggle && (
        <div className="p-4 border-b bg-white">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-gray-700">Mode:</span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setIsViewMode(true)}
                className={`px-3 py-1 text-xs rounded ${
                  isViewMode 
                    ? 'bg-blue-600 text-white' 
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                View
              </button>
              <button
                onClick={() => setIsViewMode(false)}
                className={`px-3 py-1 text-xs rounded ${
                  !isViewMode 
                    ? 'bg-blue-600 text-white' 
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                Edit
              </button>
            </div>
          </div>
        </div>
      )}
      
      <div className="p-4 space-y-4">
        <div>
          <h2 className="text-xs font-semibold text-gray-900 mb-3">Case Overview</h2>
          <div className="space-y-1 pl-2">
            {caseNode && (
              <div
                onClick={() => scrollToNodeById(caseNode.temp_id, undefined, 'overview')}
                className={`px-2 py-1 rounded text-xs hover:bg-gray-100 cursor-pointer break-words ${
                  activeNodeId === caseNode.temp_id
                    ? 'bg-blue-100 text-blue-900 font-medium'
                    : 'text-gray-600'
                }`}
              >
                Case
              </div>
            )}
            {proceedingNodes.map((proc: any, idx: number) => (
              <div key={proc.temp_id}>
                <div
                  onClick={() => scrollToNodeById(proc.temp_id, undefined, 'overview')}
                  className={`px-2 py-1 rounded text-xs hover:bg-gray-100 cursor-pointer break-words ${
                    activeNodeId === proc.temp_id
                      ? 'bg-blue-100 text-blue-900 font-medium'
                      : 'text-gray-600'
                  }`}
                >
                  Proceeding {idx + 1}
                </div>
              </div>
            ))}
            {forumNodes.map((forum: any, idx: number) => (
              <div
                key={forum.temp_id}
                onClick={() => scrollToNodeById(forum.temp_id, undefined, 'overview')}
                className={`px-2 py-1 rounded text-xs hover:bg-gray-100 cursor-pointer break-words ${
                  activeNodeId === forum.temp_id
                    ? 'bg-blue-100 text-blue-900 font-medium'
                    : 'text-gray-600'
                }`}
              >
                Forum {idx + 1}
              </div>
            ))}
            {partyNodes.length > 0 && (
              <div>
                <div
                  onClick={() => setPartiesExpanded(!partiesExpanded)}
                  className="flex items-center gap-1 px-2 py-1 rounded text-xs hover:bg-gray-100 text-gray-600 cursor-pointer"
                >
                  <span className="text-xs">{partiesExpanded ? '▼' : '▶'}</span>
                  <span>Parties ({partyNodes.length})</span>
                </div>
                {partiesExpanded && (
                  <div className="pl-4 space-y-1 mt-1">
                    {partyNodes.map((party: any, idx: number) => {
                      const partyName = pickNodeName(party) || `Party ${idx + 1}`
                      return (
                        <div
                          key={party.temp_id}
                          onClick={() => {
                            setPartiesSectionExpanded(true)
                            setTimeout(() => scrollToNodeById(party.temp_id, undefined, 'overview'), 100)
                          }}
                          className={`px-2 py-1 rounded text-xs hover:bg-gray-100 cursor-pointer break-words ${
                            activeNodeId === party.temp_id
                              ? 'bg-blue-100 text-blue-900 font-medium'
                              : 'text-gray-600'
                          }`}
                        >
                          {partyName}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
        
        <div>
          <h2 className="text-xs font-semibold text-gray-900 mb-3">
            {structureInfo.key ? formatLabel(structureInfo.key) : 'Items'} ({holdingsData.length})
          </h2>
          <div className="space-y-3">
            {holdingsData.map((entity: any, idx: number) => {
              // Get the first key with "self" property to find the root entity key
              const rootEntityKey = Object.entries(rootStructure).find(([, cfg]: [string, any]) => cfg.self)?.[0]
              const root = rootEntityKey ? entity[rootEntityKey] : entity[Object.keys(entity)[0]]
              
              if (!root) return null
              
              // For Issue nodes, show "Issue {n}: {label}", otherwise use pickNodeName
              const issueLabel = root.label === 'Issue' && root.properties?.label 
                ? root.properties.label 
                : null
              const name = issueLabel 
                ? `${structureInfo.rootLabel} ${idx + 1}: ${issueLabel}`
                : pickNodeName(root) || `${structureInfo.rootLabel} ${idx + 1}`
              const isActive = activeHoldingId === root.temp_id
              
              return (
                <div key={root.temp_id} className="space-y-1.5">
                  {/* Root entity */}
                  <div
                    onClick={() => scrollToHolding(root.temp_id)}
                    className={`px-2 py-1.5 rounded text-xs cursor-pointer ${
                      isActive ? 'bg-blue-100 text-blue-900 font-medium' : 'hover:bg-gray-100 text-gray-700'
                    }`}
                  >
                    <div className="break-words">{name}</div>
                  </div>
                  
                  {/* Dynamic content based on structure config */}
                  <div className="pl-4 space-y-1.5 border-l border-gray-300 ml-2">
                    {rootStructure && renderNestedStructureSidebar(entity, rootStructure, root.temp_id)}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}

