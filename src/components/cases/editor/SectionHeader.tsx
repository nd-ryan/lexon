/**
 * Section header component with optional action button
 */

interface SectionHeaderProps {
  title: string
  actionButton?: React.ReactNode
  className?: string
}

export function SectionHeader({
  title,
  actionButton,
  className = ''
}: SectionHeaderProps) {
  if (!actionButton) return null
  
  return (
    <div className={`flex items-center justify-between mb-3 ${className}`}>
      <h3 className="text-sm font-semibold text-gray-700">{title}</h3>
      <div>{actionButton}</div>
    </div>
  )
}

