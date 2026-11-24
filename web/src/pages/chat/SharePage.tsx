import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'

import { Spinner } from '../../components/ui/spinner'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { ConversationDetail } from '../../lib/types'

export function SharePage() {
  const { token = '' } = useParams<{ token: string }>()
  const { t } = useI18n()
  const conversation = useQuery({
    queryKey: ['shared-conversation', token],
    queryFn: () => apiRequest<ConversationDetail>(`/shares/${token}`),
    enabled: token !== '',
  })

  return (
    <div className="min-h-screen bg-canvas">
      <header className="border-b border-border bg-surface px-6 py-4">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-3">
          <div>
            <p className="text-xs text-ink-muted">{t('share.sharedConversation')}</p>
            <h1 className="text-lg font-semibold text-ink">
              {conversation.data?.title || t('chat.newConversation')}
            </h1>
          </div>
          <Link to="/chat" className="text-sm text-accent underline">
            {t('share.openChat')}
          </Link>
        </div>
      </header>
      <main className="mx-auto w-full max-w-3xl space-y-6 px-6 py-8">
        {conversation.isLoading && (
          <div className="flex items-center gap-2 text-sm text-ink-muted">
            <Spinner />
            {t('common.loading')}
          </div>
        )}
        {conversation.isError && (
          <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
            {t('share.unavailable')}
          </p>
        )}
        {(conversation.data?.messages ?? []).map((message) => (
          <article key={message.id} className="space-y-2">
            <h2 className="text-xs font-medium text-ink-muted">
              {message.role === 'user' ? t('chat.you') : t('chat.assistant')}
            </h2>
            <div className="markdown text-[15px] text-ink">
              <ReactMarkdown>{message.content}</ReactMarkdown>
            </div>
            {(message.web_sources?.length ?? 0) > 0 && (
              <div className="rounded-xl border border-border bg-surface-muted/30 px-3 py-2">
                <p className="text-[11px] font-medium text-ink-muted">
                  {t('chat.webSources')}
                </p>
                <ol className="mt-1 space-y-1 text-xs">
                  {(message.web_sources ?? []).map((source) => (
                    <li key={`${source.url}-${source.citation_index}`}>
                      <a
                        href={source.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-ink underline"
                      >
                        [{source.citation_index}] {source.title}
                      </a>
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </article>
        ))}
      </main>
    </div>
  )
}