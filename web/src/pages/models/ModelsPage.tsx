import { useQuery } from '@tanstack/react-query'
import { Check, ExternalLink, Search, Server, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { EmptyState } from '../../components/ui/empty-state'
import { Input } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { MarketModel, ModelEntry, PersonalModel } from '../../lib/types'
import { cn } from '../../lib/utils'
import { useAuthStore } from '../../store/auth'

type Tab = 'public' | 'mine' | 'platform'
const MAX_COMPARE = 3
const CATEGORIES = ['general', 'reasoning', 'coding', 'multimodal', 'embedding', 'reranker']
const CAPABILITIES = ['chat', 'stream', 'tools', 'vision', 'embedding', 'rerank']

function experienceHref(providerId: string, modelId: string): string {
  return `/chat/new?provider=${encodeURIComponent(providerId)}&model=${encodeURIComponent(modelId)}`
}

export function ModelsPage() {
  const { t, language } = useI18n()
  const navigate = useNavigate()
  const authStatus = useAuthStore((state) => state.status)
  const authenticated = authStatus === 'authenticated'
  const [tab, setTab] = useState<Tab>('public')
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [capability, setCapability] = useState('')
  const [sort, setSort] = useState('featured')
  const [mineSearch, setMineSearch] = useState('')
  const [mineCapability, setMineCapability] = useState('')
  const [detailTarget, setDetailTarget] = useState<MarketModel | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const numberFormat = new Intl.NumberFormat(language === 'zh' ? 'zh-CN' : 'en')

  const market = useQuery({
    queryKey: ['market-models', search, category, capability, sort],
    queryFn: () => {
      const params = new URLSearchParams()
      if (search.trim() !== '') params.set('search', search.trim())
      if (category !== '') params.set('category', category)
      if (capability !== '') params.set('capability', capability)
      params.set('sort', sort)
      return apiRequest<MarketModel[]>(`/market/models?${params.toString()}`, { auth: false })
    },
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

  const toggle = (id: string) => {
    setSelected((previous) => {
      if (previous.includes(id)) return previous.filter((item) => item !== id)
      if (previous.length >= MAX_COMPARE) return previous
      return [...previous, id]
    })
  }

  const tabs: { id: Tab; label: string }[] = authenticated
    ? [
        { id: 'public', label: t('models.publicTab') },
        { id: 'mine', label: t('models.myTab') },
        { id: 'platform', label: t('models.platformTab') },
      ]
    : [{ id: 'public', label: t('models.publicTab') }]

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-4">
        <h1 className="text-lg font-semibold">{t('models.title')}</h1>
        <p className="mt-1 text-sm text-ink-muted">{t('models.lead')}</p>
        <nav className="mt-3 flex gap-1">
          {tabs.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
              className={cn(
                '-mb-px border-b-2 px-3 py-2 text-sm',
                tab === item.id
                  ? 'border-accent text-accent'
                  : 'border-transparent text-ink-muted hover:text-ink',
              )}
            >
              {item.label}
            </button>
          ))}
        </nav>
      </header>

      <div className="space-y-5 px-6 py-6">
        {tab === 'public' && (
          <>
            <div className="flex flex-wrap items-end gap-2">
              <label className="relative min-w-[220px] flex-1 text-xs text-ink-muted">
                <span className="mb-1 block">{t('models.search')}</span>
                <Search className="absolute bottom-3 left-2.5 h-4 w-4 text-ink-muted" />
                <Input
                  className="pl-8"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder={t('models.searchPlaceholder')}
                />
              </label>
              <label className="text-xs text-ink-muted">
                <span className="mb-1 block">{t('models.category')}</span>
                <select
                  className="h-10 rounded-lg border border-border bg-surface px-2 text-sm"
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
              <label className="text-xs text-ink-muted">
                <span className="mb-1 block">{t('models.capabilities')}</span>
                <select
                  className="h-10 rounded-lg border border-border bg-surface px-2 text-sm"
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
              <label className="text-xs text-ink-muted">
                <span className="mb-1 block">{t('models.sort')}</span>
                <select
                  className="h-10 rounded-lg border border-border bg-surface px-2 text-sm"
                  value={sort}
                  onChange={(event) => setSort(event.target.value)}
                >
                  <option value="featured">{t('models.sortFeatured')}</option>
                  <option value="new">{t('models.sortNew')}</option>
                  <option value="name">{t('models.sortName')}</option>
                </select>
              </label>
            </div>

            {market.isLoading && (
              <div className="flex items-center gap-2 text-sm text-ink-muted">
                <Spinner />
                {t('common.loading')}
              </div>
            )}
            {market.data !== undefined && market.data.length === 0 && (
              <EmptyState title={t('models.publicEmpty')} description={t('models.publicEmptyLead')} />
            )}
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {market.data?.map((model) => (
                <article
                  key={model.id}
                  className="flex flex-col rounded-card border border-border bg-surface p-4"
                >
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
                    </div>
                  </div>
                  <p className="mt-2 line-clamp-2 text-xs text-ink-muted">{model.description}</p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {model.capabilities.slice(0, 5).map((item) => (
                      <Badge key={item} tone="neutral">
                        {item}
                      </Badge>
                    ))}
                  </div>
                  <div className="mt-3 flex items-center justify-between text-xs text-ink-muted">
                    <span>{model.category}</span>
                    <span className="font-mono">
                      {model.context_window > 0
                        ? numberFormat.format(model.context_window)
                        : '—'}{' '}
                      ctx
                    </span>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button size="sm" variant="secondary" onClick={() => setDetailTarget(model)}>
                      {t('models.details')}
                    </Button>
                    {model.available ? (
                      <Button
                        size="sm"
                        onClick={() => navigate(experienceHref(model.provider_id, model.model_id))}
                      >
                        {t('models.experience')}
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
              ))}
            </div>
          </>
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
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {myModels.map((model) => (
                <article
                  key={`${model.provider_id}:${model.model_id}`}
                  className="flex flex-col rounded-card border border-border bg-surface p-4"
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
                      <Badge key={item} tone="accent">
                        {item}
                      </Badge>
                    ))}
                  </div>
                  <div className="mt-3 flex gap-2">
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
            {detailTarget?.available && (
              <Button
                size="sm"
                onClick={() => {
                  if (detailTarget !== null) {
                    navigate(experienceHref(detailTarget.provider_id, detailTarget.model_id))
                  }
                }}
              >
                {t('models.experience')}
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
    </div>
  )
}