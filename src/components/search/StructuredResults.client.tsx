import React, { useEffect, useRef, useState } from "react";
import Card from "@/components/ui/card";
import { X } from "lucide-react";

export interface StructuredSearchResponse {
  success: boolean;
  explanation: string;
  raw_results: any[];
  cypher_queries: string[];
  query: string;
  execution_time?: number;
}

// Keys that should not be rendered anywhere (top-level or nested)
const HIDDEN_KEYS = new Set<string>([
  "success",
  // cypher queries (various casings)
  "cypher_queries",
  "cypherQueries",
  "cypherQuery",
  // execution time (various casings)
  "execution_time",
  "executionTime",
  "execution-time",
  // query type (various casings)
  "query_type",
  "queryType",
  // also hide the original query (already shown above)
  "query",
]);

// Normalization helper: lowercases and collapses non-alphanumerics to underscores
const normalizeKey = (k: string) => k.toLowerCase().replace(/[^a-z0-9]+/g, "_");
const HIDDEN_KEYS_NORMALIZED = new Set([
  "success",
  "cypher_queries",
  "execution_time",
  "query_type",
]);

// Removed old colored header styles; relying on Radix default styling for cards

const formatTitle = (key: string) =>
  key
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");

// No defaults; use strictly what is fetched from backend mappings

const pickFirstProp = (obj: Record<string, unknown>, keys: string[]): string | null => {
  for (const key of keys) {
    const val = obj[key];
    if (val !== undefined && val !== null) {
      const str = String(val).trim();
      if (str.length > 0) return str;
    }
  }
  return null;
};

const pickFirstPropKey = (obj: Record<string, unknown>, keys: string[]): string | null => {
  for (const key of keys) {
    const val = obj[key];
    if (val !== undefined && val !== null) {
      const str = String(val).trim();
      if (str.length > 0) return String(key);
    }
  }
  return null;
};

const extractNodeParts = (node: Record<string, unknown>) => {
  const { relationships, node_label, ...rest } = node as {
    relationships?: any;
    node_label?: string;
    [k: string]: unknown;
  };
  const propsOnly = rest as Record<string, unknown>;
  const rels: Array<{ type: string; direction?: string; target_label?: string; target_id?: unknown; target_name?: unknown }> =
    Array.isArray(relationships) ? relationships : [];
  return { propsOnly, relationships: rels, nodeLabel: typeof node_label === "string" ? node_label : undefined };
};

const formatNodeLabel = (label?: string) => {
  if (!label) return "";
  const spaced = label.replace(/_/g, " ").replace(/([a-z])([A-Z])/g, "$1 $2");
  return spaced
    .split(" ")
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");
};

// reserved for future color-coding by label; unused for now

const getCompactProps = (propsOnly: Record<string, unknown>, limit = 1000) => {
  const entries = Object.entries(propsOnly).filter(
    ([k, v]) => k !== "relationships" && typeof v !== "object" && v !== undefined && v !== null
  );
  return entries.slice(0, limit);
};

const pillBase = "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium";
const badgeAccent = "bg-indigo-50 text-indigo-700 border-indigo-200";
const badgeAccentSubtle = "bg-indigo-100 text-indigo-700 border-indigo-200";
const badgeGray = "bg-gray-100 text-gray-700 border-gray-200";

