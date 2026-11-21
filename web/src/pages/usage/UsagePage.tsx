import { useQuery } from '@tanstack/react-query'
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
import type { QuotaSummary, UsageCost, UsageSummary } from '../../lib/types'
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
          {(['day', 'provider', 'model'] as const).map((group) => (
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
                  : t('usage.byModel')}
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
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#E4E6EB" />
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
                        fill="#C7D2FE"
                      />
                      <Bar
                        dataKey="completion"
                        name={t('usage.completionTokens')}
                        stackId="tokens"
                        fill="#4F46E5"
                        radius={[4, 4, 0, 0]}
                      />
                    </BarChart>
                  ) : (
                    <BarChart
                      data={chartData}
                      layout="vertical"
                      margin={{ top: 8, right: 16, left: 8, bottom: 0 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#E4E6EB" />
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
                        fill="#4F46E5"
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
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#E4E6EB" />
                    <XAxis dataKey="name" tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                    <YAxis width={72} tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                    <Tooltip formatter={(value) => formatCost(Number(value))} />
                    <Bar dataKey="cost" name={t('usage.cost')} fill="#0EA5E9" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
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