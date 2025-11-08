import React from 'react'
import { analyzeRelationship } from '@/lib/relationshipHelpers'
import { pickNodeName } from '@/lib/cases/formatting'
import { filterActiveNodes } from '@/lib/cases/graphHelpers'
import { RelationshipPropertyField } from '@/components/cases/editor/RelationshipPropertyField'
import { SectionHeader } from '@/components/cases/editor/SectionHeader'
import RelationshipAction from '@/components/cases/RelationshipAction.client'
import { ReliefTypeSelector } from '@/components/cases/editor/ReliefTypeSelector'

interface IssueSectionProps {
  entityData: any
  idx: number
  rootStructure: any
  structureInfo: any
  deletedNodeIds: Set<string>
  orphanedNodeIds: Set<string>
  isViewMode: boolean
  edgesArray: any[]
  schema: any
  relationshipProps: any
  handleAddNode: (type: string, rel: string, dir: 'outgoing' | 'incoming', parentId?: string) => void
  handleSelectNode: (type: string, rel: string, dir: 'outgoing' | 'incoming', parentId?: string) => void
  handleReliefTypeSelect: (reliefId: string, reliefTypeNode: any) => void
  renderNodeCard: (node: any, label: string, options?: any) => React.ReactNode
  getLiveReliefType: (reliefId: string) => any
}

