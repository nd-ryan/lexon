/**
 * Formatting utilities for case editor
 */

export function formatLabel(label: string): string {
  if (label === 'root') return 'Case'
  const spaced = label
    .replace(/[_-]/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/\s+/g, ' ')
    .trim()
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

export function capitalizeFirst(str: string | null): string {
  if (!str) return ''
  return str.charAt(0).toUpperCase() + str.slice(1)
}

export function pickNodeName(node: any): string | undefined {
  const props = (node?.properties ?? {}) as Record<string, unknown>
  const candidates = ['name', 'title', 'text', 'case_name']
  for (const key of candidates) {
    const v = props[key]
    if (typeof v === 'string' && v.trim()) return v.trim()
  }
  return undefined
}

