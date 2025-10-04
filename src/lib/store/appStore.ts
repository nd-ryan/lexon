import { create } from 'zustand'
import type { Schema, GraphNode } from '@/types/case-graph'

type AppState = {
  schema: Schema | null
  schemaLoading: boolean
  schemaError: string | null
  loadSchema: () => Promise<void>
  
  // Catalog nodes (for can_create_new=false types: Forum, Jurisdiction, ReliefType)
  catalogNodes: Record<string, GraphNode[]>
  catalogLoading: boolean
  catalogError: string | null
  loadCatalog: () => Promise<void>
}

export const useAppStore = create<AppState>((set, get) => ({
  schema: null,
  schemaLoading: false,
  schemaError: null,
  catalogNodes: {},
  catalogLoading: false,
  catalogError: null,
  
  loadSchema: async () => {
    try {
      set({ schemaLoading: true, schemaError: null })
      const res = await fetch('/api/schema', { cache: 'no-store' })
      const data = await res.json() as { success: boolean; schema: Schema; error?: string }
      if (!res.ok || !data?.success) {
        throw new Error(data?.error || 'Failed to fetch schema')
      }
      set({ schema: data.schema, schemaLoading: false })
    } catch (e: any) {
      set({ schemaError: e?.message || 'Failed to load schema', schemaLoading: false })
    }
  },
  
  loadCatalog: async () => {
    try {
      set({ catalogLoading: true, catalogError: null })
      
      // Wait for schema to be loaded
      let schema = get().schema
      if (!schema) {
        await get().loadSchema()
        schema = get().schema
      }
      
      if (!schema) {
        throw new Error('Schema not available')
      }
      
      // Find catalog types (where can_create_new=false)
      const schemaArray = Array.isArray(schema) ? schema : []
      const catalogLabels = schemaArray
        .filter((s: any) => s?.can_create_new === false)
        .map((s: any) => s?.label)
        .filter(Boolean) as string[]
      
      // Fetch all catalog nodes in parallel
      const catalogNodes: Record<string, GraphNode[]> = {}
      await Promise.all(
        catalogLabels.map(async (label: string) => {
          try {
            const res = await fetch(`/api/catalog/${label}`, { cache: 'no-store' })
            const data = await res.json()
            if (data.success && Array.isArray(data.nodes)) {
              catalogNodes[label] = data.nodes
            } else {
              catalogNodes[label] = []
            }
          } catch (error) {
            console.error(`Failed to fetch catalog for ${label}:`, error)
            catalogNodes[label] = []
          }
        })
      )
      
      set({ catalogNodes, catalogLoading: false })
    } catch (e: any) {
      set({ catalogError: e?.message || 'Failed to load catalog', catalogLoading: false })
    }
  },
}))


