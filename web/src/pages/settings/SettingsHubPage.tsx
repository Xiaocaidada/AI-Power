import {
  BarChart3,
  Building2,
  Cable,
  FileText,
  KeyRound,
  Search,
  Server,
  UserRound,
  Webhook,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { useI18n } from '../../lib/i18n'

export function SettingsHubPage() {
  const { t } = useI18n()
  const items = [
    {
      to: '/settings/providers',
      icon: Server,
      title: t('providerHub.title'),
      description: t('settingsHub.providers'),
    },
    {
      to: '/settings/search',
      icon: Search,
      title: t('searchProviders.title'),
      description: t('settingsHub.search'),
    },
    {
      to: '/settings/integrations',
      icon: Cable,
      title: t('integrations.title'),
      description: t('settingsHub.integrations'),
    },
    {
      to: '/settings/api-keys',
      icon: KeyRound,
      title: t('apiKeys.title'),
      description: t('settingsHub.apiKeys'),
    },
    {
      to: '/settings/prompts',
      icon: FileText,
      title: t('prompts.title'),
      description: t('settingsHub.prompts'),
    },
    {
      to: '/settings/webhooks',
      icon: Webhook,
      title: t('webhooks.title'),
      description: t('settingsHub.webhooks'),
    },
    {
      to: '/settings/workspace',
      icon: Building2,
      title: t('workspace.current'),
      description: t('settingsHub.workspace'),
    },
    {
      to: '/settings/profile',
      icon: UserRound,
      title: t('profile.title'),
      description: t('settingsHub.profile'),
    },
    {
      to: '/usage',
      icon: BarChart3,
      title: t('usage.title'),
      description: t('settingsHub.usage'),
    },
  ]

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-4">
        <h1 className="text-lg font-semibold">{t('settingsHub.title')}</h1>
        <p className="mt-1 text-sm text-ink-muted">{t('settingsHub.lead')}</p>
      </header>
      <div className="mx-auto grid w-full max-w-5xl gap-4 px-6 py-6 sm:grid-cols-2 lg:grid-cols-3">
        {items.map(({ to, icon: Icon, title, description }) => (
          <Card key={to} to={to} icon={<Icon className="h-5 w-5 text-accent" />} title={title}>
            {description}
          </Card>
        ))}
      </div>
    </div>
  )
}

function Card({
  to,
  icon,
  title,
  children,
}: {
  to: string
  icon: ReactNode
  title: string
  children: ReactNode
}) {
  return (
    <Link
      to={to}
      className="rounded-2xl border border-border bg-surface p-5 transition hover:border-accent/50 hover:bg-surface-muted"
    >
      {icon}
      <h2 className="mt-3 text-sm font-semibold text-ink">{title}</h2>
      <p className="mt-1 text-xs leading-5 text-ink-muted">{children}</p>
    </Link>
  )
}