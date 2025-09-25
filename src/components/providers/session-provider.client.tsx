'use client'

import { SessionProvider } from 'next-auth/react'
import { ReactNode } from 'react'
import SchemaBootstrap from './schema-bootstrap.client'

interface Props {
  children: ReactNode
}

export default function SessionProviderWrapper({ children }: Props) {
  return (
    <SessionProvider>
      <SchemaBootstrap />
      {children}
    </SessionProvider>
  )
}