import React from 'react'

type TooltipSide = 'top' | 'bottom' | 'left' | 'right'

interface HoverTooltipProps {
  text?: string | null
  side?: TooltipSide
  className?: string
  children: React.ReactNode
}

const sideClass: Record<TooltipSide, string> = {
  top: 'bottom-full left-1/2 -translate-x-1/2 mb-1',
  bottom: 'top-full left-1/2 -translate-x-1/2 mt-1',
  left: 'right-full top-1/2 -translate-y-1/2 mr-1',
  right: 'left-full top-1/2 -translate-y-1/2 ml-1'
}

/**
 * Simple CSS-only hover tooltip that works even when the child control is disabled.
 * (Disabled buttons often don't show the native `title` tooltip reliably.)
 */
export function HoverTooltip({ text, side = 'top', className, children }: HoverTooltipProps) {
  if (!text) return <>{children}</>

  return (
    <div className={`relative group ${className || ''}`}>
      {children}
      <div
        className={`pointer-events-none absolute ${sideClass[side]} z-50 hidden group-hover:block`}
      >
        <div className="max-w-[280px] rounded bg-gray-900 px-2 py-1 text-[11px] leading-snug text-white shadow-lg">
          {text}
        </div>
      </div>
    </div>
  )
}


