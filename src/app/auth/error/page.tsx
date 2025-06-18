'use client'

import { useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
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
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="text-center text-3xl font-extrabold">
            Authentication Error
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded text-center">
            <p>{message}</p>
          </div>
          <Button asChild className="w-full">
            <Link href="/auth/signin">
              Return to Sign In
            </Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}

export default function AuthErrorPage() {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <AuthErrorPageContent />
    </Suspense>
  )
} 