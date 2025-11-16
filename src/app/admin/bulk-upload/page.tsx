"use client";
import { useState, useEffect, useRef } from 'react'
import { useSession } from 'next-auth/react'
import { useRouter } from 'next/navigation'
import Button from '@/components/ui/button'

interface CaseStatus {
  filename: string
  status: 'pending' | 'extracting' | 'uploading-kg' | 'completed' | 'failed'
  error?: string
  caseId?: string
  jobId?: string
  currentMessage?: string
  progress?: number
}

export default function BulkUploadPage() {
  const { data: session, status: sessionStatus } = useSession()
  const router = useRouter()
  const [files, setFiles] = useState<File[]>([])
  const [processing, setProcessing] = useState(false)
  const [caseStatuses, setCaseStatuses] = useState<CaseStatus[]>([])
  const [currentIndex, setCurrentIndex] = useState<number>(-1)
  const eventSourceRef = useRef<EventSource | null>(null)

  const adminEmail = process.env.NEXT_PUBLIC_ADMIN_EMAIL

  // Protect the page - only allow admin email
  useEffect(() => {
    if (sessionStatus === 'loading') return
    if (!session || !adminEmail || session.user?.email !== adminEmail) {
      router.replace('/cases')
    }
  }, [session, sessionStatus, router, adminEmail])

  const handleFilesChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = Array.from(e.target.files || [])
    setFiles(selectedFiles)
    setCaseStatuses(selectedFiles.map(f => ({
      filename: f.name,
      status: 'pending'
    })))
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

      updateCaseStatus(index, {
        status: 'completed',
        currentMessage: 'Successfully uploaded to Knowledge Graph'
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

  const processSingleCase = async (index: number): Promise<boolean> => {
    const file = files[index]
    
    try {
      // Step 1: Upload file and start extraction
      updateCaseStatus(index, {
        status: 'extracting',
        currentMessage: 'Uploading file...',
        progress: 0
      })

      const fd = new FormData()
      fd.append('file', file)
      
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

      updateCaseStatus(index, {
        jobId,
        caseId,
        currentMessage: 'Extracting case data...'
      })

      // Step 2: Monitor extraction via SSE stream
      const extractionSuccess = await processExtractionStream(index, jobId)
      
      if (!extractionSuccess) {
        return false
      }

      // Step 3: Upload to Knowledge Graph
      const kgSuccess = await processKGUpload(index, caseId)
      
      return kgSuccess
    } catch (error: any) {
      updateCaseStatus(index, {
        status: 'failed',
        error: error.message || 'Unknown error occurred'
      })
      return false
    }
  }

  const startBulkProcessing = async () => {
    setProcessing(true)
    setCurrentIndex(0)

    // Process cases sequentially
    for (let i = 0; i < files.length; i++) {
      setCurrentIndex(i)
      await processSingleCase(i)
    }

    setProcessing(false)
    setCurrentIndex(-1)
  }

  const resetForm = () => {
    setFiles([])
    setCaseStatuses([])
    setCurrentIndex(-1)
    setProcessing(false)
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }
  }

  // Show loading while checking auth
  if (sessionStatus === 'loading' || !session || !adminEmail || session.user?.email !== adminEmail) {
    return <div className="p-8">Loading...</div>
  }

  const completedCount = caseStatuses.filter(s => s.status === 'completed').length
  const failedCount = caseStatuses.filter(s => s.status === 'failed').length

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
        The process ensures cases are added to the graph in order.
      </div>

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
              className="block w-full text-sm text-gray-500
                file:mr-4 file:py-2 file:px-4
                file:rounded file:border-0
                file:text-sm file:font-semibold
                file:bg-blue-50 file:text-blue-700
                hover:file:bg-blue-100"
            />
          </div>

          <Button
            onClick={startBulkProcessing}
            disabled={files.length === 0}
            className="w-full"
          >
            Start Bulk Processing ({files.length} {files.length === 1 ? 'file' : 'files'})
          </Button>
        </div>
      )}

      {caseStatuses.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">Processing Status</h2>
            {!processing && (
              <div className="text-sm text-gray-600">
                Completed: {completedCount} | Failed: {failedCount} | Total: {caseStatuses.length}
              </div>
            )}
          </div>

          {/* Show start button if not yet processing */}
          {!processing && completedCount === 0 && failedCount === 0 && (
            <Button
              onClick={startBulkProcessing}
              className="w-full"
            >
              Start Bulk Processing ({caseStatuses.length} {caseStatuses.length === 1 ? 'file' : 'files'})
            </Button>
          )}
          
          <div className="space-y-2">
            {caseStatuses.map((caseStatus, idx) => (
              <div
                key={idx}
                className={`p-4 rounded border transition-colors ${
                  caseStatus.status === 'completed'
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
                    {caseStatus.status === 'completed' && (
                      <span className="text-sm text-green-600 whitespace-nowrap">✅ Complete</span>
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
    </div>
  )
}

