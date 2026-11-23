import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Bot, MessageSquare, Workflow } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Spinner } from '../../components/ui/spinner'
import { formatDate } from '../../lib/format'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { Conversation, CustomAgent, Plugin } from '../../lib/types'

export function AgentDetailPage() {
  const { id = '' } = useParams<{ id: string }>()
  const { t, language } = useI18n()
  const navigate = useNavigate()

  const agent = useQuery({
    queryKey: ['agent', id],
    queryFn: () => apiRequest<CustomAgent>(`/agents/${id}`),
    enabled: id !== '',
  })
  const plugins = useQuery({
    queryKey: ['plugins'],
    queryFn: () => apiRequest<Plugin[]>('/plugins'),
    staleTime: 60_000,
  })
  const conversations = useQuery({
    queryKey: ['conversations', 'agent', id],
    queryFn: () =>
      apiRequest<Conversation[]>(`/conversations?custom_agent_id=${id}&limit=50`),
    enabled: id !== '' && agent.data !== undefined && !agent.data.builtin,
  })

  if (agent.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner className="h-6 w-6 text-accent" />
      </div>
    )
  }

  if (agent.isError || agent.data === undefined) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3">
        <p className="text-sm text-ink-muted">{t('agents.missing')}</p>
        <Button variant="secondary" onClick={() => navigate('/agents')}>
          {t('agents.back')}
        </Button>
      </div>
    )
  }

  const detail = agent.data
  const pluginNames = new Map((plugins.data ?? []).map((item) => [item.id, item.name]))
  const experience = () =>
    navigate(detail.builtin ? '/chat?agentMode=1' : `/chat?agent=${detail.id}`)

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-5">
        <Link
          to="/agents"
          className="inline-flex items-center gap-1 text-xs text-ink-muted hover:text-ink"
        >
          <ArrowLeft className="h-3 w-3" />
          {t('agents.back')}
        </Link>
        <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-4">
            <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent-soft text-accent">
              <Bot className="h-6 w-6" />
            </span>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-xl font-semibold text-ink">{detail.name}</h1>
                {detail.builtin && <Badge tone="neutral">{t('agents.builtin')}</Badge>}
                {detail.visibility === 'shared' && (
                  <Badge tone="accent">{t('agents.shared')}</Badge>
                )}
              </div>
              <p className="mt-1 text-sm text-ink-muted">
                {detail.description || t('agents.noDescription')}
              </p>
              <div className="mt-2 flex flex-wrap gap-1">
                <Badge tone="neutral">{t(`agents.category.${detail.category}`)}</Badge>
                {detail.tools.map((tool) => (
                  <Badge key={tool} tone="neutral">
                    {tool}
                  </Badge>
                ))}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {detail.owned && !detail.builtin && (
              <Button
                variant="secondary"
                onClick={() => navigate(`/studio/${detail.id}`)}
              >
                <Workflow className="h-4 w-4" />
                {t('studio.openStudio')}
              </Button>
            )}
            <Button onClick={experience}>
              <MessageSquare className="h-4 w-4" />
              {t('agents.experience')}
            </Button>
          </div>
        </div>
      </header>

      <div className="grid gap-5 px-6 py-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <section className="space-y-4">
          <div className="rounded-2xl border border-border bg-surface p-5">
            <h2 className="text-sm font-semibold text-ink">{t('agents.instructions')}</h2>
            <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-ink-muted">
              {detail.instructions}
            </p>
          </div>

          {!detail.builtin && (
            <div className="rounded-2xl border border-border bg-surface">
              <h2 className="border-b border-border px-5 py-3 text-sm font-semibold text-ink">
                {t('agents.history')}
              </h2>
              <div className="divide-y divide-border">
                {(conversations.data ?? []).map((conversation) => (
                  <Link
                    key={conversation.id}
                    to={`/chat/${conversation.id}`}
                    className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-surface-muted"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm text-ink">
                        {conversation.title || t('chat.newConversation')}
                      </p>
                      <p className="truncate text-xs text-ink-muted">
                        {conversation.provider_id} · {conversation.model}
                      </p>
                    </div>
                    <span className="shrink-0 text-xs text-ink-muted">
                      {formatDate(
                        conversation.updated_at ?? conversation.created_at,
                        language,
                      )}
                    </span>
                  </Link>
                ))}
                {conversations.data !== undefined &&
                  conversations.data.length === 0 && (
                    <p className="px-5 py-8 text-center text-sm text-ink-muted">
                      {t('agents.noHistory')}
                    </p>
                  )}
              </div>
            </div>
          )}
        </section>

        <aside className="space-y-4">
          <div className="rounded-2xl border border-border bg-surface p-5">
            <h2 className="text-sm font-semibold text-ink">{t('agents.defaults')}</h2>
            <dl className="mt-3 space-y-3 text-xs">
              <div>
                <dt className="text-ink-muted">{t('agents.defaultModel')}</dt>
                <dd className="mt-1 font-mono text-ink">
                  {detail.default_provider_id ?? t('models.auto')}
                  {detail.default_model !== null ? ` · ${detail.default_model}` : ''}
                </dd>
              </div>
              <div>
                <dt className="text-ink-muted">{t('agents.plugins')}</dt>
                <dd className="mt-1 flex flex-wrap gap-1">
                  {detail.plugin_ids.length === 0 && (
                    <span className="text-ink-muted">{t('agents.noPlugins')}</span>
                  )}
                  {detail.plugin_ids.map((pluginId) => (
                    <Badge key={pluginId} tone="accent">
                      {pluginNames.get(pluginId) ?? pluginId}
                    </Badge>
                  ))}
                </dd>
              </div>
              {detail.builtin && (
                <div>
                  <dt className="text-ink-muted">{t('agents.visibility')}</dt>
                  <dd className="mt-1 text-ink">{t('agents.builtinShared')}</dd>
                </div>
              )}
            </dl>
          </div>
        </aside>
      </div>
    </div>
  )
}