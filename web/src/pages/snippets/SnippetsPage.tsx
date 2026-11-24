import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Code2, Copy, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Spinner } from '../../components/ui/spinner'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { CodeSnippet } from '../../lib/types'

export function SnippetsPage() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const snippets = useQuery({
    queryKey: ['code-snippets'],
    queryFn: () => apiRequest<CodeSnippet[]>('/code-snippets'),
  })

  const remove = async (snippet: CodeSnippet) => {
    await apiRequest(`/code-snippets/${snippet.id}`, { method: 'DELETE' })
    await queryClient.invalidateQueries({ queryKey: ['code-snippets'] })
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-4">
        <h1 className="text-lg font-semibold">{t('snippets.title')}</h1>
        <p className="mt-1 text-sm text-ink-muted">{t('snippets.lead')}</p>
      </header>
      <div className="mx-auto w-full max-w-5xl space-y-3 px-6 py-6">
        {snippets.isLoading && (
          <div className="flex items-center gap-2 text-sm text-ink-muted">
            <Spinner />
            {t('common.loading')}
          </div>
        )}
        {snippets.data !== undefined && snippets.data.length === 0 && (
          <div className="rounded-2xl border border-dashed border-border bg-surface px-6 py-10 text-center">
            <Code2 className="mx-auto h-6 w-6 text-ink-muted" />
            <p className="mt-3 text-sm text-ink">{t('snippets.empty')}</p>
            <p className="mt-1 text-xs text-ink-muted">{t('snippets.emptyHint')}</p>
          </div>
        )}
        {(snippets.data ?? []).map((snippet) => (
          <article
            key={snippet.id}
            className="rounded-2xl border border-border bg-surface p-4"
          >
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="accent">{snippet.language}</Badge>
              <h2 className="text-sm font-semibold text-ink">
                {snippet.title || t('snippets.untitled')}
              </h2>
              <span className="ml-auto flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    void navigator.clipboard
                      ?.writeText(snippet.code)
                      .catch(() => undefined)
                  }}
                >
                  <Copy className="h-3.5 w-3.5" />
                  {t('common.copy')}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void remove(snippet)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  {t('common.delete')}
                </Button>
              </span>
            </div>
            <pre className="mt-2 max-h-72 overflow-auto rounded-xl bg-surface-muted/50 p-3 text-xs text-ink">
              {snippet.code}
            </pre>
            {snippet.conversation_id !== null && (
              <Link
                to={`/chat/${snippet.conversation_id}`}
                className="mt-2 inline-block text-xs text-accent underline"
              >
                {t('snippets.openSource')}
              </Link>
            )}
          </article>
        ))}
      </div>
    </div>
  )
}