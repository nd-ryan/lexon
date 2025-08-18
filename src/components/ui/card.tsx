"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  asChild?: boolean
}

export const Card = React.forwardRef<HTMLDivElement, CardProps>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        "rounded-xl border bg-white shadow-sm dark:bg-neutral-900 dark:border-neutral-800",
        className
      )}
      {...props}
    />
  )
)
Card.displayName = "Card"

export default Card
