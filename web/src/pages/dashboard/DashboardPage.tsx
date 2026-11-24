import { useQuery } from '@tanstack/react-query'
import {
  Bell,
  Bot,
  BookOpen,
  FolderKanban,
  MessageSquare,
  Plug,
  Search,
  Server,
} from 'lucide-react'
import { Link } from 'react-router-dom'

import { Spinner } from '../../components/ui/spinner'
import { formatDate } from '../../lib/format'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { Dashboard } from '../../lib/types'

export function DashboardPage() {
  const { t, language } = useI18n()
  const dashboard = useQuery({
    queryKey: ['dashboard'],
    queryFn: () => apiRequest<Dashboard>('/dashboard'),
  })

  if (dashboard.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner className="h-6 w-6 text-accent" />
      </div>
    )
  }

  if (dashboard.isError || dashboard.data === undefined) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-ink-muted">
        {t('dashboard.loadError')}
      </div>
    )
  }

  const { counts, recent_conversations, recent_projects } = dashboard.data
  const number = new Intl.NumberFormat(language === 'zh' ? 'zh-CN' : 'en')
  const cost = new Intl.NumberFormat(language === 'zh' ? 'zh-CN' : 'en', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 4,
  })
  const cards = [
    {
      to: '/settings/providers',
      icon: Server,
      label: t('dashboard.modelServices'),
      value: counts.models,
    },
    {
      to: '/chat',
      icon: MessageSquare,
      label: t('dashboard.conversations'),
      value: counts.conversations,
    },
    {
      to: '/projects',
      icon: FolderKanban,
      label: t('dashboard.projects'),
      value: counts.projects,
    },
    {
      to: '/knowledge',
      icon: BookOpen,
      label: t('dashboard.knowledgeBases'),
      value: counts.knowledge_bases,
    },
    { to: '/agents', icon: Bot, label: t('dashboard.agents'), value: counts.agents },
    { to: '/plugins', icon: Plug, label: t('dashboard.plugins'), value: counts.plugins },
    {
      to: '/announcements',
      icon: Bell,
      label: t('dashboard.notifications'),
      value: counts.unread_notifications,
    },
    {
      to: '/usage',
      icon: Search,
      label: t('dashboard.requests30d'),
      value: counts.requests_30d,
    },
  ]

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-4">
        <h1 className="text-lg font-semibold">{t('dashboard.title')}</h1>
        <p className="mt-1 text-sm text-ink-muted">{t('dashboard.lead')}</p>
      </header>

      <div className="space-y-6 px-6 py-6">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {cards.map(({ to, icon: Icon, label, value }) => (
            <Link
              key={to + label}
              to={to}
              className="rounded-2xl border border-border bg-surface p-5 transition hover:border-accent/50 hover:bg-surface-muted"
            >
              <Icon className="h-5 w-5 text-accent" />
              <p className="mt-3 text-2xl font-semibold text-ink">{number.format(value)}</p>
              <p className="mt-1 text-xs text-ink-muted">{label}</p>
            </Link>
          ))}
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-2xl border border-border bg-surface p-5">
            <p className="text-xs text-ink-muted">{t('dashboard.models')}</p>
            <p className="mt-1 text-xl font-semibold text-ink">
              {number.format(counts.models)}
            </p>
          </div>
          <div className="rounded-2xl border border-border bg-surface p-5">
            <p className="text-xs text-ink-muted">{t('dashboard.tokens30d')}</p>
            <p className="mt-1 text-xl font-semibold text-ink">
              {number.format(counts.tokens_30d)}
            </p>
          </div>
          <div className="rounded-2xl border border-border bg-surface p-5">
            <p className="text-xs text-ink-muted">{t('dashboard.cost30d')}</p>
            <p className="mt-1 text-xl font-semibold text-ink">
              {cost.format(counts.cost_30d)}
            </p>
          </div>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <section className="rounded-2xl border border-border bg-surface">
            <div className="flex items-center justify-between border-b border-border px-5 py-3">
              <h2 className="text-sm font-semibold text-ink">
                {t('dashboard.recentChats')}
              </h2>
              <Link to="/chat" className="text-xs text-accent">
                {t('dashboard.viewAll')}
              </Link>
            </div>
            <div className="divide-y divide-border">
              {recent_conversations.map((conversation) => (
                <Link
                  key={conversation.id}
                  to={`/chat/${conversation.id}`}
                  className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-surface-muted"
                >
                  <span className="min-w-0 truncate text-sm text-ink">
                    {conversation.title || t('chat.newConversation')}
                  </span>
                  <span className="shrink-0 text-xs text-ink-muted">
                    {formatDate(
                      conversation.updated_at ?? conversation.created_at,
                      language,
                    )}
                  </span>
                </Link>
              ))}
              {recent_conversations.length === 0 && (
                <p className="px-5 py-8 text-center text-sm text-ink-muted">
                  {t('dashboard.noChats')}
                </p>
              )}
            </div>
          </section>

          <section className="rounded-2xl border border-border bg-surface">
            <div className="flex items-center justify-between border-b border-border px-5 py-3">
              <h2 className="text-sm font-semibold text-ink">
                {t('dashboard.recentProjects')}
              </h2>
              <Link to="/projects" className="text-xs text-accent">
                {t('dashboard.viewAll')}
              </Link>
            </div>
            <div className="divide-y divide-border">
              {recent_projects.map((project) => (
                <Link
                  key={project.id}
                  to={`/projects/${project.id}`}
                  className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-surface-muted"
                >
                  <span className="min-w-0 truncate text-sm text-ink">{project.name}</span>
                  <span className="shrink-0 text-xs text-ink-muted">
                    {formatDate(project.updated_at, language)}
                  </span>
                </Link>
              ))}
              {recent_projects.length === 0 && (
                <p className="px-5 py-8 text-center text-sm text-ink-muted">
                  {t('dashboard.noProjects')}
                </p>
              )}
            </div>
          </section>
        </div>

        <div className="flex flex-wrap gap-2">
          <Link
            to="/search"
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink hover:border-accent/50"
          >
            <Search className="h-4 w-4 text-accent" />
            {t('dashboard.globalSearch')}
          </Link>
          <Link
            to="/files"
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink hover:border-accent/50"
          >
            <BookOpen className="h-4 w-4 text-accent" />
            {t('dashboard.files')}
          </Link>
        </div>
      </div>
    </div>
  )
}