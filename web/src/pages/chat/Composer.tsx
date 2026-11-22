import { ArrowUp, Paperclip, Square } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { Textarea } from '../../components/ui/input'
import { Button } from '../../components/ui/button'
import { MAX_MESSAGE_CHARS } from '../../lib/config'
import { useI18n } from '../../lib/i18n'
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
  showAttach?: boolean
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
  showAttach = true,
}: ComposerProps) {
  const { t } = useI18n()
  const [sending, setSending] = useState(false)

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
      <Textarea
        rows={1}
        value={value}
        maxLength={MAX_MESSAGE_CHARS}
        autoFocus={autoFocus}
        placeholder={placeholder ?? t('chat.inputPlaceholder')}
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
      <div className="flex items-center justify-between gap-2 px-1 pt-1">
        <div className="flex min-w-0 items-center gap-1.5">
          {showAttach && (
            <Button
              variant="ghost"
              size="sm"
              disabled
              className="h-8 px-2"
              aria-label={t('chat.attach')}
              title={t('chat.attachmentSoon')}
            >
              <Paperclip className="h-3.5 w-3.5" />
            </Button>
          )}
          {footerStart}
          <span className="text-[11px] text-ink-muted">
            {countVisible ? `${value.length}/${MAX_MESSAGE_CHARS}` : ''}
          </span>
        </div>
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
  )
}