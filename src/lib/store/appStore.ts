import { create } from 'zustand'

type SchemaPayload = any

type AppState = {
  schema: SchemaPayload | null
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
      const data = await res.json()
      if (!res.ok || !data?.success) {
        throw new Error(data?.error || 'Failed to fetch schema')
      }
      set({ schema: data.schema, schemaLoading: false })
    } catch (e: any) {
      set({ schemaError: e?.message || 'Failed to load schema', schemaLoading: false })
    }
  },
}))


