'use client'

import { usePathname } from 'next/navigation'
import Link from 'next/link'
import UserNav from '@/components/auth/user-nav.client'
import AdminLink from '@/components/nav/AdminLink.client'

export default function Header() {
  const pathname = usePathname()
  
  // Don't show header on home page or auth pages
  if (pathname === '/' || pathname === '/auth/signin' || pathname === '/auth/signup') {
    return null
  }
  
  return (
    <header className="border-b bg-white">
      <div className="mx-auto w-full px-4">
        <div className="flex items-center justify-between py-3">
          <Link href="/search" className="text-2xl font-semibold tracking-tight">
            Lexon
          </Link>
          <div className="flex items-center gap-3">
            <Link href="/cases" className="text-gray-700 hover:text-gray-900">
              Cases
            </Link>
            <Link href="/search" className="text-gray-700 hover:text-gray-900">
              Search
            </Link>
            <Link href="/chat" className="text-gray-700 hover:text-gray-900">
              Chat
            </Link>
            <Link href="/cases/upload" className="text-gray-700 hover:text-gray-900">
              Upload
            </Link>
            <AdminLink />
            <UserNav />
          </div>
        </div>
      </div>
    </header>
  )
}

