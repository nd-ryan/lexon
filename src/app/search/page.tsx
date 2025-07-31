'use client';

import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useSession } from 'next-auth/react';
import { useRouter } from 'next/navigation';

// Types for structured search response - Updated to match backend StructuredSearchResponse
interface StructuredSearchResponse {
  success: boolean;
  explanation: string;
  raw_results: any[]; // Changed from SearchResult[] to any[] to match backend
  cypher_queries: string[];
  query: string;
  execution_time?: number;
}

// Search result structure from Neo4j raw results
interface SearchResult {
  [key: string]: unknown; // Neo4j results can have any structure
}

// Remove the old SearchAnalysis interface as it's not used by backend
// interface SearchAnalysis {
//   query_interpretation: string;
//   methodology: string[];
//   key_insights: string[];
//   patterns_identified: string[];
//   limitations: string[];
//   formatted_results: string[];
//   raw_query_results: unknown[];
// }

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

// Helper functions for dynamic result formatting
const getCardStyle = (key: string, index: number) => {
  const colors = [
    { border: 'border-blue-200', header: 'bg-blue-50', text: 'text-blue-900', icon: '🧠' },
    { border: 'border-green-200', header: 'bg-green-50', text: 'text-green-900', icon: '⚡' },
    { border: 'border-yellow-200', header: 'bg-yellow-50', text: 'text-yellow-900', icon: '💡' },
    { border: 'border-emerald-200', header: 'bg-emerald-50', text: 'text-emerald-900', icon: '📋' },
    { border: 'border-purple-200', header: 'bg-purple-50', text: 'text-purple-900', icon: '📊' },
    { border: 'border-indigo-200', header: 'bg-indigo-50', text: 'text-indigo-900', icon: '🔍' },
    { border: 'border-pink-200', header: 'bg-pink-50', text: 'text-pink-900', icon: '🎯' },
    { border: 'border-cyan-200', header: 'bg-cyan-50', text: 'text-cyan-900', icon: '🔧' },
    { border: 'border-orange-200', header: 'bg-orange-50', text: 'text-orange-900', icon: '📈' },
    { border: 'border-teal-200', header: 'bg-teal-50', text: 'text-teal-900', icon: '🎨' }
  ];
  
  // Use specific icons for known keys (updated for backend fields)
  const keyIcons: Record<string, string> = {
    query: '❓',
    success: '✅',
    explanation: '📝',
    raw_results: '📊',
    cypher_queries: '🔧',
    execution_time: '⏱️'
  };
  
  const color = colors[index % colors.length];
  const icon = keyIcons[key] || color.icon;
  
  return { ...color, icon };
};

const formatTitle = (key: string) => {
  return key
    .split('_')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
};

