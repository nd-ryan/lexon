"use client";

import { useState, useEffect } from 'react';
import { useSession } from 'next-auth/react';
import type { Session } from 'next-auth';
import { useRouter } from 'next/navigation';
import Button from '@/components/ui/button';
import { hasAtLeastRole } from '@/lib/rbac';

type StepName = 'reason' | 'interpret' | 'searches' | 'traversal' | 'answer';
type StepMode = 'full_chain' | 'isolated';

interface StepResult {
  success: boolean;
  duration_seconds: number;
  step?: StepName;
  mode?: StepMode;
  timings?: {
    schema_load_seconds?: number;
    prompt_build_seconds?: number;
    llm_plan_seconds?: number;
    interpret_total_seconds?: number;
    endpoint_total_seconds?: number;
    // Allow for any additional keys from the backend without breaking the UI
    [key: string]: number | undefined;
  };
  // For interpret step
  plan?: {
    steps: Array<{
      node_type: string;
      search_type: string;
      query_term?: string;
      via?: string;
    }>;
  } | null;
  // For reason step or included in interpret
  reasoning?: string;
  // Generic container for per-step inputs and outputs
  input_used?: any;
  output?: any;
  chain_history?: Array<{
    step: string;
    input: any;
    output: any;
  }>;
  error?: string;
}