export const IssueSection = React.memo(({ 
  entityData, 
  idx, 
  rootStructure,
  structureInfo,
  deletedNodeIds,
  orphanedNodeIds,
  isViewMode,
  schema,
  relationshipProps,
  handleAddNode,
  handleSelectNode,
  handleReliefTypeSelect,
  renderNodeCard,
  getLiveReliefType
}: IssueSectionProps) => {
  // Find the root entity (the one with self: true in structure)
  const rootEntityKey = Object.entries(rootStructure).find(([, cfg]: [string, any]) => cfg.self)?.[0]
  const rootEntity = rootEntityKey ? entityData[rootEntityKey] : entityData[Object.keys(entityData)[0]]
  
  // Skip this entire entity if the root itself is deleted/orphaned
  if (!rootEntity || deletedNodeIds.has(rootEntity.temp_id) || orphanedNodeIds.has(rootEntity.temp_id)) {
    return null
  }
  
  // Extract nested entities from the structured data based on the actual structure
  const ruling = entityData.ruling && !deletedNodeIds.has(entityData.ruling.temp_id) ? entityData.ruling : null
  const reliefs = filterActiveNodes(ruling?.relief || [], deletedNodeIds, orphanedNodeIds)
  const issue = rootEntity
  const args = filterActiveNodes(ruling?.arguments || [], deletedNodeIds, orphanedNodeIds)
  
  // For Issue nodes, show "Issue {n}: {label}", otherwise use pickNodeName
  const issueLabel = rootEntity.label === 'Issue' && rootEntity.properties?.label 
    ? rootEntity.properties.label 
    : null
  const entityName = issueLabel 
    ? `${structureInfo.rootLabel} ${idx + 1}: ${issueLabel}`
    : pickNodeName(rootEntity) || `${structureInfo.rootLabel} ${idx + 1}`
  
  return (
    <div 
      key={rootEntity.temp_id} 
      id={`holding-${rootEntity.temp_id}`}
      className="scroll-mt-4 border-b pb-8 last:border-b-0"
    >
      {/* Root Entity Header */}
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-gray-900">{entityName}</h2>
      </div>
      
      {/* Root Entity Details */}
      <div className="space-y-4">
        {renderNodeCard(rootEntity, `${structureInfo.rootLabel} Details`, { contextId: rootEntity.temp_id })}
        
        {/* Ruling */}
        {ruling && renderNodeCard(ruling, 'Ruling', {
          contextId: rootEntity.temp_id,
          statusBadge: (
            <RelationshipPropertyField
              sourceId={ruling.temp_id}
              targetId={rootEntity.temp_id}
              relLabel="SETS"
              propName="in_favor"
              sourceLabel="Ruling"
              isViewMode={isViewMode}
              label="In Favor"
              schema={schema}
              getValue={relationshipProps.getRulingInFavor}
              setValue={relationshipProps.setRulingInFavor}
            />
          ),
          children: (
            <>
              {/* Laws */}
              {(() => {
                const rulingStructure = rootStructure?.ruling?.include || {}
                const laws = filterActiveNodes(ruling?.law || [], deletedNodeIds, orphanedNodeIds)
                const state = analyzeRelationship(ruling, 'law', rulingStructure, schema, { law: laws })
                return (
                  <div className="mt-4">
                    <SectionHeader
                      title="Laws"
                      actionButton={!isViewMode && state && (
                        <RelationshipAction
                          state={state}
                          parentNodeLabel="Ruling"
                          position="inline"
                          onAdd={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleAddNode(type, rel, dir, ruling.temp_id)}
                          onSelect={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleSelectNode(type, rel, dir, ruling.temp_id)}
                        />
                      )}
                    />
                    <div className="space-y-4">
                      {laws.map((law: any, lawIdx: number) => 
                        renderNodeCard(law, 'Law', { 
                          index: lawIdx, 
                          depth: 1, 
                          parentId: ruling.temp_id,
                          contextId: rootEntity.temp_id
                        })
                      )}
                    </div>
                  </div>
                )
              })()}
              
              {/* Relief (intermediate layer) */}
              {(() => {
                const rulingStructure = rootStructure?.ruling?.include || {}
                const state = analyzeRelationship(ruling, 'relief', rulingStructure, schema, { relief: reliefs })
                return (
                  <div className="mt-4">
                    <SectionHeader
                      title="Relief"
                      actionButton={!isViewMode && state && (
                        <RelationshipAction
                          state={state}
                          parentNodeLabel="Ruling"
                          position="inline"
                          onAdd={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleAddNode(type, rel, dir, ruling.temp_id)}
                          onSelect={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleSelectNode(type, rel, dir, ruling.temp_id)}
                        />
                      )}
                    />
                    <div className="space-y-4">
                      {reliefs.map((relief: any, relIdx: number) => {
                        // Get live relief type from current graph state
                        const liveReliefType = getLiveReliefType(relief.temp_id)
                        
                        return renderNodeCard(relief, 'Relief', {
                          index: relIdx,
                          depth: 1,
                          parentId: ruling.temp_id,
                          contextId: rootEntity.temp_id,
                          statusBadge: (
                            <RelationshipPropertyField
                              sourceId={ruling.temp_id}
                              targetId={relief.temp_id}
                              relLabel="RESULTS_IN"
                              propName="relief_status"
                              sourceLabel="Ruling"
                              isViewMode={isViewMode}
                              label="Relief Status"
                              schema={schema}
                              getValue={relationshipProps.getReliefStatus}
                              setValue={relationshipProps.setReliefStatus}
                            />
                          ),
                          children: (
                            <>
                              {/* Relief Type Selector (inline dropdown) */}
                              <ReliefTypeSelector
                                reliefId={relief.temp_id}
                                currentReliefType={liveReliefType}
                                isViewMode={isViewMode}
                                onSelect={(selectedNode: any) => handleReliefTypeSelect(relief.temp_id, selectedNode)}
                              />
                            </>
                          )
                        })
                      })}
                    </div>
                  </div>
                )
              })()}
              
              {/* Arguments */}
              {(() => {
                return (
                  <>
                    {args.length > 0 && (
                      <div className="mt-6 pt-6 border-t-2 border-gray-200 space-y-4">
                        {args.map((argData: any, argIdx: number) => {
                          // Backend returns structured argument data
                          const arg = argData.arguments || argData
                          const doctrines = filterActiveNodes(argData.doctrine || [], deletedNodeIds, orphanedNodeIds)
                          const policies = filterActiveNodes(argData.policy || [], deletedNodeIds, orphanedNodeIds)
                          const factPatterns = filterActiveNodes(argData.factPattern || [], deletedNodeIds, orphanedNodeIds)
                          const argumentStatus = relationshipProps.getArgumentStatus(arg.temp_id, ruling.temp_id)
                          
                          return renderNodeCard(arg, 'Argument', {
                            index: argIdx,
                            depth: 1,
                            parentId: ruling.temp_id,
                            contextId: rootEntity.temp_id,
                            statusBadge: isViewMode ? (
                              argumentStatus && (
                                <span className={`px-2 py-1 rounded text-xs font-medium ${
                                  argumentStatus === 'Accepted' 
                                    ? 'bg-green-100 text-green-800' 
                                    : 'bg-red-100 text-red-800'
                                }`}>
                                  {argumentStatus}
                                </span>
                              )
                            ) : (
                              <select
                                className="px-2 py-1 rounded border border-gray-300 text-xs font-medium focus:outline-none focus:ring-2 focus:ring-blue-500"
                                value={argumentStatus || ''}
                                onChange={(e) => relationshipProps.setArgumentStatus(arg.temp_id, ruling.temp_id, e.target.value)}
                              >
                                <option value="">Select status...</option>
                                <option value="Accepted">Accepted</option>
                                <option value="Rejected">Rejected</option>
                              </select>
                            ),
                            children: (
                              <div className="mt-4 space-y-6">
                                {/* Doctrines Section */}
                                {(() => {
                                  const argStructure = rootStructure?.ruling?.include?.arguments?.include || {}
                                  const state = analyzeRelationship(arg, 'doctrine', argStructure, schema, argData)
                                  return (
                                    <div>
                                      <SectionHeader
                                        title="Doctrines"
                                        actionButton={!isViewMode && state && (
                                          <RelationshipAction
                                            state={state}
                                            parentNodeLabel="Argument"
                                            position="inline"
                                            onAdd={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleAddNode(type, rel, dir, arg.temp_id)}
                                            onSelect={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleSelectNode(type, rel, dir, arg.temp_id)}
                                          />
                                        )}
                                      />
                                      <div className="space-y-4">
                                        {doctrines.map((doc: any, docIdx: number) => 
                                          renderNodeCard(doc, 'Doctrine', { 
                                            index: docIdx, 
                                            depth: 2, 
                                            parentId: arg.temp_id,
                                            contextId: rootEntity.temp_id
                                          })
                                        )}
                                      </div>
                                    </div>
                                  )
                                })()}
                                
                                {/* Policies Section */}
                                {(() => {
                                  const argStructure = rootStructure?.ruling?.include?.arguments?.include || {}
                                  const state = analyzeRelationship(arg, 'policy', argStructure, schema, argData)
                                  return (
                                    <div>
                                      <SectionHeader
                                        title="Policies"
                                        actionButton={!isViewMode && state && (
                                          <RelationshipAction
                                            state={state}
                                            parentNodeLabel="Argument"
                                            position="inline"
                                            onAdd={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleAddNode(type, rel, dir, arg.temp_id)}
                                            onSelect={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleSelectNode(type, rel, dir, arg.temp_id)}
                                          />
                                        )}
                                      />
                                      <div className="space-y-4">
                                        {policies.map((pol: any, polIdx: number) => 
                                          renderNodeCard(pol, 'Policy', { 
                                            index: polIdx, 
                                            depth: 2, 
                                            parentId: arg.temp_id,
                                            contextId: rootEntity.temp_id
                                          })
                                        )}
                                      </div>
                                    </div>
                                  )
                                })()}
                                
                                {/* Fact Patterns Section */}
                                {(() => {
                                  const argStructure = rootStructure?.ruling?.include?.arguments?.include || {}
                                  const state = analyzeRelationship(arg, 'factPattern', argStructure, schema, argData)
                                  return (
                                    <div>
                                      <SectionHeader
                                        title="Fact Patterns"
                                        actionButton={!isViewMode && state && (
                                          <RelationshipAction
                                            state={state}
                                            parentNodeLabel="Argument"
                                            position="inline"
                                            onAdd={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleAddNode(type, rel, dir, arg.temp_id)}
                                            onSelect={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleSelectNode(type, rel, dir, arg.temp_id)}
                                          />
                                        )}
                                      />
                                      <div className="space-y-4">
                                        {factPatterns.map((fp: any, fpIdx: number) => 
                                          renderNodeCard(fp, 'Fact Pattern', { 
                                            index: fpIdx, 
                                            depth: 2, 
                                            parentId: arg.temp_id,
                                            contextId: rootEntity.temp_id
                                          })
                                        )}
                                      </div>
                                    </div>
                                  )
                                })()}
                              </div>
                            )
                          })
                        })}
                      </div>
                    )}
                    {/* Add Argument button */}
                    {!isViewMode && (() => {
                      const rulingStructure = rootStructure?.ruling?.include || {}
                      const state = analyzeRelationship(ruling, 'arguments', rulingStructure, schema, { arguments: args })
                      if (!state) return null
                      return (
                        <div className={args.length > 0 ? "mt-3" : "mt-4"}>
                          <RelationshipAction
                            state={state}
                            parentNodeLabel="Ruling"
                            position={args.length === 0 ? 'centered' : 'inline'}
                            onAdd={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleAddNode(type, rel, dir, ruling.temp_id)}
                            onSelect={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleSelectNode(type, rel, dir, ruling.temp_id)}
                          />
                        </div>
                      )
                    })()}
                  </>
                )
              })()}
            </>
          )
        })}
        {/* Add Ruling button if no ruling exists */}
        {!isViewMode && !ruling && issue && (() => {
          const state = analyzeRelationship(issue, 'ruling', rootStructure || {}, schema, { ruling: null })
          if (!state) return null
          return (
            <RelationshipAction
              state={state}
              parentNodeLabel="Issue"
              position="centered"
              onAdd={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleAddNode(type, rel, dir, issue.temp_id)}
              onSelect={(type: string, rel: string, dir: 'outgoing' | 'incoming') => handleSelectNode(type, rel, dir, issue.temp_id)}
            />
          )
        })()}
      </div>
    </div>
  )
}, (prevProps, nextProps) => {
  // Custom comparison function - return true if props are equal (skip re-render)
  // Only re-render if the specific issue's data changed or view mode changed
  const rootEntityKey = Object.entries(prevProps.rootStructure).find(([, cfg]: [string, any]) => cfg.self)?.[0]
  const prevRootId = rootEntityKey ? prevProps.entityData[rootEntityKey]?.temp_id : prevProps.entityData[Object.keys(prevProps.entityData)[0]]?.temp_id
  const nextRootId = rootEntityKey ? nextProps.entityData[rootEntityKey]?.temp_id : nextProps.entityData[Object.keys(nextProps.entityData)[0]]?.temp_id
  
  // If root IDs are different, definitely re-render
  if (prevRootId !== nextRootId) return false
  
  // If view mode changed, re-render
  if (prevProps.isViewMode !== nextProps.isViewMode) return false
  
  // CRITICAL FIX: Check if edges changed for nodes in this issue
  // Extract all node IDs from this issue
  const extractAllNodeIds = (entityData: any, rootId: string | undefined): string[] => {
    const ids: string[] = []
    
    // Add root entity (Issue/Holding) ID
    if (rootId) ids.push(rootId)
    
    const ruling = entityData.ruling
    
    // Add ruling ID
    if (ruling?.temp_id) ids.push(ruling.temp_id)
    
    // Add relief IDs
    if (ruling?.relief) {
      const reliefs = Array.isArray(ruling.relief) ? ruling.relief : []
      reliefs.forEach((r: any) => { if (r?.temp_id) ids.push(r.temp_id) })
    }
    
    // Add argument IDs
    if (ruling?.arguments) {
      const args = Array.isArray(ruling.arguments) ? ruling.arguments : []
      args.forEach((arg: any) => {
        const argNode = arg.arguments || arg
        if (argNode?.temp_id) ids.push(argNode.temp_id)
      })
    }
    
    return ids
  }
  
  const nodeIds = extractAllNodeIds(prevProps.entityData, prevRootId)
  
  // Check if any edges related to this issue changed (including properties)
  if (nodeIds.length > 0) {
    const getEdgesHash = (edgesArray: any[], nodeIds: string[]): string => {
      return edgesArray
        .filter((e: any) => 
          e.status === 'active' && 
          (nodeIds.includes(e.from) || nodeIds.includes(e.to))
        )
        .map((e: any) => {
          // Include properties in the hash to detect property changes
          const props = e.properties ? JSON.stringify(e.properties) : ''
          return `${e.from}:${e.to}:${e.label}:${props}`
        })
        .sort()
        .join('|')
    }
    
    const prevEdges = getEdgesHash(prevProps.edgesArray, nodeIds)
    const nextEdges = getEdgesHash(nextProps.edgesArray, nodeIds)
    
    // If edges changed (including their properties), re-render
    if (prevEdges !== nextEdges) return false
  }
  
  // Deep compare the entityData to see if THIS issue's data changed
  // This is the key optimization - we only care about this specific issue's data
  const prevEntityStr = JSON.stringify(prevProps.entityData)
  const nextEntityStr = JSON.stringify(nextProps.entityData)
  
  // If the specific entity data is the same, skip re-render (return true)
  // Ignore function prop changes - they're stable via useCallback
  return prevEntityStr === nextEntityStr
})

IssueSection.displayName = 'IssueSection'

