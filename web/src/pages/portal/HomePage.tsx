import { useQuery } from '@tanstack/react-query'
import { ArrowRight, BookOpen, Boxes, Layers, MessageSquare, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Textarea } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { MarketModel } from '../../lib/types'
import { useAuthStore } from '../../store/auth'

export function HomePage() {
  const { t } = useI18n()
  const navigate = useNavigate()
  const status = useAuthStore((state) => state.status)
  const [prompt, setPrompt] = useState('')
  const [modelSlug, setModelSlug] = useState('')

  const featured = useQuery({
    queryKey: ['home-featured-models'],
    queryFn: () => apiRequest<MarketModel[]>('/market/models?sort=featured', { auth: false }),
  })
  const newest = useQuery({
    queryKey: ['home-new-models'],
    queryFn: () => apiRequest<MarketModel[]>('/market/models?sort=new', { auth: false }),
  })

  const start = () => {
    const selected = (featured.data ?? []).find((model) => model.slug === modelSlug)
    const params = new URLSearchParams()
    if (selected !== undefined) {
      params.set('provider', selected.provider_id)
      params.set('model', selected.model_id)
    }
    if (prompt.trim() !== '') params.set('prompt', prompt.trim())
    const target = `/chat/new${params.toString() ? `?${params.toString()}` : ''}`
    if (status === 'anonymous') {
      navigate('/login', { state: { from: target } })
    } else {
      navigate(target)
    }
  }

  const featureCards = (featured.data ?? []).slice(0, 4)
  const newCards = (newest.data ?? []).slice(0, 4)

  return (
    <div className="flex-1">
      <section className="relative overflow-hidden border-b border-border">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_20%_10%,var(--accent-soft),transparent_35%),radial-gradient(circle_at_80%_20%,var(--surface-muted),transparent_40%)]" />
        <div className="relative mx-auto w-full max-w-5xl px-4 pb-16 pt-16 text-center sm:px-6 sm:pt-24">
          <Badge tone="accent" className="mx-auto">
            <Sparkles className="mr-1 h-3 w-3" />
            {t('portal.badge')}
          </Badge>
          <h1 className="mx-auto mt-5 max-w-3xl font-serif text-4xl leading-tight text-ink sm:text-5xl">
            {t('portal.heroTitle')}
          </h1>
          <p className="mx-auto mt-4 max-w-2xl text-sm leading-6 text-ink-muted sm:text-base">
            {t('portal.heroLead')}
          </p>

          <div className="mx-auto mt-8 max-w-3xl rounded-3xl border border-border bg-surface p-3 text-left shadow-[0_24px_80px_-40px_var(--accent)]">
            <Textarea
              className="min-h-28 border-0 bg-transparent px-3 py-2 text-base focus:border-0"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder={t('portal.inputPlaceholder')}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  start()
                }
              }}
            />
            <div className="flex flex-wrap items-center gap-2 border-t border-border px-2 pt-3">
              <select
                className="h-9 rounded-lg border border-border bg-surface px-2 text-sm text-ink"
                value={modelSlug}
                onChange={(event) => setModelSlug(event.target.value)}
              >
                <option value="">{t('portal.autoModel')}</option>
                {featureCards.map((model) => (
                  <option key={model.slug} value={model.slug}>
                    {model.name}
                  </option>
                ))}
              </select>
              <span className="text-xs text-ink-muted">{t('portal.loginHint')}</span>
              <Button size="sm" className="ml-auto" onClick={start}>
                <MessageSquare className="h-3.5 w-3.5" />
                {t('portal.start')}
              </Button>
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto w-full max-w-7xl px-4 py-12 sm:px-6">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 className="text-lg font-semibold text-ink">{t('portal.featuredTitle')}</h2>
            <p className="mt-1 text-sm text-ink-muted">{t('portal.featuredLead')}</p>
          </div>
          <Link to="/models" className="inline-flex items-center gap-1 text-sm text-accent">
            {t('portal.allModels')}
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
        {featured.isLoading && (
          <div className="mt-6 flex items-center gap-2 text-sm text-ink-muted">
            <Spinner />
            {t('common.loading')}
          </div>
        )}
        <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {featureCards.map((model) => (
            <ModelCard key={model.slug} model={model} />
          ))}
        </div>
      </section>

      <section className="border-y border-border bg-surface">
        <div className="mx-auto w-full max-w-7xl px-4 py-12 sm:px-6">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <h2 className="text-lg font-semibold text-ink">{t('portal.newTitle')}</h2>
              <p className="mt-1 text-sm text-ink-muted">{t('portal.newLead')}</p>
            </div>
          </div>
          <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {newCards.map((model) => (
              <ModelCard key={model.slug} model={model} />
            ))}
            {newCards.length === 0 && !newest.isLoading && (
              <p className="text-sm text-ink-muted">{t('portal.newEmpty')}</p>
            )}
          </div>
        </div>
      </section>

      <section className="mx-auto w-full max-w-7xl px-4 py-12 sm:px-6">
        <h2 className="text-lg font-semibold text-ink">{t('portal.entryTitle')}</h2>
        <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <EntryCard
            to="/models"
            icon={Boxes}
            title={t('portal.models')}
            description={t('portal.entryModels')}
          />
          <EntryCard
            to="/chat"
            icon={MessageSquare}
            title={t('portal.workspace')}
            description={t('portal.entryChat')}
          />
          <EntryCard
            to="/knowledge"
            icon={BookOpen}
            title={t('nav.knowledge')}
            description={t('portal.entryKnowledge')}
          />
          <EntryCard
            to="/settings/providers"
            icon={Layers}
            title={t('nav.providers')}
            description={t('portal.entryProviders')}
          />
        </div>
      </section>
    </div>
  )
}

function ModelCard({ model }: { model: MarketModel }) {
  const { t } = useI18n()
  return (
    <Link
      to={`/models/${model.slug}`}
      className="group flex flex-col rounded-2xl border border-border bg-surface p-4 transition hover:-translate-y-0.5 hover:border-accent/50 hover:shadow-lg"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent-soft text-xs font-semibold text-accent">
          {model.name.slice(0, 2).toUpperCase()}
        </span>
        <div className="flex flex-col items-end gap-1">
          {model.featured && <Badge tone="accent">{t('portal.featured')}</Badge>}
          {model.is_new && <Badge tone="success">{t('portal.new')}</Badge>}
        </div>
      </div>
      <h3 className="mt-3 truncate text-sm font-semibold text-ink">{model.name}</h3>
      <p className="truncate text-xs text-ink-muted">{model.provider_name}</p>
      <p className="mt-2 line-clamp-2 text-xs leading-5 text-ink-muted">{model.description}</p>
      <div className="mt-3 flex flex-wrap gap-1">
        {model.capabilities.slice(0, 3).map((capability) => (
          <Badge key={capability} tone="neutral">
            {capability}
          </Badge>
        ))}
      </div>
    </Link>
  )
}

function EntryCard({
  to,
  icon: Icon,
  title,
  description,
}: {
  to: string
  icon: typeof Boxes
  title: string
  description: string
}) {
  return (
    <Link
      to={to}
      className="rounded-2xl border border-border bg-surface p-4 transition hover:border-accent/50 hover:bg-surface-muted"
    >
      <Icon className="h-5 w-5 text-accent" />
      <h3 className="mt-3 text-sm font-medium text-ink">{title}</h3>
      <p className="mt-1 text-xs leading-5 text-ink-muted">{description}</p>
    </Link>
  )
}