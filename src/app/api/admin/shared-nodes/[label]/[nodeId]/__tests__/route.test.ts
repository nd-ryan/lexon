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
import { GET, PUT, DELETE } from '../route'
import { getServerSession } from 'next-auth/next'

const mockedGetServerSession = vi.mocked(getServerSession)

const createParams = (label: string, nodeId: string) => 
  Promise.resolve({ label, nodeId })

describe('GET /api/admin/shared-nodes/[label]/[nodeId]', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    process.env.NEXT_PUBLIC_ADMIN_EMAIL = 'admin@example.com'
    process.env.AI_BACKEND_URL = 'http://localhost:8000'
    process.env.FASTAPI_API_KEY = 'test-api-key'
  })

  it('returns 401 for unauthenticated users', async () => {
    mockedGetServerSession.mockResolvedValue(null)

    const request = new NextRequest('http://localhost:3000/api/admin/shared-nodes/Party/p1')
    const response = await GET(request, { params: createParams('Party', 'p1') })

    expect(response.status).toBe(401)
  })

  it('returns 401 for non-admin users', async () => {
    mockedGetServerSession.mockResolvedValue({
      user: { email: 'user@example.com' },
    } as any)

    const request = new NextRequest('http://localhost:3000/api/admin/shared-nodes/Party/p1')
    const response = await GET(request, { params: createParams('Party', 'p1') })

    expect(response.status).toBe(401)
  })

  it('proxies request to backend for admin users', async () => {
    mockedGetServerSession.mockResolvedValue({
      user: { email: 'admin@example.com' },
    } as any)

    const backendSpy = vi.fn()
    server.use(
      http.get('http://localhost:8000/api/ai/shared-nodes/:label/:nodeId', ({ request }) => {
        backendSpy(request)
        return HttpResponse.json({ success: true, node: {} }, { status: 200 })
      })
    )

    const request = new NextRequest('http://localhost:3000/api/admin/shared-nodes/Party/p1')
    const response = await GET(request, { params: createParams('Party', 'p1') })

    expect(response.status).toBe(200)
    expect(backendSpy).toHaveBeenCalledTimes(1)
    const intercepted = backendSpy.mock.calls[0][0] as Request
    expect(intercepted.headers.get('X-API-Key')).toBe('test-api-key')
  })
})

describe('PUT /api/admin/shared-nodes/[label]/[nodeId]', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    process.env.NEXT_PUBLIC_ADMIN_EMAIL = 'admin@example.com'
    process.env.AI_BACKEND_URL = 'http://localhost:8000'
    process.env.FASTAPI_API_KEY = 'test-api-key'
  })

  it('returns 401 for unauthenticated users', async () => {
    mockedGetServerSession.mockResolvedValue(null)

    const request = new NextRequest('http://localhost:3000/api/admin/shared-nodes/Party/p1', {
      method: 'PUT',
      body: JSON.stringify({ properties: { name: 'New Name' } }),
    })
    const response = await PUT(request, { params: createParams('Party', 'p1') })

    expect(response.status).toBe(401)
  })

  it('sends X-User-Id header to backend', async () => {
    mockedGetServerSession.mockResolvedValue({
      user: { email: 'admin@example.com', id: 'admin-user-id' },
    } as any)

    const backendSpy = vi.fn()
    server.use(
      http.put('http://localhost:8000/api/ai/shared-nodes/:label/:nodeId', async ({ request }) => {
        backendSpy(request)
        return HttpResponse.json({ success: true }, { status: 200 })
      })
    )

    const request = new NextRequest('http://localhost:3000/api/admin/shared-nodes/Party/p1', {
      method: 'PUT',
      body: JSON.stringify({ properties: { name: 'New Name' } }),
    })
    await PUT(request, { params: createParams('Party', 'p1') })

    expect(backendSpy).toHaveBeenCalledTimes(1)
    const intercepted = backendSpy.mock.calls[0][0] as Request
    expect(intercepted.headers.get('X-User-Id')).toMatch(/admin/)
  })

  it('forwards request body to backend', async () => {
    mockedGetServerSession.mockResolvedValue({
      user: { email: 'admin@example.com', id: 'admin-id' },
    } as any)

    const backendSpy = vi.fn()
    server.use(
      http.put('http://localhost:8000/api/ai/shared-nodes/:label/:nodeId', async ({ request }) => {
        backendSpy(request)
        return HttpResponse.json({ success: true }, { status: 200 })
      })
    )

    const body = { properties: { name: 'Updated Name' } }
    const request = new NextRequest('http://localhost:3000/api/admin/shared-nodes/Party/p1', {
      method: 'PUT',
      body: JSON.stringify(body),
    })
    await PUT(request, { params: createParams('Party', 'p1') })

    expect(backendSpy).toHaveBeenCalledTimes(1)
    const intercepted = backendSpy.mock.calls[0][0] as Request
    await expect(intercepted.json()).resolves.toEqual(body)
  })
})

