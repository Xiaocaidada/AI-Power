import { X } from 'lucide-react'
import { useEffect } from 'react'

import { useI18n } from '../../lib/i18n'
import type { Citation } from '../../lib/types'

interface CitationDrawerProps {
  open: boolean
  citations: Citation[]
  onClose: () => void
}

export function CitationDrawer({ open, citations, onClose }: CitationDrawerProps) {
  const { t } = useI18n()

  useEffect(() => {
    if (!open) return undefined
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-ink/20" onClick={onClose}>
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={t('chat.citationTitle')}
        className="flex h-full w-full max-w-sm flex-col bg-surface shadow-floating"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex h-14 items-center justify-between border-b border-border px-4">
          <h2 className="text-sm font-semibold">{t('chat.citationTitle')}</h2>
          <button
            type="button"
            aria-label={t('common.close')}
            className="rounded-md p-1 text-ink-muted hover:bg-surface-muted"
            onClick={onClose}
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {citations.length === 0 && (
            <p className="text-sm text-ink-muted">{t('chat.citationEmpty')}</p>
          )}
          <ol className="space-y-3">
            {citations.map((citation) => (
              <li key={`${citation.chunk_id}-${citation.index}`} className="rounded-lg border border-border p-3">
                <div className="flex items-center gap-2 text-xs text-citation">
                  <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-citation-soft font-mono">
                    {citation.index}
                  </span>
                  <span className="text-ink-muted">
                    {citation.page_no !== null
                      ? t('chat.page', { page: citation.page_no })
                      : t('chat.document', { id: citation.document_id.slice(0, 8) })}
                  </span>
                </div>
                <p className="mt-2 whitespace-pre-wrap text-[13px] leading-6 text-ink">
                  {citation.snippet}
                </p>
              </li>
            ))}
          </ol>
        </div>
      </aside>
    </div>
  )
}