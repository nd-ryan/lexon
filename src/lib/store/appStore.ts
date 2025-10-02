import { create } from 'zustand'
import type { Schema } from '@/types/case-graph'

type AppState = {
  schema: Schema | null
  schemaLoading: boolean
  schemaError: string | null
  loadSchema: () => Promise<void>
}

export const useAppStore = create<AppState>((set) => ({
  schema: null,
  schemaLoading: false,
  schemaError: null,
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
}))