describe('DELETE /api/admin/shared-nodes/[label]/[nodeId]', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    process.env.NEXT_PUBLIC_ADMIN_EMAIL = 'admin@example.com'
    process.env.AI_BACKEND_URL = 'http://localhost:8000'
    process.env.FASTAPI_API_KEY = 'test-api-key'
  })

  it('returns 401 for unauthenticated users', async () => {
    mockedGetServerSession.mockResolvedValue(null)

    const request = new NextRequest('http://localhost:3000/api/admin/shared-nodes/Party/p1', {
      method: 'DELETE',
    })
    const response = await DELETE(request, { params: createParams('Party', 'p1') })

    expect(response.status).toBe(401)
  })

  it('sends X-User-Id header to backend', async () => {
    mockedGetServerSession.mockResolvedValue({
      user: { email: 'admin@example.com', id: 'admin-user-id' },
    } as any)

    const backendSpy = vi.fn()
    server.use(
      http.delete('http://localhost:8000/api/ai/shared-nodes/:label/:nodeId', ({ request }) => {
        backendSpy(request)
        return HttpResponse.json({ success: true }, { status: 200 })
      })
    )

    const request = new NextRequest('http://localhost:3000/api/admin/shared-nodes/Party/p1', {
      method: 'DELETE',
    })
    await DELETE(request, { params: createParams('Party', 'p1') })

    expect(backendSpy).toHaveBeenCalledTimes(1)
    const intercepted = backendSpy.mock.calls[0][0] as Request
    expect(intercepted.headers.get('X-User-Id')).toMatch(/admin/)
  })

  it('forwards force_partial query parameter', async () => {
    mockedGetServerSession.mockResolvedValue({
      user: { email: 'admin@example.com', id: 'admin-id' },
    } as any)

    const backendSpy = vi.fn()
    server.use(
      http.delete('http://localhost:8000/api/ai/shared-nodes/:label/:nodeId', ({ request }) => {
        backendSpy(request)
        return HttpResponse.json({ success: true }, { status: 200 })
      })
    )

    const request = new NextRequest(
      'http://localhost:3000/api/admin/shared-nodes/Party/p1?force_partial=true',
      { method: 'DELETE' }
    )
    await DELETE(request, { params: createParams('Party', 'p1') })

    expect(backendSpy).toHaveBeenCalledTimes(1)
    const intercepted = backendSpy.mock.calls[0][0] as Request
    expect(new URL(intercepted.url).searchParams.get('force_partial')).toBe('true')
  })

  it('returns backend response status', async () => {
    mockedGetServerSession.mockResolvedValue({
      user: { email: 'admin@example.com', id: 'admin-id' },
    } as any)

    server.use(
      http.delete('http://localhost:8000/api/ai/shared-nodes/:label/:nodeId', () => {
        return HttpResponse.json({ error: 'Node not found' }, { status: 404 })
      })
    )

    const request = new NextRequest('http://localhost:3000/api/admin/shared-nodes/Party/p1', {
      method: 'DELETE',
    })
    const response = await DELETE(request, { params: createParams('Party', 'p1') })

    expect(response.status).toBe(404)
  })

  it('returns 500 on fetch error', async () => {
    mockedGetServerSession.mockResolvedValue({
      user: { email: 'admin@example.com', id: 'admin-id' },
    } as any)

    server.use(
      http.delete('http://localhost:8000/api/ai/shared-nodes/:label/:nodeId', () => {
        return HttpResponse.json({ error: 'Network error' }, { status: 500 })
      })
    )

    const request = new NextRequest('http://localhost:3000/api/admin/shared-nodes/Party/p1', {
      method: 'DELETE',
    })
    const response = await DELETE(request, { params: createParams('Party', 'p1') })

    expect(response.status).toBe(500)
  })
})
