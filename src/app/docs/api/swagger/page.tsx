'use client'

import { useEffect, useState } from 'react'
import { useSession } from 'next-auth/react'
import { useRouter } from 'next/navigation'
import type { Session } from 'next-auth'
import { hasAtLeastRole } from '@/lib/rbac'

export default function SwaggerPage() {
  const { data: session, status } = useSession()
  const router = useRouter()
  const [spec, setSpec] = useState<object | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [swaggerLoaded, setSwaggerLoaded] = useState(false)

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

  // Load Swagger UI script
  useEffect(() => {
    if (typeof window === 'undefined') return

    // Load CSS
    const link = document.createElement('link')
    link.rel = 'stylesheet'
    link.href = 'https://unpkg.com/swagger-ui-dist@5/swagger-ui.css'
    document.head.appendChild(link)

    // Load JS
    const script = document.createElement('script')
    script.src = 'https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js'
    script.onload = () => setSwaggerLoaded(true)
    document.body.appendChild(script)

    return () => {
      document.head.removeChild(link)
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
      .then(data => {
        // Rewrite servers for proxy
        data.servers = [
          { url: '/api/docs/proxy', description: 'Proxied via Next.js' }
        ]
        // Normalize paths
        if (data.paths) {
          const normalizedPaths: Record<string, unknown> = {}
          for (const [path, value] of Object.entries(data.paths)) {
            let normalizedPath = path
            if (path.startsWith('/external/v1')) {
              normalizedPath = path.slice('/external/v1'.length) || '/'
            } else if (path.startsWith('/v1')) {
              normalizedPath = path.slice('/v1'.length) || '/'
            }
            normalizedPaths[normalizedPath] = value
          }
          data.paths = normalizedPaths
        }
        setSpec(data)
      })
      .catch(err => setError(err.message))
  }, [canAccess, status])

  // Initialize Swagger UI
  useEffect(() => {
    if (!swaggerLoaded || !spec) return

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const SwaggerUIBundle = (window as any).SwaggerUIBundle
    if (!SwaggerUIBundle) return

    SwaggerUIBundle({
      spec,
      dom_id: '#swagger-ui',
      presets: [
        SwaggerUIBundle.presets.apis,
        SwaggerUIBundle.SwaggerUIStandalonePreset
      ],
      layout: 'BaseLayout'
    })
  }, [swaggerLoaded, spec])

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
    <div className="min-h-screen bg-white">
      <style jsx global>{`
        .swagger-ui .topbar { display: none; }
        .swagger-ui .info { margin: 30px 0; }
        .swagger-ui .info .title { font-size: 32px; font-weight: 600; }
        .swagger-ui .scheme-container { background: #f8f9fa; padding: 20px; }
      `}</style>
      <div id="swagger-ui" />
      {!spec && (
        <div className="flex min-h-[50vh] items-center justify-center">
          <div className="text-gray-500">Loading API documentation...</div>
        </div>
      )}
    </div>
  )
}
