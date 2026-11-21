import { useEffect, type ReactNode } from 'react'

import { cn } from '../../lib/utils'

interface DialogProps {
  open: boolean
  onClose: () => void
  title: string
  children?: ReactNode
  footer?: ReactNode
  dismissible?: boolean
  className?: string
}

export function Dialog({
  open,
  onClose,
  title,
  children,
  footer,
  dismissible = true,
  className,
}: DialogProps) {
  useEffect(() => {
    if (!open) return undefined
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && dismissible) onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, dismissible, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/30 p-4"
      onMouseDown={(event) => {
        if (dismissible && event.target === event.currentTarget) onClose()
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cn(
          'w-full max-w-md rounded-card bg-surface p-5 shadow-floating',
          className,
        )}
      >
        <h2 className="text-base font-semibold text-ink">{title}</h2>
        {children !== undefined && <div className="mt-3 text-sm text-ink-muted">{children}</div>}
        {footer !== undefined && <div className="mt-5 flex justify-end gap-2">{footer}</div>}
      </div>
    </div>
  )
}