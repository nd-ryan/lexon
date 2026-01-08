import { withAuth } from 'next-auth/middleware'

export default withAuth(
  function middleware() {
    // Add any additional middleware logic here
  },
  {
    callbacks: {
      authorized: ({ token, req }) => {
        // Allow root route without authentication
        if (req.nextUrl.pathname === '/') {
          return true
        }
        // Allow registration page without authentication
        if (req.nextUrl.pathname === '/register') {
          return true
        }
        // Allow features API without authentication (needed by registration page)
        if (req.nextUrl.pathname === '/api/features') {
          return true
        }
        // Allow PDF files (like white paper) without authentication
        if (req.nextUrl.pathname.endsWith('.pdf')) {
          return true
        }
        // Allow image files without authentication
        if (req.nextUrl.pathname.match(/\.(png|jpg|jpeg|gif|svg|webp|ico)$/i)) {
          return true
        }
        // Require authentication for all other routes
        return !!token
      },
    },
  }
)

export const config = {
  matcher: [
    // Protect all routes except: NextAuth pages, NextAuth API, static assets, registration, features API
    '/((?!api/auth|api/features|auth/signin|auth/signout|auth/error|register|_next|static|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|pdf)$).*)',
  ]
}