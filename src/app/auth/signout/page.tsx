'use client'

import Link from 'next/link'
// import { useEffect } from 'react' // No longer strictly needed if not performing actions
// import { signOut } from 'next-auth/react' // No longer strictly needed
import { Button } from "@/components/ui/button"; // Added Button import
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"; // Added Card imports

export default function SignOutPage() {
  // Optionally, you could automatically trigger sign out again 
  // if a user lands here with an active session, but typically 
  // next-auth redirects here *after* signout is complete.

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <Card className="w-full max-w-md"> {/* Replaced div with Card */}
        <CardHeader>
          <CardTitle className="text-center text-3xl font-extrabold">
            You have been signed out
          </CardTitle>
          <CardDescription className="text-center">
            You have been successfully signed out of your account.
          </CardDescription>
        </CardHeader>
        <CardContent className="mt-6 flex flex-col gap-3">
          <Link href="/auth/signin" className="w-full">
            <Button className="w-full">
              Sign in again
            </Button>
          </Link>
          <Link href="/" className="w-full">
            <Button variant="outline" className="w-full">
              Go to Homepage
            </Button>
          </Link>
        </CardContent>
      </Card>
    </div>
  )
} 