"use client";
import { useState, useEffect, useRef, useCallback } from 'react'
import { useSession } from 'next-auth/react'
import type { Session } from 'next-auth'
import { useRouter } from 'next/navigation'
import Button from '@/components/ui/button'
import { hasAtLeastRole } from '@/lib/rbac'

export const dynamic = 'force-dynamic'

// Prescreening types
interface PrescreeningResult {
  status: 'pending' | 'analyzing' | 'text_layer_ok' | 'courtlistener_resolved' | 'ocr_resolved' | 'failed' | 'confirmed'
  text?: string
  textSource?: 'pdf_text' | 'courtlistener' | 'ocr'
  confidence?: number
  courtlistenerMetadata?: {
    opinion_id: number
    cluster_id: number
    case_name: string
    court?: string
    date_filed?: string
    docket_number?: string
    citation?: string
    canonical_url: string
    resolver_confidence: number
  }
  warnings?: string[]
  error?: string
}

interface FileWithPrescreening {
  file: File
  prescreening: PrescreeningResult
}

interface CaseStatus {
  filename: string
  status: 'pending' | 'extracting' | 'uploading-kg' | 'completed' | 'failed'
  error?: string
  caseId?: string
  jobId?: string
  currentMessage?: string
  progress?: number
  embeddingsComplete?: boolean
  missingEmbeddingsCount?: number
}

