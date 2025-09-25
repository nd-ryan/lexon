'use client'

import { useEffect } from 'react'
import { useAppStore } from '@/lib/store/appStore'

export default function SchemaBootstrap() {
  const loadSchema = useAppStore(s => s.loadSchema)
  const schema = useAppStore(s => s.schema)

  useEffect(() => {
    if (!schema) {
      loadSchema()
    }
  }, [schema, loadSchema])

  return null
}


