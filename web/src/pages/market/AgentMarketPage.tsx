import { useQuery } from '@tanstack/react-query'
import { Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Input } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { AgentMarketFacets, AgentMarketSummary } from '../../lib/types'

export function AgentMarketPage() {
  const { t } = useI18n()
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<'newest' | 'popular' | 'featured'>('newest')
  const [featuredOnly, setFeaturedOnly] = useState(false)
  const [officialOnly, setOfficialOnly] = useState(false)
  const [category, setCategory] = useState('')
  const [publisher, setPublisher] = useState('')

  const facets = useQuery({
    queryKey: ['market-agent-facets'],
    queryFn: () =>
      apiRequest<AgentMarketFacets>('/market/agents/facets', { auth: false }),
    staleTime: 60_000,
  })
  const agents = useQuery({
    queryKey: [
      'market-agents',
      search,
      sort,
      featuredOnly,
      officialOnly,
      category,
      publisher,
    ],
    queryFn: () =>
      apiRequest<AgentMarketSummary[]>(
        `/market/agents?${new URLSearchParams({
          ...(search.trim() !== '' ? { search: search.trim() } : {}),
          ...(featuredOnly ? { featured: 'true' } : {}),
          ...(officialOnly ? { official: 'true' } : {}),
          ...(category !== '' ? { category } : {}),
          ...(publisher !== '' ? { publisher } : {}),
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
        <div className="flex flex-wrap items-center gap-2">
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t('market.search')}
            className="w-56"
          />
          <div className="flex rounded-lg border border-border bg-surface p-0.5">
            {(['newest', 'popular', 'featured'] as const).map((item) => (
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
          <select
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            aria-label={t('market.category')}
            className="h-9 rounded-lg border border-border bg-surface px-2 text-xs text-ink"
          >
            <option value="">{t('market.allCategories')}</option>
            {(facets.data?.categories ?? []).map((item) => (
              <option key={item.value} value={item.value}>
                {item.value} ({item.count})
              </option>
            ))}
          </select>
          <select
            value={publisher}
            onChange={(event) => setPublisher(event.target.value)}
            aria-label={t('market.publisher')}
            className="h-9 max-w-44 rounded-lg border border-border bg-surface px-2 text-xs text-ink"
          >
            <option value="">{t('market.allPublishers')}</option>
            {(facets.data?.publishers ?? []).map((item) => (
              <option key={item.value} value={item.value}>
                {item.value} ({item.count})
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => setFeaturedOnly((value) => !value)}
            className={`rounded-lg border px-3 py-1.5 text-xs ${
              featuredOnly
                ? 'border-accent bg-accent-soft text-accent'
                : 'border-border bg-surface text-ink-muted'
            }`}
          >
            {t('market.featuredOnly')}
          </button>
          <button
            type="button"
            onClick={() => setOfficialOnly((value) => !value)}
            className={`rounded-lg border px-3 py-1.5 text-xs ${
              officialOnly
                ? 'border-accent bg-accent-soft text-accent'
                : 'border-border bg-surface text-ink-muted'
            }`}
          >
            {t('market.officialOnly')}
          </button>
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
            className="overflow-hidden rounded-panel border border-border bg-surface transition-colors hover:border-accent/50"
          >
            {agent.cover_url && (
              <img
                src={agent.cover_url}
                alt=""
                className="h-28 w-full object-cover"
                loading="lazy"
              />
            )}
            <div className="p-5">
              <div className="flex items-start gap-3">
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-xl">
                  {agent.icon}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="truncate text-sm font-medium text-ink">{agent.name}</p>
                    <Badge tone="neutral">{agent.mode}</Badge>
                    {agent.featured && <Badge tone="accent">{t('market.featured')}</Badge>}
                    {agent.official && (
                      <Badge tone="success">{t('market.official')}</Badge>
                    )}
                  </div>
                  <p className="mt-1 line-clamp-3 text-xs text-ink-muted">
                    {agent.description}
                  </p>
                  <div className="mt-3 flex flex-wrap items-center gap-3 text-[10px] text-ink-muted">
                    {agent.publisher && <span>{agent.publisher}</span>}
                    <span>{agent.usage_count} uses</span>
                    <span>{agent.favorite_count} favorites</span>
                    <span>{agent.copy_count} copies</span>
                    <span>
                      ★ {(agent.rating_avg ?? 0).toFixed(1)} ({agent.rating_count ?? 0})
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  )
}