declare module 'next-auth' {
  interface Session {
    user: {
      id: string
      email: string
      name: string
      role: 'user' | 'editor' | 'developer' | 'admin'
    }
  }

  interface User {
    id: string
    email: string
    name: string
    role: 'user' | 'editor' | 'developer' | 'admin'
  }
}

declare module 'next-auth/jwt' {
  interface JWT {
    id: string
    role: 'user' | 'editor' | 'developer' | 'admin'
  }
}