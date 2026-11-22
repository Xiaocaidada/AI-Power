import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Pin } from 'lucide-react'
import { useEffect } from 'react'
import { Link, useParams } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Spinner } from '../../components/ui/spinner'
import { formatDate } from '../../lib/format'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { Announcement } from '../../lib/types'
import { useAuthStore } from '../../store/auth'

export function AnnouncementDetailPage() {
  const { t, language } = useI18n()
  const { id = '' } = useParams<{ id: string }>()
  const status = useAuthStore((state) => state.status)
  const queryClient = useQueryClient()

  const announcement = useQuery({
    queryKey: ['announcement', id],
    queryFn: () => apiRequest<Announcement>(`/announcements/${id}`, { auth: false }),
    enabled: id !== '',
  })

  useEffect(() => {
    if (status !== 'authenticated' || announcement.data === undefined) return
    let cancelled = false
    apiRequest(`/notifications/${announcement.data.id}/read`, { method: 'POST' })
      .then(() => {
        if (!cancelled) {
          void queryClient.invalidateQueries({ queryKey: ['notifications'] })
        }
      })
      .catch(() => {
        // Reading an announcement is best-effort; never block the page on it.
      })
    return () => {
      cancelled = true
    }
  }, [status, announcement.data, queryClient])

  if (announcement.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner className="h-6 w-6 text-accent" />
      </div>
    )
  }

  if (announcement.isError || announcement.data === undefined) {
    return (
      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col items-center justify-center gap-3 px-6">
        <p className="text-sm text-ink-muted">{t('announcements.detailMissing')}</p>
        <Button variant="secondary" onClick={() => window.history.back()}>
          {t('announcements.back')}
        </Button>
      </div>
    )
  }

  const detail = announcement.data

  return (
    <article className="mx-auto w-full max-w-3xl px-4 py-10 sm:px-6">
      <Link
        to="/announcements"
        className="inline-flex items-center gap-1 text-xs text-ink-muted hover:text-ink"
      >
        <ArrowLeft className="h-3 w-3" />
        {t('announcements.back')}
      </Link>

      <div className="mt-5 flex flex-wrap items-center gap-2">
        {detail.pinned && (
          <Badge tone="accent">
            <Pin className="mr-1 h-3 w-3" />
            {t('announcements.pinned')}
          </Badge>
        )}
        <Badge tone="neutral">{t(`announcements.category.${detail.category}`)}</Badge>
        <span className="text-xs text-ink-muted">
          {t('announcements.publishedAt')} ·{' '}
          {formatDate(detail.published_at ?? detail.created_at, language)}
        </span>
      </div>

      <h1 className="mt-4 font-serif text-3xl leading-tight text-ink">{detail.title}</h1>
      {detail.summary !== '' && (
        <p className="mt-2 text-sm leading-6 text-ink-muted">{detail.summary}</p>
      )}

      {detail.cover_url !== '' && (
        <img
          src={detail.cover_url}
          alt=""
          className="mt-6 w-full rounded-2xl border border-border object-cover"
        />
      )}

      <div className="mt-6 whitespace-pre-wrap text-[15px] leading-8 text-ink">
        {detail.body}
      </div>
    </article>
  )
}