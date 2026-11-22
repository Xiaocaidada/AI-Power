import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { Button } from '../../components/ui/button'
import { EmptyState } from '../../components/ui/empty-state'
import { Input } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import { mergePages, pageFromItems } from '../../lib/pagination'
import type {
  QuotaSummary,
  TraceRecord,
  UsageByKey,
  UsageCost,
  UsageSummary,
} from '../../lib/types'
import { cn } from '../../lib/utils'
import {
  defaultRange,
  fillDailyBuckets,
  rangeQuery,
  sumBuckets,
  type DateRange,
  type GroupBy,
} from '../../lib/usage'

const PRESETS = [7, 30, 90] as const

export function UsagePage() {
  const { t, language } = useI18n()
  const navigate = useNavigate()
  const [preset, setPreset] = useState<number | 'custom'>(30)
  const [range, setRange] = useState<DateRange>(() => defaultRange(30))
  const [groupBy, setGroupBy] = useState<GroupBy>('day')

  const numberFormat = new Intl.NumberFormat(language === 'zh' ? 'zh-CN' : 'en')
  const format = (value: number) => numberFormat.format(value)
  const costFormat = new Intl.NumberFormat(language === 'zh' ? 'zh-CN' : 'en', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 6,
  })
  const formatCost = (value: number) => costFormat.format(value)

  const validRange = range.from <= range.to
  const usage = useQuery({
    queryKey: ['usage', range.from, range.to, groupBy],
    queryFn: () => {
      const bounds = rangeQuery(range)
      return apiRequest<UsageSummary>(
        `/usage/summary?from=${encodeURIComponent(bounds.from)}&to=${encodeURIComponent(
          bounds.to,
        )}&group_by=${groupBy}`,
      )
    },
    enabled: validRange,
  })

  const quota = useQuery({
    queryKey: ['quota'],
    queryFn: () => apiRequest<QuotaSummary>('/usage/quota'),
  })

  const cost = useQuery({
    queryKey: ['usage-cost', range.from, range.to, groupBy],
    queryFn: () => {
      const bounds = rangeQuery(range)
      return apiRequest<UsageCost>(
        `/usage/cost?from=${encodeURIComponent(bounds.from)}&to=${encodeURIComponent(
          bounds.to,
        )}&group_by=${groupBy}`,
      )
    },
    enabled: validRange,
  })
  const costByKey = new Map((cost.data?.buckets ?? []).map((bucket) => [bucket.key, bucket]))

  const byKey = useQuery({
    queryKey: ['usage-by-key', range.from, range.to],
    queryFn: () => {
      const bounds = rangeQuery(range)
      return apiRequest<UsageByKey>(
        `/usage/by-key?from=${encodeURIComponent(bounds.from)}&to=${encodeURIComponent(
          bounds.to,
        )}`,
      )
    },
    enabled: validRange,
  })

  const traces = useInfiniteQuery({
    queryKey: ['traces', 'recent'],
    queryFn: async ({ pageParam }) =>
      pageFromItems(
        await apiRequest<TraceRecord[]>(
          `/traces?limit=10${pageParam ? `&before=${pageParam}` : ''}`,
        ),
        10,
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next,
    enabled: validRange,
  })
  const traceRows = mergePages(traces.data?.pages)

  const buckets = usage.data?.buckets ?? []
  const totals = sumBuckets(buckets)
  const chartBuckets =
    groupBy === 'day'
      ? fillDailyBuckets(buckets, range)
      : [...buckets].sort((left, right) => right.total_tokens - left.total_tokens)
  const chartData = chartBuckets.map((bucket) => ({
    name: groupBy === 'day' ? bucket.key.slice(5) : bucket.key,
    prompt: bucket.prompt_tokens,
    completion: bucket.completion_tokens,
    total: bucket.total_tokens,
  }))
  const tableRows = buckets.filter((bucket) => bucket.requests > 0 || bucket.total_tokens > 0)
  const costChartData = (cost.data?.buckets ?? []).map((bucket) => ({
    name: groupBy === 'day' ? bucket.key.slice(5) : bucket.key,
    cost: bucket.cost,
  }))

  const selectPreset = (days: number) => {
    setPreset(days)
    setRange(defaultRange(days))
  }

  const updateDate = (key: 'from' | 'to', value: string) => {
    setPreset('custom')
    setRange((previous) => ({ ...previous, [key]: value }))
  }

  const kpis = [
    { label: t('usage.requests'), value: totals.requests },
    { label: t('usage.promptTokens'), value: totals.prompt_tokens },
    { label: t('usage.completionTokens'), value: totals.completion_tokens },
    { label: t('usage.totalTokens'), value: totals.total_tokens },
  ]

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-4">
        <h1 className="text-lg font-semibold">{t('usage.title')}</h1>
        <p className="mt-1 text-sm text-ink-muted">{t('usage.lead')}</p>
      </header>

      <div className="space-y-5 px-6 py-6">
        {quota.data !== undefined && (
          <section className="rounded-card border border-border bg-surface p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-semibold">{t('quota.title')}</h2>
              <span className="text-xs text-ink-muted">
                {t('quota.plan', { plan: quota.data.plan })}
              </span>
            </div>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {(
                [
                  { label: t('quota.requests'), window: quota.data.requests },
                  { label: t('quota.tokens'), window: quota.data.tokens },
                ] as const
              ).map(({ label, window }) => (
                <div key={label} className="rounded-lg bg-surface-muted p-3">
                  <div className="flex items-center justify-between text-xs text-ink-muted">
                    <span>{label}</span>
                    <span>
                      {t('quota.used', {
                        used: format(window.used),
                        limit: format(window.limit),
                      })}
                    </span>
                  </div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface">
                    <div
                      className="h-full bg-accent"
                      style={{
                        width: `${Math.min((window.used / Math.max(window.limit, 1)) * 100, 100)}%`,
                      }}
                    />
                  </div>
                  <p className="mt-1 text-[11px] text-ink-muted">
                    {t('quota.remaining', { remaining: format(window.remaining) })} ·{' '}
                    {t('quota.reset', { seconds: window.reset_seconds })}
                  </p>
                </div>
              ))}
            </div>
            <p className="mt-2 text-xs text-ink-muted">
              {t('quota.keys')}:{' '}
              {t('quota.keysValue', {
                used: quota.data.active_keys,
                limit: quota.data.max_keys,
              })}
            </p>
          </section>
        )}
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex flex-wrap items-center gap-2">
            {PRESETS.map((days) => (
              <Button
                key={days}
                size="sm"
                variant={preset === days ? 'primary' : 'secondary'}
                onClick={() => selectPreset(days)}
              >
                {t(`usage.range${days}`)}
              </Button>
            ))}
            <span className="text-xs text-ink-muted">{t('usage.custom')}</span>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-xs text-ink-muted">
              <span className="mb-1 block">{t('usage.from')}</span>
              <Input
                type="date"
                className="h-9 w-40"
                value={range.from}
                onChange={(event) => updateDate('from', event.target.value)}
              />
            </label>
            <label className="text-xs text-ink-muted">
              <span className="mb-1 block">{t('usage.to')}</span>
              <Input
                type="date"
                className="h-9 w-40"
                value={range.to}
                onChange={(event) => updateDate('to', event.target.value)}
              />
            </label>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-ink-muted">{t('usage.groupBy')}</span>
          {(['day', 'provider', 'model', 'source'] as const).map((group) => (
            <Button
              key={group}
              size="sm"
              variant={groupBy === group ? 'primary' : 'secondary'}
              onClick={() => setGroupBy(group)}
            >
              {group === 'day'
                ? t('usage.byDay')
                : group === 'provider'
                  ? t('usage.byProvider')
                  : group === 'model'
                    ? t('usage.byModel')
                    : t('usage.bySource')}
            </Button>
          ))}
        </div>

        {!validRange && (
          <p role="alert" className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
            {t('usage.invalidRange')}
          </p>
        )}

        {usage.isError && (
          <div className="flex items-center gap-3 text-sm text-ink-muted">
            {t('errors.generic')}
            <Button variant="secondary" size="sm" onClick={() => void usage.refetch()}>
              {t('common.retry')}
            </Button>
          </div>
        )}

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          {kpis.map((kpi) => (
            <div key={kpi.label} className="rounded-card border border-border bg-surface p-4">
              <p className="text-xs text-ink-muted">{kpi.label}</p>
              <p className="mt-1 font-mono text-xl text-ink">
                {usage.isLoading ? '—' : format(kpi.value)}
              </p>
            </div>
          ))}
          <div className="rounded-card border border-border bg-surface p-4">
            <p className="text-xs text-ink-muted">{t('usage.cost')}</p>
            <p className="mt-1 font-mono text-xl text-ink">
              {cost.isLoading || cost.data === undefined ? '—' : formatCost(cost.data.total_cost)}
            </p>
            {cost.data !== undefined && cost.data.unpriced_requests > 0 && (
              <p className="mt-1 text-[11px] text-warning">
                {t('usage.unpricedHint', { count: cost.data.unpriced_requests })}
              </p>
            )}
          </div>
        </div>

        {usage.isLoading ? (
          <div className="flex items-center gap-2 text-sm text-ink-muted">
            <Spinner />
            {t('common.loading')}
          </div>
        ) : totals.requests === 0 ? (
          <EmptyState title={t('usage.empty')} description={t('usage.emptyLead')}>
            <Button onClick={() => navigate('/chat')}>{t('usage.goChat')}</Button>
          </EmptyState>
        ) : (
          <>
            <section className="rounded-card border border-border bg-surface p-4">
              <h2 className="mb-3 text-sm font-medium">{t('usage.chartTitle')}</h2>
              <div className="h-[280px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  {groupBy === 'day' ? (
                    <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#94A3B8" strokeOpacity={0.3} />
                      <XAxis dataKey="name" tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                      <YAxis
                        width={56}
                        tick={{ fontSize: 12 }}
                        tickLine={false}
                        axisLine={false}
                      />
                      <Tooltip />
                      <Legend />
                      <Bar
                        dataKey="prompt"
                        name={t('usage.promptTokens')}
                        stackId="tokens"
                        fill="#818CF8"
                      />
                      <Bar
                        dataKey="completion"
                        name={t('usage.completionTokens')}
                        stackId="tokens"
                        fill="#6366F1"
                        radius={[4, 4, 0, 0]}
                      />
                    </BarChart>
                  ) : (
                    <BarChart
                      data={chartData}
                      layout="vertical"
                      margin={{ top: 8, right: 16, left: 8, bottom: 0 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#94A3B8" strokeOpacity={0.3} />
                      <XAxis
                        type="number"
                        tick={{ fontSize: 12 }}
                        tickLine={false}
                        axisLine={false}
                      />
                      <YAxis
                        type="category"
                        dataKey="name"
                        width={140}
                        tick={{ fontSize: 12 }}
                        tickLine={false}
                        axisLine={false}
                      />
                      <Tooltip />
                      <Bar
                        dataKey="total"
                        name={t('usage.totalTokens')}
                        fill="#6366F1"
                        radius={[0, 4, 4, 0]}
                      />
                    </BarChart>
                  )}
                </ResponsiveContainer>
              </div>
              <p className="mt-2 text-[11px] text-ink-muted">{t('usage.nullUsageHint')}</p>
            </section>

            <section className="rounded-card border border-border bg-surface p-4">
              <h2 className="mb-3 text-sm font-medium">{t('usage.costChartTitle')}</h2>
              <div className="h-[240px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={costChartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#94A3B8" strokeOpacity={0.3} />
                    <XAxis dataKey="name" tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                    <YAxis width={72} tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                    <Tooltip formatter={(value) => formatCost(Number(value))} />
                    <Bar dataKey="cost" name={t('usage.cost')} fill="#38BDF8" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </section>

            <section className="rounded-card border border-border bg-surface p-4">
              <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="text-sm font-medium">{t('usage.byKeyTitle')}</h2>
                <p className="text-[11px] text-ink-muted">{t('usage.byKeyHint')}</p>
              </div>
              {byKey.isLoading ? (
                <div className="flex items-center gap-2 text-sm text-ink-muted">
                  <Spinner />
                  {t('common.loading')}
                </div>
              ) : (byKey.data?.buckets.length ?? 0) === 0 ? (
                <p className="text-sm text-ink-muted">{t('usage.noKeyUsage')}</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[620px] text-left text-sm">
                    <thead className="border-b border-border text-xs uppercase tracking-wide text-ink-muted">
                      <tr>
                        <th className="px-3 py-2 font-medium">{t('usage.keyName')}</th>
                        <th className="px-3 py-2 text-right font-medium">{t('usage.requests')}</th>
                        <th className="px-3 py-2 text-right font-medium">
                          {t('usage.totalTokens')}
                        </th>
                        <th className="px-3 py-2 text-right font-medium">{t('usage.cost')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {byKey.data?.buckets.map((bucket) => (
                        <tr
                          key={bucket.api_key_id ?? 'unattributed'}
                          className="border-b border-border last:border-0"
                        >
                          <td className="px-3 py-2">
                            {bucket.api_key_id === null ? (
                              <span className="text-ink-muted">{t('usage.unattributed')}</span>
                            ) : (
                              <span className="flex flex-wrap items-baseline gap-2">
                                <span className="text-ink">{bucket.name}</span>
                                <span className="font-mono text-[11px] text-ink-muted">
                                  {bucket.prefix}
                                </span>
                              </span>
                            )}
                          </td>
                          <td className="px-3 py-2 text-right">{format(bucket.requests)}</td>
                          <td className="px-3 py-2 text-right">
                            {format(bucket.total_tokens)}
                          </td>
                          <td className="px-3 py-2 text-right font-mono text-xs">
                            {formatCost(bucket.cost)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <section className="rounded-card border border-border bg-surface p-4">
              <h2 className="mb-3 text-sm font-medium">{t('usage.recentRequests')}</h2>
              <ul className="divide-y divide-border text-sm">
                {traceRows.map((trace) => (
                  <li key={trace.id} className="flex flex-wrap items-center gap-2 py-2">
                    <span className="font-mono text-xs text-ink">
                      {trace.request_id.slice(0, 8)}
                    </span>
                    <span
                      className={cn(
                        'text-xs',
                        trace.status === 'completed' ? 'text-success' : 'text-danger',
                      )}
                    >
                      {trace.status}
                    </span>
                    <span className="text-xs text-ink-muted">
                      {trace.ttft_ms === null ? '—' : `${Math.round(trace.ttft_ms)} ms`}
                      {' / '}
                      {trace.total_ms === null ? '—' : `${Math.round(trace.total_ms)} ms`}
                    </span>
                    <span className="ml-auto text-[11px] text-ink-muted">
                      {trace.created_at.slice(0, 19).replace('T', ' ')}
                    </span>
                  </li>
                ))}
                {traceRows.length === 0 && (
                  <li className="py-2 text-sm text-ink-muted">{t('usage.noRequests')}</li>
                )}
              </ul>
              {traces.hasNextPage && (
                <div className="mt-2 flex justify-center">
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={traces.isFetchingNextPage}
                    onClick={() => void traces.fetchNextPage()}
                  >
                    {traces.isFetchingNextPage ? t('common.loading') : t('common.loadMore')}
                  </Button>
                </div>
              )}
            </section>

            <section className="overflow-x-auto rounded-card border border-border bg-surface">
              <table className="w-full min-w-[560px] text-left text-sm">
                <thead className="border-b border-border text-xs uppercase tracking-wide text-ink-muted">
                  <tr>
                    <th className="px-3 py-2 font-medium">{t('usage.tableKey')}</th>
                    <th className="px-3 py-2 text-right font-medium">{t('usage.requests')}</th>
                    <th className="px-3 py-2 text-right font-medium">{t('usage.promptTokens')}</th>
                    <th className="px-3 py-2 text-right font-medium">
                      {t('usage.completionTokens')}
                    </th>
                    <th className="px-3 py-2 text-right font-medium">{t('usage.totalTokens')}</th>
                    <th className="px-3 py-2 text-right font-medium">{t('usage.cost')}</th>
                  </tr>
                </thead>
                <tbody>
                  {tableRows.map((bucket) => (
                    <tr key={bucket.key} className="border-b border-border last:border-0">
                      <td className="px-3 py-2 font-mono text-xs text-ink">{bucket.key}</td>
                      <td className="px-3 py-2 text-right">{format(bucket.requests)}</td>
                      <td className="px-3 py-2 text-right">{format(bucket.prompt_tokens)}</td>
                      <td className="px-3 py-2 text-right">{format(bucket.completion_tokens)}</td>
                      <td className="px-3 py-2 text-right font-medium">
                        {format(bucket.total_tokens)}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-xs">
                        {formatCost(costByKey.get(bucket.key)?.cost ?? 0)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          </>
        )}
      </div>
    </div>
  )
}