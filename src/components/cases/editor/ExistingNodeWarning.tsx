/**
 * Warning message for existing nodes
 */

export function ExistingNodeWarning() {
  return (
    <div className="mt-3 p-3 bg-amber-50 border-l-4 border-amber-400 rounded-r-md shadow-sm">
      <div className="flex items-center gap-3">
        <div className="flex-shrink-0">
          <svg 
            className="w-5 h-5 text-amber-600" 
            fill="currentColor" 
            viewBox="0 0 20 20"
            aria-hidden="true"
          >
            <path 
              fillRule="evenodd" 
              d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" 
              clipRule="evenodd" 
            />
          </svg>
        </div>
        <div className="flex-1">
          <p className="text-xs text-amber-700 leading-relaxed">
            This node exists in the knowledge graph. Any edits you make will apply to <span className="font-semibold">all cases</span> connected to this node.
          </p>
        </div>
      </div>
    </div>
  )
}

