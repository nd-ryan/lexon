'use client'

import { useSession, signOut } from 'next-auth/react'
import Link from 'next/link'

export default function UserNav() {
  const { data: session, status } = useSession()

  if (status === 'loading') {
    return <div>Loading...</div>
  }

  if (!session) {
    return (
      <div className="flex space-x-4">
        <Link 
          href="/auth/signin"
          className="text-gray-700 hover:text-gray-900 px-3 py-2 rounded-md text-sm font-medium"
        >
          Sign In
        </Link>
        <Link 
          href="/auth/signup"
          className="bg-indigo-600 hover:bg-indigo-700 text-white px-3 py-2 rounded-md text-sm font-medium"
        >
          Sign Up
        </Link>
      </div>
    )
  }

  return (
    <div className="flex items-center space-x-4">
      <span className="text-gray-700">
        Welcome, {session.user?.name || session.user?.email}
      </span>
      <button
        onClick={() => signOut({ callbackUrl: '/' })}
        className="text-gray-700 hover:text-gray-900 px-3 py-2 rounded-md text-sm font-medium cursor-pointer"
      >
        Sign Out
      </button>
    </div>
  )
}