"use client";

import { useState, useEffect } from 'react';
import Button from '@/components/ui/button';
import { useSession } from 'next-auth/react';
import { useRouter } from 'next/navigation';

export default function ImportPage() {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

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
      const res = await fetch('/api/import-kg', {
        method: 'POST',
        body: formData,
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data.detail || 'An error occurred during upload.');
      } else {
        // Handle the response from advanced processing
        if (data.success) {
          const resultText = data.result || data.message || '';
          setSuccess(`✅ Document processing complete! File: "${data.filename}"\n\nResult: ${resultText.substring(0, 300)}${resultText.length > 300 ? '...' : ''}`);
        } else {
          // Handle any error in the response
          setError(data.error || 'Processing failed but no specific error was provided.');
        }
        setFile(null);
      }
    } catch {
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
            <input
              id="file-upload"
              name="file-upload"
              type="file"
              onChange={handleFileChange}
              accept=".docx"
              className="block w-full text-sm text-gray-900 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-medium file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100"
            />
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