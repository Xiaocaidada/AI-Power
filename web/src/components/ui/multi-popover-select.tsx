import { Check, ChevronDown } from 'lucide-react'
import { useEffect, useId, useRef, useState, type ReactNode } from 'react'

import { cn } from '../../lib/utils'

export interface MultiSelectOption {
  value: string
  label: string
  description?: string
}

interface MultiPopoverSelectProps {
  label: string
  values: string[]
  options: MultiSelectOption[]
  onChange: (values: string[]) => void
  icon?: ReactNode
  disabled?: boolean
  placeholder?: string
  className?: string
}

export function MultiPopoverSelect({
  label,
  values,
  options,
  onChange,
  icon,
  disabled = false,
  placeholder,
  className,
}: MultiPopoverSelectProps) {
  const [open, setOpen] = useState(false)
  const panelRef = useRef<HTMLDivElement | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const listId = useId()

  const selected = options.filter((option) => values.includes(option.value))
  const summary =
    selected.length === 0
      ? (placeholder ?? label)
      : selected.length === 1
        ? selected[0].label
        : `${selected[0].label} +${selected.length - 1}`

  useEffect(() => {
    if (!open) return
    panelRef.current
      ?.querySelector<HTMLElement>('[role="option"]')
      ?.focus({ preventScroll: true })
  }, [open])

  const close = () => {
    setOpen(false)
    triggerRef.current?.focus({ preventScroll: true })
  }

  const toggle = (value: string) => {
    onChange(
      values.includes(value)
        ? values.filter((item) => item !== value)
        : [...values, value],
    )
  }

  return (
    <div className={cn('relative inline-flex', className)}>
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-label={`${label}: ${summary}`}
        disabled={disabled}
        className={cn(
          'inline-flex max-w-[15rem] items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:cursor-not-allowed disabled:opacity-60',
          values.length === 0
            ? 'border-border bg-surface text-ink-muted hover:text-ink'
            : 'border-accent/40 bg-accent-soft text-accent',
        )}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && open) close()
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault()
            setOpen(true)
          }
        }}
      >
        {icon}
        <span className="truncate">{summary}</span>
        <ChevronDown
          className={cn('h-3 w-3 shrink-0 transition-transform', open && 'rotate-180')}
        />
      </button>
      {open && (
        <>
          <button
            type="button"
            aria-hidden
            tabIndex={-1}
            className="fixed inset-0 z-30 cursor-default"
            onClick={() => setOpen(false)}
          />
          <div
            ref={panelRef}
            id={listId}
            role="listbox"
            aria-label={label}
            aria-multiselectable="true"
            className="absolute left-0 top-full z-40 mt-2 max-h-72 w-max min-w-[15rem] max-w-[calc(100vw-2rem)] overflow-y-auto rounded-xl border border-border bg-surface p-1 shadow-floating"
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                event.preventDefault()
                close()
              }
            }}
          >
            {options.map((option) => {
              const active = values.includes(option.value)
              return (
                <button
                  key={option.value}
                  type="button"
                  role="option"
                  aria-selected={active}
                  className={cn(
                    'flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left text-xs transition-colors focus:outline-none',
                    active
                      ? 'bg-accent-soft text-accent'
                      : 'text-ink-muted hover:bg-surface-muted hover:text-ink focus:bg-surface-muted focus:text-ink',
                  )}
                  onClick={() => toggle(option.value)}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{option.label}</span>
                    {option.description !== undefined && (
                      <span className="mt-0.5 block truncate text-[10px] text-ink-muted">
                        {option.description}
                      </span>
                    )}
                  </span>
                  {active && <Check className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
                </button>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}