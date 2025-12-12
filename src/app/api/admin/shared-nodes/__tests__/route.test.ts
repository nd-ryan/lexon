import { describe, it, expect, vi, beforeEach } from 'vitest'
import { NextRequest } from 'next/server'

// Mock next-auth BEFORE importing the route
const getServerSession = vi.fn()
vi.mock('next-auth/next', () => ({
  getServerSession,
}))

// Mock auth options
vi.mock('@/lib/auth', () => ({
  authOptions: {},
}))

// Mock fetch
const mockFetch = vi.fn()
global.fetch = mockFetch

// Import AFTER mocks are set up
import { GET } from '../route'

describe('GET /api/admin/shared-nodes', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    process.env.NEXT_PUBLIC_ADMIN_EMAIL = 'admin@example.com'
    process.env.AI_BACKEND_URL = 'http://localhost:8000'
    process.env.FASTAPI_API_KEY = 'test-api-key'
  })

  it('returns 401 for unauthenticated users', async () => {
    getServerSession.mockResolvedValue(null)

    const request = new NextRequest('http://localhost:3000/api/admin/shared-nodes')
    const response = await GET(request)

    expect(response.status).toBe(401)
    const data = await response.json()
    expect(data.error).toBe('Unauthorized')
  })

  it('returns 401 for non-admin users', async () => {
    getServerSession.mockResolvedValue({
      user: { email: 'user@example.com' },
    } as any)

    const request = new NextRequest('http://localhost:3000/api/admin/shared-nodes')
    const response = await GET(request)

    expect(response.status).toBe(401)
  })

  it('proxies request to backend for admin users', async () => {
    getServerSession.mockResolvedValue({
      user: { email: 'admin@example.com' },
    } as any)

    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ success: true, nodes: [] }),
    } as any)

    const request = new NextRequest('http://localhost:3000/api/admin/shared-nodes?label=Party')
    const response = await GET(request)

    expect(response.status).toBe(200)
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/ai/shared-nodes'),
      expect.objectContaining({
        headers: expect.objectContaining({
          'X-API-Key': 'test-api-key',
        }),
      })
    )
  })

  it('forwards query parameters to backend', async () => {
    getServerSession.mockResolvedValue({
      user: { email: 'admin@example.com' },
    } as any)

    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ success: true, nodes: [] }),
    } as any)

    const request = new NextRequest(
      'http://localhost:3000/api/admin/shared-nodes?label=Party&orphaned_only=true&limit=50'
    )
    await GET(request)

    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('label=Party'),
      expect.any(Object)
    )
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('orphaned_only=true'),
      expect.any(Object)
    )
  })

  it('returns 500 on fetch error', async () => {
    getServerSession.mockResolvedValue({
      user: { email: 'admin@example.com' },
    } as any)

    mockFetch.mockRejectedValue(new Error('Network error'))

    const request = new NextRequest('http://localhost:3000/api/admin/shared-nodes')
    const response = await GET(request)

    expect(response.status).toBe(500)
  })
})
