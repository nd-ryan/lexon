import { NextRequest, NextResponse } from 'next/server'
import bcrypt from 'bcryptjs'
import { prisma } from '@/lib/prisma'
import { features } from '@/config/features'

export async function POST(request: NextRequest) {
  // Check if registration is enabled
  if (!features.registrationEnabled) {
    return NextResponse.json(
      { error: 'Sign-up is currently disabled. Please contact the administrator for access.' },
      { status: 403 }
    )
  }

  try {
    const { name, email, password, accessCode } = await request.json()

    // Validate access code if required
    if (features.registrationAccessCode) {
      if (!accessCode || accessCode !== features.registrationAccessCode) {
        return NextResponse.json(
          { error: 'Invalid access code' },
          { status: 403 }
        )
      }
    }

    // Validation
    if (!name || !email || !password) {
      return NextResponse.json(
        { error: 'Missing required fields' },
        { status: 400 }
      )
    }

    if (password.length < 6) {
      return NextResponse.json(
        { error: 'Password must be at least 6 characters' },
        { status: 400 }
      )
    }

    // Check if user already exists
    const existingUser = await prisma.user.findUnique({
      where: { email }
    })

    if (existingUser) {
      return NextResponse.json(
        { error: 'User already exists' },
        { status: 400 }
      )
    }

    // Hash password
    const hashedPassword = await bcrypt.hash(password, 12)

    // Create user
    const user = await prisma.user.create({
      data: {
        name,
        email,
        password: hashedPassword,
        role: 'user',
      }
    })

    // Remove password from response
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { password: _, ...userWithoutPassword } = user

    return NextResponse.json(
      { message: 'User created successfully', user: userWithoutPassword },
      { status: 201 }
    )
  } catch (error) {
    console.error('Sign-up error:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    )
  }
}