import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ExternalLink, Search, Server, Sparkles } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { EmptyState } from '../../components/ui/empty-state'
import { Input } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  MarketModel,
  MarketModelPage,
  MarketProvider,
  ModelEntry,
  PersonalModel,
} from '../../lib/types'
import { cn } from '../../lib/utils'
import { useAuthStore } from '../../store/auth'
import { ActivateModelDialog } from './ActivateModelDialog'

type Tab = 'public' | 'mine' | 'platform'
const MAX_COMPARE = 3
const PAGE_SIZE = 24
const CATEGORIES = ['general', 'reasoning', 'coding', 'multimodal', 'embedding', 'reranker']
const CAPABILITIES = ['chat', 'stream', 'tools', 'vision', 'embedding', 'rerank']
const CAPABILITY_CLASSES: Record<string, string> = {
  chat: 'bg-accent-soft text-accent',
  stream: 'bg-sky-500/10 text-sky-600 dark:text-sky-300',
  tools: 'bg-warning/10 text-warning',
  vision: 'bg-violet-500/10 text-violet-600 dark:text-violet-300',
  reasoning: 'bg-success/10 text-success',
  embedding: 'bg-teal-500/10 text-teal-600 dark:text-teal-300',
  rerank: 'bg-rose-500/10 text-rose-600 dark:text-rose-300',
}
const CAPABILITY_FALLBACK = 'bg-surface-muted text-ink-muted'

function experienceHref(providerId: string, modelId: string): string {
  return `/chat?provider=${encodeURIComponent(providerId)}&model=${encodeURIComponent(modelId)}`
}

