import CredentialsProvider from 'next-auth/providers/credentials'
import { PrismaAdapter } from '@next-auth/prisma-adapter'
import { prisma } from './prisma'
import * as bcrypt from 'bcryptjs'

export const authOptions = {
  adapter: PrismaAdapter(prisma),
  providers: [
    CredentialsProvider({
      name: 'credentials',
      credentials: {
        email: { label: 'Email', type: 'email' },
        password: { label: 'Password', type: 'password' }
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) {
          return null
        }

        // Never allow raw DB/Prisma errors to propagate into NextAuth's redirect
        // (it can produce invalid Location headers due to newlines/special chars).
        // If anything fails here, treat it as an auth failure.
        let user: any
        try {
          user = await prisma.user.findUnique({
            where: {
              email: credentials.email
            }
          })
        } catch (err) {
          console.error('Credentials authorize(): Prisma error', err)
          return null
        }

        if (!user || !user.password) {
          return null
        }

        let isPasswordValid = false
        try {
          isPasswordValid = await bcrypt.compare(
            credentials.password,
            user.password
          )
        } catch (err) {
          console.error('Credentials authorize(): bcrypt error', err)
          return null
        }

        if (!isPasswordValid) {
          return null
        }

        return {
          id: user.id,
          email: user.email,
          name: user.name || '',
          role: user.role,
        }
      }
    })
  ],
  session: {
    strategy: 'jwt' as const
  },
  pages: {
    signIn: '/auth/signin',
    signOut: '/auth/signout',
    error: '/auth/error',
    verifyRequest: '/auth/verify',
    newUser: '/auth/welcome'
  },
  callbacks: {
    async jwt({ token, user }: { token: any, user?: any }) {
      if (user) {
        token.id = user.id
        token.role = (user as any).role
      }
      return token
    },
    session: async ({ session, token }: { session: any, token: any }) => {
      if (session?.user && token?.id) {
        session.user.id = token.id as string;
      }
      if (session?.user && token?.role) {
        session.user.role = token.role as any
      }
      return session
    },
  },
}