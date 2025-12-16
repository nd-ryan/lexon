/**
 * Action menu for node cards (delete/unlink)
 */

import { useState } from 'react'
import { Trash2 } from 'lucide-react'
import { HoverTooltip } from '@/components/ui/HoverTooltip'

interface NodeActionMenuProps {
  nodeId: string
  parentId?: string
  showUnlink: boolean
  parentLabel: string
  onDelete: (nodeId: string) => void
  onUnlink: (nodeId: string, parentId: string) => void
  deleteDisabledReason?: string | null
  unlinkDisabledReason?: string | null
}

export function NodeActionMenu({ 
  nodeId, 
  parentId,
  showUnlink,
  parentLabel,
  onDelete,
  onUnlink,
  deleteDisabledReason,
  unlinkDisabledReason
}: NodeActionMenuProps) {
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <div className="relative">
      <button
        onClick={(e) => {
          e.stopPropagation()
          setMenuOpen(!menuOpen)
        }}
        className="p-1 rounded hover:bg-gray-200 text-gray-500 hover:text-gray-700 transition-colors cursor-pointer"
        title="Node actions"
      >
        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 16 16">
          <circle cx="8" cy="2" r="1.5"/>
          <circle cx="8" cy="8" r="1.5"/>
          <circle cx="8" cy="14" r="1.5"/>
        </svg>
      </button>
      
      {menuOpen && (
        <>
          <div 
            className="fixed inset-0 z-10" 
            onClick={() => setMenuOpen(false)}
          />
          <div className="absolute right-0 top-full mt-1 w-56 bg-white rounded-lg shadow-lg border z-20 py-1">
            {showUnlink ? (
              <HoverTooltip text={unlinkDisabledReason} side="left" className="w-full">
                <button
                  onClick={() => {
                    if (unlinkDisabledReason) return
                    if (parentId) {
                      onUnlink(nodeId, parentId)
                    }
                    setMenuOpen(false)
                  }}
                  disabled={Boolean(unlinkDisabledReason)}
                  className={`w-full px-4 py-2 text-left text-sm flex items-center gap-2 ${
                    unlinkDisabledReason
                      ? 'text-gray-500 cursor-not-allowed'
                      : 'hover:bg-amber-50 text-amber-700 cursor-pointer'
                  }`}
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                  </svg>
                  <span>Unlink from {parentLabel}</span>
                </button>
              </HoverTooltip>
            ) : (
              <HoverTooltip text={deleteDisabledReason} side="left" className="w-full">
                <button
                  onClick={() => {
                    if (deleteDisabledReason) return
                    onDelete(nodeId)
                    setMenuOpen(false)
                  }}
                  disabled={Boolean(deleteDisabledReason)}
                  className={`w-full px-4 py-2 text-left text-sm flex items-center gap-2 ${
                    deleteDisabledReason
                      ? 'text-gray-500 cursor-not-allowed'
                      : 'hover:bg-red-50 text-red-600 cursor-pointer'
                  }`}
                >
                  <Trash2 className="w-4 h-4" />
                  <span>Delete node</span>
                </button>
              </HoverTooltip>
            )}
          </div>
        </>
      )}
    </div>
  )
}

