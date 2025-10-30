/**
 * Hook for fetching and managing case data
 */

import { useEffect, useState } from 'react'
import type { CaseGraph } from '@/types/case-graph'

export function useCaseData(id: string) {
  const [data, setData] = useState<CaseGraph | null>(null)
  const [displayData, setDisplayData] = useState<any>(null)
  const [viewConfig, setViewConfig] = useState<any>(null)

  useEffect(() => {
    (async () => {
      // Fetch both raw and display data
      const [rawRes, displayRes] = await Promise.all([
        fetch(`/api/cases/${id}`),
        fetch(`/api/cases/${id}/display`)
      ])
      const rawData = await rawRes.json()
      const display = await displayRes.json()
      
      setData(rawData.case)
      setViewConfig(display.success ? display.viewConfig : null)
      
      // Store the structured display data for rendering
      if (display.success && display.data) {
        setDisplayData(display.data)
        console.log('Display data received:', display.data)
      }
    })()
  }, [id])

  return {
    data,
    setData,
    displayData,
    setDisplayData,
    viewConfig,
    setViewConfig
  }
}

