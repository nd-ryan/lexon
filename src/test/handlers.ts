import { http, HttpResponse, HttpHandler } from 'msw'

// Mock data for shared nodes tests
export const mockSharedNodes = [
  {
    label: 'Party',
    id: 'party-001',
    name: 'John Smith',
    properties: { party_id: 'party-001', name: 'John Smith', party_type: 'individual' },
    connectionCount: 5,
    isOrphaned: false,
  },
  {
    label: 'Party',
    id: 'party-002',
    name: 'Acme Corp',
    properties: { party_id: 'party-002', name: 'Acme Corp', party_type: 'organization' },
    connectionCount: 3,
    isOrphaned: false,
  },
  {
    label: 'Domain',
    id: 'domain-001',
    name: 'Criminal Law',
    properties: { domain_id: 'domain-001', name: 'Criminal Law' },
    connectionCount: 10,
    isOrphaned: false,
  },
]

export const mockSharedLabels = ['Domain', 'Party', 'Forum', 'Jurisdiction', 'Doctrine']

export const mockConnectedCases = [
  { case_id: 'case-001', case_name: 'Smith v. Jones', citation: '123 F.3d 456' },
  { case_id: 'case-002', case_name: 'Doe v. Roe', citation: '789 F.2d 012' },
]

export const mockSchema = [
  { label: 'Domain', case_unique: false, can_create_new: false, min_per_case: 1, properties: {} },
  { label: 'Party', case_unique: false, can_create_new: true, min_per_case: 1, properties: {} },
  { label: 'Forum', case_unique: false, can_create_new: false, min_per_case: 1, properties: {} },
  { label: 'Case', case_unique: true, can_create_new: true, min_per_case: 1, properties: {} },
]

// Shared nodes API handlers
export const sharedNodesHandlers: HttpHandler[] = [
  // GET /api/schema - for fetching shared labels
  http.get('/api/schema', () => {
    return HttpResponse.json({ schema: mockSchema })
  }),

  // GET /api/admin/shared-nodes - list shared nodes
  http.get('/api/admin/shared-nodes', ({ request }) => {
    const url = new URL(request.url)
    const label = url.searchParams.get('label')
    const orphanedOnly = url.searchParams.get('orphaned_only') === 'true'

    let nodes = [...mockSharedNodes]
    
    // Only filter by label if a specific label is provided (not "all" or empty)
    if (label && label !== 'all' && label !== '') {
      nodes = nodes.filter(n => n.label === label)
    }
    
    if (orphanedOnly) {
      nodes = nodes.filter(n => n.isOrphaned)
    }

    return HttpResponse.json({
      success: true,
      nodes,
      labels: mockSharedLabels,
    })
  }),

  // GET /api/admin/shared-nodes/:label/:nodeId - get single node
  http.get('/api/admin/shared-nodes/:label/:nodeId', ({ params }) => {
    const { label, nodeId } = params
    const node = mockSharedNodes.find(n => n.label === label && n.id === nodeId)

    if (!node) {
      return HttpResponse.json({ error: 'Node not found' }, { status: 404 })
    }

    return HttpResponse.json({
      success: true,
      node,
      connectedCases: mockConnectedCases,
      minPerCase: 1,
    })
  }),

  // PUT /api/admin/shared-nodes/:label/:nodeId - update node
  http.put('/api/admin/shared-nodes/:label/:nodeId', async ({ params, request }) => {
    const { label, nodeId } = params
    const body = await request.json() as { properties: Record<string, unknown> }

    const node = mockSharedNodes.find(n => n.label === label && n.id === nodeId)

    if (!node) {
      return HttpResponse.json({ error: 'Node not found' }, { status: 404 })
    }

    return HttpResponse.json({
      success: true,
      node: {
        ...node,
        properties: { ...node.properties, ...body.properties },
      },
    })
  }),

  // DELETE /api/admin/shared-nodes/:label/:nodeId - delete node
  http.delete('/api/admin/shared-nodes/:label/:nodeId', ({ request, params }) => {
    const { label, nodeId } = params
    const url = new URL(request.url)
    const forcePartial = url.searchParams.get('force_partial') === 'true'

    const node = mockSharedNodes.find(n => n.label === label && n.id === nodeId)

    if (!node) {
      return HttpResponse.json({ error: 'Node not found' }, { status: 404 })
    }

    // Simulate min_per_case violation for Party nodes
    if (label === 'Party' && !forcePartial) {
      return HttpResponse.json({
        success: false,
        error: 'min_per_case_violation',
        message: 'Cannot delete: 1 case(s) would have fewer than 1 Party node(s)',
        blockedCases: [{ case_id: 'case-001', case_name: 'Smith v. Jones', currentCount: 1 }],
        deletableCases: [{ case_id: 'case-002', case_name: 'Doe v. Roe', currentCount: 2 }],
        minPerCase: 1,
      })
    }

    return HttpResponse.json({
      success: true,
      partial: forcePartial,
      message: forcePartial 
        ? 'Node remains connected to 1 case(s) due to min_per_case constraint'
        : 'Node deleted successfully',
      deletedFromCases: mockConnectedCases.map(c => ({ ...c, status: 'deleted' })),
      remainingCases: forcePartial ? [mockConnectedCases[0]] : [],
    })
  }),
]

// Extend this list per test suite to cover API routes.
export const handlers: HttpHandler[] = [
  ...sharedNodesHandlers,
]
