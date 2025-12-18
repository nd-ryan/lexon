import { describe, it, expect, vi, beforeEach } from 'vitest'
import { NextRequest } from 'next/server'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'

vi.mock('next-auth/next', () => ({
  getServerSession: vi.fn(),
}))

vi.mock('@/lib/auth', () => ({
  authOptions: {},
}))

import { GET } from '../route'
import { getServerSession } from 'next-auth/next'

const mockedGetServerSession = vi.mocked(getServerSession)

const createParams = (caseId: string) => Promise.resolve({ caseId })

describe('GET /api/admin/neo4j-cases/[caseId]/graph', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    process.env.NEXT_PUBLIC_ADMIN_EMAIL = 'admin@example.com'
    process.env.AI_BACKEND_URL = 'http://localhost:8000'
    process.env.FASTAPI_API_KEY = 'test-api-key'
  })

  it('returns 401 for unauthenticated users', async () => {
    mockedGetServerSession.mockResolvedValue(null)
    const request = new NextRequest('http://localhost:3000/api/admin/neo4j-cases/c1/graph')
    const response = await GET(request, { params: createParams('c1') })
    expect(response.status).toBe(401)
  })

  it('proxies request to backend for admin users', async () => {
    mockedGetServerSession.mockResolvedValue({
      user: { email: 'admin@example.com' },
    } as any)

    const backendSpy = vi.fn()
    server.use(
      http.get('http://localhost:8000/api/ai/neo4j-cases/:caseId/graph', ({ request }) => {
        backendSpy(request)
        return HttpResponse.json({ success: true, nodes: [], relationships: [] }, { status: 200 })
      })
    )

    const request = new NextRequest('http://localhost:3000/api/admin/neo4j-cases/c1/graph')
    const response = await GET(request, { params: createParams('c1') })

    expect(response.status).toBe(200)
    expect(backendSpy).toHaveBeenCalledTimes(1)
    const intercepted = backendSpy.mock.calls[0][0] as Request
    expect(intercepted.headers.get('X-API-Key')).toBe('test-api-key')
  })
})


