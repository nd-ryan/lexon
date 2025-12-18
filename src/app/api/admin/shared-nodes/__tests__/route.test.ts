import { describe, it, expect, vi, beforeEach } from 'vitest'
import { NextRequest } from 'next/server'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'

// Mock next-auth
vi.mock('next-auth/next', () => ({
  getServerSession: vi.fn(),
}))

// Mock auth options
vi.mock('@/lib/auth', () => ({
  authOptions: {},
}))

// Import AFTER mocks are set up
import { GET } from '../route'
import { getServerSession } from 'next-auth/next'

const mockedGetServerSession = vi.mocked(getServerSession)

describe('GET /api/admin/shared-nodes', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    process.env.NEXT_PUBLIC_ADMIN_EMAIL = 'admin@example.com'
    delete process.env.NEXT_PUBLIC_ADMIN_EMAILS
    process.env.AI_BACKEND_URL = 'http://localhost:8000'
    process.env.FASTAPI_API_KEY = 'test-api-key'
  })

  it('returns 401 for unauthenticated users', async () => {
    mockedGetServerSession.mockResolvedValue(null)

    const request = new NextRequest('http://localhost:3000/api/admin/shared-nodes')
    const response = await GET(request)

    expect(response.status).toBe(401)
    const data = await response.json()
    expect(data.error).toBe('Unauthorized')
  })

  it('returns 401 for non-admin users', async () => {
    mockedGetServerSession.mockResolvedValue({
      user: { email: 'user@example.com' },
    } as any)

    const request = new NextRequest('http://localhost:3000/api/admin/shared-nodes')
    const response = await GET(request)

    expect(response.status).toBe(401)
  })

  it('proxies request to backend for admin users', async () => {
    mockedGetServerSession.mockResolvedValue({
      user: { email: 'admin@example.com' },
    } as any)

    const backendSpy = vi.fn()
    server.use(
      http.get('http://localhost:8000/api/ai/shared-nodes', ({ request }) => {
        backendSpy(request)
        return HttpResponse.json({ success: true, nodes: [] }, { status: 200 })
      })
    )

    const request = new NextRequest('http://localhost:3000/api/admin/shared-nodes?label=Party')
    const response = await GET(request)

    expect(response.status).toBe(200)
    expect(backendSpy).toHaveBeenCalledTimes(1)
    const intercepted = backendSpy.mock.calls[0][0] as Request
    expect(intercepted.headers.get('X-API-Key')).toBe('test-api-key')
  })

  it('allows any email included in NEXT_PUBLIC_ADMIN_EMAILS', async () => {
    delete process.env.NEXT_PUBLIC_ADMIN_EMAIL
    process.env.NEXT_PUBLIC_ADMIN_EMAILS = 'admin@example.com,other@example.com'

    mockedGetServerSession.mockResolvedValue({
      user: { email: 'other@example.com' },
    } as any)

    server.use(
      http.get('http://localhost:8000/api/ai/shared-nodes', () => {
        return HttpResponse.json({ success: true, nodes: [] }, { status: 200 })
      })
    )

    const request = new NextRequest('http://localhost:3000/api/admin/shared-nodes?label=Party')
    const response = await GET(request)

    expect(response.status).toBe(200)
  })

  it('forwards query parameters to backend', async () => {
    mockedGetServerSession.mockResolvedValue({
      user: { email: 'admin@example.com' },
    } as any)

    const backendSpy = vi.fn()
    server.use(
      http.get('http://localhost:8000/api/ai/shared-nodes', ({ request }) => {
        backendSpy(request)
        return HttpResponse.json({ success: true, nodes: [] }, { status: 200 })
      })
    )

    const request = new NextRequest(
      'http://localhost:3000/api/admin/shared-nodes?label=Party&orphaned_only=true&limit=50'
    )
    await GET(request)

    expect(backendSpy).toHaveBeenCalledTimes(1)
    const intercepted = backendSpy.mock.calls[0][0] as Request
    const url = new URL(intercepted.url)
    expect(url.searchParams.get('label')).toBe('Party')
    expect(url.searchParams.get('orphaned_only')).toBe('true')
    expect(url.searchParams.get('limit')).toBe('50')
  })

  it('returns 500 on fetch error', async () => {
    mockedGetServerSession.mockResolvedValue({
      user: { email: 'admin@example.com' },
    } as any)

    server.use(
      http.get('http://localhost:8000/api/ai/shared-nodes', () => {
        return HttpResponse.json({ error: 'Network error' }, { status: 500 })
      })
    )

    const request = new NextRequest('http://localhost:3000/api/admin/shared-nodes')
    const response = await GET(request)

    expect(response.status).toBe(500)
  })
})
