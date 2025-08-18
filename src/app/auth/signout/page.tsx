"use client"

import Link from 'next/link'
import Button from "@/components/ui/button"
import Card from "@/components/ui/card"

export default function SignOutPage() {
  // Optionally, you could automatically trigger sign out again 
  // if a user lands here with an active session, but typically 
  // next-auth redirects here *after* signout is complete.

  return (
    <section className="py-10">
      <div className="mx-auto max-w-md px-4">
        <Card>
          <div className="p-6">
            <h2 className="text-center text-xl font-semibold">You have been signed out</h2>
            <p className="text-center text-sm text-gray-600 mb-3">You have been successfully signed out of your account.</p>
            <div className="mt-3 flex flex-col gap-3">
              <Link href="/auth/signin">
                <Button className="w-full">Sign in again</Button>
              </Link>
              <Link href="/">
                <Button variant="outline" className="w-full">Go to Homepage</Button>
              </Link>
            </div>
          </div>
        </Card>
      </div>
    </section>
  )
} 