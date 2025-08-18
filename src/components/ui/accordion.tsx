"use client"

import * as React from "react"
import { ChevronDownIcon } from "lucide-react"

import { cn } from "@/lib/utils"

export type AccordionProps = React.HTMLAttributes<HTMLDivElement>
function Accordion({ className, ...props }: AccordionProps) {
  return <div data-slot="accordion" className={cn("divide-y border rounded-md", className)} {...props} />
}

export type AccordionItemProps = React.HTMLAttributes<HTMLDivElement>
function AccordionItem({ className, ...props }: AccordionItemProps) {
  return <div data-slot="accordion-item" className={cn("", className)} {...props} />
}

export type AccordionTriggerProps = React.ButtonHTMLAttributes<HTMLButtonElement>
function AccordionTrigger({ className, children, ...props }: AccordionTriggerProps) {
  return (
    <div className="flex">
      <button
        data-slot="accordion-trigger"
        className={cn(
          "flex flex-1 items-start justify-between gap-4 rounded-md py-4 text-left text-sm font-medium transition-all outline-none hover:underline",
          className
        )}
        {...props}
      >
        {children}
        <ChevronDownIcon className="text-gray-500 pointer-events-none size-4 shrink-0 translate-y-0.5 transition-transform duration-200" />
      </button>
    </div>
  )
}

export type AccordionContentProps = React.HTMLAttributes<HTMLDivElement>
function AccordionContent({ className, children, ...props }: AccordionContentProps) {
  return (
    <div data-slot="accordion-content" className="overflow-hidden text-sm" {...props}>
      <div className={cn("pt-0 pb-4", className)}>{children}</div>
    </div>
  )
}

export { Accordion, AccordionItem, AccordionTrigger, AccordionContent }
