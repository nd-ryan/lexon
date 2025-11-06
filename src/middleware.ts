import { withAuth } from 'next-auth/middleware'

export default withAuth(
  function middleware() {
    // Add any additional middleware logic here
  },
  {
    callbacks: {
      authorized: ({ token }) => !!token,
    },
  }
)

export const config = {
  matcher: [
    // Protect all routes except: NextAuth pages, NextAuth API, static assets
    '/((?!api/auth|auth/signin|auth/signout|auth/error|_next|static|favicon.ico).*)',
  ]
}