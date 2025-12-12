import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import AdminLink from './AdminLink.client'
import { vi } from 'vitest'
import { useSession } from 'next-auth/react'

vi.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href, ...props }: any) => (
    <a href={href as string} {...props}>
      {children}
    </a>
  )
}))

vi.mock('next-auth/react', () => ({
  useSession: vi.fn()
}))

const mockedUseSession = vi.mocked(useSession)

describe('AdminLink', () => {
  beforeEach(() => {
    process.env.NEXT_PUBLIC_ADMIN_EMAIL = 'admin@example.com'
    mockedUseSession.mockReset()
  })

  it('returns null for non-admin sessions', () => {
    mockedUseSession.mockReturnValue({ data: { user: { email: 'user@example.com' } } } as any)

    const { container } = render(<AdminLink />)
    expect(container.firstChild).toBeNull()
  })

  it('shows menu items when admin clicks toggle and closes on outside click', () => {
    mockedUseSession.mockReturnValue({ data: { user: { email: 'admin@example.com' } } } as any)

    render(<AdminLink />)

    const button = screen.getByRole('button', { name: /admin/i })
    expect(button).toBeInTheDocument()

    fireEvent.click(button)
    expect(screen.getByText(/Bulk Case Upload/i)).toBeInTheDocument()
    expect(screen.getByText(/Shared Nodes/i)).toBeInTheDocument()

    fireEvent.mouseDown(document.body)
    expect(screen.queryByText(/Bulk Case Upload/i)).not.toBeInTheDocument()
  })
})
