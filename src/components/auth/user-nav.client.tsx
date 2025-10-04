'use client'

import { useSession, signOut } from 'next-auth/react'
import Link from 'next/link'
import { useState, useEffect } from 'react'

export default function UserNav() {
  const { data: session, status } = useSession()
  const [registrationEnabled, setRegistrationEnabled] = useState(false)

  useEffect(() => {
    // Fetch feature flags from API
    fetch('/api/features')
      .then(res => res.json())
      .then(data => setRegistrationEnabled(data.registrationEnabled))
      .catch(() => setRegistrationEnabled(false))
  }, [])

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
        {registrationEnabled && (
          <Link 
            href="/auth/signup"
            className="bg-indigo-600 hover:bg-indigo-700 text-white px-3 py-2 rounded-md text-sm font-medium"
          >
            Sign Up
          </Link>
        )}
      </div>
    )
  }

  return (
    <button
      onClick={() => signOut({ callbackUrl: '/' })}
      className="text-gray-700 hover:text-gray-900 px-3 py-2 rounded-md text-sm font-medium cursor-pointer"
    >
      Sign Out
    </button>
  )
}