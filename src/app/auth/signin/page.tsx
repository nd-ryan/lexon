"use client"

import { useState, useEffect, Suspense } from 'react'
import { signIn, useSession } from 'next-auth/react'
import { useRouter, useSearchParams } from 'next/navigation'
import Button from "@/components/ui/button"
import Card from "@/components/ui/card"
import Input from "@/components/ui/input"

function SignInPageContent() {
  const [formData, setFormData] = useState({
    email: '',
    password: ''
  })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const router = useRouter()
  const searchParams = useSearchParams()
  const message = searchParams.get('message')
  const { status } = useSession();

  useEffect(() => {
    if (status === 'authenticated') {
      router.replace('/cases');
    }
  }, [status, router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')

    try {
      const result = await signIn('credentials', {
        email: formData.email,
        password: formData.password,
        callbackUrl: '/cases',
      })
      if (result?.error) {
        setError('Invalid email or password')
        setLoading(false)
      }
    } catch {
      setError('Network error. Please try again.')
      setLoading(false)
    }
  }

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData(prev => ({
      ...prev,
      [e.target.name]: e.target.value
    }))
  }

  return (
    <section className="py-10">
      <div className="mx-auto max-w-md px-4">
        <Card>
          <div className="p-6">
            <h2 className="text-center text-xl font-semibold mb-3">Sign in to your account</h2>
            <form onSubmit={handleSubmit} className="space-y-3">
              {message && (
                <div className="rounded-md border border-green-200 bg-green-50 text-green-700 px-4 py-2 text-sm">
                  {message}
                </div>
              )}
              {error && (
                <div className="rounded-md border border-red-200 bg-red-50 text-red-700 px-4 py-2 text-sm">
                  {error}
                </div>
              )}
              <div>
                <Input
                  id="email"
                  name="email"
                  type="email"
                  placeholder="Email address"
                  required
                  value={formData.email}
                  onChange={handleChange}
                />
              </div>
              <div>
                <Input
                  id="password"
                  name="password"
                  type="password"
                  placeholder="Password"
                  required
                  value={formData.password}
                  onChange={handleChange}
                />
              </div>
              <Button type="submit" disabled={loading} className="w-full">
                {loading ? 'Signing in...' : 'Sign in'}
              </Button>
            </form>
          </div>
        </Card>
      </div>
    </section>
  )
}

export default function SignInPage() {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <SignInPageContent />
    </Suspense>
  )
} 