export default function BulkUploadPage() {
  const { data: session, status: sessionStatus } = useSession()
  const router = useRouter()
  const [filesWithPrescreening, setFilesWithPrescreening] = useState<FileWithPrescreening[]>([])
  const [processing, setProcessing] = useState(false)
  const [prescreening, setPrescreening] = useState(false)
  const [caseStatuses, setCaseStatuses] = useState<CaseStatus[]>([])
  const [currentIndex, setCurrentIndex] = useState<number>(-1)
  const [reviewingIndex, setReviewingIndex] = useState<number | null>(null)
  const eventSourceRef = useRef<EventSource | null>(null)

  const role = (session?.user as Session['user'])?.role
  const isAdmin = hasAtLeastRole(role, 'admin')

  // Protect the page - only allow admin email
  useEffect(() => {
    if (sessionStatus === 'loading') return
    if (!session || !isAdmin) {
      router.replace('/cases')
    }
  }, [session, sessionStatus, router, isAdmin])

  const updatePrescreeningStatus = useCallback((index: number, updates: Partial<PrescreeningResult>) => {
    setFilesWithPrescreening(prev => prev.map((f, i) => 
      i === index ? { ...f, prescreening: { ...f.prescreening, ...updates } } : f
    ))
  }, [])

  const prescreenFile = async (file: File, index: number): Promise<void> => {
    // Only prescreen PDFs
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      updatePrescreeningStatus(index, {
        status: 'text_layer_ok',
        textSource: 'pdf_text',
      })
      return
    }

    updatePrescreeningStatus(index, { status: 'analyzing' })

    try {
      const fd = new FormData()
      fd.append('file', file)

      // Use AbortController with long timeout (15 minutes) for OCR which can take a while
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), 15 * 60 * 1000)

      const res = await fetch('/api/admin/prescreening', {
        method: 'POST',
        body: fd,
        signal: controller.signal,
      })

      clearTimeout(timeoutId)

      if (!res.ok) {
        const errorData = await res.json()
        throw new Error(errorData.error || 'Prescreening failed')
      }

      const data = await res.json()

      updatePrescreeningStatus(index, {
        status: data.status as PrescreeningResult['status'],
        text: data.text,
        textSource: data.text_source,
        confidence: data.confidence,
        courtlistenerMetadata: data.courtlistener_metadata,
        warnings: data.warnings,
        error: data.error,
      })
    } catch (error: any) {
      const message = error.name === 'AbortError' 
        ? 'Prescreening timed out (15 min limit)' 
        : (error.message || 'Prescreening failed')
      updatePrescreeningStatus(index, {
        status: 'failed',
        error: message,
      })
    }
  }

  const handleFilesChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = Array.from(e.target.files || [])
    
    // Initialize files with pending prescreening status
    const filesWithStatus: FileWithPrescreening[] = selectedFiles.map(f => ({
      file: f,
      prescreening: { status: 'pending' }
    }))
    
    setFilesWithPrescreening(filesWithStatus)
    setCaseStatuses([])
    
    // Start prescreening for PDFs
    setPrescreening(true)
    
    // Process files with concurrency limit
    // Keep concurrency at 1 to avoid overwhelming Gemini API with large image requests
    const CONCURRENCY = 1
    const queue = [...selectedFiles.entries()]
    const processing: Promise<void>[] = []

    while (queue.length > 0 || processing.length > 0) {
      while (processing.length < CONCURRENCY && queue.length > 0) {
        const [index, file] = queue.shift()!
        const promise = prescreenFile(file, index).then(() => {
          processing.splice(processing.indexOf(promise), 1)
        })
        processing.push(promise)
      }
      if (processing.length > 0) {
        await Promise.race(processing)
      }
    }

    setPrescreening(false)
  }

  const confirmPrescreening = (index: number) => {
    updatePrescreeningStatus(index, { status: 'confirmed' })
    setReviewingIndex(null)
  }

  const updateCaseStatus = (index: number, updates: Partial<CaseStatus>) => {
    setCaseStatuses(prev => prev.map((s, i) => 
      i === index ? { ...s, ...updates } : s
    ))
  }

  const processExtractionStream = (index: number, jobId: string): Promise<boolean> => {
    return new Promise((resolve) => {
      const eventSource = new EventSource(`/api/cases/upload/progress/${jobId}`)
      eventSourceRef.current = eventSource

      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          
          if (data.type === 'progress') {
            updateCaseStatus(index, {
              currentMessage: data.message || 'Processing...',
              progress: data.progress || 0
            })
          } else if (data.type === 'complete') {
            updateCaseStatus(index, {
              currentMessage: 'Extraction completed',
              progress: 100
            })
            eventSource.close()
            eventSourceRef.current = null
            resolve(true)
          } else if (data.type === 'error') {
            updateCaseStatus(index, {
              status: 'failed',
              error: data.message || 'Extraction failed'
            })
            eventSource.close()
            eventSourceRef.current = null
            resolve(false)
          }
        } catch (e) {
          console.error('Failed to parse SSE event:', e)
        }
      }

      eventSource.onerror = (err) => {
        console.error('EventSource error:', err)
        if (eventSource.readyState === 2) {
          updateCaseStatus(index, {
            status: 'failed',
            error: 'Connection to extraction stream failed'
          })
          eventSource.close()
          eventSourceRef.current = null
          resolve(false)
        }
      }
    })
  }

  const processKGUpload = async (index: number, caseId: string): Promise<boolean> => {
    try {
      updateCaseStatus(index, {
        status: 'uploading-kg',
        currentMessage: 'Uploading to Knowledge Graph...'
      })

      const kgRes = await fetch('/api/kg/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: caseId })
      })

      const kgData = await kgRes.json()

      if (!kgRes.ok || !kgData.success) {
        throw new Error(kgData.error || 'KG upload failed')
      }

      const embeddingsComplete = kgData.embeddings_complete !== false
      const missingCount = kgData.embeddings_summary?.missing ?? 0

      updateCaseStatus(index, {
        status: 'completed',
        currentMessage: embeddingsComplete 
          ? 'Successfully uploaded to Knowledge Graph'
          : `Uploaded to KG (${missingCount} embeddings missing)`,
        embeddingsComplete,
        missingEmbeddingsCount: missingCount
      })

      return true
    } catch (error: any) {
      updateCaseStatus(index, {
        status: 'failed',
        error: `KG upload failed: ${error.message}`
      })
      return false
    }
  }

  const processSingleCase = async (statusIndex: number, fileIndex: number): Promise<boolean> => {
    const { file, prescreening } = filesWithPrescreening[fileIndex]
    
    try {
      updateCaseStatus(statusIndex, {
        status: 'extracting',
        currentMessage: 'Uploading file...',
        progress: 0
      })

      const fd = new FormData()
      fd.append('file', file)
      
      // Include prescreened text only for courtlistener/ocr (NOT pdf_text)
      // For pdf_text: prescreening only extracted first few pages for quality check,
      // so we need the extraction job to read the full PDF
      if (prescreening.text && prescreening.textSource && prescreening.textSource !== 'pdf_text') {
        fd.append('prescreened_text', prescreening.text)
        fd.append('text_source', prescreening.textSource)
      }
      
      const uploadRes = await fetch('/api/cases/upload', {
        method: 'POST',
        body: fd
      })
      
      if (!uploadRes.ok) {
        const errorData = await uploadRes.json()
        throw new Error(errorData.error || 'Upload failed')
      }
      
      const uploadData = await uploadRes.json()
      const { jobId, caseId } = uploadData

      if (!jobId || !caseId) {
        throw new Error('Invalid response from upload endpoint')
      }

      updateCaseStatus(statusIndex, {
        jobId,
        caseId,
        currentMessage: 'Extracting case data...'
      })

      const extractionSuccess = await processExtractionStream(statusIndex, jobId)
      
      if (!extractionSuccess) {
        return false
      }

      const kgSuccess = await processKGUpload(statusIndex, caseId)
      
      return kgSuccess
    } catch (error: any) {
      updateCaseStatus(statusIndex, {
        status: 'failed',
        error: error.message || 'Unknown error occurred'
      })
      return false
    }
  }

  const startBulkProcessing = async () => {
    // Filter to only process files that passed prescreening (not failed)
    const filesToProcess = filesWithPrescreening
      .map((f, i) => ({ file: f, fileIndex: i }))
      .filter(({ file }) => file.prescreening.status !== 'failed')
    
    // Initialize case statuses only for files we'll process
    setCaseStatuses(filesToProcess.map(({ file }) => ({
      filename: file.file.name,
      status: 'pending'
    })))
    
    setProcessing(true)
    setCurrentIndex(0)

    for (let i = 0; i < filesToProcess.length; i++) {
      setCurrentIndex(i)
      // Pass both the status index (i) and the original file index
      await processSingleCase(i, filesToProcess[i].fileIndex)
    }

    setProcessing(false)
    setCurrentIndex(-1)
  }

  const resetForm = () => {
    setFilesWithPrescreening([])
    setCaseStatuses([])
    setCurrentIndex(-1)
    setProcessing(false)
    setPrescreening(false)
    setReviewingIndex(null)
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }
  }

  // Show loading while checking auth
  if (sessionStatus === 'loading' || !session || !isAdmin) {
    return <div className="p-8">Loading...</div>
  }

  // Calculate counts
  const readyCount = filesWithPrescreening.filter(f => 
    f.prescreening.status === 'text_layer_ok' || f.prescreening.status === 'confirmed'
  ).length
  const needsReviewCount = filesWithPrescreening.filter(f => 
    f.prescreening.status === 'courtlistener_resolved' || f.prescreening.status === 'ocr_resolved'
  ).length
  const failedPrescreeningCount = filesWithPrescreening.filter(f => 
    f.prescreening.status === 'failed'
  ).length
  const analyzingCount = filesWithPrescreening.filter(f => 
    f.prescreening.status === 'analyzing' || f.prescreening.status === 'pending'
  ).length

  const allReady = filesWithPrescreening.length > 0 && 
    readyCount === filesWithPrescreening.length - failedPrescreeningCount &&
    analyzingCount === 0

  const completedCount = caseStatuses.filter(s => s.status === 'completed' && s.embeddingsComplete !== false).length
  const warningCount = caseStatuses.filter(s => s.status === 'completed' && s.embeddingsComplete === false).length
  const failedCount = caseStatuses.filter(s => s.status === 'failed').length

  // Review modal
  const reviewingFile = reviewingIndex !== null ? filesWithPrescreening[reviewingIndex] : null

  return (
    <div className="p-8 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Admin: Bulk Case Upload</h1>
        <span className="text-sm text-gray-600">
          Logged in as: {session.user?.email}
        </span>
      </div>

      <div className="bg-yellow-50 border border-yellow-200 rounded p-4 text-sm">
        <strong>⚠️ Admin Only:</strong> This page processes multiple cases sequentially, 
        extracting each one and uploading to the Knowledge Graph before moving to the next.
        PDFs are pre-screened to detect flattened documents and resolve them via CourtListener or OCR.
      </div>

      {/* File Selection (only show when not processing) */}
      {!processing && caseStatuses.length === 0 && (
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-2">
              Select Case Documents (.docx or .pdf)
            </label>
            <input
              type="file"
              multiple
              accept=".docx,.pdf"
              onChange={handleFilesChange}
              disabled={prescreening}
              className="block w-full text-sm text-gray-500
                file:mr-4 file:py-2 file:px-4
                file:rounded file:border-0
                file:text-sm file:font-semibold
                file:bg-blue-50 file:text-blue-700
                hover:file:bg-blue-100
                disabled:opacity-50"
            />
          </div>

          {/* Prescreening Status */}
          {filesWithPrescreening.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="font-medium">Pre-screening Status</h3>
                {prescreening && (
                  <span className="text-sm text-blue-600">Analyzing...</span>
                )}
                {!prescreening && (
                  <span className="text-sm text-gray-600">
                    Ready: {readyCount} | Needs Review: {needsReviewCount} | Failed: {failedPrescreeningCount}
                  </span>
                )}
              </div>

              <div className="space-y-2 max-h-80 overflow-y-auto">
                {filesWithPrescreening.map((item, idx) => (
                  <div
                    key={idx}
                    className={`p-3 rounded border text-sm ${
                      item.prescreening.status === 'text_layer_ok' || item.prescreening.status === 'confirmed'
                        ? 'bg-green-50 border-green-200'
                        : item.prescreening.status === 'courtlistener_resolved' || item.prescreening.status === 'ocr_resolved'
                        ? 'bg-amber-50 border-amber-200'
                        : item.prescreening.status === 'failed'
                        ? 'bg-red-50 border-red-200'
                        : 'bg-gray-50 border-gray-200'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex-1 min-w-0">
                        <div className="font-medium truncate">{item.file.name}</div>
                        {item.prescreening.status === 'analyzing' && (
                          <div className="text-xs text-gray-600 mt-1">Analyzing PDF...</div>
                        )}
                        {item.prescreening.status === 'text_layer_ok' && (
                          <div className="text-xs text-green-600 mt-1">✓ Text layer OK</div>
                        )}
                        {item.prescreening.status === 'confirmed' && (
                          <div className="text-xs text-green-600 mt-1">✓ Confirmed</div>
                        )}
                        {item.prescreening.status === 'courtlistener_resolved' && (
                          <div className="text-xs text-amber-700 mt-1">
                            ⚠️ Resolved via CourtListener ({Math.round((item.prescreening.confidence || 0) * 100)}% confidence)
                            {item.prescreening.courtlistenerMetadata?.case_name && (
                              <span className="block text-amber-600">
                                {item.prescreening.courtlistenerMetadata.case_name}
                              </span>
                            )}
                          </div>
                        )}
                        {item.prescreening.status === 'ocr_resolved' && (
                          <div className="text-xs text-amber-700 mt-1">
                            ⚠️ Text extracted via OCR - please verify
                          </div>
                        )}
                        {item.prescreening.status === 'failed' && (
                          <div className="text-xs text-red-600 mt-1">
                            ✗ {item.prescreening.error || 'Pre-screening failed'}
                          </div>
                        )}
                        {item.prescreening.warnings && item.prescreening.warnings.length > 0 && (
                          <div className="text-xs text-amber-600 mt-1">
                            {item.prescreening.warnings.join('; ')}
                          </div>
                        )}
                      </div>
                      
                      <div className="ml-3 flex-shrink-0">
                        {(item.prescreening.status === 'courtlistener_resolved' || item.prescreening.status === 'ocr_resolved') && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setReviewingIndex(idx)}
                          >
                            Review
                          </Button>
                        )}
                        {item.prescreening.status === 'pending' && (
                          <span className="text-gray-400">⏳</span>
                        )}
                        {item.prescreening.status === 'analyzing' && (
                          <span className="text-blue-500 animate-pulse">🔍</span>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              {/* Start Processing Button */}
              {!prescreening && filesWithPrescreening.length > 0 && (
                <Button
                  onClick={startBulkProcessing}
                  disabled={!allReady || needsReviewCount > 0 || readyCount === 0}
                  className="w-full"
                >
                  {needsReviewCount > 0 
                    ? `Review ${needsReviewCount} file(s) before processing`
                    : allReady && readyCount > 0
                    ? failedPrescreeningCount > 0
                      ? `Start Processing ${readyCount} file${readyCount !== 1 ? 's' : ''} (${failedPrescreeningCount} skipped)`
                      : `Start Processing (${readyCount} file${readyCount !== 1 ? 's' : ''})`
                    : allReady && readyCount === 0
                    ? 'No files ready to process'
                    : 'Waiting for pre-screening...'
                  }
                </Button>
              )}

              {failedPrescreeningCount > 0 && (
                <p className="text-xs text-gray-500">
                  {failedPrescreeningCount} file(s) failed pre-screening and will be skipped.
                </p>
              )}
            </div>
          )}
        </div>
      )}

      {/* Processing Status */}
      {caseStatuses.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">Processing Status</h2>
            {!processing && (
              <div className="text-sm text-gray-600">
                Completed: {completedCount} {warningCount > 0 && `| Warnings: ${warningCount}`} | Failed: {failedCount} | Total: {caseStatuses.length}
              </div>
            )}
          </div>
          
          <div className="space-y-2">
            {caseStatuses.map((caseStatus, idx) => (
              <div
                key={idx}
                className={`p-4 rounded border transition-colors ${
                  caseStatus.status === 'completed' && caseStatus.embeddingsComplete === false
                    ? 'bg-amber-50 border-amber-200'
                    : caseStatus.status === 'completed'
                    ? 'bg-green-50 border-green-200'
                    : caseStatus.status === 'failed'
                    ? 'bg-red-50 border-red-200'
                    : caseStatus.status === 'pending'
                    ? 'bg-gray-50 border-gray-200'
                    : 'bg-blue-50 border-blue-200'
                } ${idx === currentIndex ? 'ring-2 ring-blue-400' : ''}`}
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-sm truncate">{caseStatus.filename}</div>
                    {caseStatus.caseId && (
                      <div className="text-xs text-gray-600 mt-1 font-mono">
                        Case ID: {caseStatus.caseId}
                      </div>
                    )}
                    {caseStatus.currentMessage && (
                      <div className="text-xs text-gray-700 mt-1">
                        {caseStatus.currentMessage}
                      </div>
                    )}
                    {caseStatus.status === 'extracting' && caseStatus.progress !== undefined && (
                      <div className="mt-2">
                        <div className="w-full bg-gray-200 rounded-full h-2 overflow-hidden">
                          <div
                            className="h-full bg-blue-500 transition-all duration-300"
                            style={{ width: `${caseStatus.progress}%` }}
                          />
                        </div>
                        <div className="text-xs text-gray-600 mt-1">{caseStatus.progress}%</div>
                      </div>
                    )}
                  </div>
                  
                  <div className="flex items-center gap-2 ml-4">
                    {caseStatus.status === 'pending' && (
                      <span className="text-sm text-gray-600 whitespace-nowrap">⏳ Waiting...</span>
                    )}
                    {caseStatus.status === 'extracting' && (
                      <span className="text-sm text-blue-600 whitespace-nowrap">📄 Extracting...</span>
                    )}
                    {caseStatus.status === 'uploading-kg' && (
                      <span className="text-sm text-blue-600 whitespace-nowrap">🔄 Uploading to KG...</span>
                    )}
                    {caseStatus.status === 'completed' && caseStatus.embeddingsComplete !== false && (
                      <span className="text-sm text-green-600 whitespace-nowrap">✅ Complete</span>
                    )}
                    {caseStatus.status === 'completed' && caseStatus.embeddingsComplete === false && (
                      <span className="text-sm text-amber-600 whitespace-nowrap">⚠️ Missing embeddings</span>
                    )}
                    {caseStatus.status === 'failed' && (
                      <span className="text-sm text-red-600 whitespace-nowrap">❌ Failed</span>
                    )}
                  </div>
                </div>
                
                {caseStatus.error && (
                  <div className="mt-2 text-xs text-red-600 bg-red-100 rounded p-2">
                    Error: {caseStatus.error}
                  </div>
                )}
              </div>
            ))}
          </div>

          {!processing && (
            <div className="flex gap-2">
              <Button
                onClick={resetForm}
                variant="outline"
                className="flex-1"
              >
                Upload More Cases
              </Button>
              {completedCount > 0 && (
                <Button
                  onClick={() => router.push('/cases')}
                  className="flex-1"
                >
                  View Cases ({completedCount} processed)
                </Button>
              )}
            </div>
          )}

          {processing && (
            <div className="bg-blue-50 border border-blue-200 rounded p-4 text-center text-sm text-blue-700">
              Processing case {currentIndex + 1} of {caseStatuses.length}... Please do not close this page.
            </div>
          )}
        </div>
      )}

      {/* Review Modal */}
      {reviewingFile && reviewingIndex !== null && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col">
            <div className="p-4 border-b flex items-center justify-between">
              <h3 className="font-semibold">Review: {reviewingFile.file.name}</h3>
              <button
                onClick={() => setReviewingIndex(null)}
                className="text-gray-500 hover:text-gray-700"
              >
                ✕
              </button>
            </div>
            
            <div className="flex-1 overflow-auto p-4 space-y-4">
              {/* Source Info */}
              <div className="bg-blue-50 border border-blue-200 rounded p-3 text-sm">
                <div className="font-medium mb-1">
                  {reviewingFile.prescreening.status === 'courtlistener_resolved' 
                    ? '📚 Text from CourtListener'
                    : '🔍 Text extracted via OCR'
                  }
                </div>
                {reviewingFile.prescreening.courtlistenerMetadata && (
                  <div className="space-y-1 text-gray-700">
                    <div><strong>Case:</strong> {reviewingFile.prescreening.courtlistenerMetadata.case_name}</div>
                    {reviewingFile.prescreening.courtlistenerMetadata.court && (
                      <div><strong>Court:</strong> {reviewingFile.prescreening.courtlistenerMetadata.court}</div>
                    )}
                    {reviewingFile.prescreening.courtlistenerMetadata.date_filed && (
                      <div><strong>Date:</strong> {reviewingFile.prescreening.courtlistenerMetadata.date_filed}</div>
                    )}
                    {reviewingFile.prescreening.courtlistenerMetadata.citation && (
                      <div><strong>Citation:</strong> {reviewingFile.prescreening.courtlistenerMetadata.citation}</div>
                    )}
                    <div>
                      <strong>Confidence:</strong> {Math.round(reviewingFile.prescreening.confidence! * 100)}%
                    </div>
                    <a 
                      href={reviewingFile.prescreening.courtlistenerMetadata.canonical_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:underline"
                    >
                      View on CourtListener →
                    </a>
                  </div>
                )}
                {reviewingFile.prescreening.warnings && reviewingFile.prescreening.warnings.length > 0 && (
                  <div className="mt-2 text-amber-700">
                    <strong>⚠️ Warnings:</strong> {reviewingFile.prescreening.warnings.join('; ')}
                  </div>
                )}
              </div>

              {/* Text Preview */}
              <div>
                <div className="font-medium mb-2">Extracted Text Preview:</div>
                <div className="bg-gray-50 border rounded p-3 max-h-80 overflow-y-auto font-mono text-xs whitespace-pre-wrap">
                  {reviewingFile.prescreening.text?.slice(0, 5000) || 'No text available'}
                  {reviewingFile.prescreening.text && reviewingFile.prescreening.text.length > 5000 && (
                    <div className="text-gray-500 mt-2">
                      ... ({reviewingFile.prescreening.text.length - 5000} more characters)
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="p-4 border-t flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => setReviewingIndex(null)}
              >
                Cancel
              </Button>
              <Button
                onClick={() => confirmPrescreening(reviewingIndex)}
              >
                Confirm - Use This Text
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
