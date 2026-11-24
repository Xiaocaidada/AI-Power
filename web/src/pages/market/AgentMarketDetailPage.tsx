import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Copy } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Spinner } from '../../components/ui/spinner'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import { hasSession } from '../../lib/tokens'
import type {
  AgentMarketDetail,
  AgentReportReason,
  AgentReview,
  AgentReviewList,
  CustomAgent,
} from '../../lib/types'

export function AgentMarketDetailPage() {
  const { slug = '' } = useParams<{ slug: string }>()
  const { t } = useI18n()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [copying, setCopying] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [rating, setRating] = useState(5)
  const [reviewText, setReviewText] = useState('')
  const [reportReason, setReportReason] = useState<AgentReportReason>('spam')
  const [reportDetail, setReportDetail] = useState('')
  const [reportSent, setReportSent] = useState(false)
  const [reviewBusy, setReviewBusy] = useState(false)
  const agent = useQuery({
    queryKey: ['market-agent', slug],
    queryFn: () =>
      apiRequest<AgentMarketDetail>(`/market/agents/${slug}`, { auth: false }),
    enabled: slug !== '',
  })
  const reviewsQuery = useQuery({
    queryKey: ['market-agent-reviews', slug],
    queryFn: () =>
      apiRequest<AgentReviewList>(`/market/agents/${slug}/reviews`, { auth: false }),
    enabled: slug !== '',
  })
  const mineQuery = useQuery({
    queryKey: ['market-agent-my-review', slug, agent.data?.id ?? ''],
    queryFn: () => apiRequest<AgentReview | null>(`/agents/${agent.data?.id}/review`),
    enabled: agent.data !== undefined && hasSession(),
  })

  useEffect(() => {
    if (mineQuery.data === null || mineQuery.data === undefined) return
    setRating(mineQuery.data.rating)
    setReviewText(mineQuery.data.content)
  }, [mineQuery.data])

  if (agent.isLoading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Spinner className="h-6 w-6 text-accent" />
      </div>
    )
  }
  if (agent.isError || agent.data === undefined) {
    return (
      <div className="mx-auto flex min-h-[50vh] w-full max-w-3xl flex-col items-center justify-center gap-3 px-6">
        <p className="text-sm text-ink-muted">{t('market.missing')}</p>
        <Link to="/market/agents" className="text-sm text-accent">
          {t('market.back')}
        </Link>
      </div>
    )
  }

  const detail = agent.data
  const copy = async () => {
    if (!hasSession()) {
      navigate(`/login?next=${encodeURIComponent(`/market/agents/${slug}`)}`)
      return
    }
    setCopying(true)
    setError(null)
    try {
      const created = await apiRequest<CustomAgent>(`/agents/${detail.id}/copy`, {
        method: 'POST',
      })
      navigate(`/studio/${created.id}`)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('errors.generic'))
    } finally {
      setCopying(false)
    }
  }

  const submitReview = async () => {
    if (!hasSession()) {
      navigate(`/login?next=${encodeURIComponent(`/market/agents/${slug}`)}`)
      return
    }
    setReviewBusy(true)
    setError(null)
    try {
      await apiRequest(`/agents/${detail.id}/review`, {
        method: 'PUT',
        body: { rating, content: reviewText },
      })
      await queryClient.invalidateQueries({ queryKey: ['market-agent-reviews', slug] })
      await queryClient.invalidateQueries({ queryKey: ['market-agent', slug] })
      await queryClient.invalidateQueries({ queryKey: ['market-agent-my-review'] })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('errors.generic'))
    } finally {
      setReviewBusy(false)
    }
  }

  const removeReview = async () => {
    setReviewBusy(true)
    setError(null)
    try {
      await apiRequest(`/agents/${detail.id}/review`, { method: 'DELETE' })
      await queryClient.invalidateQueries({ queryKey: ['market-agent-reviews', slug] })
      await queryClient.invalidateQueries({ queryKey: ['market-agent', slug] })
      await queryClient.invalidateQueries({ queryKey: ['market-agent-my-review'] })
      setReviewText('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('errors.generic'))
    } finally {
      setReviewBusy(false)
    }
  }

  const sendReport = async () => {
    if (!hasSession()) {
      navigate(`/login?next=${encodeURIComponent(`/market/agents/${slug}`)}`)
      return
    }
    setError(null)
    try {
      await apiRequest(`/agents/${detail.id}/report`, {
        method: 'POST',
        body: { reason: reportReason, detail: reportDetail },
      })
      setReportSent(true)
      setReportDetail('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('errors.generic'))
    }
  }

  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-10">
      <Link
        to="/market/agents"
        className="inline-flex items-center gap-1 text-xs text-ink-muted hover:text-ink"
      >
        <ArrowLeft className="h-3 w-3" />
        {t('market.back')}
      </Link>
      {detail.cover_url && (
        <img
          src={detail.cover_url}
          alt=""
          className="mt-4 h-48 w-full rounded-panel border border-border object-cover"
        />
      )}
      <header className="mt-4 flex flex-wrap items-start gap-4">
        <span className="flex h-16 w-16 items-center justify-center rounded-2xl bg-accent-soft text-3xl">
          {detail.icon}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold text-ink">{detail.name}</h1>
            <Badge tone="neutral">{detail.mode}</Badge>
            {detail.featured && <Badge tone="accent">{t('market.featured')}</Badge>}
            {detail.official && <Badge tone="success">{t('market.official')}</Badge>}
            {detail.allow_copy && <Badge tone="success">{t('market.copyable')}</Badge>}
          </div>
          <p className="mt-1 text-sm text-ink-muted">{detail.description}</p>
          <div className="mt-2 flex flex-wrap gap-4 text-[11px] text-ink-muted">
            {detail.publisher && <span>{detail.publisher}</span>}
            <span>{detail.usage_count} uses</span>
            <span>{detail.favorite_count} favorites</span>
            <span>{detail.copy_count} copies</span>
            <span>
              ★ {(detail.rating_avg ?? 0).toFixed(1)} ({detail.rating_count ?? 0})
            </span>
            {detail.model_hint && <span>{detail.model_hint}</span>}
          </div>
        </div>
        <Button size="sm" disabled={copying || !detail.allow_copy} onClick={() => void copy()}>
          <Copy className="h-3.5 w-3.5" />
          {t('market.copyToWorkspace')}
        </Button>
      </header>
      {error !== null && <p className="mt-2 text-xs text-danger">{error}</p>}

      <div className="mt-8 grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <section className="rounded-card border border-border bg-surface p-5">
          <h2 className="text-sm font-medium text-ink">{t('market.about')}</h2>
          <p className="mt-2 whitespace-pre-wrap text-sm text-ink-muted">
            {detail.usage_instructions || detail.description}
          </p>
          {detail.welcome_message && (
            <p className="mt-3 rounded-lg bg-surface-muted p-3 text-xs text-ink">
              {detail.welcome_message}
            </p>
          )}
          {detail.examples.length > 0 && (
            <>
              <h3 className="mt-4 text-xs font-medium text-ink">{t('market.examples')}</h3>
              <ul className="mt-1 list-inside list-disc text-xs text-ink-muted">
                {detail.examples.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          )}
        </section>

        <section className="space-y-4">
          <div className="rounded-card border border-border bg-surface p-5">
            <h2 className="text-sm font-medium text-ink">{t('market.requirements')}</h2>
            {detail.kb_requirements.length === 0 &&
            detail.plugin_requirements.length === 0 ? (
              <p className="mt-2 text-xs text-ink-muted">{t('market.noRequirements')}</p>
            ) : (
              <div className="mt-2 space-y-2 text-xs text-ink-muted">
                {detail.kb_requirements.length > 0 && (
                  <p>
                    <span className="font-medium text-ink">KB</span>:{' '}
                    {detail.kb_requirements.join(', ')}
                  </p>
                )}
                {detail.plugin_requirements.length > 0 && (
                  <p>
                    <span className="font-medium text-ink">Plugins</span>:{' '}
                    {detail.plugin_requirements.join(', ')}
                  </p>
                )}
              </div>
            )}
          </div>

          {detail.workflow ? (
            <div className="rounded-card border border-border bg-surface p-5">
              <h2 className="text-sm font-medium text-ink">{t('market.structure')}</h2>
              <div className="mt-2 space-y-2">
                {detail.workflow.nodes.map((node) => (
                  <div
                    key={node.id}
                    className="flex items-center justify-between rounded-lg bg-surface-muted px-3 py-1.5 text-xs"
                  >
                    <span className="text-ink">{node.id}</span>
                    <span className="text-ink-muted">{node.type}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="rounded-card border border-border bg-surface p-5">
              <h2 className="text-sm font-medium text-ink">{t('market.structure')}</h2>
              <p className="mt-2 text-xs text-ink-muted">
                {t('market.structureHidden')}
              </p>
            </div>
          )}
        </section>
      </div>

      <section className="mt-6 grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <div className="rounded-card border border-border bg-surface p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-ink">{t('market.reviews')}</h2>
            <span className="text-xs text-ink-muted">
              ★ {(reviewsQuery.data?.rating_avg ?? detail.rating_avg ?? 0).toFixed(1)} (
              {reviewsQuery.data?.rating_count ?? detail.rating_count ?? 0})
            </span>
          </div>
          {(reviewsQuery.data?.reviews.length ?? 0) === 0 ? (
            <p className="mt-2 text-xs text-ink-muted">{t('market.noReviews')}</p>
          ) : (
            <ul className="mt-3 space-y-3">
              {(reviewsQuery.data?.reviews ?? []).map((review) => (
                <li key={review.id} className="rounded-lg bg-surface-muted px-3 py-2">
                  <div className="flex items-center gap-2 text-xs">
                    <span className="text-warning">{'★'.repeat(review.rating)}</span>
                    <span className="text-ink-muted">{review.author}</span>
                    <span className="ml-auto text-[10px] text-ink-muted">
                      {new Date(review.updated_at).toLocaleDateString()}
                    </span>
                  </div>
                  {review.content && (
                    <p className="mt-1 whitespace-pre-wrap text-xs text-ink">
                      {review.content}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}

          {hasSession() && (
            <div className="mt-4 border-t border-border pt-3">
              <p className="text-xs font-medium text-ink">
                {mineQuery.data ? t('market.updateReview') : t('market.writeReview')}
              </p>
              <div className="mt-2 flex items-center gap-1">
                {[1, 2, 3, 4, 5].map((value) => (
                  <button
                    key={value}
                    type="button"
                    aria-label={`${value} stars`}
                    onClick={() => setRating(value)}
                    className={
                      value <= rating ? 'text-warning' : 'text-ink-muted/40'
                    }
                  >
                    ★
                  </button>
                ))}
              </div>
              <textarea
                value={reviewText}
                onChange={(event) => setReviewText(event.target.value)}
                placeholder={
                  mineQuery.data?.content ?? t('market.reviewPlaceholder')
                }
                className="mt-2 min-h-16 w-full rounded-lg border border-border bg-surface px-3 py-2 text-xs text-ink"
              />
              <div className="mt-2 flex gap-2">
                <Button size="sm" disabled={reviewBusy} onClick={() => void submitReview()}>
                  {t('market.submitReview')}
                </Button>
                {mineQuery.data && (
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={reviewBusy}
                    onClick={() => void removeReview()}
                  >
                    {t('market.deleteReview')}
                  </Button>
                )}
              </div>
            </div>
          )}
        </div>

        <div className="rounded-card border border-border bg-surface p-5">
          <h2 className="text-sm font-medium text-ink">{t('market.report')}</h2>
          <p className="mt-1 text-[11px] text-ink-muted">{t('market.reportLead')}</p>
          {reportSent ? (
            <p className="mt-3 text-xs text-success">{t('market.reportThanks')}</p>
          ) : (
            <div className="mt-3 space-y-2">
              <select
                value={reportReason}
                onChange={(event) =>
                  setReportReason(event.target.value as AgentReportReason)
                }
                className="h-9 w-full rounded-lg border border-border bg-surface px-2 text-xs text-ink"
              >
                {(['spam', 'abuse', 'copyright', 'misleading', 'other'] as const).map(
                  (reason) => (
                    <option key={reason} value={reason}>
                      {t(`market.reportReason.${reason}`)}
                    </option>
                  ),
                )}
              </select>
              <textarea
                value={reportDetail}
                onChange={(event) => setReportDetail(event.target.value)}
                placeholder={t('market.reportDetail')}
                className="min-h-16 w-full rounded-lg border border-border bg-surface px-3 py-2 text-xs text-ink"
              />
              <Button size="sm" variant="secondary" onClick={() => void sendReport()}>
                {t('market.submitReport')}
              </Button>
            </div>
          )}
        </div>
      </section>
    </div>
  )
}