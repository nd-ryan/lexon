'use client';

import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useSession } from 'next-auth/react';
import { useRouter } from 'next/navigation';

// Types for structured search response
interface SearchResult {
  entity_type: string;
  entity_id?: string;
  name?: string;
  description?: string;
  properties: Record<string, any>;
  relationships: any[];
  relevance_score?: number;
}

interface SearchAnalysis {
  query_interpretation: string;
  methodology: string[];
  key_insights: string[];
  patterns_identified: string[];
  limitations: string[];
  formatted_results: string[];
  raw_query_results: any[];
}

interface StructuredSearchResponse {
  success: boolean;
  query: string;
  total_results: number;
  results: SearchResult[];
  cypher_queries: string[];
  analysis: SearchAnalysis;
  execution_time?: number;
  mcp_tools_used: boolean;
  agent_reasoning: any[];
}

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
  
  // Use specific icons for known keys
  const keyIcons: Record<string, string> = {
    query_interpretation: '🧠',
    methodology: '⚡',
    key_insights: '💡',
    formatted_results: '📋',
    results: '📊',
    patterns_identified: '🔍',
    limitations: '⚠️',
    cypher_queries: '🔧',
    raw_query_results: '📄',
    execution_time: '⏱️',
    total_results: '📈',
    success: '✅',
    agent_reasoning: '🤖'
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

const renderValue = (value: any, key: string): React.ReactNode => {
  if (value === null || value === undefined) {
    return (
      <div className="flex items-center justify-center py-4 text-muted-foreground">
        <span className="text-sm italic">No data available</span>
      </div>
    );
  }

  if (typeof value === 'boolean') {
    return (
      <div className="flex justify-start">
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
          <div className="bg-muted/50 rounded-lg border p-4 max-h-64 overflow-y-auto scrollbar-thin scrollbar-track-gray-100 scrollbar-thumb-gray-300">
            <pre className="text-sm text-foreground whitespace-pre-wrap leading-relaxed font-mono">
              {value}
            </pre>
          </div>
          <div className="absolute top-2 right-2 bg-background/80 backdrop-blur-sm px-2 py-1 rounded text-xs text-muted-foreground">
            {value.length} chars
          </div>
        </div>
      );
    }
    return (
      <div className="prose prose-sm max-w-none">
        <p className="text-foreground leading-relaxed m-0">{value}</p>
      </div>
    );
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return (
        <div className="flex items-center justify-center py-6 text-muted-foreground border-2 border-dashed rounded-lg">
          <span className="text-sm italic">Empty list</span>
        </div>
      );
    }

    // Handle array of strings/simple values
    if (value.every(item => typeof item === 'string' || typeof item === 'number')) {
      return (
        <div className="space-y-2">
          {value.map((item, index) => (
            <div key={index} className="flex items-start gap-3 p-2 rounded-md hover:bg-muted/50 transition-colors">
              <div className="flex-shrink-0 w-2 h-2 bg-primary/60 rounded-full mt-2"></div>
              <span className="text-foreground leading-relaxed flex-1 break-words">{String(item)}</span>
            </div>
          ))}
        </div>
      );
    }

    // Handle array of objects (like search results)
    if (key === 'results' && value.every(item => typeof item === 'object' && item !== null)) {
      return (
        <div className="space-y-4">
          {value.map((result: any, index: number) => (
            <Card key={index} className="transition-all hover:shadow-md border-l-4 border-l-primary/20">
              <CardContent className="space-y-3">
                {Object.entries(result).map(([resultKey, resultValue]) => (
                  <div key={resultKey} className="group">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-sm font-medium text-muted-foreground bg-muted px-2 py-1 rounded">
                        {formatTitle(resultKey)}
                      </span>
                    </div>
                    <div className="ml-0">
                      {typeof resultValue === 'object' && resultValue !== null ? (
                        <div className="bg-muted/30 rounded-md border p-3 max-h-48 overflow-y-auto">
                          <pre className="text-xs text-foreground whitespace-pre-wrap font-mono leading-relaxed">
                            {JSON.stringify(resultValue, null, 2)}
                          </pre>
                        </div>
                      ) : (
                        <div className="text-foreground break-words">{String(resultValue)}</div>
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
        <div className="bg-muted/30 rounded-lg border p-4 max-h-96 overflow-y-auto scrollbar-thin scrollbar-track-gray-100 scrollbar-thumb-gray-300">
          <pre className="text-xs text-foreground whitespace-pre-wrap font-mono leading-relaxed">
            {JSON.stringify(value, null, 2)}
          </pre>
        </div>
        <div className="absolute top-2 right-2 bg-background/80 backdrop-blur-sm px-2 py-1 rounded text-xs text-muted-foreground">
          {value.length} items
        </div>
      </div>
    );
  }

  if (typeof value === 'object' && value !== null) {
    // Handle nested objects
    return (
      <div className="space-y-4">
        {Object.entries(value).map(([nestedKey, nestedValue]) => (
          <div key={nestedKey} className="relative">
            <div className="border-l-2 border-primary/20 pl-4 pb-4">
              <div className="flex items-center gap-2 mb-3">
                <div className="w-2 h-2 bg-primary/60 rounded-full"></div>
                <span className="font-medium text-foreground text-sm">
                  {formatTitle(nestedKey)}
                </span>
              </div>
              <div className="ml-2">
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
const formatStructuredResults = (data: any) => {
  // Get all keys from the data object
  const dataKeys = Object.keys(data);
  
  return (
    <div className="space-y-8">
      {dataKeys.map((key, index) => {
        const value = data[key];
        const style = getCardStyle(key, index);
        
        // Skip null/undefined values
        if (value === null || value === undefined) {
          return null;
        }
        
        // Calculate count for arrays
        let count = '';
        let countBadge = null;
        if (Array.isArray(value)) {
          count = ` (${value.length})`;
          countBadge = (
            <span className="inline-flex items-center px-2 py-1 bg-primary/10 text-primary text-xs font-medium rounded-full">
              {value.length} items
            </span>
          );
        } else if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
          const objKeys = Object.keys(value);
          if (objKeys.length > 0) {
            count = ` (${objKeys.length} props)`;
            countBadge = (
              <span className="inline-flex items-center px-2 py-1 bg-primary/10 text-primary text-xs font-medium rounded-full">
                {objKeys.length} properties
              </span>
            );
          }
        }

        return (
          <Card key={key} className={`${style.border} shadow-sm hover:shadow-md transition-all duration-200 overflow-hidden`}>
            <CardHeader className={`${style.header} border-b border-border/50`}>
              <div className="flex items-center justify-between w-full">
                <CardTitle className={`${style.text} flex items-center gap-3`}>
                  <span className="text-lg">{style.icon}</span>
                  <span className="font-semibold tracking-tight">{formatTitle(key)}</span>
                </CardTitle>
                {countBadge}
              </div>
            </CardHeader>
            <CardContent className="p-6">
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
  const [searchType, setSearchType] = useState<'basic' | 'crew'>('crew');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [searchResult, setSearchResult] = useState<StructuredSearchResponse | null>(null);
  const [searchHistory, setSearchHistory] = useState<SearchHistoryItem[]>([]);
  const [expandedHistoryId, setExpandedHistoryId] = useState<string | null>(null);
  const { data: session, status } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (status === 'unauthenticated') {
      router.push('/auth/signin');
    } else if (status === 'authenticated') {
      fetchSearchHistory();
    }
  }, [status, router]);

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

    setLoading(true);
    setError('');
    setSearchResult(null);

    try {
      const endpoint = searchType === 'crew' ? '/api/search/crew' : '/api/search';
      const res = await fetch(endpoint, {
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
    } catch {
      setError('An error occurred. Please try again.');
      console.error("Search failed:");
    } finally {
      setLoading(false);
    }
  };

  const isStructuredResponse = (data: any): data is StructuredSearchResponse => {
    return 'results' in data && 'analysis' in data && 'total_results' in data;
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
                            const result = historyItem.searchResult as any;
                            // Try to find any numeric field that might represent result count
                            if (result.total_results !== undefined) return `${result.total_results} results`;
                            if (result.results && Array.isArray(result.results)) return `${result.results.length} results`;
                            if (typeof result === 'object') {
                              // Count all array properties
                              const arrays = Object.values(result).filter(v => Array.isArray(v));
                              const totalItems = arrays.reduce((sum, arr) => sum + arr.length, 0);
                              return totalItems > 0 ? `${totalItems} items` : 'No count';
                            }
                            return 'Unknown';
                          })()}
                        </span>
                        {historyItem.executionTime && (
                          <span className="text-muted-foreground">⏱️ {historyItem.executionTime.toFixed(1)}s</span>
                        )}
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
          <h1 className="text-4xl font-bold text-foreground mb-2 tracking-tight">Natural Language Search</h1>
          <p className="text-muted-foreground text-lg">Explore your knowledge graph with AI-powered insights</p>
        </div>
        
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Main search area */}
          <div className="lg:col-span-2 space-y-8">
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
                  
                  <div className="bg-primary/5 border border-primary/20 rounded-lg p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-primary text-lg">🤖</span>
                      <span className="font-semibold text-primary">AI Agent Search</span>
                    </div>
                    <p className="text-sm text-muted-foreground leading-relaxed">
                      Enhanced analysis using CrewAI agents with structured insights powered by Neo4j MCP tools
                    </p>
                  </div>

                  <div className="bg-muted/30 rounded-lg p-4 border">
                    <p className="font-medium text-foreground mb-3">Try asking questions like:</p>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm">
                      <div className="flex items-start gap-2">
                        <div className="w-1.5 h-1.5 bg-primary rounded-full mt-2 flex-shrink-0"></div>
                        <span className="text-muted-foreground">"Show me all cases related to contract disputes"</span>
                      </div>
                      <div className="flex items-start gap-2">
                        <div className="w-1.5 h-1.5 bg-primary rounded-full mt-2 flex-shrink-0"></div>
                        <span className="text-muted-foreground">"What are the most common legal doctrines?"</span>
                      </div>
                      <div className="flex items-start gap-2">
                        <div className="w-1.5 h-1.5 bg-primary rounded-full mt-2 flex-shrink-0"></div>
                        <span className="text-muted-foreground">"Find cases involving specific parties"</span>
                      </div>
                      <div className="flex items-start gap-2">
                        <div className="w-1.5 h-1.5 bg-primary rounded-full mt-2 flex-shrink-0"></div>
                        <span className="text-muted-foreground">"Analyze patterns in legal precedents"</span>
                      </div>
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

            {searchResult && (
              <div className="space-y-8">
                {formatStructuredResults(searchResult)}
              </div>
            )}
          </div>
          
          {/* Search history sidebar */}
          <div className="lg:col-span-1">
            <div className="sticky top-8">
              {renderSearchHistory()}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default function SearchPageContainer() {
  const { data: session, status } = useSession();
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