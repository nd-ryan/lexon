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
    '/((?!auth|api|_next|static|favicon.ico).*)',
  ]
}