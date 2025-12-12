import { describe, it, expect, vi, beforeEach } from 'vitest'
import { NextRequest } from 'next/server'

// Mock fetch
const mockFetch = vi.fn()
global.fetch = mockFetch

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

    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ success: true, node: {} }),
    } as any)

    const request = new NextRequest('http://localhost:3000/api/admin/shared-nodes/Party/p1')
    const response = await GET(request, { params: createParams('Party', 'p1') })

    expect(response.status).toBe(200)
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/ai/shared-nodes/Party/p1'),
      expect.any(Object)
    )
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

    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ success: true }),
    } as any)

    const request = new NextRequest('http://localhost:3000/api/admin/shared-nodes/Party/p1', {
      method: 'PUT',
      body: JSON.stringify({ properties: { name: 'New Name' } }),
    })
    await PUT(request, { params: createParams('Party', 'p1') })

    expect(mockFetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        headers: expect.objectContaining({
          'X-User-Id': expect.stringMatching(/admin/),
        }),
      })
    )
  })

  it('forwards request body to backend', async () => {
    mockedGetServerSession.mockResolvedValue({
      user: { email: 'admin@example.com', id: 'admin-id' },
    } as any)

    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ success: true }),
    } as any)

    const body = { properties: { name: 'Updated Name' } }
    const request = new NextRequest('http://localhost:3000/api/admin/shared-nodes/Party/p1', {
      method: 'PUT',
      body: JSON.stringify(body),
    })
    await PUT(request, { params: createParams('Party', 'p1') })

    expect(mockFetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify(body),
      })
    )
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

    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ success: true }),
    } as any)

    const request = new NextRequest('http://localhost:3000/api/admin/shared-nodes/Party/p1', {
      method: 'DELETE',
    })
    await DELETE(request, { params: createParams('Party', 'p1') })

    expect(mockFetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        headers: expect.objectContaining({
          'X-User-Id': expect.stringMatching(/admin/),
        }),
      })
    )
  })

  it('forwards force_partial query parameter', async () => {
    mockedGetServerSession.mockResolvedValue({
      user: { email: 'admin@example.com', id: 'admin-id' },
    } as any)

    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ success: true }),
    } as any)

    const request = new NextRequest(
      'http://localhost:3000/api/admin/shared-nodes/Party/p1?force_partial=true',
      { method: 'DELETE' }
    )
    await DELETE(request, { params: createParams('Party', 'p1') })

    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('force_partial=true'),
      expect.any(Object)
    )
  })

  it('returns backend response status', async () => {
    mockedGetServerSession.mockResolvedValue({
      user: { email: 'admin@example.com', id: 'admin-id' },
    } as any)

    mockFetch.mockResolvedValue({
      ok: false,
      status: 404,
      json: () => Promise.resolve({ error: 'Node not found' }),
    } as any)

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

    mockFetch.mockRejectedValue(new Error('Network error'))

    const request = new NextRequest('http://localhost:3000/api/admin/shared-nodes/Party/p1', {
      method: 'DELETE',
    })
    const response = await DELETE(request, { params: createParams('Party', 'p1') })

    expect(response.status).toBe(500)
  })
})
