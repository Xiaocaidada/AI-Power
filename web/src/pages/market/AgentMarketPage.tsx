import { useQuery } from '@tanstack/react-query'
import { Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Input } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { AgentMarketSummary } from '../../lib/types'

export function AgentMarketPage() {
  const { t } = useI18n()
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<'newest' | 'popular'>('newest')

  const agents = useQuery({
    queryKey: ['market-agents', search, sort],
    queryFn: () =>
      apiRequest<AgentMarketSummary[]>(
        `/market/agents?${new URLSearchParams({
          ...(search.trim() !== '' ? { search: search.trim() } : {}),
          sort,
        }).toString()}`,
        { auth: false },
      ),
  })

  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-10">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 font-serif text-3xl text-ink">
            <Sparkles className="h-6 w-6 text-accent" />
            {t('market.title')}
          </h1>
          <p className="mt-2 text-sm text-ink-muted">{t('market.lead')}</p>
        </div>
        <div className="flex items-center gap-2">
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t('market.search')}
            className="w-56"
          />
          <div className="flex rounded-lg border border-border bg-surface p-0.5">
            {(['newest', 'popular'] as const).map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => setSort(item)}
                className={`rounded-md px-3 py-1.5 text-xs ${
                  sort === item ? 'bg-accent-soft text-accent' : 'text-ink-muted'
                }`}
              >
                {t(`market.${item}`)}
              </button>
            ))}
          </div>
        </div>
      </header>

      {agents.isLoading && <Spinner className="mt-10" />}
      {agents.data !== undefined && agents.data.length === 0 && (
        <p className="mt-10 text-sm text-ink-muted">{t('market.empty')}</p>
      )}
      <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {(agents.data ?? []).map((agent) => (
          <Link
            key={agent.id}
            to={`/market/agents/${agent.slug}`}
            className="rounded-panel border border-border bg-surface p-5 transition-colors hover:border-accent/50"
          >
            <div className="flex items-start gap-3">
              <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-accent-soft text-xl">
                {agent.icon}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="truncate text-sm font-medium text-ink">{agent.name}</p>
                  <Badge tone="neutral">{agent.mode}</Badge>
                </div>
                <p className="mt-1 line-clamp-3 text-xs text-ink-muted">
                  {agent.description}
                </p>
                <div className="mt-3 flex items-center gap-3 text-[10px] text-ink-muted">
                  <span>{agent.usage_count} uses</span>
                  <span>{agent.favorite_count} favorites</span>
                  <span>{agent.copy_count} copies</span>
                </div>
              </div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  )
}