const NodeResultsGrid = ({ nodes, titleProps, idProps }: { nodes: Array<Record<string, unknown>>; titleProps: string[]; idProps: string[] }) => {
  const [appendedNodes, setAppendedNodes] = useState<Array<Record<string, unknown>>>([]);

  const handleOpenRelated = async (label?: string, idValue?: string) => {
    if (!label || !idValue) return;
    try {
      const res = await fetch(`/api/node/enriched?label=${encodeURIComponent(label)}&id_value=${encodeURIComponent(idValue)}`, { cache: 'no-store' });
      if (!res.ok) return;
      const payload = await res.json();
      const added = Array.isArray(payload?.nodes) ? payload.nodes : [];
      if (added.length > 0) {
        setAppendedNodes((prev) => [...prev, ...added]);
      }
    } catch {}
  };
  const debugLoggedRef = useRef(false);
  if (!Array.isArray(nodes) || nodes.length === 0) {
    return (
      <div className="flex items-center justify-center py-8 text-gray-500 border-2 border-dashed rounded-lg">
        <span className="text-sm italic">No results</span>
      </div>
    );
  }
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-2 gap-6 md:gap-8">
      {[...nodes, ...appendedNodes].map((node: Record<string, unknown>, index: number) => {
        const { propsOnly, relationships, nodeLabel } = extractNodeParts(node);
        const titleKey = pickFirstPropKey(propsOnly, titleProps);
        const title = (titleKey ? String((propsOnly as any)[titleKey]) : pickFirstProp(propsOnly, titleProps)) || "";
        // Do not render a subtitle with IDs
        const subtitle = "";
        const compactProps = getCompactProps(propsOnly, 1000)
          .filter(([k]) => !idProps.includes(String(k)))
          .filter(([k]) => (titleKey ? String(k) !== titleKey : true));

        const isAppended = index >= nodes.length;
        const appendedIndex = isAppended ? index - nodes.length : -1;

        if (!debugLoggedRef.current && index === 0 && typeof window !== 'undefined') {
          debugLoggedRef.current = true;
          try {
            // Basic runtime diagnostics to verify title selection
            console.debug("StructuredResults diagnostics:", {
              titleProps,
              idProps,
              firstNodeKeys: Object.keys(propsOnly || {}),
              computedTitle: title,
              computedSubtitle: subtitle,
            });
          } catch {}
        }

        return (
          <Card key={index} className="hover:shadow-md transition-all overflow-hidden flex flex-col min-h-0">
            {isAppended && (
              <div className="flex justify-end w-full p-2">
                <button
                  type="button"
                  onClick={() => {
                    if (appendedIndex >= 0) {
                      setAppendedNodes((prev) => prev.filter((_, i) => i !== appendedIndex));
                    }
                  }}
                  aria-label="Remove card"
                  title="Remove card"
                  className="inline-flex items-center justify-center h-6 w-6 rounded-md border border-red-200 bg-red-50 text-red-700 hover:bg-red-100"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            )}
            <div className="p-4 flex-1 flex flex-col min-h-0 overflow-y-auto pr-1">
              <div className="mb-3">
                <div className="flex items-center flex-wrap gap-2">
                  <span className="text-base font-medium leading-tight break-words whitespace-normal flex-1">
                    {title}
                  </span>
                  {nodeLabel && (
                    <span className={`${pillBase} ${badgeAccent}`}>
                      {formatNodeLabel(nodeLabel)}
                    </span>
                  )}
                </div>
                {/* subtitle removed (IDs hidden) */}
              </div>
              <div className="grid grid-cols-2 gap-2 items-start text-xs">
                {compactProps.length === 0 ? (
                  <div className="col-span-2 text-gray-500 italic">No simple properties</div>
                ) : (
                  compactProps.map(([k, v]) => (
                    <div key={k} className="rounded-lg border p-2 bg-gray-100">
                      <div className="text-xs text-gray-500 uppercase tracking-wide mb-2">
                        {formatTitle(k)}:&nbsp;
                      </div>
                      <div className="text-xs break-words whitespace-pre-wrap">
                        {String(v ?? "")}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
            <div className="border-t bg-gray-100">
              <div className="p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs text-gray-600 font-medium">Relationships</span>
                  <span className={`${pillBase} ${badgeAccent}`}>{relationships.length}</span>
                </div>
                <div className="max-h-28 overflow-y-auto pr-1 space-y-1">
                  {relationships.length === 0 ? (
                    <span className="text-xs text-gray-500 italic">None</span>
                  ) : (
                    relationships.map((rel, i) => {
                      const isIncoming = (rel as any)?.direction === 'in';
                      const otherText = String((rel as any)?.target_name ?? (rel as any)?.target_id ?? "");
                      const otherLabel = (rel as any)?.target_label as string | undefined;
                      const thisLabel = nodeLabel;

                      return (
                        <div key={i} className="text-xs flex items-center gap-2 bg-white/60 border rounded-md px-2 py-1">
                          {isIncoming ? (
                            <>
                              {/* Incoming: (Label) Name → TYPE → (This NodeLabel) */}
                              {otherLabel && (
                                <span className={`${pillBase} ${badgeGray}`}>{otherLabel}</span>
                              )}
                              <button
                                type="button"
                                className="truncate underline text-blue-600 hover:text-blue-800 cursor-pointer bg-transparent p-0 border-0"
                                onClick={() => handleOpenRelated(otherLabel, String((rel as any)?.target_id ?? ''))}
                                aria-label={`Open related ${otherLabel ?? 'node'}`}
                                title={`Open related ${otherLabel ?? 'node'}`}
                              >
                                <span className="truncate text-sm">{otherText}</span>
                              </button>
                              <span className="text-gray-500">→</span>
                              <span className={`${pillBase} ${badgeAccent}`}>{String((rel as any)?.type || '')}</span>
                              <span className="text-gray-500">→</span>
                              <span className={`${pillBase} ${badgeAccentSubtle}`}>{`This${thisLabel ? ` ${thisLabel}` : ''}`}</span>
                            </>
                          ) : (
                            <>
                              {/* Outgoing: TYPE → Name (Label) */}
                              <span className={`${pillBase} ${badgeAccent}`}>{String((rel as any)?.type || '')}</span>
                              <span className="text-gray-500">→</span>
                              <button
                                type="button"
                                className="truncate underline text-blue-600 hover:text-blue-800 cursor-pointer bg-transparent p-0 border-0"
                                onClick={() => handleOpenRelated(otherLabel, String((rel as any)?.target_id ?? ''))}
                                aria-label={`Open related ${otherLabel ?? 'node'}`}
                                title={`Open related ${otherLabel ?? 'node'}`}
                              >
                                <span className="truncate text-sm">{otherText}</span>
                              </button>
                              {otherLabel && (
                                <span className={`${pillBase} ${badgeGray}`}>{otherLabel}</span>
                              )}
                            </>
                          )}
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            </div>
          </Card>
        );
      })}
    </div>
  );
};

const renderValue = (value: unknown, key: string, titleProps: string[], idProps: string[]): React.ReactNode => {
  if (value === null || value === undefined) {
    return (
      <div className="flex items-center justify-center py-4 text-gray-500">
        <span className="text-sm italic">No data available</span>
      </div>
    );
  }

  if (typeof value === "boolean") {
    return (
      <div className="flex justify-start px-2">
        <span
          className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium transition-colors ${
            value ? "bg-green-50 text-green-700 border border-green-200" : "bg-red-50 text-red-700 border border-red-200"
          }`}
        >
          <span className="text-xs">{value ? "✅" : "❌"}</span>
          {value ? "True" : "False"}
        </span>
      </div>
    );
  }

  if (typeof value === "number") {
    const displayValue = key.includes("time") ? `${value.toFixed(2)}s` : value.toString();
    return (
      <div className="flex justify-start">
        <span className="inline-flex items-center gap-2 px-3 py-1.5 bg-blue-50 text-blue-700 border border-blue-200 rounded-full text-sm font-mono">
          {key.includes("time") && <span className="text-xs">⏱️</span>}
          {displayValue}
        </span>
      </div>
    );
  }

  if (typeof value === "string") {
    if (value.length > 500) {
      return (
        <div className="relative">
          <div className="bg-gray-100 rounded-lg border p-6 max-h-64 overflow-y-auto scrollbar-thin scrollbar-track-gray-100 scrollbar-thumb-gray-300">
            <pre className="text-sm text-gray-900 whitespace-pre-wrap leading-relaxed font-mono">{value}</pre>
          </div>
        </div>
      );
    }
    return (
      <div className="prose prose-sm max-w-none">
        <p className="text-gray-900 leading-relaxed m-0 px-2 text-sm py-1">{value}</p>
      </div>
    );
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return (
        <div className="flex items-center justify-center py-8 text-gray-500 border-2 border-dashed rounded-lg">
          <span className="text-sm italic">Empty list</span>
        </div>
      );
    }

    if (value.every((item) => typeof item === "string" || typeof item === "number")) {
      return (
        <div className="space-y-3">
          {value.map((item, index) => (
            <div
              key={index}
              className="flex items-start gap-4 p-3 rounded-lg hover:bg-gray-100 transition-colors border"
            >
              <div className="flex-shrink-0 w-2 h-2 bg-primary/60 rounded-full mt-2.5"></div>
              <span className="text-gray-900 leading-relaxed flex-1 break-words text-sm">{String(item)}</span>
            </div>
          ))}
        </div>
      );
    }

    if (key === "raw_results" && value.every((item) => typeof item === "object" && item !== null)) {
      return <NodeResultsGrid nodes={value as Array<Record<string, unknown>>} titleProps={titleProps} idProps={idProps} />;
    }

    return (
      <div className="relative">
        <div className="bg-gray-100 rounded-lg border p-6 max-h-96 overflow-y-auto scrollbar-thin scrollbar-track-gray-100 scrollbar-thumb-gray-300">
          <pre className="text-sm text-gray-900 whitespace-pre-wrap font-mono leading-relaxed">{JSON.stringify(value, null, 2)}</pre>
        </div>
        <div className="absolute top-3 right-3 bg-white/90 backdrop-blur-sm px-3 py-1.5 rounded-md text-xs text-gray-600 font-medium">
          {value.length} items
        </div>
      </div>
    );
  }

  if (typeof value === "object" && value !== null) {
    return (
      <div className="space-y-6">
        {Object.entries(value)
          .filter(([nestedKey]) => !HIDDEN_KEYS.has(String(nestedKey)) && !HIDDEN_KEYS_NORMALIZED.has(normalizeKey(String(nestedKey))))
          .map(([nestedKey, nestedValue]) => {
            const nk = normalizeKey(String(nestedKey));
            if (nk === "query") {
              return null; // skip nested query
            }
            if (nk === "explanation" || nk === "raw_results") {
              // Render content directly without a titled wrapper
              return (
                <div key={nestedKey} className="ml-2 pl-4">
                  {renderValue(nestedValue, nestedKey, titleProps, idProps)}
                </div>
              );
            }
            return (
              <div key={nestedKey} className="relative">
                <div className="border-l-2 border-primary/30 pl-6 pb-4">
                  <div className="flex items-center gap-3 mb-4">
                    <div className="w-2.5 h-2.5 bg-primary/60 rounded-full"></div>
                    <span className="font-medium text-gray-900 text-sm">{formatTitle(nestedKey)}</span>
                  </div>
                  <div className="ml-2 pl-4">{renderValue(nestedValue, nestedKey, titleProps, idProps)}</div>
                </div>
              </div>
            );
          })}
      </div>
    );
  }

  return <div className="text-gray-900 break-words">{String(value)}</div>;
};

export function StructuredResults({ data }: { data: StructuredSearchResponse }) {
  const [titleProps, setTitleProps] = useState<string[]>([]);
  const [idProps, setIdProps] = useState<string[]>([]);

  useEffect(() => {
    let isMounted = true;
    (async () => {
      try {
        const res = await fetch('/api/property-mappings', { cache: 'no-store' });
        if (!res.ok) return;
        const data = await res.json();
        const mappings = data?.mappings;
        if (!mappings) return;
        const nameProps = Array.isArray(mappings.name_properties) ? mappings.name_properties : [];
        const idPropsList = Array.isArray(mappings.id_properties) ? mappings.id_properties : [];
        if (isMounted) {
          setTitleProps(Array.isArray(nameProps) ? nameProps : []);
          setIdProps(Array.isArray(idPropsList) ? idPropsList : []);
        }
      } catch {
        // Silent fallback to defaults
      }
    })();
    return () => {
      isMounted = false;
    };
  }, []);

  const dataKeys = (Object.keys(data) as Array<keyof StructuredSearchResponse>).filter(
    (k) => !HIDDEN_KEYS.has(String(k)) && !HIDDEN_KEYS_NORMALIZED.has(normalizeKey(String(k)))
  );

  return (
    <div className="space-y-6">
      {!data && (
        <div className="p-4 bg-red-50 rounded">No valid data to display</div>
      )}
      {data && (
        <>
          {dataKeys
            .filter((k) => !HIDDEN_KEYS.has(String(k)))
            .map((key) => {
              const value = (data as any)[key];

              if (value === null || value === undefined) {
                return null;
              }

              return (
                <Card key={String(key)} className="overflow-hidden">
                  <div className="p-4">
                    {renderValue(value, String(key), titleProps, idProps)}
                  </div>
                </Card>
              );
            })}
        </>
      )}
    </div>
  );
}

export default StructuredResults;