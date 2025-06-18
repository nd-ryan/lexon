import { NextResponse } from 'next/server'

export async function POST() {
  // Temporarily disable sign-up
  return NextResponse.json(
    { error: 'Sign-up is temporarily disabled. Please contact the administrator for access.' },
    { status: 403 }
  )

  // Original sign-up code (commented out for temporary disable)
  /*
  import { NextRequest } from 'next/server'
  import bcrypt from 'bcryptjs'
  import { prisma } from '@/lib/prisma'
  
  export async function POST(request: NextRequest) {
    try {
      const { name, email, password } = await request.json()

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
          password: hashedPassword
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
  */
}