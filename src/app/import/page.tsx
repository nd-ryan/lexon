'use client';

import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useSession } from 'next-auth/react';
import { useRouter } from 'next/navigation';

export default function ImportPage() {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [processingMode, setProcessingMode] = useState<'standard' | 'advanced'>('standard');
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
    return null; // or a loading spinner, as the redirect is happening
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setFile(e.target.files[0]);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) {
      setError('Please select a file to upload.');
      return;
    }

    setLoading(true);
    setError('');
    setSuccess('');

    const formData = new FormData();
    formData.append('file', file);

    try {
      const AI_BACKEND_URL = process.env.NEXT_PUBLIC_AI_BACKEND_URL || 'http://localhost:8000';
      const endpoint = processingMode === 'advanced' ? '/api/ai/import-kg/advanced' : '/api/ai/import-kg';
      const res = await fetch(`${AI_BACKEND_URL}${endpoint}`, {
        method: 'POST',
        body: formData,
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data.detail || 'An error occurred during upload.');
      } else {
        // Handle the new CrewAI response format
        if (data.type === 'crew_processing' || data.type === 'crew_processing_advanced') {
          // Extract counts from the analysis if available, or show general success
          const analysisText = data.analysis || '';
          const mode = data.type === 'crew_processing_advanced' ? 'Advanced' : 'Standard';
          const mcpInfo = data.mcp_tools_used ? ' (with MCP tools)' : '';
          
          setSuccess(`✅ ${mode} processing complete${mcpInfo}! File: "${data.filename}"\n\nAnalysis: ${analysisText.substring(0, 300)}${analysisText.length > 300 ? '...' : ''}`);
        } else {
          // Fallback for any legacy response format
          setSuccess(`Successfully imported: ${data.counts?.cases || 0} cases, ${data.counts?.parties || 0} parties, ${data.counts?.provisions || 0} provisions.`);
        }
        setFile(null);
      }
    } catch (err) {
      setError('A network error occurred. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="max-w-md w-full space-y-8 p-10 bg-white shadow-lg rounded-xl">
        <div>
          <h2 className="mt-6 text-center text-3xl font-extrabold text-gray-900">
            Import Knowledge Graph
          </h2>
          <p className="mt-2 text-center text-sm text-gray-600">
            Upload a .docx file to create and import a knowledge graph into Neo4j.
          </p>
        </div>
        <form className="mt-8 space-y-6" onSubmit={handleSubmit}>
          {error && (
            <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded">
              {error}
            </div>
          )}
          {success && (
            <div className="bg-green-100 border border-green-400 text-green-700 px-4 py-3 rounded">
              <pre className="whitespace-pre-wrap text-sm">{success}</pre>
            </div>
          )}
          <div>
            <label htmlFor="file-upload" className="sr-only">
              Choose file
            </label>
            <Input
              id="file-upload"
              name="file-upload"
              type="file"
              onChange={handleFileChange}
              accept=".docx"
            />
          </div>

          <div className="space-y-3">
            <label className="text-sm font-medium text-gray-700">Processing Mode</label>
            <div className="flex items-center space-x-6">
              <label className="flex items-center space-x-2">
                <input
                  type="radio"
                  value="standard"
                  checked={processingMode === 'standard'}
                  onChange={(e) => setProcessingMode(e.target.value as 'standard' | 'advanced')}
                  className="text-blue-600"
                />
                <span className="text-sm text-gray-700">Standard</span>
              </label>
              <label className="flex items-center space-x-2">
                <input
                  type="radio"
                  value="advanced"
                  checked={processingMode === 'advanced'}
                  onChange={(e) => setProcessingMode(e.target.value as 'standard' | 'advanced')}
                  className="text-blue-600"
                />
                <span className="text-sm text-gray-700">Advanced (MCP)</span>
              </label>
            </div>
            <p className="text-xs text-gray-500">
              {processingMode === 'standard' 
                ? 'AI agent processing with document analysis tools'
                : 'Enhanced processing with direct Neo4j database tools'
              }
            </p>
          </div>

          <div>
            <Button
              type="submit"
              disabled={loading || !file}
              className="w-full"
            >
              {loading ? 'Importing...' : 'Import'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
} 