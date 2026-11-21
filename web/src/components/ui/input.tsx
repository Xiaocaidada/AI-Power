import type { InputHTMLAttributes, TextareaHTMLAttributes } from 'react'

import { cn } from '../../lib/utils'

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        'h-10 w-full rounded-lg border border-border bg-surface px-3 text-sm text-ink',
        'placeholder:text-ink-muted/70 focus:border-accent focus:outline-none',
        className,
      )}
      {...props}
    />
  )
}

export function Textarea({
  className,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        'w-full resize-none rounded-lg border border-border bg-surface px-3 py-2.5 text-sm',
        'text-ink placeholder:text-ink-muted/70 focus:border-accent focus:outline-none',
        className,
      )}
      {...props}
    />
  )
}