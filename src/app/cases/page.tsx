"use client";
import useSWR from 'swr'
import Link from 'next/link'

const fetcher = (url: string) => fetch(url).then(r => r.json())

export default function CasesListPage() {
  const { data, error, isLoading } = useSWR('/api/cases', fetcher)
  if (isLoading) return <div className="p-8">Loading...</div>
  if (error) return <div className="p-8 text-red-600">Error</div>
  const items = data?.items || []
  return (
    <div className="p-8 space-y-4">
      <div className="flex justify-between">
        <h1 className="text-2xl font-bold">Cases</h1>
        <Link className="text-blue-600 underline" href="/cases/upload">Upload</Link>
      </div>
      <ul className="space-y-2">
        {items.map((c: any) => (
          <li key={c.id} className="border p-3 rounded">
            <Link href={`/cases/${c.id}`} className="font-medium">{c.extracted?.case_name || c.filename}</Link>
            <div className="text-sm text-gray-600">{c.status}</div>
          </li>
        ))}
      </ul>
    </div>
  )
}


