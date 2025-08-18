"use client"

import { useSearchParams } from 'next/navigation'
import Link from 'next/link'
import Button from "@/components/ui/button"
import Card from "@/components/ui/card"
import { Suspense } from 'react';

function AuthErrorPageContent() {
  const searchParams = useSearchParams()
  const error = searchParams.get('error')

  const errorMessages: { [key: string]: string } = {
    CredentialsSignin: 'Invalid email or password. Please try again.',
    OAuthSignin: 'Error signing in with OAuth provider. Please try again.',
    OAuthCallback: 'Error processing OAuth callback. Please try again.',
    OAuthCreateAccount: 'Error creating account with OAuth. Please try again.',
    EmailCreateAccount: 'Error creating account with email. Please try again.',
    Callback: 'Error in callback handler. Please try again.',
    OAuthAccountNotLinked: 
      'This OAuth account is not linked to a user. If you have an existing account, please sign in with that method first, then link your OAuth account in your profile.',
    EmailSignin: 'Error sending sign-in email. Please try again.',
    SessionRequired: 'You must be signed in to view this page.',
    Default: 'An unexpected error occurred during authentication. Please try again.'
  }

  const message = error && errorMessages[error] ? errorMessages[error] : errorMessages.Default

  return (
    <section className="py-10">
      <div className="mx-auto max-w-md px-4">
        <Card>
          <div className="p-6">
            <h2 className="text-center text-xl font-semibold">Authentication Error</h2>
            <div className="my-3 text-center text-sm text-gray-700">
              {message}
            </div>
            <Link href="/auth/signin">
              <Button className="w-full">Return to Sign In</Button>
            </Link>
          </div>
        </Card>
      </div>
    </section>
  )
}

export default function AuthErrorPage() {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <AuthErrorPageContent />
    </Suspense>
  )
} 