import { ArrowUp, Square } from 'lucide-react'
import { useState } from 'react'

import { Textarea } from '../../components/ui/input'
import { Button } from '../../components/ui/button'
import { MAX_MESSAGE_CHARS } from '../../lib/config'
import { useI18n } from '../../lib/i18n'

interface ComposerProps {
  value: string
  onValueChange: (value: string) => void
  onSend: (content: string) => Promise<void>
  disabled?: boolean
  streaming?: boolean
  onStop?: () => void
  placeholder?: string
}

export function Composer({
  value,
  onValueChange,
  onSend,
  disabled = false,
  streaming = false,
  onStop,
  placeholder,
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

  return (
    <div className="rounded-card border border-border bg-surface p-2 shadow-subtle focus-within:border-accent">
      <Textarea
        rows={1}
        value={value}
        maxLength={MAX_MESSAGE_CHARS}
        placeholder={placeholder ?? t('chat.inputPlaceholder')}
        className="max-h-36 min-h-10 resize-none border-0 bg-transparent px-2 py-2 focus:border-0"
        onChange={(event) => {
          onValueChange(event.target.value)
          const element = event.currentTarget
          element.style.height = 'auto'
          element.style.height = `${Math.min(element.scrollHeight, 144)}px`
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault()
            void submit()
          }
        }}
      />
      <div className="flex items-center justify-between px-1 pt-1">
        <span className="text-[11px] text-ink-muted">
          {countVisible ? `${value.length}/${MAX_MESSAGE_CHARS}` : ''}
        </span>
        {streaming ? (
          <Button size="sm" variant="secondary" onClick={onStop}>
            <Square className="h-3 w-3" />
            {t('chat.stop')}
          </Button>
        ) : (
          <Button
            size="sm"
            aria-label={t('chat.send')}
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