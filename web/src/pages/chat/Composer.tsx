import { ArrowUp, FileText, Image as ImageIcon, Paperclip, Square, X } from 'lucide-react'
import { useRef, useState, type ReactNode } from 'react'

import { Textarea } from '../../components/ui/input'
import { Button } from '../../components/ui/button'
import { ATTACHMENT_ACCEPT } from '../../lib/attachments'
import { MAX_MESSAGE_CHARS } from '../../lib/config'
import { useI18n } from '../../lib/i18n'
import type { ChatAttachment } from '../../lib/types'
import { cn } from '../../lib/utils'

interface ComposerProps {
  value: string
  onValueChange: (value: string) => void
  onSend: (content: string) => Promise<void>
  disabled?: boolean
  streaming?: boolean
  onStop?: () => void
  placeholder?: string
  size?: 'default' | 'hero'
  autoFocus?: boolean
  footerStart?: ReactNode
  footerEnd?: ReactNode
  showAttach?: boolean
  attachments?: ChatAttachment[]
  attaching?: boolean
  onAttachFiles?: (files: File[]) => void
  onRemoveAttachment?: (id: string) => void
}

export function Composer({
  value,
  onValueChange,
  onSend,
  disabled = false,
  streaming = false,
  onStop,
  placeholder,
  size = 'default',
  autoFocus = false,
  footerStart,
  footerEnd,
  showAttach = true,
  attachments = [],
  attaching = false,
  onAttachFiles,
  onRemoveAttachment,
}: ComposerProps) {
  const { t } = useI18n()
  const [sending, setSending] = useState(false)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const submit = async () => {
    const text = value.trim()
    if (text === '' || disabled || sending || streaming) return
    setSending(true)
    try {
      await onSend(text)
      onValueChange('')
    } catch {
      // Keep the draft so the user can retry without retyping.
    } finally {
      setSending(false)
    }
  }

  const countVisible = value.length > MAX_MESSAGE_CHARS - 1000
  const hero = size === 'hero'

  return (
    <div
      className={cn(
        'rounded-2xl border border-border bg-surface shadow-subtle transition-colors focus-within:border-accent',
        hero ? 'p-3' : 'p-2',
      )}
    >
      {(attachments.length > 0 || attaching) && (
        <div className="flex flex-wrap gap-1.5 px-1 pb-2 pt-1">
          {attachments.map((attachment) => (
            <span
              key={attachment.id}
              className="inline-flex max-w-[14rem] items-center gap-1.5 rounded-full bg-surface-muted px-2.5 py-1 text-[11px] text-ink"
            >
              {attachment.kind === 'image' ? (
                <ImageIcon className="h-3 w-3 text-ink-muted" />
              ) : (
                <FileText className="h-3 w-3 text-ink-muted" />
              )}
              <span className="truncate">{attachment.filename}</span>
              {onRemoveAttachment !== undefined && (
                <button
                  type="button"
                  aria-label={t('chat.removeAttachment')}
                  className="rounded p-0.5 text-ink-muted hover:text-danger"
                  onClick={() => onRemoveAttachment(attachment.id)}
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </span>
          ))}
          {attaching && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-muted px-2.5 py-1 text-[11px] text-ink-muted">
              {t('chat.uploadingAttachment')}
            </span>
          )}
        </div>
      )}
      <Textarea
        rows={1}
        value={value}
        maxLength={MAX_MESSAGE_CHARS}
        autoFocus={autoFocus}
        placeholder={placeholder ?? t('chat.inputPlaceholder')}
        title={t('chat.inputShortcut')}
        className={cn(
          'resize-none border-0 bg-transparent px-2 py-2 focus:border-0',
          hero ? 'max-h-44 min-h-12 text-[15px]' : 'max-h-36 min-h-10 text-sm',
        )}
        onChange={(event) => {
          onValueChange(event.target.value)
          const element = event.currentTarget
          element.style.height = 'auto'
          element.style.height = `${Math.min(element.scrollHeight, hero ? 176 : 144)}px`
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault()
            void submit()
          }
        }}
      />
      <div className="flex flex-wrap items-end justify-between gap-2 px-1 pt-1">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
          {showAttach && (
            <>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept={ATTACHMENT_ACCEPT}
                className="hidden"
                onChange={(event) => {
                  const files = Array.from(event.target.files ?? [])
                  if (files.length > 0) onAttachFiles?.(files)
                  event.target.value = ''
                }}
              />
              <Button
                variant="ghost"
                size="sm"
                disabled={onAttachFiles === undefined || attaching}
                className="h-8 px-2"
                aria-label={t('chat.attach')}
                title={
                  onAttachFiles === undefined
                    ? t('chat.attachmentSoon')
                    : t('chat.attachHint')
                }
                onClick={() => fileInputRef.current?.click()}
              >
                <Paperclip className="h-3.5 w-3.5" />
              </Button>
            </>
          )}
          {footerStart}
          <span className="text-[11px] text-ink-muted">
            {countVisible ? `${value.length}/${MAX_MESSAGE_CHARS}` : ''}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {footerEnd}
          {streaming ? (
            <Button size="sm" variant="secondary" onClick={onStop}>
              <Square className="h-3 w-3" />
              {t('chat.stop')}
            </Button>
          ) : (
            <Button
              size="sm"
              aria-label={t('chat.send')}
              className="h-8 w-8 rounded-full p-0"
              disabled={disabled || sending || value.trim() === ''}
              onClick={() => void submit()}
            >
              <ArrowUp className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}