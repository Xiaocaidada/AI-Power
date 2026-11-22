import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Megaphone, Pin } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Spinner } from '../../components/ui/spinner'
import { formatDate } from '../../lib/format'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { Announcement } from '../../lib/types'
import { cn } from '../../lib/utils'

const CATEGORIES = ['notice', 'update', 'event', 'maintenance'] as const

export function AnnouncementsPage() {
  const { t, language } = useI18n()
  const [category, setCategory] = useState<string | null>(null)

  const announcements = useQuery({
    queryKey: ['announcements', category],
    queryFn: () =>
      apiRequest<Announcement[]>(
        `/announcements?limit=50${category === null ? '' : `&category=${category}`}`,
        { auth: false },
      ),
  })

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-10 sm:px-6">
      <header>
        <h1 className="font-serif text-3xl text-ink">{t('announcements.title')}</h1>
        <p className="mt-2 text-sm text-ink-muted">{t('announcements.lead')}</p>
      </header>

      <div className="mt-6 flex flex-wrap gap-2">
        <FilterChip active={category === null} onClick={() => setCategory(null)}>
          {t('announcements.all')}
        </FilterChip>
        {CATEGORIES.map((item) => (
          <FilterChip
            key={item}
            active={category === item}
            onClick={() => setCategory(item)}
          >
            {t(`announcements.category.${item}`)}
          </FilterChip>
        ))}
      </div>

      {announcements.isLoading && (
        <div className="mt-8 flex items-center gap-2 text-sm text-ink-muted">
          <Spinner />
          {t('common.loading')}
        </div>
      )}

      {announcements.data !== undefined && announcements.data.length === 0 && (
        <p className="mt-10 rounded-2xl border border-dashed border-border bg-surface px-6 py-12 text-center text-sm text-ink-muted">
          {t('announcements.empty')}
        </p>
      )}

      <div className="mt-6 space-y-3">
        {(announcements.data ?? []).map((item) => (
          <Link
            key={item.id}
            to={`/announcements/${item.id}`}
            className="group block rounded-2xl border border-border bg-surface p-5 transition hover:border-accent/50 hover:shadow-lg"
          >
            <div className="flex flex-wrap items-center gap-2">
              {item.pinned && (
                <Badge tone="accent">
                  <Pin className="mr-1 h-3 w-3" />
                  {t('announcements.pinned')}
                </Badge>
              )}
              <Badge tone="neutral">
                {t(`announcements.category.${item.category}`)}
              </Badge>
              <span className="text-xs text-ink-muted">
                {formatDate(item.published_at ?? item.created_at, language)}
              </span>
            </div>
            <h2 className="mt-3 text-base font-semibold text-ink group-hover:text-accent">
              {item.title}
            </h2>
            {item.summary !== '' && (
              <p className="mt-1 line-clamp-2 text-sm leading-6 text-ink-muted">
                {item.summary}
              </p>
            )}
            <span className="mt-3 inline-flex items-center gap-1 text-xs text-accent">
              <Megaphone className="h-3 w-3" />
              <ArrowRight className="h-3 w-3" />
            </span>
          </Link>
        ))}
      </div>
    </div>
  )
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'rounded-full border px-3 py-1.5 text-xs transition',
        active
          ? 'border-accent bg-accent-soft font-medium text-accent'
          : 'border-border text-ink-muted hover:text-ink',
      )}
    >
      {children}
    </button>
  )
}