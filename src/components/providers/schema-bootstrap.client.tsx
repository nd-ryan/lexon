'use client'

import { useEffect } from 'react'
import { useAppStore } from '@/lib/store/appStore'

export default function SchemaBootstrap() {
  const loadSchema = useAppStore(s => s.loadSchema)
  const loadCatalog = useAppStore(s => s.loadCatalog)
  const schema = useAppStore(s => s.schema)
  const catalogNodes = useAppStore(s => s.catalogNodes)

  // Load schema on mount
  useEffect(() => {
    if (!schema) {
      loadSchema()
    }
  }, [schema, loadSchema])
  
  // Load catalog after schema is available
  useEffect(() => {
    if (schema && Object.keys(catalogNodes).length === 0) {
      loadCatalog()
    }
  }, [schema, catalogNodes, loadCatalog])

  return null
}


