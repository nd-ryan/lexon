'use client'

import React, { useState, useEffect, useCallback } from 'react'
import { useSession } from 'next-auth/react'
import type { Session } from 'next-auth'
import { useRouter } from 'next/navigation'
import { hasAtLeastRole } from '@/lib/rbac'

// Types
interface LinkableSchema {
  linkableConcepts: Record<string, string[]>  // { "Doctrine": ["Issue", "Argument"], ... }
  conceptProperties: Record<string, string[]>
  relationships: Record<string, string>  // { "Issue->Doctrine": "RELATES_TO_DOCTRINE", ... }
}

interface Concept {
  id: string
  name: string
  description: string
  connectionCount: number
  properties: Record<string, any>
}

interface TargetCounts {
  targetCounts: Record<string, number>  // { "Argument": 342, "Issue": 156 }
  totalTargets: number
}

interface Match {
  nodeId: string
  nodeLabel: string
  caseId: string
  caseName: string
  nodeTextPreview: string
  selected: boolean
}

interface AnalysisResult {
  conceptLabel: string
  conceptId: string
  conceptName: string
  totalAnalyzed: number
  matches: Match[]
  matchCount: number
}

type WizardStep = 'select-type' | 'select-concept' | 'analyze' | 'review'

export default function ConceptLinkingPage() {
  const { data: session, status } = useSession()
  const router = useRouter()
  
  // Auth state
  const role = (session?.user as Session['user'])?.role
  const isAdmin = hasAtLeastRole(role, 'admin')
  
  // Wizard state
  const [step, setStep] = useState<WizardStep>('select-type')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  
  // Data state
  const [schema, setSchema] = useState<LinkableSchema | null>(null)
  const [selectedType, setSelectedType] = useState<string>('')
  const [concepts, setConcepts] = useState<Concept[]>([])
  const [selectedConcept, setSelectedConcept] = useState<Concept | null>(null)
  const [targetCounts, setTargetCounts] = useState<TargetCounts | null>(null)
  const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null)
  const [matches, setMatches] = useState<Match[]>([])
  const [committing, setCommitting] = useState(false)
  const [commitResult, setCommitResult] = useState<{ success: boolean; message: string } | null>(null)
  
  // Search state
  const [conceptSearch, setConceptSearch] = useState('')
  
  // Auth check
  useEffect(() => {
    if (status === 'loading') return
    if (!session || !isAdmin) {
      router.push('/')
    }
  }, [session, status, isAdmin, router])
  
  // Fetch schema on mount
  useEffect(() => {
    async function fetchSchema() {
      try {
        const res = await fetch('/api/admin/concept-linking/schema')
        if (res.ok) {
          const data = await res.json()
          if (data.success) {
            setSchema({
              linkableConcepts: data.linkableConcepts,
              conceptProperties: data.conceptProperties,
              relationships: data.relationships,
            })
          }
        }
      } catch (e) {
        console.error('Failed to fetch schema:', e)
        setError('Failed to load schema')
      }
    }
    fetchSchema()
  }, [])
  
  // Fetch concepts when type is selected
  useEffect(() => {
    if (!selectedType) {
      setConcepts([])
      return
    }
    
    async function fetchConcepts() {
      setLoading(true)
      setError(null)
      try {
        const res = await fetch(`/api/admin/concept-linking/concepts/${selectedType}`)
        if (res.ok) {
          const data = await res.json()
          if (data.success) {
            setConcepts(data.concepts || [])
          }
        } else {
          setError('Failed to load concepts')
        }
      } catch (e) {
        console.error('Failed to fetch concepts:', e)
        setError('Failed to load concepts')
      } finally {
        setLoading(false)
      }
    }
    fetchConcepts()
  }, [selectedType])
  
  // Fetch target counts when concept is selected
  useEffect(() => {
    if (!selectedConcept || !selectedType) {
      setTargetCounts(null)
      return
    }
    
    async function fetchTargetCounts() {
      try {
        const res = await fetch(
          `/api/admin/concept-linking/concepts/${selectedType}/${selectedConcept.id}/target-counts`
        )
        if (res.ok) {
          const data = await res.json()
          if (data.success) {
            setTargetCounts({
              targetCounts: data.targetCounts,
              totalTargets: data.totalTargets,
            })
          }
        }
      } catch (e) {
        console.error('Failed to fetch target counts:', e)
      }
    }
    fetchTargetCounts()
  }, [selectedConcept, selectedType])
  
  // Run analysis
  const runAnalysis = useCallback(async () => {
    if (!selectedType || !selectedConcept) return
    
    setLoading(true)
    setError(null)
    setAnalysisResult(null)
    setMatches([])
    
    try {
      const res = await fetch('/api/admin/concept-linking/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          conceptLabel: selectedType,
          conceptId: selectedConcept.id,
          batchSize: 100,
          maxNodes: 1000,
        }),
      })
      
      if (res.ok) {
        const data = await res.json()
        if (data.success) {
          setAnalysisResult(data)
          // Initialize matches with all selected by default
          const matchesWithSelection = (data.matches || []).map((m: Omit<Match, 'selected'>) => ({
            ...m,
            selected: true,
          }))
          setMatches(matchesWithSelection)
          setStep('review')
        } else {
          setError(data.error || 'Analysis failed')
        }
      } else {
        const data = await res.json()
        setError(data.error || 'Analysis failed')
      }
    } catch (e) {
      console.error('Analysis failed:', e)
      setError('Analysis failed')
    } finally {
      setLoading(false)
    }
  }, [selectedType, selectedConcept])
  
  // Toggle match selection
  const toggleMatch = (nodeId: string) => {
    setMatches(prev => prev.map(m => 
      m.nodeId === nodeId ? { ...m, selected: !m.selected } : m
    ))
  }
  
  // Select/deselect all
  const selectAll = () => {
    setMatches(prev => prev.map(m => ({ ...m, selected: true })))
  }
  
  const deselectAll = () => {
    setMatches(prev => prev.map(m => ({ ...m, selected: false })))
  }
  
  // Commit selected matches
  const commitMatches = async () => {
    if (!selectedType || !selectedConcept) return
    
    const selectedMatches = matches.filter(m => m.selected)
    if (selectedMatches.length === 0) {
      setError('No matches selected')
      return
    }
    
    setCommitting(true)
    setError(null)
    setCommitResult(null)
    
    try {
      const res = await fetch('/api/admin/concept-linking/commit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          conceptLabel: selectedType,
          conceptId: selectedConcept.id,
          matches: selectedMatches.map(m => ({
            nodeId: m.nodeId,
            nodeLabel: m.nodeLabel,
            caseId: m.caseId,
          })),
        }),
      })
      
      const data = await res.json()
      
      if (data.success) {
        setCommitResult({
          success: true,
          message: `Successfully created ${data.neo4jRelationshipsCreated} relationships across ${data.postgresCasesUpdated} cases`,
        })
        // Remove committed matches from the list
        setMatches(prev => prev.filter(m => !m.selected))
      } else {
        setCommitResult({
          success: false,
          message: data.errors?.join(', ') || 'Commit failed',
        })
      }
    } catch (e) {
      console.error('Commit failed:', e)
      setCommitResult({ success: false, message: 'Commit failed' })
    } finally {
      setCommitting(false)
    }
  }
  
  // Reset wizard
  const resetWizard = () => {
    setStep('select-type')
    setSelectedType('')
    setSelectedConcept(null)
    setTargetCounts(null)
    setAnalysisResult(null)
    setMatches([])
    setCommitResult(null)
    setError(null)
    setConceptSearch('')
  }
  
  // Filter concepts by search
  const filteredConcepts = conceptSearch.trim()
    ? concepts.filter(c => 
        c.name.toLowerCase().includes(conceptSearch.toLowerCase()) ||
        c.description.toLowerCase().includes(conceptSearch.toLowerCase())
      )
    : concepts
  
  // Count selected matches
  const selectedCount = matches.filter(m => m.selected).length
  
  if (status === 'loading') {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-gray-600">Loading...</div>
      </div>
    )
  }
  
  if (!session || !isAdmin) {
    return null
  }
  
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-6xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-gray-900">Concept Auto-Linking</h1>
          <p className="text-gray-600 mt-1">
            Use AI to find and link shared concepts (Doctrines, Policies, etc.) to existing case data.
          </p>
        </div>
        
        {/* Progress Steps */}
        <div className="mb-8">
          <div className="flex items-center gap-2">
            {(['select-type', 'select-concept', 'analyze', 'review'] as WizardStep[]).map((s, i) => (
              <React.Fragment key={s}>
                <div 
                  className={`flex items-center justify-center w-8 h-8 rounded-full text-sm font-medium transition-colors ${
                    step === s 
                      ? 'bg-indigo-600 text-white' 
                      : i < ['select-type', 'select-concept', 'analyze', 'review'].indexOf(step)
                        ? 'bg-indigo-200 text-indigo-800'
                        : 'bg-gray-200 text-gray-500'
                  }`}
                >
                  {i + 1}
                </div>
                <span className={`text-sm ${step === s ? 'text-indigo-600 font-medium' : 'text-gray-500'}`}>
                  {s === 'select-type' && 'Select Type'}
                  {s === 'select-concept' && 'Select Concept'}
                  {s === 'analyze' && 'Analyze'}
                  {s === 'review' && 'Review & Commit'}
                </span>
                {i < 3 && (
                  <div className={`flex-1 h-px ${
                    i < ['select-type', 'select-concept', 'analyze', 'review'].indexOf(step) 
                      ? 'bg-indigo-300' 
                      : 'bg-gray-200'
                  }`} />
                )}
              </React.Fragment>
            ))}
          </div>
        </div>
        
        {/* Error Display */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
            <p className="text-red-800 text-sm">{error}</p>
          </div>
        )}
        
        {/* Step 1: Select Concept Type */}
        {step === 'select-type' && (
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-lg font-semibold mb-4">Select Concept Type</h2>
            <p className="text-gray-600 text-sm mb-6">
              Choose the type of shared concept you want to link to existing case data.
            </p>
            
            {!schema ? (
              <div className="text-center py-8 text-gray-500">Loading schema...</div>
            ) : (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {Object.entries(schema.linkableConcepts).map(([label, targets]) => (
                  <button
                    key={label}
                    onClick={() => {
                      setSelectedType(label)
                      setStep('select-concept')
                    }}
                    className="p-4 border-2 rounded-lg hover:border-indigo-500 hover:bg-indigo-50 transition-colors text-left"
                  >
                    <div className="font-medium text-gray-900">{label}</div>
                    <div className="text-xs text-gray-500 mt-1">
                      Links to: {targets.join(', ')}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        
        {/* Step 2: Select Specific Concept */}
        {step === 'select-concept' && (
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold">Select {selectedType}</h2>
              <button
                onClick={() => {
                  setSelectedType('')
                  setStep('select-type')
                }}
                className="text-sm text-indigo-600 hover:text-indigo-800"
              >
                ← Change Type
              </button>
            </div>
            <p className="text-gray-600 text-sm mb-4">
              Select a specific {selectedType.toLowerCase()} to find matching case data for.
            </p>
            
            {/* Search */}
            <div className="mb-4">
              <input
                type="text"
                value={conceptSearch}
                onChange={(e) => setConceptSearch(e.target.value)}
                placeholder={`Search ${selectedType}s...`}
                className="w-full border rounded-lg px-4 py-2"
              />
            </div>
            
            {loading ? (
              <div className="text-center py-8 text-gray-500">Loading {selectedType}s...</div>
            ) : filteredConcepts.length === 0 ? (
              <div className="text-center py-8 text-gray-500">
                {conceptSearch ? `No ${selectedType}s match "${conceptSearch}"` : `No ${selectedType}s found`}
              </div>
            ) : (
              <div className="space-y-2 max-h-96 overflow-y-auto">
                {filteredConcepts.map((concept) => (
                  <button
                    key={concept.id}
                    onClick={() => {
                      setSelectedConcept(concept)
                      setStep('analyze')
                    }}
                    className={`w-full p-4 border rounded-lg hover:border-indigo-500 hover:bg-indigo-50 transition-colors text-left ${
                      selectedConcept?.id === concept.id ? 'border-indigo-500 bg-indigo-50' : ''
                    }`}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="font-medium text-gray-900">{concept.name}</div>
                        <div className="text-sm text-gray-500 mt-1 line-clamp-2">
                          {concept.description || 'No description'}
                        </div>
                      </div>
                      <div className="text-xs text-gray-400 ml-4">
                        {concept.connectionCount} connections
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        
        {/* Step 3: Analyze */}
        {step === 'analyze' && selectedConcept && (
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold">Analyze Matches</h2>
              <button
                onClick={() => {
                  setSelectedConcept(null)
                  setStep('select-concept')
                }}
                className="text-sm text-indigo-600 hover:text-indigo-800"
              >
                ← Change Concept
              </button>
            </div>
            
            {/* Selected Concept Details */}
            <div className="bg-gray-50 rounded-lg p-4 mb-6">
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-sm text-gray-500">{selectedType}</div>
                  <div className="text-lg font-medium text-gray-900">{selectedConcept.name}</div>
                  <div className="text-sm text-gray-600 mt-1">{selectedConcept.description}</div>
                </div>
              </div>
            </div>
            
            {/* Target Counts Preview */}
            {targetCounts && (
              <div className="mb-6">
                <h3 className="text-sm font-medium text-gray-700 mb-2">Nodes to Analyze</h3>
                <div className="flex flex-wrap gap-3">
                  {Object.entries(targetCounts.targetCounts).map(([label, count]) => (
                    <div key={label} className="bg-gray-100 rounded px-3 py-1.5">
                      <span className="font-medium">{count}</span>
                      <span className="text-gray-600 ml-1">{label}s</span>
                    </div>
                  ))}
                  <div className="bg-indigo-100 text-indigo-800 rounded px-3 py-1.5">
                    <span className="font-medium">{targetCounts.totalTargets}</span>
                    <span className="ml-1">total</span>
                  </div>
                </div>
              </div>
            )}
            
            {/* Info Box */}
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
              <p className="text-blue-800 text-sm">
                <strong>ℹ️ How it works:</strong> The AI will analyze each {schema?.linkableConcepts[selectedType]?.join(' and ')} 
                that isn&apos;t already linked to this {selectedType.toLowerCase()}, and suggest matches based on semantic relevance.
                You&apos;ll review the suggestions before any changes are made.
              </p>
            </div>
            
            {/* Run Analysis Button */}
            <button
              onClick={runAnalysis}
              disabled={loading}
              className="w-full py-3 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {loading ? (
                <>
                  <div className="animate-spin h-5 w-5 border-2 border-white border-t-transparent rounded-full" />
                  Analyzing... (this may take a few minutes)
                </>
              ) : (
                <>
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                  Run AI Analysis
                </>
              )}
            </button>
          </div>
        )}
        
        {/* Step 4: Review & Commit */}
        {step === 'review' && analysisResult && (
          <div className="space-y-6">
            {/* Summary Card */}
            <div className="bg-white rounded-lg shadow p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold">Review Matches</h2>
                <button
                  onClick={resetWizard}
                  className="text-sm text-indigo-600 hover:text-indigo-800"
                >
                  ← Start Over
                </button>
              </div>
              
              {/* Concept Info */}
              <div className="bg-gray-50 rounded-lg p-4 mb-4">
                <div className="text-sm text-gray-500">{selectedType}</div>
                <div className="font-medium">{analysisResult.conceptName}</div>
              </div>
              
              {/* Stats */}
              <div className="grid grid-cols-4 gap-4 mb-4">
                <div className="text-center">
                  <div className="text-2xl font-bold text-gray-900">{analysisResult.totalAnalyzed}</div>
                  <div className="text-xs text-gray-500">Analyzed</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-green-600">{analysisResult.highConfidenceCount}</div>
                  <div className="text-xs text-green-600">High Confidence</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-yellow-600">{analysisResult.mediumConfidenceCount}</div>
                  <div className="text-xs text-yellow-600">Medium</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-orange-600">{analysisResult.lowConfidenceCount}</div>
                  <div className="text-xs text-orange-600">Low</div>
                </div>
              </div>
              
              {/* Quick Select Buttons */}
              <div className="flex flex-wrap gap-2 mb-4">
                <button
                  onClick={() => selectByConfidence('all')}
                  className="px-3 py-1 text-sm border rounded hover:bg-gray-50"
                >
                  Select All
                </button>
                <button
                  onClick={() => selectByConfidence('none')}
                  className="px-3 py-1 text-sm border rounded hover:bg-gray-50"
                >
                  Deselect All
                </button>
                <div className="w-px bg-gray-300" />
                <button
                  onClick={() => selectByConfidence('high')}
                  className="px-3 py-1 text-sm border border-green-300 text-green-700 rounded hover:bg-green-50"
                >
                  + High
                </button>
                <button
                  onClick={() => deselectByConfidence('high')}
                  className="px-3 py-1 text-sm border border-green-300 text-green-700 rounded hover:bg-green-50"
                >
                  − High
                </button>
                <button
                  onClick={() => selectByConfidence('medium')}
                  className="px-3 py-1 text-sm border border-yellow-300 text-yellow-700 rounded hover:bg-yellow-50"
                >
                  + Medium
                </button>
                <button
                  onClick={() => deselectByConfidence('medium')}
                  className="px-3 py-1 text-sm border border-yellow-300 text-yellow-700 rounded hover:bg-yellow-50"
                >
                  − Medium
                </button>
                <button
                  onClick={() => selectByConfidence('low')}
                  className="px-3 py-1 text-sm border border-orange-300 text-orange-700 rounded hover:bg-orange-50"
                >
                  + Low
                </button>
                <button
                  onClick={() => deselectByConfidence('low')}
                  className="px-3 py-1 text-sm border border-orange-300 text-orange-700 rounded hover:bg-orange-50"
                >
                  − Low
                </button>
              </div>
              
              {/* Commit Result */}
              {commitResult && (
                <div className={`p-4 rounded-lg mb-4 ${
                  commitResult.success ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'
                }`}>
                  {commitResult.success && (
                    <svg className="inline w-5 h-5 mr-2\" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                  )}
                  {commitResult.message}
                </div>
              )}
              
              {/* Commit Button */}
              <button
                onClick={commitMatches}
                disabled={committing || selectedCount === 0}
                className="w-full py-3 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {committing ? (
                  <>
                    <div className="animate-spin h-5 w-5 border-2 border-white border-t-transparent rounded-full" />
                    Committing...
                  </>
                ) : (
                  <>
                    Commit {selectedCount} Selected Match{selectedCount !== 1 ? 'es' : ''}
                  </>
                )}
              </button>
            </div>
            
            {/* Matches List */}
            {matches.length > 0 ? (
              <div className="bg-white rounded-lg shadow overflow-hidden">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="w-12 px-4 py-3">
                        <input
                          type="checkbox"
                          checked={selectedCount === matches.length}
                          onChange={() => selectedCount === matches.length ? deselectAll() : selectAll()}
                          className="rounded"
                        />
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Case</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Node Preview</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {matches.map((match) => (
                      <tr 
                        key={match.nodeId} 
                        className={`hover:bg-gray-50 ${match.selected ? 'bg-indigo-50' : ''}`}
                        onClick={() => toggleMatch(match.nodeId)}
                        style={{ cursor: 'pointer' }}
                      >
                        <td className="px-4 py-3">
                          <input
                            type="checkbox"
                            checked={match.selected}
                            onChange={() => toggleMatch(match.nodeId)}
                            onClick={(e) => e.stopPropagation()}
                            className="rounded"
                          />
                        </td>
                        <td className="px-4 py-3">
                          <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded text-xs font-medium">
                            {match.nodeLabel}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <div className="text-sm text-gray-900 max-w-[200px] truncate">
                            {match.caseName}
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <div className="text-sm text-gray-600 max-w-[400px] line-clamp-2">
                            {match.nodeTextPreview}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="bg-white rounded-lg shadow p-8 text-center text-gray-500">
                {commitResult?.success 
                  ? 'All matches have been committed!'
                  : 'No matches found. The AI did not find any nodes that relate to this concept.'}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
