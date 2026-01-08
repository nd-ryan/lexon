"use client"

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import Button from "@/components/ui/button"
import Card from "@/components/ui/card"
import Input from "@/components/ui/input"
import { useSession, signIn } from 'next-auth/react'

export default function SignUpPage() {
  const [formData, setFormData] = useState({
    name: '',
    email: '',
    password: '',
    accessCode: ''
  })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [accessCodeRequired, setAccessCodeRequired] = useState(false)
  const [registrationEnabled, setRegistrationEnabled] = useState<boolean | null>(null)
  const router = useRouter()
  const { status } = useSession();

  // Check registration feature flag first - before rendering anything
  useEffect(() => {
    fetch('/api/features')
      .then(res => res.json())
      .then(data => {
        if (!data.registrationEnabled) {
          router.replace('/auth/signin');
          return;
        }
        setRegistrationEnabled(true)
        setAccessCodeRequired(data.accessCodeRequired ?? false)
      })
      .catch(() => router.replace('/auth/signin'))
  }, [router]);

  // Redirect authenticated users
  useEffect(() => {
    if (status === 'authenticated') {
      router.replace('/');
    }
  }, [status, router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')

    if (formData.password.length < 6) {
      setError('Password must be at least 6 characters')
      setLoading(false)
      return
    }

    try {
      const res = await fetch('/api/auth/signup', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(formData)
      })

      const data = await res.json()

      if (!res.ok) {
        setError(data.error || 'Something went wrong')
      } else {
        // Auto sign-in after successful registration
        await signIn('credentials', {
          email: formData.email,
          password: formData.password,
          callbackUrl: '/cases',
        })
      }
    } catch {
      setError('Network error. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData(prev => ({
      ...prev,
      [e.target.name]: e.target.value
    }))
  }

  // Don't render anything until we've confirmed registration is enabled
  if (registrationEnabled !== true) {
    return null
  }

  return (
    <section className="py-10">
      <div className="mx-auto max-w-md px-4">
        <Card>
          <div className="p-6">
            <h2 className="text-center text-xl font-semibold mb-3">Create your account</h2>
            <form onSubmit={handleSubmit} className="space-y-3">
              {error && (
                <div className="rounded-md border border-red-200 bg-red-50 text-red-700 px-4 py-2 text-sm">
                  {error}
                </div>
              )}
              <div>
                <Input
                  id="name"
                  name="name"
                  type="text"
                  placeholder="Name"
                  autoComplete="name"
                  required
                  value={formData.name}
                  onChange={handleChange}
                />
              </div>
              <div>
                <Input
                  id="email"
                  name="email"
                  type="email"
                  placeholder="Email address"
                  autoComplete="email"
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
                  placeholder="Password (min. 6 characters)"
                  autoComplete="new-password"
                  required
                  value={formData.password}
                  onChange={handleChange}
                />
              </div>
              {accessCodeRequired && (
                <div>
                  <Input
                    id="accessCode"
                    name="accessCode"
                    type="text"
                    placeholder="Access code"
                    autoComplete="off"
                    required
                    value={formData.accessCode}
                    onChange={handleChange}
                  />
                </div>
              )}
              <Button type="submit" disabled={loading} className="w-full">
                {loading ? 'Signing up...' : 'Sign up'}
              </Button>
              <div className="mt-3 text-center">
                <Link href="/auth/signin" className="text-sm text-indigo-700 hover:underline">Already have an account? Sign in</Link>
              </div>
            </form>
          </div>
        </Card>
      </div>
    </section>
  )
}