export default function QueryEvalPage() {
  const { data: session, status: sessionStatus } = useSession();
  const router = useRouter();
  const [query, setQuery] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<StepResult | null>(null);
  const [step, setStep] = useState<StepName>('interpret');
  const [mode, setMode] = useState<StepMode>('full_chain');
  const [seedJson, setSeedJson] = useState<string>('');
  const [seedError, setSeedError] = useState<string | null>(null);

  const role = (session?.user as Session['user'])?.role
  const isAdmin = hasAtLeastRole(role, 'admin');

  // Protect the page - only allow admin email
  useEffect(() => {
    if (sessionStatus === 'loading') return;
    if (!session || !isAdmin) {
      router.replace('/cases');
    }
  }, [session, sessionStatus, router, isAdmin]);

  // Show loading while checking auth
  if (sessionStatus === 'loading' || !session || !isAdmin) {
    return <div className="p-8">Loading...</div>;
  }

  const runEval = async () => {
    if (!query.trim()) return;
    setIsLoading(true);
    setResult(null);
    setSeedError(null);

    let parsedSeed: any = undefined;
    if (mode === 'isolated' && seedJson.trim()) {
      try {
        parsedSeed = JSON.parse(seedJson);
      } catch {
        setSeedError('Seed JSON is invalid');
        setIsLoading(false);
        return;
      }
    }

    try {
      const res = await fetch('/api/v1/eval/step', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          query,
          step,
          mode,
          seed: parsedSeed,
        }),
      });

      if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.detail || 'Request failed');
      }

      const data = await res.json();
      setResult(data);
      // If backend auto-generated a seed, pretty-print it for further editing
      if (data?.input_used && mode === 'isolated') {
        setSeedJson(JSON.stringify(data.input_used, null, 2));
      }
    } catch (err: any) {
      setResult({ success: false, duration_seconds: 0, error: err.message });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="p-8 max-w-4xl mx-auto space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Query Flow Evaluation</h1>
          <p className="text-gray-500">Isolate and test individual steps of the search agent.</p>
        </div>
        <span className="text-sm text-gray-600">
          Logged in as: {session.user?.email}
        </span>
      </div>

      <div className="bg-yellow-50 border border-yellow-200 rounded p-4 text-sm">
        <strong>⚠️ Admin Only:</strong> Use this tool to debug and evaluate the performance of individual agent steps.
      </div>

      <div className="border rounded-lg p-6 bg-white shadow-sm space-y-4">
        <div className="flex justify-between items-center">
          <div className="space-y-1">
            <h2 className="text-lg font-semibold">Query Flow Step Evaluator</h2>
            <p className="text-xs text-gray-500">
              Choose a step, decide whether to run preceding steps or test in isolation, and inspect inputs/outputs.
            </p>
          </div>
          <span className="text-xs bg-blue-100 text-blue-800 px-2 py-1 rounded">
            {step === 'reason' ? 'Step 1: Reasoning' :
             step === 'interpret' ? 'Step 2: Interpret & Plan' :
             step === 'searches' ? 'Step 3: Vector Searches' :
             step === 'traversal' ? 'Step 4: Deterministic Traversal' :
             'Step 5: Answer Synthesis'}
          </span>
        </div>

        <div className="space-y-2">
          <label className="text-sm font-medium">Test Query</label>
          <div className="flex gap-2">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g., What are the antitrust implications of platform monopolies?"
              className="flex-1 border rounded px-3 py-2 text-sm"
            />
            <Button 
              onClick={runEval} 
              disabled={isLoading || !query.trim()}
            >
              {isLoading ? 'Running...' : 'Run Step'}
            </Button>
          </div>
        </div>

        {/* Step & mode controls */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="space-y-1">
            <label className="text-sm font-medium">Step</label>
            <select
              value={step}
              onChange={(e) => setStep(e.target.value as StepName)}
              className="w-full border rounded px-3 py-2 text-sm bg-white"
            >
              <option value="reason">1. Reasoning</option>
              <option value="interpret">2. Interpret & Plan</option>
              <option value="searches">3. Vector Searches</option>
              <option value="traversal">4. Deterministic Traversal</option>
              <option value="answer">5. Gather Enriched Data (Raw Answer)</option>
            </select>
          </div>

          <div className="space-y-1">
            <label className="text-sm font-medium">Mode</label>
            <div className="flex gap-3 text-xs">
              <label className="flex items-center gap-1 cursor-pointer">
                <input
                  type="radio"
                  name="mode"
                  value="full_chain"
                  checked={mode === 'full_chain'}
                  onChange={() => setMode('full_chain')}
                />
                <span>Run preceding steps (full chain)</span>
              </label>
              <label className="flex items-center gap-1 cursor-pointer">
                <input
                  type="radio"
                  name="mode"
                  value="isolated"
                  checked={mode === 'isolated'}
                  onChange={() => setMode('isolated')}
                />
                <span>Isolated (with editable seed)</span>
              </label>
            </div>
          </div>
        </div>

        {/* Seed editor for isolated mode and steps beyond reason */}
        {mode === 'isolated' && step !== 'reason' && (
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <label className="text-sm font-medium">Seed input JSON</label>
              <span className="text-xs text-gray-500">
                Leave blank to auto-fill from running preceding steps once.
              </span>
            </div>
            <textarea
              value={seedJson}
              onChange={(e) => setSeedJson(e.target.value)}
              rows={8}
              className="w-full border rounded px-3 py-2 text-xs font-mono"
              placeholder={
                step === 'interpret'
                  ? '{ "reasoning": "..." }'
                  : step === 'searches'
                  ? '{ "route_plan": { "steps": [...] } }'
                  : '{ "found_nodes": { "id": { "id": "...", "label": "...", "properties": {...}, "score": 1.0 } } }'
              }
            />
            {seedError && (
              <div className="text-xs text-red-600">{seedError}</div>
            )}
          </div>
        )}

        {/* Output Display */}
        {result && (
          <div className={`mt-4 p-4 rounded text-sm font-mono whitespace-pre-wrap overflow-auto max-h-[400px] ${
            result.success ? 'bg-gray-50 border border-gray-200' : 'bg-red-50 border border-red-200 text-red-700'
          }`}>
            {result.success ? (
              <>
                <div className="mb-2 text-green-600 font-bold">
                  ✅ Success ({result.duration_seconds.toFixed(3)}s total)
                </div>
                {result.timings && (
                  <div className="mb-3 text-xs text-gray-700 space-y-1">
                    <div className="font-semibold">Timing breakdown:</div>
                    {Object.entries(result.timings).map(([key, value]) => (
                      <div key={key}>• {key}: {value?.toFixed(3)}s</div>
                    ))}
                  </div>
                )}
                {/* Show reasoning if present */}
                {result.reasoning && (
                  <div className="mb-2">
                    <div className="font-semibold mb-1">Reasoning:</div>
                    <div className="bg-white p-2 border rounded text-xs whitespace-pre-wrap">
                        {result.reasoning}
                    </div>
                  </div>
                )}
                {/* Show plan if present (usually for interpret step) */}
                {result.plan && (
                  <div className="mb-2">
                    <div className="font-semibold mb-1">Route Plan:</div>
                    <pre>{JSON.stringify(result.plan, null, 2)}</pre>
                  </div>
                )}
                {/* Special handling for searches/traversal/answer steps - show summary */}
                {result.output?.state?.summary && (
                  <div className="mb-3 bg-blue-50 p-3 rounded border border-blue-200">
                    <div className="font-semibold mb-2 text-blue-900">Results Summary</div>
                    <div className="text-xs space-y-1">
                      <div><strong>Total unique nodes:</strong> {result.output.state.summary.total_nodes}</div>
                      {result.output.state.summary.nodes_by_label && Object.keys(result.output.state.summary.nodes_by_label).length > 0 && (
                        <div>
                          <strong>By label (unique):</strong>
                          <div className="ml-4 mt-1">
                            {Object.entries(result.output.state.summary.nodes_by_label).map(([label, count]) => (
                              <div key={label}>• {label}: {count as number}</div>
                            ))}
                          </div>
                        </div>
                      )}
                      {result.output.state.summary.step_results_summary && Object.keys(result.output.state.summary.step_results_summary).length > 0 && (
                        <div className="mt-2">
                          <strong>Per-step results:</strong>
                          <div className="ml-4 mt-1">
                            {Object.entries(result.output.state.summary.step_results_summary).map(([stepKey, stepInfo]: [string, any]) => (
                              <div key={stepKey} className={stepInfo.search_type === 'embedding' ? 'text-green-700' : 'text-purple-700'}>
                                • {stepKey}: {stepInfo.unique_nodes} unique {stepInfo.node_type} nodes 
                                {stepInfo.total_results !== stepInfo.unique_nodes && (
                                  <span className="text-gray-600"> ({stepInfo.total_results} total, {stepInfo.duplicates} duplicates)</span>
                                )}
                                <span className="ml-1 text-gray-500">({stepInfo.search_type})</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                      {result.output.state.summary.nodes_by_step && Object.keys(result.output.state.summary.nodes_by_step).length > 0 && (
                        <div className="mt-2 pt-2 border-t border-blue-300">
                          <strong>Deduplication stats:</strong>
                          <div className="ml-4 mt-1 text-gray-700">
                            {Object.entries(result.output.state.summary.nodes_by_step).map(([stepKey, stepStats]: [string, any]) => (
                              <div key={stepKey}>
                                • {stepKey}: {stepStats.unique_nodes} unique from {stepStats.total_results} results
                                {stepStats.duplicates > 0 && <span className="text-orange-600"> ({stepStats.duplicates} duplicates removed)</span>}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}
                {/* Sample nodes by step */}
                {result.output?.state?.found_nodes && result.output?.state?.step_results && (
                  <div className="mb-3">
                    <details className="text-xs">
                      <summary className="cursor-pointer font-semibold text-blue-600 hover:text-blue-800">
                        View sample nodes by step
                      </summary>
                      <div className="mt-2 space-y-3">
                        {Object.entries(result.output.state.step_results)
                          .sort((a, b) => parseInt(a[0]) - parseInt(b[0]))
                          .map(([stepKey, nodeIds]: [string, any]) => {
                          const stepIdx = parseInt(stepKey);
                          // Use safe access for steps array
                          const steps = result.output?.state?.route_plan?.steps || [];
                          const stepInfo = stepIdx < steps.length ? steps[stepIdx] : null;
                          const sampleSize = 3;
                          const sampleIds = Array.isArray(nodeIds) ? nodeIds.slice(0, sampleSize) : [];
                          
                          return (
                            <div key={stepKey} className="border rounded overflow-hidden">
                              <div className={`px-3 py-2 font-medium flex justify-between items-center ${
                                stepInfo?.search_type === 'embedding' ? 'bg-green-50 text-green-900 border-b border-green-100' : 'bg-purple-50 text-purple-900 border-b border-purple-100'
                              }`}>
                                <span>Step {stepKey}: {stepInfo?.node_type || 'Unknown'}</span>
                                <span className="text-xs opacity-75 uppercase tracking-wide">{stepInfo?.search_type || 'N/A'}</span>
                              </div>
                              <div className="p-2 bg-gray-50">
                                <div className="text-xs text-gray-600 mb-2 flex justify-between">
                                  <span>Path: {stepInfo?.path ? stepInfo.path.join(' → ') : 'N/A'}</span>
                                  <span>Showing {sampleSize} of {Array.isArray(nodeIds) ? nodeIds.length : 0} results</span>
                                </div>
                                <div className="space-y-2">
                                  {sampleIds.map((nodeId: string) => {
                                    const node = result.output?.state?.found_nodes?.[nodeId];
                                    if (!node) return null;
                                    
                                    return (
                                      <div key={nodeId} className="bg-white p-2 rounded border text-xs shadow-sm">
                                        <div className="font-mono text-gray-500 mb-1 flex justify-between">
                                          <span>{nodeId.substring(0, 8)}...</span>
                                          <span className="font-semibold text-gray-700">Score: {node.score?.toFixed(4)}</span>
                                        </div>
                                        <div className="font-medium text-gray-900 mb-1">{node.label}</div>
                                        {node.found_by_steps && (
                                          <div className="text-gray-500 mb-1">Found by steps: {node.found_by_steps.join(', ')}</div>
                                        )}
                                        {node.properties && (
                                          <div className="mt-1 pt-1 border-t border-gray-100">
                                            <div className="text-gray-700 space-y-1">
                                              {Object.entries(node.properties).slice(0, 2).map(([key, value]) => (
                                                <div key={key} className="flex gap-2">
                                                  <span className="font-semibold min-w-[80px]">{key}:</span>
                                                  <span className="truncate">{typeof value === 'string' && value.length > 100 ? value.substring(0, 100) + '...' : String(value)}</span>
                                                </div>
                                              ))}
                                            </div>
                                          </div>
                                        )}
                                      </div>
                                    );
                                  })}
                                </div>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </details>
                  </div>
                )}
                {/* Chain History Display */}
                {result.chain_history && Array.isArray(result.chain_history) ? (
                  <div className="space-y-6 border-t pt-4 mt-4">
                    <h3 className="text-lg font-bold text-gray-800">Execution History (Full Chain)</h3>
                    {result.chain_history.map((stepData: any, idx: number) => (
                      <div key={idx} className="border rounded-lg overflow-hidden shadow-sm">
                        <div className="bg-gray-100 px-4 py-2 font-semibold flex justify-between items-center">
                          <span>Step {idx + 1}: {stepData.step.toUpperCase()}</span>
                        </div>
                        <div className="p-4 space-y-4">
                          {/* Input Section */}
                          <div>
                            <div className="font-semibold text-sm mb-1 text-gray-700">Input</div>
                            <details className="text-xs">
                              <summary className="cursor-pointer text-blue-600 hover:text-blue-800 mb-1">
                                View input payload ({Object.keys(stepData.input || {}).length} fields)
                              </summary>
                              <pre className="bg-white p-3 rounded border border-gray-200 overflow-auto max-h-40 shadow-inner">
                                {JSON.stringify(stepData.input, null, 2)}
                              </pre>
                            </details>
                          </div>

                          {/* Output Section */}
                          <div>
                            <div className="font-semibold text-sm mb-1 text-gray-700">Output</div>
                            <details className="text-xs" open={true}>
                              <summary className="cursor-pointer text-blue-600 hover:text-blue-800 mb-1">
                                View output payload
                              </summary>
                              <pre className="bg-white p-3 rounded border border-gray-200 overflow-auto max-h-60 shadow-inner">
                                {JSON.stringify(stepData.output, null, 2)}
                              </pre>
                            </details>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  /* Generic input/output payloads for isolated mode or fallback */
                  <div className="flex flex-col gap-4 border-t pt-4 mt-4">
                    {/* Output first (most relevant) */}
                    {result.output && (
                      <div>
                        <div className="font-semibold mb-1 flex justify-between items-center">
                          <span>Output (Result of {step})</span>
                          <span className="text-xs font-normal text-gray-500">JSON Payload</span>
                        </div>
                        <details className="text-xs" open={!result.output?.state?.summary}>
                          <summary className="cursor-pointer text-blue-600 hover:text-blue-800 mb-1">
                            View full output payload
                          </summary>
                          <pre className="bg-white p-3 rounded border border-gray-200 overflow-auto max-h-96 shadow-inner">
                            {JSON.stringify(result.output, null, 2)}
                          </pre>
                        </details>
                      </div>
                    )}
                    
                    {/* Input second */}
                    {result.input_used && (
                      <div>
                        <div className="font-semibold mb-1 flex justify-between items-center">
                          <span>Input (Context for {step})</span>
                          <span className="text-xs font-normal text-gray-500">JSON Payload</span>
                        </div>
                        <details className="text-xs">
                          <summary className="cursor-pointer text-blue-600 hover:text-blue-800 mb-1">
                            View input payload ({Object.keys(result.input_used).length} fields)
                          </summary>
                          <pre className="bg-white p-3 rounded border border-gray-200 overflow-auto max-h-60 shadow-inner">
                            {JSON.stringify(result.input_used, null, 2)}
                          </pre>
                        </details>
                      </div>
                    )}
                  </div>
                )}
              </>
            ) : (
              <div>❌ Error: {result.error}</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
