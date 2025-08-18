"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

export type TabsProps = React.HTMLAttributes<HTMLDivElement>
export function Tabs({ className, ...props }: TabsProps) {
  return <div data-slot="tabs" className={cn("flex flex-col gap-2", className)} {...props} />
}

export type TabsListProps = React.HTMLAttributes<HTMLDivElement>
export function TabsList({ className, ...props }: TabsListProps) {
  return (
    <div
      data-slot="tabs-list"
      className={cn(
        "bg-gray-100 text-gray-600 inline-flex h-9 w-fit items-center justify-center rounded-lg p-1",
        className
      )}
      {...props}
    />
  )
}

export type TabsTriggerProps = React.ButtonHTMLAttributes<HTMLButtonElement>
export function TabsTrigger({ className, ...props }: TabsTriggerProps) {
  return (
    <button
      data-slot="tabs-trigger"
      className={cn(
        "inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-transparent px-2 py-1 text-sm font-medium whitespace-nowrap transition-colors",
        "data-[state=active]:bg-white data-[state=active]:text-gray-900",
        "text-gray-800",
        className
      )}
      {...props}
    />
  )
}

export type TabsContentProps = React.HTMLAttributes<HTMLDivElement>
export function TabsContent({ className, ...props }: TabsContentProps) {
  return <div data-slot="tabs-content" className={cn("flex-1 outline-none", className)} {...props} />
}
