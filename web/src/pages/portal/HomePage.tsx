import { useQuery } from '@tanstack/react-query'
import {
  ArrowRight,
  BookOpen,
  Bot,
  Boxes,
  Brain,
  CalendarDays,
  Layers,
  MessageSquare,
  Pin,
  Sparkles,
} from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import { Link, useNavigate } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Spinner } from '../../components/ui/spinner'
import { errorMessage } from '../../lib/errors'
import { formatDate } from '../../lib/format'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import { streamChat } from '../../lib/sse'
import type {
  Announcement,
  Conversation,
  HomeFeed,
  HomePlacement,
  MarketModel,
  ModelEntry,
  ProviderConfig,
} from '../../lib/types'
import { useAuthStore } from '../../store/auth'
import { Composer } from '../chat/Composer'

export function HomePage() {
  const { t } = useI18n()
  const navigate = useNavigate()
  const status = useAuthStore((state) => state.status)
  const [prompt, setPrompt] = useState('')
  const [modelValue, setModelValue] = useState('auto::auto')
  const [answer, setAnswer] = useState('')
  const [answerConversationId, setAnswerConversationId] = useState<string | null>(null)
  const [streaming, setStreaming] = useState(false)
  const [homeError, setHomeError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const featured = useQuery({
    queryKey: ['home-featured-models'],
    queryFn: () => apiRequest<MarketModel[]>('/market/models?sort=featured', { auth: false }),
  })
  const newest = useQuery({
    queryKey: ['home-new-models'],
    queryFn: () => apiRequest<MarketModel[]>('/market/models?sort=new', { auth: false }),
  })
  const home = useQuery({
    queryKey: ['home-feed'],
    queryFn: () => apiRequest<HomeFeed>('/home', { auth: false }),
  })
  const banners = home.data?.banners ?? []
  const placements = [...(home.data?.featured ?? []), ...(home.data?.activities ?? [])]
  const announcements = home.data?.announcements ?? []

  const models = useQuery({
    queryKey: ['home-models'],
    queryFn: () => apiRequest<ModelEntry[]>('/models'),
    enabled: status === 'authenticated',
  })
  const providers = useQuery({
    queryKey: ['home-providers'],
    queryFn: () => apiRequest<ProviderConfig[]>('/provider-configs'),
    enabled: status === 'authenticated',
  })

  useEffect(() => {
    if (status !== 'authenticated') return
    const pending = sessionStorage.getItem('home_pending_prompt')
    if (pending !== null && pending.trim() !== '') {
      setPrompt(pending)
      sessionStorage.removeItem('home_pending_prompt')
    }
  }, [status])

  const start = async (content: string): Promise<void> => {
    if (status !== 'authenticated') {
      sessionStorage.setItem('home_pending_prompt', content)
      navigate('/login', { state: { from: '/' } })
      return
    }
    setStreaming(true)
    setHomeError(null)
    setAnswer('')
    setAnswerConversationId(null)
    setPrompt('')
    try {
      const [providerId, model] = modelValue.split('::')
      const conversation = await apiRequest<Conversation>('/conversations', {
        method: 'POST',
        body: { provider_id: providerId, model },
      })
      setAnswerConversationId(conversation.id)
      const controller = new AbortController()
      abortRef.current = controller
      await streamChat({
        conversationId: conversation.id,
        content,
        mode: 'chat',
        signal: controller.signal,
        onEvent: (event) => {
          if (event.data === null || typeof event.data !== 'object') return
          const data = event.data as Record<string, unknown>
          if (event.event === 'delta') {
            setAnswer((previous) => previous + String(data.text ?? ''))
          } else if (event.event === 'error') {
            setHomeError(String(data.message ?? t('errors.generic')))
          }
        },
      })
    } catch (caught) {
      if (abortRef.current?.signal.aborted !== true) {
        setHomeError(errorMessage(caught))
      }
    } finally {
      setStreaming(false)
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

          <div className="mx-auto mt-8 max-w-3xl animate-page text-left">
            <Composer
              value={prompt}
              onValueChange={setPrompt}
              onSend={start}
              size="hero"
              autoFocus
              showAttach={false}
              streaming={streaming}
              onStop={() => abortRef.current?.abort()}
              placeholder={t('portal.inputPlaceholder')}
              footerStart={
                <>
                  <select
                    aria-label={t('portal.model')}
                    className="h-7 max-w-44 rounded-md border border-border bg-surface px-1 text-[11px] text-ink"
                    value={modelValue}
                    disabled={status !== 'authenticated'}
                    onChange={(event) => setModelValue(event.target.value)}
                  >
                    <option value="auto::auto">{t('portal.autoModel')}</option>
                    {(models.data ?? [])
                      .filter((model) => model.available)
                      .map((model) => (
                        <option
                          key={`${model.provider_id}::${model.model_id}`}
                          value={`${model.provider_id}::${model.model_id}`}
                        >
                          {model.display_name}
                        </option>
                      ))}
                  </select>
                  <span className="hidden text-[11px] text-ink-muted sm:inline">
                    {status === 'authenticated' ? t('portal.inlineHint') : t('portal.loginHint')}
                  </span>
                </>
              }
            />
            {(streaming || answer !== '' || homeError !== null) && (
              <div className="mt-3 animate-page rounded-2xl border border-border bg-surface p-4 shadow-subtle">
                {homeError !== null && <p className="text-sm text-danger">{homeError}</p>}
                {streaming && answer === '' ? (
                  <div className="flex items-center gap-2 text-sm text-ink-muted">
                    <Spinner />
                    {t('chat.generating')}
                  </div>
                ) : (
                  <div className="markdown text-sm text-ink">
                    <ReactMarkdown>{answer}</ReactMarkdown>
                  </div>
                )}
                {answerConversationId !== null && (
                  <Link
                    to={`/chat/${answerConversationId}`}
                    className="mt-3 inline-flex items-center gap-1 text-sm text-accent hover:underline"
                  >
                    {t('portal.continueChat')}
                    <ArrowRight className="h-3.5 w-3.5" />
                  </Link>
                )}
              </div>
            )}
          </div>

          {banners.length > 0 && (
            <div className="mx-auto mt-6 grid max-w-3xl gap-3 text-left sm:grid-cols-2">
              {banners.map((banner) => (
                <BannerCard key={banner.id} banner={banner} />
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="mx-auto w-full max-w-7xl px-4 py-12 sm:px-6">
        <h2 className="text-lg font-semibold text-ink">{t('portal.capabilityTitle')}</h2>
        <p className="mt-1 text-sm text-ink-muted">{t('portal.capabilityLead')}</p>
        <div className="mt-5 grid gap-4 md:grid-cols-3">
          <EntryCard
            to="/studio"
            icon={Bot}
            title={t('portal.capabilityAgent')}
            description={t('portal.capabilityAgentLead')}
          />
          <EntryCard
            to="/knowledge"
            icon={BookOpen}
            title={t('portal.capabilityKnowledge')}
            description={t('portal.capabilityKnowledgeLead')}
          />
          <EntryCard
            to="/memory"
            icon={Brain}
            title={t('portal.capabilityMemory')}
            description={t('portal.capabilityMemoryLead')}
          />
        </div>
      </section>

      <section className="border-y border-border bg-surface">
        <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center gap-5 px-4 py-8 sm:px-6">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-accent-soft text-accent">
            <Layers className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold text-ink">{t('portal.providerTitle')}</h2>
            <p className="mt-1 text-sm text-ink-muted">{t('portal.providerLead')}</p>
          </div>
          {status === 'authenticated' && (
            <Badge tone="neutral">
              {t('portal.providerCount', { count: providers.data?.length ?? 0 })}
            </Badge>
          )}
          <Button variant="secondary" size="sm" onClick={() => navigate('/settings/providers')}>
            {t('portal.manageProviders')}
            <ArrowRight className="h-3.5 w-3.5" />
          </Button>
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

      {placements.length > 0 && (
        <section className="border-t border-border bg-surface-muted/40">
          <div className="mx-auto w-full max-w-7xl px-4 py-12 sm:px-6">
            <h2 className="text-lg font-semibold text-ink">{t('portal.activityTitle')}</h2>
            <p className="mt-1 text-sm text-ink-muted">{t('portal.activityLead')}</p>
            <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {placements.map((placement) => (
                <PlacementCard key={placement.id} placement={placement} />
              ))}
            </div>
          </div>
        </section>
      )}

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

      {announcements.length > 0 && (
        <section className="border-t border-border bg-surface">
          <div className="mx-auto w-full max-w-7xl px-4 py-12 sm:px-6">
            <div className="flex flex-wrap items-end justify-between gap-2">
              <div>
                <h2 className="text-lg font-semibold text-ink">
                  {t('portal.announcementsTitle')}
                </h2>
                <p className="mt-1 text-sm text-ink-muted">
                  {t('portal.announcementsLead')}
                </p>
              </div>
              <Link to="/announcements" className="inline-flex items-center gap-1 text-sm text-accent">
                {t('portal.allAnnouncements')}
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>
            <div className="mt-5 divide-y divide-border rounded-2xl border border-border">
              {announcements.map((item) => (
                <AnnouncementRow key={item.id} announcement={item} />
              ))}
            </div>
          </div>
        </section>
      )}

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
            to="/dashboard"
            icon={MessageSquare}
            title={t('nav.console')}
            description={t('portal.entryConsole')}
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

function SmartLink({
  href,
  className,
  children,
}: {
  href: string
  className: string
  children: ReactNode
}) {
  if (href.startsWith('http://') || href.startsWith('https://')) {
    return (
      <a href={href} target="_blank" rel="noreferrer" className={className}>
        {children}
      </a>
    )
  }
  if (href.startsWith('/')) {
    return (
      <Link to={href} className={className}>
        {children}
      </Link>
    )
  }
  return <div className={className}>{children}</div>
}

function BannerCard({ banner }: { banner: HomePlacement }) {
  return (
    <SmartLink
      href={banner.link_url}
      className="group flex gap-3 rounded-2xl border border-border bg-surface p-4 text-left shadow-sm transition hover:border-accent/50 hover:shadow-lg"
    >
      {banner.image_url !== '' ? (
        <img
          src={banner.image_url}
          alt=""
          className="h-16 w-24 shrink-0 rounded-xl object-cover"
        />
      ) : (
        <span className="flex h-16 w-24 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent">
          <Sparkles className="h-5 w-5" />
        </span>
      )}
      <div className="min-w-0">
        <h3 className="truncate text-sm font-semibold text-ink">{banner.title}</h3>
        <p className="mt-1 line-clamp-2 text-xs leading-5 text-ink-muted">
          {banner.subtitle || banner.body}
        </p>
        {banner.link_label !== '' && (
          <span className="mt-1 inline-flex items-center gap-1 text-xs text-accent">
            {banner.link_label}
            <ArrowRight className="h-3 w-3" />
          </span>
        )}
      </div>
    </SmartLink>
  )
}

function PlacementCard({ placement }: { placement: HomePlacement }) {
  return (
    <SmartLink
      href={placement.link_url}
      className="group flex flex-col rounded-2xl border border-border bg-surface p-5 transition hover:border-accent/50 hover:shadow-lg"
    >
      <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent-soft text-accent">
        <Sparkles className="h-4 w-4" />
      </span>
      <h3 className="mt-3 text-sm font-semibold text-ink">{placement.title}</h3>
      {placement.subtitle !== '' && (
        <p className="mt-1 text-xs text-ink-muted">{placement.subtitle}</p>
      )}
      {placement.body !== '' && (
        <p className="mt-2 line-clamp-3 text-xs leading-5 text-ink-muted">{placement.body}</p>
      )}
      {placement.link_label !== '' && (
        <span className="mt-3 inline-flex items-center gap-1 text-xs text-accent">
          {placement.link_label}
          <ArrowRight className="h-3 w-3" />
        </span>
      )}
    </SmartLink>
  )
}

function AnnouncementRow({ announcement }: { announcement: Announcement }) {
  const { t, language } = useI18n()
  return (
    <Link
      to={`/announcements/${announcement.id}`}
      className="flex flex-wrap items-center gap-3 px-4 py-3 transition hover:bg-surface-muted"
    >
      {announcement.pinned && <Pin className="h-3.5 w-3.5 shrink-0 text-accent" />}
      <Badge tone="neutral">{t(`announcements.category.${announcement.category}`)}</Badge>
      <span className="min-w-0 flex-1 truncate text-sm text-ink">{announcement.title}</span>
      <span className="inline-flex items-center gap-1 text-xs text-ink-muted">
        <CalendarDays className="h-3 w-3" />
        {formatDate(announcement.published_at ?? announcement.created_at, language)}
      </span>
      <ArrowRight className="h-3.5 w-3.5 shrink-0 text-ink-muted" />
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