'use client'

import { useEffect, useState } from 'react'
import { useSession } from 'next-auth/react'
import { useRouter } from 'next/navigation'
import type { Session } from 'next-auth'
import { hasAtLeastRole } from '@/lib/rbac'

export default function RedocPage() {
  const { data: session, status } = useSession()
  const router = useRouter()
  const [spec, setSpec] = useState<object | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [redocLoaded, setRedocLoaded] = useState(false)

  const role = (session?.user as Session['user'])?.role
  const canAccess = hasAtLeastRole(role, 'developer')

  // Check auth
  useEffect(() => {
    if (status === 'loading') return
    if (!session) {
      router.push('/auth/signin')
      return
    }
    if (!canAccess) {
      router.push('/')
    }
  }, [session, status, canAccess, router])

  // Load ReDoc script
  useEffect(() => {
    if (typeof window === 'undefined') return

    const script = document.createElement('script')
    script.src = 'https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js'
    script.onload = () => setRedocLoaded(true)
    document.body.appendChild(script)

    return () => {
      document.body.removeChild(script)
    }
  }, [])

  // Fetch OpenAPI spec
  useEffect(() => {
    if (!canAccess || status !== 'authenticated') return

    fetch('/api/docs/openapi')
      .then(res => {
        if (!res.ok) throw new Error('Failed to fetch OpenAPI spec')
        return res.json()
      })
      .then(data => setSpec(data))
      .catch(err => setError(err.message))
  }, [canAccess, status])

  // Initialize ReDoc
  useEffect(() => {
    if (!redocLoaded || !spec) return

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const Redoc = (window as any).Redoc
    if (!Redoc) return

    const container = document.getElementById('redoc-container')
    if (!container) return

    // Clear any existing content
    container.innerHTML = ''

    Redoc.init(spec, {
      scrollYOffset: 60, // Account for header height
      hideDownloadButton: false,
      expandResponses: '200,201',
      pathInMiddlePanel: true,
      theme: {
        colors: {
          primary: { main: '#1a56db' }
        },
        typography: {
          fontSize: '15px',
          fontFamily: 'var(--font-geist-sans), -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
          headings: { fontFamily: 'var(--font-geist-sans), -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif' }
        },
        sidebar: { width: '280px' },
        rightPanel: { backgroundColor: '#263238' }
      }
    }, container)
  }, [redocLoaded, spec])

  if (status === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-gray-500">Loading...</div>
      </div>
    )
  }

  if (!canAccess) {
    return null
  }

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-red-500">Error: {error}</div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-white redoc-wrap">
      {/* Fix vertical alignment in Redoc right panel - examples should be at top, not centered */}
      <style>{`
        /* Redoc wraps each endpoint in a flex row that centers content vertically.
           Override to align at the top instead. Target multiple possible structures. */
        .redoc-wrap [data-section-id] > div {
          align-items: flex-start !important;
        }
        .redoc-wrap div[id^="operation"] > div {
          align-items: flex-start !important;
        }
        .redoc-wrap div[id^="tag/"] > div > div {
          align-items: flex-start !important;
        }
        /* Target styled-components generated classes (sc- prefix) */
        .redoc-wrap div[class^="sc-"] {
          align-items: flex-start !important;
        }
        .redoc-wrap div[class*=" sc-"] {
          align-items: flex-start !important;
        }
        /* Target the wrap container around content rows */
        .redoc-wrap .api-content > div {
          align-items: flex-start !important;
        }
        .redoc-wrap section > div {
          align-items: flex-start !important;
        }
      `}</style>
      <div id="redoc-container" />
      {!spec && (
        <div className="flex min-h-[50vh] items-center justify-center">
          <div className="text-gray-500">Loading API documentation...</div>
        </div>
      )}
    </div>
  )
}
