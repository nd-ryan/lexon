'use client'

import { useSession } from 'next-auth/react'
import Link from 'next/link'

export default function AdminLink() {
  const { data: session } = useSession()
  const adminEmail = process.env.NEXT_PUBLIC_ADMIN_EMAIL
  
  if (!session || !adminEmail || session.user?.email !== adminEmail) {
    return null
  }
  
  return (
    <Link href="/admin/bulk-upload" className="text-gray-700 hover:text-gray-900">
      Admin
    </Link>
  )
}

