'use client'

import { useState, useRef, useEffect } from 'react'
import Link from 'next/link'
import { useSession } from 'next-auth/react'
import type { Session } from 'next-auth'
import { hasAtLeastRole } from '@/lib/rbac'

const docsLinks = [
  { href: '/docs/api/swagger', label: 'Swagger UI', description: 'Interactive API explorer' },
  { href: '/docs/api/redoc', label: 'ReDoc', description: 'API reference documentation' },
  { href: '/docs/api/quickstart', label: 'Quick Start', description: 'Get started in 5 minutes' },
  { href: '/api/docs/postman', label: 'Postman Collection', description: 'Download for Postman', download: true },
]

export default function ApiDocsDropdown() {
  const [isOpen, setIsOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const { data: session } = useSession()
  const role = (session?.user as Session['user'])?.role
  const canSeeDocs = hasAtLeastRole(role, 'developer')

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Close dropdown on escape key
  useEffect(() => {
    function handleEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setIsOpen(false)
      }
    }

    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [])

  if (!canSeeDocs) {
    return null
  }

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-1 text-gray-700 hover:text-gray-900"
        aria-expanded={isOpen}
        aria-haspopup="true"
      >
        API Docs
        <svg
          className={`h-4 w-4 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isOpen && (
        <div className="absolute right-0 z-50 mt-2 w-64 rounded-md bg-white py-1 shadow-lg ring-1 ring-black ring-opacity-5">
          {docsLinks.map((link) => (
            link.download ? (
              <a
                key={link.href}
                href={link.href}
                download
                className="block px-4 py-2 hover:bg-gray-50"
                onClick={() => setIsOpen(false)}
              >
                <div className="text-sm font-medium text-gray-900">{link.label}</div>
                <div className="text-xs text-gray-500">{link.description}</div>
              </a>
            ) : (
              <Link
                key={link.href}
                href={link.href}
                className="block px-4 py-2 hover:bg-gray-50"
                onClick={() => setIsOpen(false)}
              >
                <div className="text-sm font-medium text-gray-900">{link.label}</div>
                <div className="text-xs text-gray-500">{link.description}</div>
              </Link>
            )
          ))}
        </div>
      )}
    </div>
  )
}
