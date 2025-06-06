'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useSession } from 'next-auth/react';
import { useRouter } from 'next/navigation';

export default function SearchPage() {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<{ cypherQuery: string; results: any[] } | null>(null);
  
  const { status } = useSession();
  const router = useRouter();

  if (status === 'unauthenticated') {
    router.push('/auth/signin');
    return null;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query) {
      setError('Please enter a search query.');
      return;
    }

    setLoading(true);
    setError('');
    setResult(null);

    try {
      const res = await fetch('/api/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data.error || 'An error occurred during search.');
      } else {
        setResult(data);
      }
    } catch (err) {
      setError('A network error occurred. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 p-4 sm:p-6 lg:p-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-3xl font-bold text-gray-900 mb-6">Natural Language Search</h1>
        
        <form onSubmit={handleSubmit} className="flex items-center space-x-2 mb-8">
          <Input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask a question about your knowledge graph..."
            className="flex-grow"
          />
          <Button type="submit" disabled={loading}>
            {loading ? 'Searching...' : 'Search'}
          </Button>
        </form>

        {error && (
          <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-6">
            <p className="font-bold">Error</p>
            <p>{error}</p>
          </div>
        )}

        {result && (
          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Generated Cypher Query</CardTitle>
              </CardHeader>
              <CardContent>
                <pre className="bg-gray-100 p-4 rounded-md overflow-x-auto">
                  <code>{result.cypherQuery}</code>
                </pre>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Results</CardTitle>
              </CardHeader>
              <CardContent>
                {result.results.length > 0 ? (
                  <pre className="bg-gray-100 p-4 rounded-md overflow-x-auto">
                    <code>{JSON.stringify(result.results, null, 2)}</code>
                  </pre>
                ) : (
                  <p>No results found.</p>
                )}
              </CardContent>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
} 