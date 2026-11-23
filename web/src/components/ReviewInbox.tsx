import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, X } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { Badge } from './ui/badge'
import { Button } from './ui/button'
import { Input } from './ui/input'
import { apiRequest } from '../lib/http'
import { useI18n } from '../lib/i18n'
import type { WorkflowReview } from '../lib/types'

interface ReviewInboxProps {
  runId?: string
}

export function ReviewInbox({ runId }: ReviewInboxProps) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [comments, setComments] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState('')
  const [error, setError] = useState<string | null>(null)

  const reviews = useQuery({
    queryKey: ['workflow-reviews', runId ?? 'all'],
    queryFn: () =>
      apiRequest<WorkflowReview[]>(
        `/workflows/reviews?status=pending${
          runId === undefined ? '' : `&run_id=${runId}`
        }`,
      ),
    refetchInterval: 3000,
  })

  const respond = async (review: WorkflowReview, decision: 'approved' | 'rejected') => {
    setBusy(review.id)
    setError(null)
    try {
      await apiRequest(`/workflows/reviews/${review.id}/respond`, {
        method: 'POST',
        body: { decision, comment: comments[review.id] ?? '', output: '' },
      })
      await queryClient.invalidateQueries({ queryKey: ['workflow-reviews'] })
      setComments((current) => {
        const next = { ...current }
        delete next[review.id]
        return next
      })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('errors.generic'))
    } finally {
      setBusy('')
    }
  }

  const items = reviews.data ?? []
  if (items.length === 0) return null

  return (
    <section className="rounded-card border border-warning/40 bg-warning/10 p-4">
      <div className="flex items-center gap-2">
        <p className="text-sm font-medium text-ink">{t('reviews.inboxTitle')}</p>
        <Badge tone="warning">{items.length}</Badge>
      </div>
      <p className="mt-1 text-[11px] text-ink-muted">{t('reviews.inboxLead')}</p>
      <div className="mt-3 space-y-3">
        {items.map((review) => (
          <div
            key={review.id}
            className="rounded-lg border border-border bg-surface px-3 py-2"
          >
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-ink-muted">
              <Badge tone="neutral">{review.node_id}</Badge>
              <Link to={`/workflows?run=${review.run_id}`} className="text-accent">
                {t('reviews.openRun')}
              </Link>
            </div>
            <p className="mt-2 max-h-32 overflow-y-auto whitespace-pre-wrap text-xs text-ink">
              {review.prompt}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Input
                value={comments[review.id] ?? ''}
                onChange={(event) =>
                  setComments((current) => ({
                    ...current,
                    [review.id]: event.target.value,
                  }))
                }
                placeholder={t('reviews.comment')}
                className="h-8 w-56 text-xs"
              />
              <Button
                size="sm"
                disabled={busy === review.id}
                onClick={() => void respond(review, 'approved')}
              >
                <Check className="h-3.5 w-3.5" />
                {t('reviews.approve')}
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={busy === review.id}
                onClick={() => void respond(review, 'rejected')}
              >
                <X className="h-3.5 w-3.5" />
                {t('reviews.reject')}
              </Button>
            </div>
          </div>
        ))}
      </div>
      {error !== null && <p className="mt-2 text-xs text-danger">{error}</p>}
    </section>
  )
}