import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import SharedNodesPage from './page'
import { useSession } from 'next-auth/react'
import { useRouter } from 'next/navigation'
import { server } from '@/test/server'
import { http, HttpResponse } from 'msw'

// Mock next-auth
vi.mock('next-auth/react', () => ({
  useSession: vi.fn(),
}))

// Mock next/navigation
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(),
}))

const mockedUseSession = vi.mocked(useSession)
const mockedUseRouter = vi.mocked(useRouter)

describe('SharedNodesPage', () => {
  const mockPush = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    mockedUseRouter.mockReturnValue({ push: mockPush } as any)
    window.localStorage.clear()
  })

  describe('Authentication', () => {
    it('shows loading state while session is loading', () => {
      mockedUseSession.mockReturnValue({
        data: null,
        status: 'loading',
      } as any)

      render(<SharedNodesPage />)
      expect(screen.getByText('Loading...')).toBeInTheDocument()
    })

    it('redirects non-admin users to home', async () => {
      mockedUseSession.mockReturnValue({
        data: { user: { email: 'user@example.com', role: 'user' } },
        status: 'authenticated',
      } as any)

      render(<SharedNodesPage />)

      await waitFor(() => {
        expect(mockPush).toHaveBeenCalledWith('/')
      })
    })

    it('redirects unauthenticated users to home', async () => {
      mockedUseSession.mockReturnValue({
        data: null,
        status: 'unauthenticated',
      } as any)

      render(<SharedNodesPage />)

      await waitFor(() => {
        expect(mockPush).toHaveBeenCalledWith('/')
      })
    })
  })

  describe('Page Rendering', () => {
    beforeEach(() => {
      mockedUseSession.mockReturnValue({
        data: { user: { email: 'admin@example.com', id: 'admin-id', role: 'admin' } },
        status: 'authenticated',
      } as any)
    })

    it('renders page title and description', async () => {
      render(<SharedNodesPage />)

      expect(screen.getByRole('heading', { name: /Shared Nodes/i })).toBeInTheDocument()
      expect(screen.getByText(/Manage non-case-unique nodes/i)).toBeInTheDocument()
    })

    it('renders node type dropdown', async () => {
      render(<SharedNodesPage />)

      await waitFor(() => {
        expect(screen.getByLabelText(/Node Type/i)).toBeInTheDocument()
      })
    })

    it('renders search input', async () => {
      render(<SharedNodesPage />)

      await waitFor(() => {
        expect(screen.getByPlaceholderText(/Filter by name or ID/i)).toBeInTheDocument()
      })
    })

    it('renders orphaned only checkbox', async () => {
      render(<SharedNodesPage />)

      await waitFor(() => {
        expect(screen.getByLabelText(/Orphaned only/i)).toBeInTheDocument()
      })
    })

    it('renders refresh button', async () => {
      render(<SharedNodesPage />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Refresh/i })).toBeInTheDocument()
      })
    })

    it('renders nodes table with data', async () => {
      render(<SharedNodesPage />)

      await waitFor(() => {
        expect(screen.getByText('John Smith')).toBeInTheDocument()
      }, { timeout: 3000 })

      // Check table headers
      expect(screen.getByText('Type')).toBeInTheDocument()
      expect(screen.getByText('Name')).toBeInTheDocument()
      expect(screen.getByText('Case Connections')).toBeInTheDocument()
      expect(screen.getByText('Status')).toBeInTheDocument()
      expect(screen.getByText('Preset')).toBeInTheDocument()
      expect(screen.getByText('Actions')).toBeInTheDocument()
    })

    it('shows node count in header', async () => {
      render(<SharedNodesPage />)

      await waitFor(() => {
        expect(screen.getByText(/nodes\)/i)).toBeInTheDocument()
      })
    })
  })

  describe('Filtering', () => {
    beforeEach(() => {
      mockedUseSession.mockReturnValue({
        data: { user: { email: 'admin@example.com', id: 'admin-id', role: 'admin' } },
        status: 'authenticated',
      } as any)
    })

    it('filters nodes by search query', async () => {
      const user = userEvent.setup()
      render(<SharedNodesPage />)

      await waitFor(() => {
        expect(screen.getByText('John Smith')).toBeInTheDocument()
      })

      const searchInput = screen.getByPlaceholderText(/Filter by name or ID/i)
      await user.type(searchInput, 'Acme')

      await waitFor(() => {
        expect(screen.getByText('Acme Corp')).toBeInTheDocument()
        expect(screen.queryByText('John Smith')).not.toBeInTheDocument()
      })
    })

    it('shows empty state when search has no results', async () => {
      const user = userEvent.setup()
      render(<SharedNodesPage />)

      await waitFor(() => {
        expect(screen.getByText('John Smith')).toBeInTheDocument()
      })

      const searchInput = screen.getByPlaceholderText(/Filter by name or ID/i)
      await user.type(searchInput, 'nonexistent')

      await waitFor(() => {
        expect(screen.getByText(/No nodes match/i)).toBeInTheDocument()
      })
    })

    it('changes node type and refetches', async () => {
      const user = userEvent.setup()
      render(<SharedNodesPage />)

      await waitFor(() => {
        expect(screen.getByLabelText(/Node Type/i)).toBeInTheDocument()
      })

      const select = screen.getByLabelText(/Node Type/i)
      await user.selectOptions(select, 'Domain')

      // Should trigger a refetch - the mock will filter to Domain nodes
      await waitFor(() => {
        expect(screen.getByText('Criminal Law')).toBeInTheDocument()
      })
    })
  })

  describe('Edit Modal', () => {
    beforeEach(() => {
      mockedUseSession.mockReturnValue({
        data: { user: { email: 'admin@example.com', id: 'admin-id', role: 'admin' } },
        status: 'authenticated',
      } as any)
    })

    it('opens edit modal when Edit button is clicked', async () => {
      const user = userEvent.setup()
      render(<SharedNodesPage />)

      await waitFor(() => {
        expect(screen.getByText('John Smith')).toBeInTheDocument()
      })

      const editButtons = screen.getAllByRole('button', { name: /Edit/i })
      await user.click(editButtons[0])

      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /Edit Party/i })).toBeInTheDocument()
      })
    })

    it('shows connected cases in edit modal', async () => {
      const user = userEvent.setup()
      render(<SharedNodesPage />)

      await waitFor(() => {
        expect(screen.getByText('John Smith')).toBeInTheDocument()
      })

      const editButtons = screen.getAllByRole('button', { name: /Edit/i })
      await user.click(editButtons[0])

      await waitFor(() => {
        expect(screen.getByText(/Connected Cases/i)).toBeInTheDocument()
        expect(screen.getByText('Smith v. Jones')).toBeInTheDocument()
      })
    })

    it('closes edit modal on Cancel', async () => {
      const user = userEvent.setup()
      render(<SharedNodesPage />)

      await waitFor(() => {
        expect(screen.getByText('John Smith')).toBeInTheDocument()
      })

      const editButtons = screen.getAllByRole('button', { name: /Edit/i })
      await user.click(editButtons[0])

      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /Edit Party/i })).toBeInTheDocument()
      })

      const cancelButton = screen.getByRole('button', { name: /Cancel/i })
      await user.click(cancelButton)

      await waitFor(() => {
        expect(screen.queryByRole('heading', { name: /Edit Party/i })).not.toBeInTheDocument()
      })
    })

    it('shows success message after successful update', async () => {
      const user = userEvent.setup()
      render(<SharedNodesPage />)

      await waitFor(() => {
        expect(screen.getByText('John Smith')).toBeInTheDocument()
      })

      const editButtons = screen.getAllByRole('button', { name: /Edit/i })
      await user.click(editButtons[0])

      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /Edit Party/i })).toBeInTheDocument()
      })

      const saveButton = screen.getByRole('button', { name: /Save Changes/i })
      await user.click(saveButton)

      await waitFor(() => {
        expect(screen.getByText(/updated successfully/i)).toBeInTheDocument()
      })
    })
  })

  describe('Delete Modal', () => {
    beforeEach(() => {
      mockedUseSession.mockReturnValue({
        data: { user: { email: 'admin@example.com', id: 'admin-id', role: 'admin' } },
        status: 'authenticated',
      } as any)
    })

    it('opens delete modal when Delete button is clicked', async () => {
      const user = userEvent.setup()
      render(<SharedNodesPage />)

      await waitFor(() => {
        expect(screen.getByText('John Smith')).toBeInTheDocument()
      })

      const deleteButtons = screen.getAllByRole('button', { name: /Delete/i })
      await user.click(deleteButtons[0])

      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /Delete Party/i })).toBeInTheDocument()
      })
    })

    it('shows warning message in delete modal', async () => {
      const user = userEvent.setup()
      render(<SharedNodesPage />)

      await waitFor(() => {
        expect(screen.getByText('John Smith')).toBeInTheDocument()
      })

      const deleteButtons = screen.getAllByRole('button', { name: /Delete/i })
      await user.click(deleteButtons[0])

      await waitFor(() => {
        expect(screen.getByText(/preserved in the Knowledge Graph/i)).toBeInTheDocument()
      })
    })

    it('shows connected cases in delete modal', async () => {
      const user = userEvent.setup()
      render(<SharedNodesPage />)

      await waitFor(() => {
        expect(screen.getByText('John Smith')).toBeInTheDocument()
      })

      const deleteButtons = screen.getAllByRole('button', { name: /Delete/i })
      await user.click(deleteButtons[0])

      await waitFor(() => {
        expect(screen.getByText(/Will be removed from/i)).toBeInTheDocument()
        expect(screen.getByText('Smith v. Jones')).toBeInTheDocument()
      })
    })

    it('shows min_per_case violation confirmation', async () => {
      const user = userEvent.setup()
      render(<SharedNodesPage />)

      await waitFor(() => {
        expect(screen.getByText('John Smith')).toBeInTheDocument()
      })

      // Click delete on a Party node (which triggers min_per_case violation in mock)
      const deleteButtons = screen.getAllByRole('button', { name: /Delete/i })
      await user.click(deleteButtons[0])

      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /Delete Party/i })).toBeInTheDocument()
      })

      // Click the delete button in the modal
      const confirmDelete = screen.getByRole('button', { name: /Detach from Cases/i })
      await user.click(confirmDelete)

      // Should show the min_per_case violation modal
      await waitFor(() => {
        expect(screen.getByText(/Cannot Detach From All Cases/i)).toBeInTheDocument()
      })
    })
  })

  describe('Error Handling', () => {
    beforeEach(() => {
      mockedUseSession.mockReturnValue({
        data: { user: { email: 'admin@example.com', id: 'admin-id', role: 'admin' } },
        status: 'authenticated',
      } as any)
    })

    it('shows error message when API fails', async () => {
      // Override the handler to return an error
      server.use(
        http.get('/api/admin/shared-nodes', () => {
          return HttpResponse.json({ error: 'Server error' }, { status: 500 })
        })
      )

      render(<SharedNodesPage />)

      await waitFor(() => {
        expect(screen.getByText(/Server error/i)).toBeInTheDocument()
      }, { timeout: 3000 })
    })
  })
})
