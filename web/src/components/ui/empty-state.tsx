import type { ReactNode } from 'react'

interface EmptyStateProps {
  title: string
  description?: string
  children?: ReactNode
}

export function EmptyState({ title, description, children }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-16 text-center">
      <p className="font-serif text-xl text-ink">{title}</p>
      {description !== undefined && (
        <p className="max-w-md text-sm text-ink-muted">{description}</p>
      )}
      {children !== undefined && <div className="mt-3">{children}</div>}
    </div>
  )
}