const renderValue = (value: unknown, key: string): React.ReactNode => {
  if (value === null || value === undefined) {
    return (
      <div className="flex items-center justify-center py-4 text-muted-foreground">
        <span className="text-sm italic">No data available</span>
      </div>
    );
  }

  if (typeof value === 'boolean') {
    return (
      <div className="flex justify-start px-2">
        <span className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium transition-colors ${
          value 
            ? 'bg-green-50 text-green-700 border border-green-200' 
            : 'bg-red-50 text-red-700 border border-red-200'
        }`}>
          <span className="text-xs">{value ? '✅' : '❌'}</span>
          {value ? 'True' : 'False'}
        </span>
      </div>
    );
  }

  if (typeof value === 'number') {
    const displayValue = key.includes('time') ? `${value.toFixed(2)}s` : value.toString();
    return (
      <div className="flex justify-start">
        <span className="inline-flex items-center gap-2 px-3 py-1.5 bg-blue-50 text-blue-700 border border-blue-200 rounded-full text-sm font-mono">
          {key.includes('time') && <span className="text-xs">⏱️</span>}
          {displayValue}
        </span>
      </div>
    );
  }

  if (typeof value === 'string') {
    if (value.length > 500) {
      return (
        <div className="relative">
          <div className="bg-muted/50 rounded-lg border p-6 max-h-64 overflow-y-auto scrollbar-thin scrollbar-track-gray-100 scrollbar-thumb-gray-300">
            <pre className="text-sm text-foreground whitespace-pre-wrap leading-relaxed font-mono">
              {value}
            </pre>
          </div>
          <div className="absolute top-3 right-3 bg-background/90 backdrop-blur-sm px-3 py-1.5 rounded-md text-xs text-muted-foreground font-medium">
            {value.length} chars
          </div>
        </div>
      );
    }
    return (
      <div className="prose prose-sm max-w-none">
        <p className="text-foreground leading-relaxed m-0 px-2 text-sm py-1">{value}</p>
      </div>
    );
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return (
        <div className="flex items-center justify-center py-8 text-muted-foreground border-2 border-dashed rounded-lg">
          <span className="text-sm italic">Empty list</span>
        </div>
      );
    }

    // Handle array of strings/simple values
    if (value.every(item => typeof item === 'string' || typeof item === 'number')) {
      return (
        <div className="space-y-3">
          {value.map((item, index) => (
            <div key={index} className="flex items-start gap-4 p-3 rounded-lg hover:bg-muted/50 transition-colors border border-transparent hover:border-border/30">
              <div className="flex-shrink-0 w-2 h-2 bg-primary/60 rounded-full mt-2.5"></div>
              <span className="text-foreground leading-relaxed flex-1 break-words text-sm">{String(item)}</span>
            </div>
          ))}
        </div>
      );
    }

    // Handle array of objects (like search results)
    if (key === 'raw_results' && value.every(item => typeof item === 'object' && item !== null)) {
      return (
        <div className="space-y-6">
          {value.map((result: Record<string, unknown>, index: number) => (
            <Card key={index} className="transition-all hover:shadow-md border-l-4 border-l-primary/20">
              <CardContent className="space-y-4 p-6">
                {Object.entries(result).map(([resultKey, resultValue]) => (
                  <div key={resultKey} className="group">
                    <div className="flex items-center gap-2 mb-3">
                      <span className="text-sm font-medium text-muted-foreground bg-muted px-3 py-1.5 rounded-md">
                        {formatTitle(resultKey)}
                      </span>
                    </div>
                    <div className="ml-0 pl-4 border-l-2 border-border/20">
                      {typeof resultValue === 'object' && resultValue !== null ? (
                        <div className="bg-muted/30 rounded-lg border p-4 max-h-48 overflow-y-auto">
                          <pre className="text-xs text-foreground whitespace-pre-wrap font-mono leading-relaxed">
                            {JSON.stringify(resultValue, null, 2)}
                          </pre>
                        </div>
                      ) : (
                        <div className="text-foreground break-words text-sm leading-relaxed">{String(resultValue)}</div>
                      )}
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          ))}
        </div>
      );
    }

    // Handle other complex arrays
    return (
      <div className="relative">
        <div className="bg-muted/30 rounded-lg border p-6 max-h-96 overflow-y-auto scrollbar-thin scrollbar-track-gray-100 scrollbar-thumb-gray-300">
          <pre className="text-sm text-foreground whitespace-pre-wrap font-mono leading-relaxed">
            {JSON.stringify(value, null, 2)}
          </pre>
        </div>
        <div className="absolute top-3 right-3 bg-background/90 backdrop-blur-sm px-3 py-1.5 rounded-md text-xs text-muted-foreground font-medium">
          {value.length} items
        </div>
      </div>
    );
  }

  if (typeof value === 'object' && value !== null) {
    // Handle nested objects
    return (
      <div className="space-y-6">
        {Object.entries(value).map(([nestedKey, nestedValue]) => (
          <div key={nestedKey} className="relative">
            <div className="border-l-2 border-primary/30 pl-6 pb-4">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-2.5 h-2.5 bg-primary/60 rounded-full"></div>
                <span className="font-medium text-foreground text-sm">
                  {formatTitle(nestedKey)}
                </span>
              </div>
              <div className="ml-2 pl-4">
                {renderValue(nestedValue, nestedKey)}
              </div>
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="text-foreground break-words">
      {String(value)}
    </div>
  );
};

// Helper function to format structured search results dynamically
const formatStructuredResults = (data: StructuredSearchResponse) => {
  // Check if data is null or undefined
  if (!data) {
    return <div className="p-4 bg-red-50 rounded">No valid data to display</div>;
  }
  
  // Get all keys from the data object
  const dataKeys = Object.keys(data) as Array<keyof StructuredSearchResponse>;
  
  return (
    <div className="space-y-12">
      {dataKeys.map((key, index) => {
        const value = data[key];
        const style = getCardStyle(key, index);
        
        // Skip null/undefined values
        if (value === null || value === undefined) {
          return null;
        }
        
        // Calculate count for arrays
        let countBadge = null;
        if (Array.isArray(value)) {
          countBadge = (
            <span className="inline-flex items-center px-3 py-1.5 bg-primary/10 text-primary text-xs font-medium rounded-full">
              {value.length} items
            </span>
          );
        } else if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
          const objKeys = Object.keys(value);
          if (objKeys.length > 0) {
            countBadge = (
              <span className="inline-flex items-center px-3 py-1.5 bg-primary/10 text-primary text-xs font-medium rounded-full">
                {objKeys.length} properties
              </span>
            );
          }
        }

        return (
          <Card key={key} className={`${style.border} shadow-sm hover:shadow-md transition-all duration-200 overflow-hidden`}>
            <CardHeader className={`${style.header} border-b border-border/50 py-6`}>
              <div className="flex items-center justify-between w-full">
                <CardTitle className={`${style.text} flex items-center gap-4`}>
                  <span className="text-xl">{style.icon}</span>
                  <span className="font-semibold tracking-tight text-lg">{formatTitle(key)}</span>
                </CardTitle>
                {countBadge}
              </div>
            </CardHeader>
            <CardContent className="p-8">
              <div className="max-w-none">
                {renderValue(value, key)}
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
};

const SearchPage = () => {
  const [query, setQuery] = useState('');
  const [searchType] = useState<'basic' | 'crew'>('crew');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [searchResult, setSearchResult] = useState<StructuredSearchResponse | null>(null);
  const [searchHistory, setSearchHistory] = useState<SearchHistoryItem[]>([]);
  const [expandedHistoryId, setExpandedHistoryId] = useState<string | null>(null);
  const [streamingStatus, setStreamingStatus] = useState<string>('');
  const [streamingProgress, setStreamingProgress] = useState<string[]>([]);
  const [eventSource, setEventSource] = useState<EventSource | null>(null);
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

  const renderSearchHistory = () => {
    if (loading) {
      return (
        <Card className="shadow-sm">
          <CardHeader className="border-b border-border/50">
            <CardTitle className="flex items-center gap-2">
              <span>📜</span>
              Recent Searches
            </CardTitle>
          </CardHeader>
          <CardContent className="p-6">
            <div className="flex items-center justify-center py-8">
              <div className="flex flex-col items-center gap-3">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
                <p className="text-muted-foreground text-sm">Loading search history...</p>
              </div>
            </div>
          </CardContent>
        </Card>
      );
    }

    if (searchHistory.length === 0) {
      return (
        <Card className="shadow-sm">
          <CardHeader className="border-b border-border/50">
            <CardTitle className="flex items-center gap-2">
              <span>📜</span>
              Recent Searches
            </CardTitle>
          </CardHeader>
          <CardContent className="p-6">
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <div className="text-4xl mb-3">🔍</div>
              <p className="text-muted-foreground text-sm">No search history yet.</p>
              <p className="text-muted-foreground text-sm">Try searching for something!</p>
            </div>
          </CardContent>
        </Card>
      );
    }

    return (
      <Card className="shadow-sm">
        <CardHeader className="border-b border-border/50">
          <CardTitle className="flex items-center justify-between">
            <span className="flex items-center gap-2">
              <span>📜</span>
              Recent Searches
            </span>
            <span className="text-sm font-normal text-muted-foreground">
              {searchHistory.length} searches
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-4">
          <div className="space-y-3 max-h-[70vh] overflow-y-auto scrollbar-thin scrollbar-track-transparent scrollbar-thumb-border">
            {searchHistory.map((historyItem) => (
              <div key={historyItem.id} className="border rounded-lg hover:bg-muted/50 transition-colors">
                <div 
                  className="cursor-pointer p-4"
                  onClick={() => setExpandedHistoryId(
                    expandedHistoryId === historyItem.id ? null : historyItem.id
                  )}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-foreground text-sm truncate mb-2">{historyItem.query}</p>
                      <div className="flex items-center gap-2 text-xs flex-wrap">
                        <span className={`inline-flex items-center px-2 py-1 rounded-full font-medium ${
                          historyItem.success 
                            ? 'bg-green-100 text-green-700 border border-green-200' 
                            : 'bg-red-100 text-red-700 border border-red-200'
                        }`}>
                          {historyItem.success ? '✅' : '❌'}
                        </span>
                        <span className="text-muted-foreground">
                          {(() => {
                            const result = historyItem.searchResult;
                            // Use the correct backend field names
                            if (result && result.raw_results && Array.isArray(result.raw_results)) return `${result.raw_results.length} results`;
                            if (typeof result === 'object' && result !== null) {
                              // Count all array properties as fallback
                              const arrays = Object.values(result).filter(v => Array.isArray(v));
                              const totalItems = arrays.reduce((sum, arr) => sum + arr.length, 0);
                              return totalItems > 0 ? `${totalItems} items` : 'No count';
                            }
                            return 'Unknown';
                          })()}
                        </span>
                        <span className="text-muted-foreground">{new Date(historyItem.createdAt).toLocaleDateString()}</span>
                      </div>
                    </div>
                    <Button variant="ghost" size="sm" className="flex-shrink-0 h-8 w-8 p-0">
                      <span className="text-xs">
                        {expandedHistoryId === historyItem.id ? '▼' : '▶'}
                      </span>
                    </Button>
                  </div>
                </div>

                {expandedHistoryId === historyItem.id && (
                  <div className="border-t border-border/50 p-4 bg-muted/20">
                    <div className="space-y-4 max-h-96 overflow-y-auto scrollbar-thin scrollbar-track-transparent scrollbar-thumb-border">
                      {formatStructuredResults(historyItem.searchResult)}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    );
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-background to-muted/20 p-4 sm:p-6 lg:p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <h1 className="text-4xl font-bold text-foreground mb-2 tracking-tight">Lexon Search</h1>
        </div>
        
        <div className="max-w-4xl mx-auto space-y-8">
          <Card className="shadow-sm">
            <CardContent className="p-6">
              <form onSubmit={handleSubmit} className="space-y-6">
                <div className="flex items-center gap-3">
                  <Input
                    type="text"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Ask a question about your knowledge graph..."
                    className="flex-grow text-base"
                  />
                  <Button type="submit" disabled={loading} className="px-6">
                    {loading ? 'Searching...' : 'Search'}
                  </Button>
                </div>
                

                <div className="bg-muted/30 rounded-lg p-4 border">
                  <p className="font-medium text-foreground mb-3">Notes:</p>
                  <div className="flex flex-col gap-2">
                    <p className="text-sm text-muted-foreground leading-relaxed">
                      Embedding search is not supported yet.
                    </p>
                    <p className="text-sm text-muted-foreground leading-relaxed">
                      Current results includes data that will not be shown to the eventual end user, such as the raw query and technical details.
                    </p>
                    <p className="text-sm text-muted-foreground leading-relaxed"></p>
                  </div>
                </div>
              </form>
            </CardContent>
          </Card>

          {error && (
            <Card className="border-destructive/50 bg-destructive/5">
              <CardContent className="p-6">
                <div className="flex items-start gap-3">
                  <span className="text-destructive text-lg">⚠️</span>
                  <div>
                    <p className="font-semibold text-destructive mb-1">Error</p>
                    <p className="text-destructive/80">{error}</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {loading && (
            <Card className="border-blue-200 bg-blue-50/50">
              <CardContent className="p-6">
                <div className="flex items-start gap-4">
                  <div className="flex-shrink-0">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-3">
                      <span className="text-blue-600 text-lg">🤖</span>
                      <p className="font-semibold text-blue-900">AI Search in Progress</p>
                    </div>
                    
                    {streamingStatus && (
                      <div className="mb-4">
                        <p className="text-blue-800 font-medium mb-2">Current Status:</p>
                        <div className="bg-blue-100 border border-blue-200 rounded-lg p-3">
                          <p className="text-blue-900 text-sm">{streamingStatus}</p>
                        </div>
                      </div>
                    )}

                    {streamingProgress.length > 0 && (
                      <div>
                        <p className="text-blue-800 font-medium mb-2">Progress Log:</p>
                        <div className="bg-white border border-blue-200 rounded-lg p-3 max-h-32 overflow-y-auto">
                          <div className="space-y-1">
                            {streamingProgress.map((step, index) => (
                              <div key={index} className="flex items-start gap-2 text-sm">
                                <span className="text-blue-500 text-xs mt-1">•</span>
                                <span className="text-blue-900 flex-1">{step}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

                      {searchResult && (
              <div className="space-y-12">
                {formatStructuredResults(searchResult)}
              </div>
            )}

          {/* Search history moved below main content */}
          {renderSearchHistory()}
        </div>
      </div>
    </div>
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