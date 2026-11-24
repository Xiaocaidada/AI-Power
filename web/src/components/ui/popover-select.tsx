import { Check, ChevronDown } from 'lucide-react'
import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from 'react'

import { cn } from '../../lib/utils'

export interface PopoverSelectOption {
  value: string
  label: string
  description?: string
  group?: string
  trailing?: string
  disabled?: boolean
}

interface PopoverSelectProps {
  label: string
  value: string
  options: PopoverSelectOption[]
  onChange: (value: string) => void
  icon?: ReactNode
  disabled?: boolean
  variant?: 'chip' | 'ghost'
  placement?: 'top' | 'bottom'
  placeholder?: string
  className?: string
  triggerClassName?: string
}

export function PopoverSelect({
  label,
  value,
  options,
  onChange,
  icon,
  disabled = false,
  variant = 'chip',
  placement = 'bottom',
  placeholder,
  className,
  triggerClassName,
}: PopoverSelectProps) {
  const [open, setOpen] = useState(false)
  const panelRef = useRef<HTMLDivElement | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const listId = useId()
  const selected = options.find((option) => option.value === value)
  const currentLabel = selected?.label ?? placeholder ?? value

  const groupOrder: string[] = []
  for (const option of options) {
    if (option.group !== undefined && !groupOrder.includes(option.group)) {
      groupOrder.push(option.group)
    }
  }
  const ungrouped = options.filter((option) => option.group === undefined)

  useEffect(() => {
    if (!open) return
    const panel = panelRef.current
    const target =
      panel?.querySelector<HTMLElement>('[aria-selected="true"]') ??
      panel?.querySelector<HTMLElement>('[role="option"]')
    target?.focus({ preventScroll: true })
  }, [open])

  const close = () => {
    setOpen(false)
    triggerRef.current?.focus({ preventScroll: true })
  }

  const onTriggerKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      setOpen(true)
    } else if (event.key === 'Escape' && open) {
      event.preventDefault()
      close()
    }
  }

  const onPanelKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      close()
      return
    }
    if (event.key === 'Tab') {
      setOpen(false)
      return
    }
    if (
      event.key !== 'ArrowDown' &&
      event.key !== 'ArrowUp' &&
      event.key !== 'Home' &&
      event.key !== 'End'
    ) {
      return
    }
    event.preventDefault()
    const items = Array.from(
      panelRef.current?.querySelectorAll<HTMLElement>(
        '[role="option"]:not([aria-disabled="true"])',
      ) ?? [],
    )
    if (items.length === 0) return
    const active = document.activeElement
    const index = items.findIndex((item) => item === active)
    let nextIndex = index
    if (event.key === 'ArrowDown') nextIndex = index < 0 ? 0 : (index + 1) % items.length
    if (event.key === 'ArrowUp') {
      nextIndex = index < 0 ? items.length - 1 : (index - 1 + items.length) % items.length
    }
    if (event.key === 'Home') nextIndex = 0
    if (event.key === 'End') nextIndex = items.length - 1
    items[nextIndex]?.focus({ preventScroll: false })
  }

  const renderOption = (option: PopoverSelectOption) => {
    const active = option.value === value
    return (
      <button
        key={option.value}
        type="button"
        role="option"
        aria-selected={active}
        aria-disabled={option.disabled === true}
        disabled={option.disabled === true}
        className={cn(
          'flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left text-xs transition-colors focus:outline-none',
          option.disabled === true
            ? 'cursor-not-allowed text-ink-muted/50'
            : active
              ? 'bg-accent-soft text-accent'
              : 'text-ink-muted hover:bg-surface-muted hover:text-ink focus:bg-surface-muted focus:text-ink',
        )}
        onClick={() => {
          if (option.disabled === true) return
          onChange(option.value)
          close()
        }}
      >
        <span className="min-w-0 flex-1">
          <span className="block truncate">{option.label}</span>
          {option.description !== undefined && (
            <span className="mt-0.5 block truncate text-[10px] text-ink-muted">
              {option.description}
            </span>
          )}
        </span>
        {option.trailing !== undefined && (
          <span className="shrink-0 text-[10px] text-ink-muted">{option.trailing}</span>
        )}
        {active && <Check className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
      </button>
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
        aria-label={`${label}: ${currentLabel}`}
        disabled={disabled}
        className={cn(
          'inline-flex max-w-[15rem] items-center gap-1.5 rounded-full text-xs transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:cursor-not-allowed disabled:opacity-60',
          triggerClassName,
          variant === 'chip' &&
            cn(
              'border px-3 py-1.5',
              value === ''
                ? 'border-border bg-surface text-ink-muted hover:text-ink'
                : 'border-accent/40 bg-accent-soft text-accent',
            ),
          variant === 'ghost' &&
            'bg-transparent px-2 py-1 text-ink-muted hover:bg-surface-muted hover:text-ink',
          open && variant === 'ghost' && 'bg-surface-muted text-ink',
        )}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={onTriggerKeyDown}
      >
        {icon}
        <span className="truncate">{currentLabel}</span>
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
            onKeyDown={onPanelKeyDown}
            className={cn(
              'absolute left-0 z-40 max-h-72 w-max min-w-[15rem] max-w-[calc(100vw-2rem)] overflow-y-auto rounded-xl border border-border bg-surface p-1 shadow-floating',
              placement === 'top' ? 'bottom-full mb-2' : 'top-full mt-2',
            )}
          >
            {ungrouped.length > 0 && (
              <div className="space-y-0.5">{ungrouped.map(renderOption)}</div>
            )}
            {groupOrder.map((group) => (
              <div key={group}>
                {ungrouped.length > 0 || groupOrder.indexOf(group) > 0 ? (
                  <div className="mx-2 my-1 border-t border-border" />
                ) : null}
                <p className="px-2.5 pb-0.5 pt-1 text-[10px] uppercase tracking-wide text-ink-muted/70">
                  {group}
                </p>
                <div className="space-y-0.5">
                  {options
                    .filter((option) => option.group === group)
                    .map(renderOption)}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}