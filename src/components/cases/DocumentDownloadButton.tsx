"use client"

import { useState } from 'react'
import { FileText } from 'lucide-react'

interface DocumentDownloadButtonProps {
  caseId: string
  hasFile: boolean
  className?: string
}

export function DocumentDownloadButton({ caseId, hasFile, className = '' }: DocumentDownloadButtonProps) {
  const [loading, setLoading] = useState(false)

  const handleClick = async (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    
    if (!hasFile || loading) return
    
    setLoading(true)
    try {
      const res = await fetch(`/api/cases/${caseId}/download`)
      const data = await res.json()
      
      if (data.success && data.url) {
        // Open the presigned URL in a new tab
        window.open(data.url, '_blank')
      } else {
        console.error('Failed to get download URL:', data.error || 'Unknown error')
      }
    } catch (error) {
      console.error('Failed to download document:', error)
    } finally {
      setLoading(false)
    }
  }

  if (!hasFile) {
    return (
      <div className={`relative group ${className}`}>
        <button
          type="button"
          disabled
          className="p-1.5 text-gray-300 cursor-not-allowed"
          aria-label="Source document not available"
        >
          <FileText className="w-4 h-4" />
        </button>
        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 px-2 py-1 text-xs text-white bg-gray-800 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none z-10">
          Source document not available
        </div>
      </div>
    )
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={loading}
      className={`p-1.5 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded transition-colors ${loading ? 'opacity-50' : ''} ${className}`}
      aria-label="View source document"
      title="View source document"
    >
      <FileText className="w-4 h-4" />
    </button>
  )
}
