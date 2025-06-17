'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useSession } from 'next-auth/react';
import { useRouter } from 'next/navigation';

const AI_BACKEND_URL = process.env.NEXT_PUBLIC_AI_BACKEND_URL || 'http://localhost:8000';

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

// Basic search response (legacy)
interface BasicSearchResponse {
  cypher_query: string;
  results: any[];
  count: number;
}

// Helper function to format structured search results
const formatStructuredResults = (data: StructuredSearchResponse) => {
  return (
    <div className="space-y-6">
      {/* Query Interpretation */}
      <Card className="border-blue-200">
        <CardHeader className="bg-blue-50">
          <CardTitle className="text-blue-900 flex items-center">
            <span className="mr-2">🧠</span>
            Query Interpretation
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-4">
          <p className="text-gray-700">{data.analysis.query_interpretation}</p>
        </CardContent>
      </Card>

      {/* Methodology */}
      <Card className="border-green-200">
        <CardHeader className="bg-green-50">
          <CardTitle className="text-green-900 flex items-center">
            <span className="mr-2">⚡</span>
            Methodology ({data.analysis.methodology.length} steps)
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-4">
          <ol className="list-decimal list-inside space-y-2">
            {data.analysis.methodology.map((step, index) => (
              <li key={index} className="text-gray-700">{step}</li>
            ))}
          </ol>
        </CardContent>
      </Card>

      {/* Key Insights */}
      <Card className="border-yellow-200">
        <CardHeader className="bg-yellow-50">
          <CardTitle className="text-yellow-900 flex items-center">
            <span className="mr-2">💡</span>
            Key Insights ({data.analysis.key_insights.length})
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-4">
          <ul className="space-y-3">
            {data.analysis.key_insights.map((insight, index) => (
              <li key={index} className="flex items-start">
                <span className="text-yellow-600 mr-2 mt-1">•</span>
                <span className="text-gray-700">{insight}</span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      {/* Formatted Results */}
      <Card className="border-emerald-200">
        <CardHeader className="bg-emerald-50">
          <CardTitle className="text-emerald-900 flex items-center">
            <span className="mr-2">📋</span>
            Results ({data.analysis.formatted_results.length})
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-4">
          {data.analysis.formatted_results.length > 0 ? (
            <div className="space-y-2">
              {data.analysis.formatted_results.map((result, index) => (
                <div key={index} className="flex items-start">
                  <span className="text-emerald-600 mr-2 mt-1">•</span>
                  <span className="text-gray-700">{result}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-gray-500 text-center py-4">No formatted results available.</p>
          )}
        </CardContent>
      </Card>

      {/* Search Results */}
      <Card className="border-purple-200">
        <CardHeader className="bg-purple-50">
          <CardTitle className="text-purple-900 flex items-center">
            <span className="mr-2">📊</span>
            Search Results ({data.total_results})
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-4">
          {data.results.length > 0 ? (
            <div className="space-y-4">
              {data.results.map((result, index) => (
                <div key={index} className="border rounded-lg p-4 bg-white hover:bg-gray-50">
                  <div className="flex items-center justify-between mb-2">
                    <span className="inline-block px-2 py-1 text-xs font-medium bg-purple-100 text-purple-800 rounded">
                      {result.entity_type}
                    </span>
                    {result.relevance_score && (
                      <span className="text-sm text-gray-500">
                        Relevance: {(result.relevance_score * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                  
                  {result.name && (
                    <h4 className="font-semibold text-gray-900 mb-1">{result.name}</h4>
                  )}
                  
                  {result.description && (
                    <p className="text-gray-600 mb-2">{result.description}</p>
                  )}
                  
                  {Object.keys(result.properties).length > 0 && (
                    <div className="mt-3">
                      <h5 className="text-sm font-medium text-gray-700 mb-2">Properties:</h5>
                      <div className="bg-gray-50 rounded p-2">
                        <pre className="text-xs text-gray-600 whitespace-pre-wrap">
                          {JSON.stringify(result.properties, null, 2)}
                        </pre>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-gray-500 text-center py-8">No results found.</p>
          )}
        </CardContent>
      </Card>

      {/* Patterns Identified */}
      {data.analysis.patterns_identified.length > 0 && (
        <Card className="border-indigo-200">
          <CardHeader className="bg-indigo-50">
            <CardTitle className="text-indigo-900 flex items-center">
              <span className="mr-2">🔍</span>
              Patterns Identified ({data.analysis.patterns_identified.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-4">
            <ul className="space-y-2">
              {data.analysis.patterns_identified.map((pattern, index) => (
                <li key={index} className="flex items-start">
                  <span className="text-indigo-600 mr-2 mt-1">•</span>
                  <span className="text-gray-700">{pattern}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {/* Technical Details */}
      <Card className="border-gray-200">
        <CardHeader className="bg-gray-50">
          <CardTitle className="text-gray-900 flex items-center">
            <span className="mr-2">⚙️</span>
            Technical Details
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-4">
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="font-medium text-gray-700">Execution Time:</span>
              <span className="ml-2 text-gray-600">
                {data.execution_time ? `${data.execution_time.toFixed(2)}s` : 'N/A'}
              </span>
            </div>
            <div>
              <span className="font-medium text-gray-700">MCP Tools Used:</span>
              <span className="ml-2 text-gray-600">
                {data.mcp_tools_used ? '✅ Yes' : '❌ No'}
              </span>
            </div>
          </div>
          
          {data.cypher_queries.length > 0 && (
            <div className="mt-4">
              <h5 className="text-sm font-medium text-gray-700 mb-2">Cypher Queries:</h5>
              <div className="bg-gray-100 rounded p-3">
                {data.cypher_queries.map((query, index) => (
                  <pre key={index} className="text-xs text-gray-600 whitespace-pre-wrap">
                    {query}
                  </pre>
                ))}
              </div>
            </div>
          )}

          {data.analysis.limitations.length > 0 && (
            <div className="mt-4">
              <h5 className="text-sm font-medium text-gray-700 mb-2">Limitations:</h5>
              <ul className="space-y-1 text-sm text-gray-600">
                {data.analysis.limitations.map((limitation, index) => (
                  <li key={index} className="flex items-start">
                    <span className="text-orange-500 mr-2 mt-0.5">⚠️</span>
                    <span>{limitation}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Raw Query Results */}
      {data.analysis.raw_query_results.length > 0 && (
        <Card className="border-slate-200">
          <CardHeader className="bg-slate-50">
            <CardTitle className="text-slate-900 flex items-center">
              <span className="mr-2">🔧</span>
              Raw Query Results ({data.analysis.raw_query_results.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-4">
            <div className="bg-slate-100 rounded-lg p-4 max-h-96 overflow-y-auto">
              <pre className="text-xs text-slate-700 whitespace-pre-wrap">
                {JSON.stringify(data.analysis.raw_query_results, null, 2)}
              </pre>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

// Helper function to format basic search results (legacy)
const formatBasicResults = (data: BasicSearchResponse) => {
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Generated Cypher Query</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="bg-gray-100 p-4 rounded-md overflow-x-auto">
            <code>{data.cypher_query}</code>
          </pre>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Results ({data.count})</CardTitle>
        </CardHeader>
        <CardContent>
          {data.results.length > 0 ? (
            <pre className="bg-gray-100 p-4 rounded-md overflow-x-auto max-h-96">
              <code>{JSON.stringify(data.results, null, 2)}</code>
            </pre>
          ) : (
            <p className="text-gray-500 text-center py-8">No results found.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default function SearchPage() {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<StructuredSearchResponse | BasicSearchResponse | null>(null);
  
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
      const res = await fetch(`${AI_BACKEND_URL}/api/ai/search/crew`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data.detail || 'An error occurred during search.');
      } else {
        setResult(data);
      }
    } catch (err) {
      setError('A network error occurred. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const isStructuredResponse = (data: any): data is StructuredSearchResponse => {
    return data && typeof data === 'object' && 'analysis' in data && 'results' in data;
  };

  return (
    <div className="min-h-screen bg-gray-50 p-4 sm:p-6 lg:p-8">
      <div className="max-w-5xl mx-auto">
        <h1 className="text-3xl font-bold text-gray-900 mb-6">Natural Language Search</h1>
        
        <form onSubmit={handleSubmit} className="space-y-4 mb-8">
          <div className="flex items-center space-x-2">
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
          </div>
          
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
            <div className="flex items-center mb-2">
              <span className="text-blue-600 mr-2">🤖</span>
              <span className="font-medium text-blue-900">AI Agent Search</span>
            </div>
            <p className="text-sm text-blue-700">
              Enhanced analysis using CrewAI agents with structured insights powered by Neo4j MCP tools
            </p>
          </div>

          <div className="text-sm text-gray-600">
            <p className="mb-2"><strong>Try asking questions like:</strong></p>
            <ul className="space-y-1 ml-4 text-gray-500">
              <li>• "Show me all cases related to contract disputes"</li>
              <li>• "What are the most common legal doctrines?"</li>
              <li>• "Find cases involving specific parties or judges"</li>
              <li>• "Analyze patterns in legal precedents"</li>
            </ul>
          </div>
        </form>

        {error && (
          <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-6">
            <p className="font-bold">Error</p>
            <p>{error}</p>
          </div>
        )}

        {result && (
          <div className="space-y-6">
            {isStructuredResponse(result) ? (
              formatStructuredResults(result)
            ) : (
              formatBasicResults(result as BasicSearchResponse)
            )}
          </div>
        )}
      </div>
    </div>
  );
} 