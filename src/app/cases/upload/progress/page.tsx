"use client";
import { useEffect, useState, Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'

function UploadProgressContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const jobId = searchParams.get('jobId')
  const caseId = searchParams.get('caseId')
  
  const [status, setStatus] = useState<string>('Initializing...')
  const [phase, setPhase] = useState<string>('init')
  const [progress, setProgress] = useState<number>(0)
  const [error, setError] = useState<string>('')
  const [complete, setComplete] = useState(false)

  useEffect(() => {
    if (!jobId) {
      setError('No job ID provided')
      return
    }

    console.log('Connecting to progress stream for job:', jobId)
    
    // Use Next.js API proxy which handles FastAPI authentication
    const eventSource = new EventSource(`/api/cases/upload/progress/${jobId}`)
    
    console.log('EventSource created, readyState:', eventSource.readyState)
    
    eventSource.onopen = () => {
      console.log('EventSource connection opened')
    }

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        console.log('Progress event:', data)
        
        if (data.type === 'connected') {
          console.log('Connected to job stream')
        } else if (data.type === 'progress') {
          setStatus(data.message || 'Processing...')
          setPhase(data.phase || '')
          setProgress(data.progress || 0)
        } else if (data.type === 'complete') {
          setStatus(data.message || 'Extraction completed!')
          setProgress(100)
          setComplete(true)
          eventSource.close()
          
          // Redirect to case page after a short delay
          setTimeout(() => {
            router.push(`/cases/${caseId || data.caseId}`)
          }, 2000)
        } else if (data.type === 'error') {
          setError(data.message || 'An error occurred')
          setProgress(0)
          eventSource.close()
        } else if (data.type === 'end') {
          eventSource.close()
        } else if (data.type === 'keepalive') {
          // Ignore keepalive messages
        }
      } catch (e) {
        console.error('Failed to parse event:', e, event.data)
      }
    }

    eventSource.onerror = (err) => {
      console.error('EventSource error:', err)
      console.error('EventSource readyState:', eventSource.readyState)
      console.error('EventSource URL:', eventSource.url)
      setError('Connection lost. Please refresh the page.')
      eventSource.close()
    }

    return () => {
      eventSource.close()
    }
  }, [jobId, caseId, router])

  return (
    <div className="p-8 max-w-2xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold">Processing Case Upload</h1>
      
      {error ? (
        <div className="bg-red-50 border border-red-200 rounded p-4 text-red-700">
          <p className="font-semibold">Error</p>
          <p>{error}</p>
          <button
            onClick={() => router.push('/cases/upload')}
            className="mt-4 px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700"
          >
            Try Again
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="bg-blue-50 border border-blue-200 rounded p-4">
            <p className="text-sm text-blue-600 font-medium mb-2">Status: {phase.toUpperCase()}</p>
            <p className="text-gray-800">{status}</p>
          </div>
          
          <div className="w-full bg-gray-200 rounded-full h-4 overflow-hidden">
            <div
              className={`h-full ${complete ? 'bg-green-500' : 'bg-blue-500'} transition-all duration-500`}
              style={{ width: `${progress}%` }}
            />
          </div>
          
          <p className="text-center text-sm text-gray-600">{progress}% complete</p>
          
          {complete && (
            <div className="bg-green-50 border border-green-200 rounded p-4 text-green-700 text-center">
              <p className="font-semibold">✓ Extraction Complete!</p>
              <p className="text-sm">Redirecting to case details...</p>
            </div>
          )}
          
          {!complete && (
            <div className="text-center text-sm text-gray-500">
              <p>This process may take several minutes.</p>
              <p>Please keep this page open.</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function UploadProgressPage() {
  return (
    <Suspense fallback={<div className="p-8 max-w-2xl mx-auto">Loading...</div>}>
      <UploadProgressContent />
    </Suspense>
  )
}

