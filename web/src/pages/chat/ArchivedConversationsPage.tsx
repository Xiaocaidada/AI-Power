import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArchiveRestore } from 'lucide-react'

import { Button } from '../../components/ui/button'
import { Spinner } from '../../components/ui/spinner'
import { formatDate } from '../../lib/format'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { Conversation } from '../../lib/types'

export function ArchivedConversationsPage() {
  const { t, language } = useI18n()
  const queryClient = useQueryClient()
  const conversations = useQuery({
    queryKey: ['conversations', 'archived'],
    queryFn: () => apiRequest<Conversation[]>('/conversations?archived=true&limit=100'),
  })

  const restore = async (conversation: Conversation) => {
    await apiRequest(`/conversations/${conversation.id}`, {
      method: 'PATCH',
      body: { archived: false },
    })
    await queryClient.invalidateQueries({ queryKey: ['conversations'] })
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-4">
        <h1 className="text-lg font-semibold">{t('chat.archivedTitle')}</h1>
        <p className="mt-1 text-sm text-ink-muted">{t('chat.archivedLead')}</p>
      </header>

      <div className="px-6 py-6">
        {conversations.isLoading && <Spinner />}
        <div className="space-y-2">
          {(conversations.data ?? []).map((conversation) => (
            <article
              key={conversation.id}
              className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-ink">
                  {conversation.title || t('chat.newConversation')}
                </p>
                <p className="truncate text-xs text-ink-muted">
                  {conversation.provider_id} · {conversation.model} ·{' '}
                  {formatDate(
                    conversation.archived_at ?? conversation.created_at,
                    language,
                  )}
                </p>
              </div>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => void restore(conversation)}
              >
                <ArchiveRestore className="h-3.5 w-3.5" />
                {t('chat.restore')}
              </Button>
            </article>
          ))}
        </div>
        {conversations.data !== undefined && conversations.data.length === 0 && (
          <p className="rounded-2xl border border-dashed border-border px-6 py-16 text-center text-sm text-ink-muted">
            {t('chat.archivedEmpty')}
          </p>
        )}
      </div>
    </div>
  )
}