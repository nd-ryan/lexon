"use client";

import { useState, useEffect } from 'react';
import Button from "@/components/ui/button";
import Card from "@/components/ui/card";
import Input from "@/components/ui/input";
import { useSession } from 'next-auth/react';
import { useRouter } from 'next/navigation';
import StructuredResults, { StructuredSearchResponse } from '@/components/search/StructuredResults.client';
 

// Search history types
interface SearchHistoryItem {
  id: string;
  query: string;
  queryType: string;
  success: boolean;
  executionTime?: number;
  searchResult: StructuredSearchResponse; // Complete search result as JSON
  createdAt: string;
  updatedAt: string;
}

// Results formatting moved to `StructuredResults` component

const SearchPage = () => {
  const [query, setQuery] = useState('');
  const [searchType] = useState<'basic' | 'crew'>('crew');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [searchResult, setSearchResult] = useState<StructuredSearchResponse | null>(null);
  const [searchHistory, setSearchHistory] = useState<SearchHistoryItem[]>([]);
  // const [expandedHistoryId, setExpandedHistoryId] = useState<string | null>(null);
  const [streamingStatus, setStreamingStatus] = useState<string>('');
  const [streamingProgress, setStreamingProgress] = useState<string[]>([]);
  const [eventSource, setEventSource] = useState<EventSource | null>(null);
  const [activeSearchResult, setActiveSearchResult] = useState<StructuredSearchResponse | null>(null);
  // Note: flag not used by UI anymore; keeping to preserve minimal behavior but avoid lints
  const [, setIsViewingHistory] = useState<boolean>(false);
  const [selectedHistoryId, setSelectedHistoryId] = useState<string>('');
  const { status } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (status === 'unauthenticated') {
      router.push('/auth/signin');
    } else if (status === 'authenticated') {
      fetchSearchHistory();
    }
  }, [status, router]);

  // Effect to clean up EventSource on component unmount
  useEffect(() => {
    return () => {
      if (eventSource) {
        eventSource.close();
      }
    };
  }, [eventSource]);

  const saveSearchToHistory = async (result: StructuredSearchResponse) => {
    try {
      await fetch('/api/search-history', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          query: result.query,
          queryType: searchType,
          success: result.success,
          executionTime: result.execution_time,
          searchResult: result, // Send the whole thing
        }),
      });
      // Refresh history after saving
      fetchSearchHistory();
    } catch {
      console.error("Failed to save search history:");
    }
  };

  const fetchSearchHistory = async () => {
    try {
      const response = await fetch('/api/search-history?limit=10');
      if (response.ok) {
        const data = await response.json();
        setSearchHistory(data.searches || []);
      }
    } catch {
      console.error('Failed to fetch search history:');
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query) {
      setError('Please enter a search query.');
      return;
    }

    // Close any existing stream before starting a new one
    if (eventSource) {
      eventSource.close();
    }

    setLoading(true);
    setError('');
    setSearchResult(null);
    setIsViewingHistory(false);
    setSelectedHistoryId('');
    setStreamingStatus('Enqueueing search job...');
    setStreamingProgress([]);

    try {
      if (searchType === 'crew') {
        // Step 1: Enqueue the job and get a job ID
        const enqueueResponse = await fetch('/api/search/crew/stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query }),
        });

        if (!enqueueResponse.ok) {
          const errorText = await enqueueResponse.text();
          throw new Error(`Failed to enqueue search job: ${errorText}`);
        }

        const { job_id } = await enqueueResponse.json();
        if (!job_id) {
          throw new Error('No job ID received from the server.');
        }

        setStreamingStatus(`Job enqueued (ID: ${job_id}). Getting secure access...`);

        // Step 2: Get streaming token for secure access
        const tokenResponse = await fetch('/api/auth/stream-token', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ jobId: job_id }),
        });

        if (!tokenResponse.ok) {
          throw new Error('Failed to get streaming token');
        }

        const { token, backendUrl } = await tokenResponse.json();
        
        // Debug logging for JWT token
        console.log('🔍 JWT Token received from Vercel API:');
        console.log('🔍 Token length:', token?.length);
        console.log('🔍 Token first 50 chars:', token?.substring(0, 50));
        console.log('🔍 Backend URL:', backendUrl);
        console.log('🔍 Full EventSource URL:', `${backendUrl}/api/ai/search/results/${job_id}?token=${token}`);
        
        setStreamingStatus(`Connecting to results stream...`);

        // Step 3: Connect to the results stream using EventSource with token
        const es = new EventSource(`${backendUrl}/api/ai/search/results/${job_id}?token=${token}`);
        setEventSource(es);

        es.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            
            switch (data.type) {
              case 'status':
              case 'progress':
                setStreamingStatus(data.message);
                setStreamingProgress(prev => [...prev, data.message]);
                break;
              case 'warning':
                setStreamingStatus(`Warning: ${data.message}`);
                setStreamingProgress(prev => [...prev, `⚠️ ${data.message}`]);
                break;
              case 'complete':
              case 'end': // The backend uses 'end' to signal completion
                setStreamingStatus('Search completed!');
                setLoading(false); // Stop loading indicator
                if (data.data) {
                  const resultData = data.data;
                  
                  // Ensure the data has the expected structure
                  const structuredResult: StructuredSearchResponse = {
                    success: resultData.success ?? true,
                    explanation: resultData.explanation ?? "No explanation provided",
                    raw_results: Array.isArray(resultData.raw_results) ? resultData.raw_results : [],
                    cypher_queries: Array.isArray(resultData.cypher_queries) ? resultData.cypher_queries : [],
                    query: resultData.query ?? "",
                    execution_time: resultData.execution_time
                  };
                  
                  setSearchResult(structuredResult);
                  setActiveSearchResult(structuredResult);
                  setIsViewingHistory(false);
                  if (structuredResult.success) {
                    saveSearchToHistory(structuredResult);
                  }
                }
                es.close();
                setEventSource(null);
                break;
              case 'error':
                throw new Error(data.message || 'An error occurred in the search job.');
            }
          } catch (parseError) {
            console.error('Error parsing SSE data:', parseError, 'Raw data:', event.data);
          }
        };

        es.onerror = (err) => {
          console.error("❌ EventSource failed:", err);
          console.error("❌ EventSource readyState:", es.readyState);
          console.error("❌ EventSource URL:", es.url);
          setError('An error occurred while streaming results. The connection may have been lost.');
          setLoading(false);
          es.close();
          setEventSource(null);
        };
      } else {
        // This is the logic for a non-streaming, basic search (unchanged)
        const res = await fetch('/api/search', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query }),
        });

        const data = await res.json();

        if (!res.ok) {
          throw new Error(data.detail || 'An error occurred during the search.');
        }

        setSearchResult(data);
        if (data.success) {
          saveSearchToHistory(data);
        }
        setLoading(false);
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'An unknown error occurred.';
      setError(`An error occurred: ${errorMessage}`);
      console.error("Search failed:", error);
      setLoading(false);
    }
  };

  // Replace list UI with a top-right dropdown toggle
  // const renderSearchHistory = () => null;

  return (
    <section className="py-6">
      <div className="mx-auto max-w-5xl px-4">
        <div className="flex items-center justify-end mb-6 gap-3">
            {activeSearchResult && (
              <Button
                variant="outline"
                onClick={() => {
                  setSearchResult(activeSearchResult);
                  setIsViewingHistory(false);
                  setSelectedHistoryId('');
                }}
              >
                Back to current search
              </Button>
            )}
            <div>
              <label htmlFor="history" className="sr-only">Recent searches</label>
              <select
                id="history"
                className="h-9 rounded-md border border-gray-300 bg-white px-2 text-sm"
                value={selectedHistoryId || ""}
                onChange={(e) => {
                  const id = e.target.value
                  setSelectedHistoryId(id)
                  const item = searchHistory.find((s) => s.id === id)
                  if (item) {
                    setSearchResult(item.searchResult)
                    setIsViewingHistory(true)
                  }
                }}
              >
                <option value="" disabled>
                  Recent searches
                </option>
                {searchHistory.map((s) => (
                  <option key={s.id} value={s.id}>
                    {new Date(s.createdAt).toLocaleString()} — {s.query}
                  </option>
                ))}
              </select>
            </div>
        </div>

        <div className="flex flex-col gap-5">
          <Card>
            <div className="p-4">
              <form onSubmit={handleSubmit}>
                <div className="flex items-center gap-3">
                  <div className="flex-1">
                    <Input
                      value={query}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => setQuery(e.target.value)}
                      placeholder="Ask a question about your knowledge graph..."
                      aria-label="Search query"
                    />
                  </div>
                  <Button type="submit" disabled={loading}>
                    {loading ? 'Searching...' : 'Search'}
                  </Button>
                </div>
              </form>
            </div>
          </Card>

          {error && (
            <div className="rounded-md border border-red-200 bg-red-50 text-red-700 px-4 py-3">
              {error}
            </div>
          )}

          {loading && (
            <Card>
              <div className="p-4">
                <div className="flex items-start gap-3">
                  <div className="h-5 w-5 animate-spin rounded-full border-2 border-gray-300 border-t-gray-700 mt-0.5" />
                  <div className="flex flex-col gap-2 w-full">
                    <p className="font-medium">AI Search in Progress</p>
                    {streamingStatus && (
                      <p className="text-sm text-gray-700">{streamingStatus}</p>
                    )}
                    {streamingProgress.length > 0 && (
                      <div className="max-h-40 overflow-y-auto">
                        {streamingProgress.map((step, index) => (
                          <div key={index} className="text-sm">• {step}</div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </Card>
          )}

          {searchResult && (
            <StructuredResults data={searchResult} />
          )}
        </div>
      </div>
    </section>
  );
};

export default function SearchPageContainer() {
  const { status } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (status === 'unauthenticated') {
      router.push('/auth/signin');
    }
  }, [status, router]);

  if (status === 'loading') {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p>Loading...</p>
      </div>
    );
  }

  if (status === 'unauthenticated') {
    return null;
  }

  return <SearchPage />;
} 