export function ModelsPage() {
  const { t, language } = useI18n()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const authStatus = useAuthStore((state) => state.status)
  const authenticated = authStatus === 'authenticated'
  const [tab, setTab] = useState<Tab>('public')
  const [activateTarget, setActivateTarget] = useState<MarketModel | null>(null)
  const [searchParams] = useSearchParams()
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [capability, setCapability] = useState('')
  const [providerFilter, setProviderFilter] = useState(
    () => searchParams.get('provider') ?? '',
  )
  const [sort, setSort] = useState('featured')
  const [page, setPage] = useState(1)
  const [mineSearch, setMineSearch] = useState('')
  const [mineCapability, setMineCapability] = useState('')
  const [detailTarget, setDetailTarget] = useState<MarketModel | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const numberFormat = new Intl.NumberFormat(language === 'zh' ? 'zh-CN' : 'en')

  const market = useQuery({
    queryKey: ['market-models', search, category, capability, providerFilter, sort, page],
    queryFn: () => {
      const params = new URLSearchParams()
      if (search.trim() !== '') params.set('search', search.trim())
      if (category !== '') params.set('category', category)
      if (capability !== '') params.set('capability', capability)
      if (providerFilter !== '') params.set('provider_id', providerFilter)
      params.set('sort', sort)
      params.set('page', String(page))
      params.set('per_page', String(PAGE_SIZE))
      return apiRequest<MarketModelPage>(`/market/models/page?${params.toString()}`, {
        auth: false,
      })
    },
    placeholderData: (previous) => previous,
  })
  useEffect(() => {
    setPage(1)
  }, [search, category, capability, providerFilter, sort])
  const total = market.data?.total
  const totalPages =
    total === undefined ? Math.max(page, 1) : Math.max(1, Math.ceil(total / PAGE_SIZE))
  useEffect(() => {
    if (page > totalPages) setPage(totalPages)
  }, [page, totalPages])
  const marketProviders = useQuery({
    queryKey: ['market-providers'],
    queryFn: () => apiRequest<MarketProvider[]>('/market/providers', { auth: false }),
    staleTime: 60_000,
  })
  const personal = useQuery({
    queryKey: ['provider-configs', 'models'],
    queryFn: () => apiRequest<PersonalModel[]>('/provider-configs/models'),
    staleTime: 60_000,
    enabled: authenticated,
  })
  const platform = useQuery({
    queryKey: ['models'],
    queryFn: () => apiRequest<ModelEntry[]>('/models'),
    enabled: authenticated,
  })
  const compare = useQuery({
    queryKey: ['models-compare', selected.join(',')],
    queryFn: () =>
      apiRequest<ModelEntry[]>(`/models/compare?ids=${encodeURIComponent(selected.join(','))}`),
    enabled: selected.length >= 2,
  })

  const myModels = (personal.data ?? []).filter((model) => {
    const term = mineSearch.trim().toLowerCase()
    const matchesTerm =
      term === '' ||
      model.display_name.toLowerCase().includes(term) ||
      model.model_id.toLowerCase().includes(term) ||
      model.provider_name.toLowerCase().includes(term)
    const matchesCapability =
      mineCapability === '' || model.capabilities.includes(mineCapability)
    return matchesTerm && matchesCapability
  })

  const personalFor = (model: MarketModel): PersonalModel | undefined =>
    personal.data?.find(
      (item) =>
        item.model_id === model.model_id &&
        item.provider_name.toLowerCase() === model.provider_name.toLowerCase(),
    )

  const detailMine =
    detailTarget === null ? undefined : personalFor(detailTarget)

  const startActivate = (model: MarketModel) => {
    if (!authenticated) {
      navigate('/login', { state: { from: '/models' } })
      return
    }
    setActivateTarget(model)
  }

  const toggle = (id: string) => {
    setSelected((previous) => {
      if (previous.includes(id)) return previous.filter((item) => item !== id)
      if (previous.length >= MAX_COMPARE) return previous
      return [...previous, id]
    })
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: 'public', label: t('models.publicTab') },
    { id: 'mine', label: t('models.myTab') },
    { id: 'platform', label: t('models.platformTab') },
  ]

  const selectTab = (next: Tab) => {
    if (next !== 'public' && !authenticated) {
      navigate('/login', { state: { from: '/models' } })
      return
    }
    setTab(next)
  }

  useEffect(() => {
    if (!authenticated && tab !== 'public') setTab('public')
  }, [authenticated, tab])

  return (
    <div className="flex-1">
      <header className="border-b border-border bg-surface px-6 py-3">
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
          <div className="min-w-0">
            <h1 className="text-lg font-semibold leading-6">{t('models.title')}</h1>
            <p className="text-xs text-ink-muted">{t('models.lead')}</p>
          </div>
          <nav
            className="flex items-center gap-0.5 rounded-lg bg-surface-muted p-0.5"
            aria-label={t('models.title')}
          >
            {tabs.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => selectTab(item.id)}
                aria-current={tab === item.id ? 'page' : undefined}
                className={cn(
                  'rounded-md px-3 py-1.5 text-sm transition-colors',
                  tab === item.id
                    ? 'bg-surface font-medium text-ink shadow-sm'
                    : 'text-ink-muted hover:text-ink',
                )}
              >
                {item.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <div className="space-y-5 px-6 py-6">
        {tab === 'public' && (
          <div className="flex flex-col gap-5 lg:flex-row lg:items-start">
            <div className="order-2 min-w-0 flex-1 space-y-5 lg:order-1">
              <label className="relative block w-full text-xs text-ink-muted">
                <span className="mb-1 block">{t('models.search')}</span>
                <Search className="absolute bottom-3 left-2.5 h-4 w-4 text-ink-muted" />
                <Input
                  className="pl-8"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder={t('models.searchPlaceholder')}
                />
              </label>

            {market.isLoading && (
              <div className="flex items-center gap-2 text-sm text-ink-muted">
                <Spinner />
                {t('common.loading')}
              </div>
            )}
            {market.data !== undefined && market.data.total === 0 && (
              <EmptyState title={t('models.publicEmpty')} description={t('models.publicEmptyLead')} />
            )}
            <div className="grid auto-rows-fr grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-4">
              {market.data?.items.map((model) => {
                const mine = personalFor(model)
                return (
                <article
                  key={model.id}
                  className="group relative flex h-full min-h-[360px] flex-col rounded-card border border-border bg-surface p-4 transition duration-200 hover:-translate-y-1 hover:border-accent/50 hover:shadow-floating"
                >
                  <Link
                    to={`/models/${model.slug}`}
                    aria-label={model.name}
                    className="absolute inset-0 z-0 rounded-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                  />
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <h2 className="truncate text-sm font-semibold text-ink">{model.name}</h2>
                      <p className="truncate text-[11px] text-ink-muted">
                        {model.provider_name} · {model.model_id}
                      </p>
                    </div>
                    <div className="flex flex-col items-end gap-1">
                      {model.featured && <Badge tone="accent">{t('models.featured')}</Badge>}
                      {model.is_new && <Badge tone="success">{t('models.new')}</Badge>}
                      {mine !== undefined && (
                        <Badge tone="success">{t('models.mineConfigured')}</Badge>
                      )}
                    </div>
                  </div>
                  <p className="mt-2 line-clamp-2 text-xs text-ink-muted">{model.description}</p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {model.capabilities.slice(0, 5).map((item) => (
                      <span
                        key={item}
                        className={cn(
                          'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
                          CAPABILITY_CLASSES[item] ?? CAPABILITY_FALLBACK,
                        )}
                      >
                        {item}
                      </span>
                    ))}
                  </div>
                  <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-[11px] text-ink-muted">
                    <div>
                      <dt>{t('models.context')}</dt>
                      <dd className="font-mono text-ink">
                        {model.context_window > 0
                          ? numberFormat.format(model.context_window)
                          : '—'}
                      </dd>
                    </div>
                    <div>
                      <dt>{t('models.maxOutput')}</dt>
                      <dd className="font-mono text-ink">
                        {model.max_output !== null ? numberFormat.format(model.max_output) : '—'}
                      </dd>
                    </div>
                    <div>
                      <dt>{t('models.inputTypes')}</dt>
                      <dd className="truncate text-ink">
                        {model.input_types.length > 0 ? model.input_types.join(', ') : '—'}
                      </dd>
                    </div>
                    <div>
                      <dt>{t('models.outputTypes')}</dt>
                      <dd className="truncate text-ink">
                        {model.output_types.length > 0 ? model.output_types.join(', ') : '—'}
                      </dd>
                    </div>
                    {model.thinking_supported && (
                      <div className="col-span-2">
                        <dt>{t('models.thinkingLevels')}</dt>
                        <dd className="truncate text-ink">
                          {model.thinking_levels.length > 0
                            ? model.thinking_levels.join(' / ')
                            : t('models.thinkingDefault')}
                        </dd>
                      </div>
                    )}
                  </dl>
                  <div className="relative z-10 mt-auto flex items-center justify-between gap-2 pt-3 text-xs text-ink-muted">
                    <span>{model.category}</span>
                    {model.docs_url !== '' && (
                      <a
                        href={model.docs_url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-accent hover:underline"
                      >
                        <ExternalLink className="h-3 w-3" />
                        {t('models.docs')}
                      </a>
                    )}
                  </div>
                  <div className="relative z-10 mt-3 flex flex-wrap gap-2">
                    <Button size="sm" variant="secondary" onClick={() => setDetailTarget(model)}>
                      {t('models.details')}
                    </Button>
                    {mine !== undefined ? (
                      <Button
                        size="sm"
                        onClick={() =>
                          navigate(experienceHref(mine.provider_id, mine.model_id))
                        }
                      >
                        {t('models.experience')}
                      </Button>
                    ) : model.available ? (
                      <Button
                        size="sm"
                        onClick={() => navigate(experienceHref(model.provider_id, model.model_id))}
                      >
                        {t('models.experience')}
                      </Button>
                    ) : model.catalog ? (
                      <Button size="sm" onClick={() => startActivate(model)}>
                        {t('models.activate')}
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => navigate('/settings/providers')}
                      >
                        {t('models.configure')}
                      </Button>
                    )}
                  </div>
                </article>
                )
              })}
            </div>
            {(market.data?.total ?? 0) > PAGE_SIZE && (
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs text-ink-muted">
                  {t('models.pageInfo', {
                    page,
                    pages: totalPages,
                    total: market.data?.total ?? 0,
                  })}
                </span>
                <div className="flex gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={page <= 1}
                    onClick={() => setPage((current) => Math.max(1, current - 1))}
                  >
                    {t('models.pagePrev')}
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={page >= totalPages}
                    onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
                  >
                    {t('models.pageNext')}
                  </Button>
                </div>
              </div>
            )}
              </div>
              <aside className="order-1 w-full shrink-0 rounded-card border border-border bg-surface p-4 lg:order-2 lg:sticky lg:top-20 lg:w-56">
                <div className="space-y-3">
                  <label className="block text-xs text-ink-muted">
                    <span className="mb-1 block">{t('models.category')}</span>
                    <select
                      className="h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm"
                      value={category}
                      onChange={(event) => setCategory(event.target.value)}
                    >
                      <option value="">{t('models.allCategories')}</option>
                      {CATEGORIES.map((item) => (
                        <option key={item} value={item}>
                          {item}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block text-xs text-ink-muted">
                    <span className="mb-1 block">{t('models.provider')}</span>
                    <select
                      className="h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm"
                      value={providerFilter}
                      onChange={(event) => setProviderFilter(event.target.value)}
                    >
                      <option value="">{t('models.allProviders')}</option>
                      {marketProviders.data?.map((item) => (
                        <option key={item.provider_id} value={item.provider_id}>
                          {item.name} ({item.model_count})
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block text-xs text-ink-muted">
                    <span className="mb-1 block">{t('models.capabilities')}</span>
                    <select
                      className="h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm"
                      value={capability}
                      onChange={(event) => setCapability(event.target.value)}
                    >
                      <option value="">{t('models.allCapabilities')}</option>
                      {CAPABILITIES.map((item) => (
                        <option key={item} value={item}>
                          {item}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block text-xs text-ink-muted">
                    <span className="mb-1 block">{t('models.sort')}</span>
                    <select
                      className="h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm"
                      value={sort}
                      onChange={(event) => setSort(event.target.value)}
                    >
                      <option value="featured">{t('models.sortFeatured')}</option>
                      <option value="new">{t('models.sortNew')}</option>
                      <option value="name">{t('models.sortName')}</option>
                    </select>
                  </label>
                </div>
              </aside>
            </div>
        )}

        {tab === 'mine' && (
          <>
            <div className="flex flex-wrap items-end gap-2">
              <label className="relative min-w-[220px] flex-1 text-xs text-ink-muted">
                <span className="mb-1 block">{t('models.search')}</span>
                <Search className="absolute bottom-3 left-2.5 h-4 w-4 text-ink-muted" />
                <Input
                  className="pl-8"
                  value={mineSearch}
                  onChange={(event) => setMineSearch(event.target.value)}
                  placeholder={t('models.mySearchPlaceholder')}
                />
              </label>
              <label className="text-xs text-ink-muted">
                <span className="mb-1 block">{t('models.capabilities')}</span>
                <select
                  className="h-10 rounded-lg border border-border bg-surface px-2 text-sm"
                  value={mineCapability}
                  onChange={(event) => setMineCapability(event.target.value)}
                >
                  <option value="">{t('models.allCapabilities')}</option>
                  {CAPABILITIES.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {personal.isLoading && (
              <div className="flex items-center gap-2 text-sm text-ink-muted">
                <Spinner />
                {t('common.loading')}
              </div>
            )}
            {personal.data !== undefined && personal.data.length === 0 && (
              <EmptyState title={t('models.mineEmpty')} description={t('models.mineEmptyLead')}>
                <Button onClick={() => navigate('/settings/providers')}>
                  <Server className="h-4 w-4" />
                  {t('models.configure')}
                </Button>
              </EmptyState>
            )}
            <div className="grid auto-rows-fr grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-4">
              {myModels.map((model) => (
                <article
                  key={`${model.provider_id}:${model.model_id}`}
                  className="flex h-full min-h-[360px] flex-col rounded-card border border-border bg-surface p-4"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <h2 className="truncate text-sm font-semibold text-ink">
                        {model.display_name}
                      </h2>
                      <p className="truncate text-[11px] text-ink-muted">
                        {model.provider_name} · {model.model_id}
                      </p>
                    </div>
                    <Badge tone="success">{t('models.available')}</Badge>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {model.capabilities.map((item) => (
                      <span
                        key={item}
                        className={cn(
                          'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
                          CAPABILITY_CLASSES[item] ?? CAPABILITY_FALLBACK,
                        )}
                      >
                        {item}
                      </span>
                    ))}
                  </div>
                  <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-[11px] text-ink-muted">
                    <div>
                      <dt>{t('models.context')}</dt>
                      <dd className="font-mono text-ink">
                        {model.context_window !== undefined && model.context_window > 0
                          ? numberFormat.format(model.context_window)
                          : '—'}
                      </dd>
                    </div>
                    <div>
                      <dt>{t('models.maxOutput')}</dt>
                      <dd className="font-mono text-ink">
                        {model.max_output !== undefined && model.max_output !== null
                          ? numberFormat.format(model.max_output)
                          : '—'}
                      </dd>
                    </div>
                    {model.reasoning_levels !== undefined && model.reasoning_levels.length > 0 && (
                      <div className="col-span-2">
                        <dt>{t('models.thinkingLevels')}</dt>
                        <dd className="truncate text-ink">{model.reasoning_levels.join(' / ')}</dd>
                      </div>
                    )}
                  </dl>
                  <div className="mt-auto flex gap-2 pt-3">
                    <Button
                      size="sm"
                      onClick={() => navigate(experienceHref(model.provider_id, model.model_id))}
                    >
                      <Sparkles className="h-3 w-3" />
                      {t('models.experience')}
                    </Button>
                  </div>
                </article>
              ))}
            </div>
          </>
        )}

        {tab === 'platform' && (
          <>
            {platform.isLoading && (
              <div className="flex items-center gap-2 text-sm text-ink-muted">
                <Spinner />
                {t('common.loading')}
              </div>
            )}
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {platform.data?.map((model) => {
                const active = selected.includes(model.id)
                return (
                  <article
                    key={model.id}
                    className={cn(
                      'rounded-card border bg-surface p-4',
                      active ? 'border-accent' : 'border-border',
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <h2 className="truncate text-sm font-semibold text-ink">
                          {model.display_name}
                        </h2>
                        <p className="truncate font-mono text-[11px] text-ink-muted">
                          {model.provider_id} · {model.model_id}
                        </p>
                      </div>
                      <Badge tone={model.available ? 'success' : 'danger'}>
                        {model.available ? t('models.available') : t('models.unavailable')}
                      </Badge>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-1">
                      {model.tags.map((tag) => (
                        <Badge key={tag} tone="accent">
                          {tag}
                        </Badge>
                      ))}
                    </div>
                    <div className="mt-4 flex justify-end">
                      <Button
                        size="sm"
                        variant={active ? 'primary' : 'secondary'}
                        onClick={() => toggle(model.id)}
                      >
                        {active && <Check className="h-3 w-3" />}
                        {active
                          ? t('models.selected', { count: selected.length })
                          : t('models.compare')}
                      </Button>
                    </div>
                  </article>
                )
              })}
            </div>
            {selected.length >= 2 && (
              <section className="rounded-card border border-border bg-surface p-4">
                <div className="mb-3 flex items-center justify-between">
                  <h2 className="text-sm font-semibold">{t('models.compareTitle')}</h2>
                  <Button variant="ghost" size="sm" onClick={() => setSelected([])}>
                    {t('models.clear')}
                  </Button>
                </div>
                {compare.isLoading && <Spinner />}
                {compare.data !== undefined && (
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[560px] text-left text-sm">
                      <thead className="border-b border-border text-xs uppercase text-ink-muted">
                        <tr>
                          <th className="px-3 py-2 font-medium"> </th>
                          {compare.data.map((model) => (
                            <th key={model.id} className="px-3 py-2 font-medium">
                              {model.display_name}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        <tr className="border-b border-border">
                          <td className="px-3 py-2 text-ink-muted">{t('models.context')}</td>
                          {compare.data.map((model) => (
                            <td key={model.id} className="px-3 py-2 font-mono">
                              {numberFormat.format(model.context_window)}
                            </td>
                          ))}
                        </tr>
                        <tr className="border-b border-border">
                          <td className="px-3 py-2 text-ink-muted">{t('models.inputPrice')}</td>
                          {compare.data.map((model) => (
                            <td key={model.id} className="px-3 py-2 font-mono">
                              {model.input_price}
                            </td>
                          ))}
                        </tr>
                        <tr>
                          <td className="px-3 py-2 text-ink-muted">{t('models.outputPrice')}</td>
                          {compare.data.map((model) => (
                            <td key={model.id} className="px-3 py-2 font-mono">
                              {model.output_price}
                            </td>
                          ))}
                        </tr>
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            )}
          </>
        )}
      </div>

      <Dialog
        open={detailTarget !== null}
        onClose={() => setDetailTarget(null)}
        title={detailTarget?.name ?? ''}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setDetailTarget(null)}>
              {t('models.close')}
            </Button>
            {detailTarget !== null && detailMine !== undefined && (
              <Button
                size="sm"
                onClick={() =>
                  navigate(experienceHref(detailMine.provider_id, detailMine.model_id))
                }
              >
                {t('models.experience')}
              </Button>
            )}
            {detailTarget !== null &&
              detailMine === undefined &&
              detailTarget.available && (
                <Button
                  size="sm"
                  onClick={() =>
                    navigate(
                      experienceHref(detailTarget.provider_id, detailTarget.model_id),
                    )
                  }
                >
                  {t('models.experience')}
                </Button>
              )}
            {detailTarget !== null &&
              detailMine === undefined &&
              !detailTarget.available &&
              detailTarget.catalog && (
                <Button
                  size="sm"
                  onClick={() => {
                    const target = detailTarget
                    setDetailTarget(null)
                    startActivate(target)
                  }}
                >
                  {t('models.activate')}
                </Button>
              )}
          </>
        }
      >
        {detailTarget !== null && (
          <div className="space-y-3 text-sm">
            <p className="text-ink-muted">
              {detailTarget.provider_name} · {detailTarget.model_id}
            </p>
            <p>{detailTarget.description}</p>
            <div className="flex flex-wrap gap-1">
              {detailTarget.capabilities.map((item) => (
                <Badge key={item} tone="accent">
                  {item}
                </Badge>
              ))}
            </div>
            <dl className="grid grid-cols-2 gap-2 text-xs text-ink-muted">
              <div>
                <dt>{t('models.context')}</dt>
                <dd className="font-mono text-ink">
                  {numberFormat.format(detailTarget.context_window)}
                </dd>
              </div>
              <div>
                <dt>{t('models.maxOutput')}</dt>
                <dd className="font-mono text-ink">{detailTarget.max_output ?? '—'}</dd>
              </div>
              <div>
                <dt>{t('models.inputTypes')}</dt>
                <dd>{detailTarget.input_types.join(', ')}</dd>
              </div>
              <div>
                <dt>{t('models.outputTypes')}</dt>
                <dd>{detailTarget.output_types.join(', ')}</dd>
              </div>
              {detailTarget.thinking_supported && (
                <div>
                  <dt>{t('models.thinkingLevels')}</dt>
                  <dd>
                    {detailTarget.thinking_levels.length > 0
                      ? detailTarget.thinking_levels.join(' / ')
                      : t('models.thinkingDefault')}
                    {detailTarget.thinking_required && (
                      <span className="ml-1 text-warning">
                        {t('models.thinkingRequired')}
                      </span>
                    )}
                  </dd>
                </div>
              )}
            </dl>
            {detailTarget.docs_url !== '' && (
              <a
                href={detailTarget.docs_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-xs text-accent"
              >
                <ExternalLink className="h-3 w-3" />
                {t('models.docs')}
              </a>
            )}
            {!detailTarget.available && (
              <p className="rounded-lg bg-warning/10 px-3 py-2 text-xs text-warning">
                {t('models.configRequired')}
              </p>
            )}
          </div>
        )}
      </Dialog>
      {activateTarget !== null && (
        <ActivateModelDialog
          key={activateTarget.slug}
          model={activateTarget}
          onClose={() => setActivateTarget(null)}
          onActivated={(providerId, modelId) => {
            setActivateTarget(null)
            queryClient.invalidateQueries({ queryKey: ['market-models'] })
            navigate(experienceHref(providerId, modelId))
          }}
        />
      )}
    </div>
  )
}