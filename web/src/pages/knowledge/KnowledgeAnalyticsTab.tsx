import { useQuery } from '@tanstack/react-query'
import { BarChart3, Clock, Layers, RefreshCw } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Spinner } from '../../components/ui/spinner'
import { formatDate } from '../../lib/format'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { KnowledgeProcessAnalytics } from '../../lib/types'

const RANGES = [7, 30, 90]

export function KnowledgeAnalyticsTab({ kbId }: { kbId: string }) {
  const { t, language } = useI18n()
  const [days, setDays] = useState(30)
  const analytics = useQuery({
    queryKey: ['kb-processing-analytics', kbId, days],
    queryFn: () =>
      apiRequest<KnowledgeProcessAnalytics>(
        `/knowledge-bases/${kbId}/processing/analytics?days=${days}`,
      ),
    refetchInterval: 10_000,
  })

  if (analytics.isLoading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner className="h-5 w-5 text-accent" />
      </div>
    )
  }
  if (analytics.isError || analytics.data === undefined) {
    return (
      <p className="py-16 text-center text-sm text-ink-muted">
        {t('knowledge.analytics.loadError')}
      </p>
    )
  }
  const data = analytics.data
  const kpis = [
    { label: t('knowledge.analytics.total'), value: data.total },
    {
      label: t('knowledge.analytics.successRate'),
      value: `${Math.round(data.success_rate * 100)}%`,
    },
    {
      label: t('knowledge.analytics.avgDuration'),
      value: `${Math.round(data.avg_duration_ms)} ms`,
    },
    {
      label: t('knowledge.analytics.p95Duration'),
      value: `${Math.round(data.p95_duration_ms)} ms`,
    },
    {
      label: t('knowledge.analytics.avgChunks'),
      value: data.avg_chunks,
    },
    {
      label: t('knowledge.analytics.pendingApply'),
      value: data.pending_apply,
    },
  ]

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-medium text-ink">
            <BarChart3 className="h-4 w-4 text-accent" />
            {t('knowledge.analytics.title')}
          </h2>
          <p className="mt-1 text-xs text-ink-muted">
            {t('knowledge.analytics.lead')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-lg border border-border bg-surface p-0.5">
            {RANGES.map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setDays(value)}
                className={`rounded-md px-3 py-1 text-xs ${
                  days === value
                    ? 'bg-accent-soft text-accent'
                    : 'text-ink-muted'
                }`}
              >
                {t('knowledge.analytics.days', { count: value })}
              </button>
            ))}
          </div>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => void analytics.refetch()}
            aria-label={t('knowledge.analytics.refresh')}
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {kpis.map((item) => (
          <div
            key={item.label}
            className="rounded-card border border-border bg-surface p-4"
          >
            <p className="text-xs text-ink-muted">{item.label}</p>
            <p className="mt-1 text-xl font-semibold text-ink">{item.value}</p>
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[20rem_minmax(0,1fr)]">
        <section className="rounded-card border border-border bg-surface p-4">
          <h3 className="flex items-center gap-2 text-sm font-medium text-ink">
            <Clock className="h-4 w-4" />
            {t('knowledge.analytics.failures')}
          </h3>
          {Object.keys(data.failure_codes).length === 0 ? (
            <p className="mt-2 text-xs text-ink-muted">
              {t('knowledge.analytics.noFailures')}
            </p>
          ) : (
            <ul className="mt-2 space-y-1">
              {Object.entries(data.failure_codes).map(([code, count]) => (
                <li
                  key={code}
                  className="flex items-center justify-between rounded-lg bg-surface-muted px-2 py-1 text-xs"
                >
                  <span className="font-mono text-ink">{code}</span>
                  <Badge tone="danger">{count}</Badge>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="rounded-card border border-border bg-surface p-4">
          <h3 className="flex items-center gap-2 text-sm font-medium text-ink">
            <Layers className="h-4 w-4" />
            {t('knowledge.analytics.recent')}
          </h3>
          {data.recent.length === 0 ? (
            <p className="mt-2 text-xs text-ink-muted">
              {t('knowledge.analytics.noRuns')}
            </p>
          ) : (
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-[10px] uppercase text-ink-muted">
                  <tr>
                    <th className="py-1 pr-2">{t('knowledge.analytics.document')}</th>
                    <th className="py-1 pr-2">{t('knowledge.analytics.status')}</th>
                    <th className="py-1 pr-2">{t('knowledge.analytics.duration')}</th>
                    <th className="py-1 pr-2">{t('knowledge.analytics.chunks')}</th>
                    <th className="py-1 pr-2">{t('knowledge.analytics.applied')}</th>
                    <th className="py-1">{t('knowledge.analytics.started')}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent.map((run) => (
                    <tr key={run.id} className="border-t border-border/60">
                      <td className="max-w-48 truncate py-1.5 pr-2 text-ink">
                        {run.filename || run.document_id || '—'}
                      </td>
                      <td className="py-1.5 pr-2">
                        <Badge
                          tone={
                            run.status === 'completed'
                              ? 'success'
                              : run.status === 'failed'
                                ? 'danger'
                                : 'neutral'
                          }
                        >
                          {run.status}
                        </Badge>
                        {run.error_code && (
                          <span className="ml-1 text-[10px] text-danger">
                            {run.error_code}
                          </span>
                        )}
                      </td>
                      <td className="py-1.5 pr-2 text-ink-muted">
                        {run.duration_ms === null
                          ? '—'
                          : `${Math.round(run.duration_ms)} ms`}
                      </td>
                      <td className="py-1.5 pr-2 text-ink-muted">{run.chunk_count}</td>
                      <td className="py-1.5 pr-2 text-ink-muted">
                        {run.applied
                          ? t('knowledge.analytics.yes')
                          : t('knowledge.analytics.no')}
                      </td>
                      <td className="py-1.5 text-ink-muted">
                        {formatDate(run.started_at, language)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}