import type { UsageBucket } from './types'

const DAY_MS = 86_400_000

export type GroupBy = 'day' | 'provider' | 'model' | 'source'

export interface DateRange {
  from: string
  to: string
}

export interface UsageTotals {
  requests: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export function toDateInput(date: Date): string {
  return date.toISOString().slice(0, 10)
}

export function defaultRange(days: number, now: Date = new Date()): DateRange {
  const end = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()))
  const start = new Date(end.getTime() - (days - 1) * DAY_MS)
  return { from: toDateInput(start), to: toDateInput(end) }
}

export function rangeQuery(range: DateRange): { from: string; to: string } {
  return {
    from: `${range.from}T00:00:00Z`,
    to: `${range.to}T23:59:59Z`,
  }
}

export function sumBuckets(buckets: UsageBucket[]): UsageTotals {
  return buckets.reduce<UsageTotals>(
    (totals, bucket) => ({
      requests: totals.requests + bucket.requests,
      prompt_tokens: totals.prompt_tokens + bucket.prompt_tokens,
      completion_tokens: totals.completion_tokens + bucket.completion_tokens,
      total_tokens: totals.total_tokens + bucket.total_tokens,
    }),
    { requests: 0, prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 },
  )
}

export function fillDailyBuckets(buckets: UsageBucket[], range: DateRange): UsageBucket[] {
  const byKey = new Map(buckets.map((bucket) => [bucket.key, bucket]))
  const start = Date.parse(`${range.from}T00:00:00Z`)
  const end = Date.parse(`${range.to}T00:00:00Z`)
  if (!Number.isFinite(start) || !Number.isFinite(end) || start > end) return []

  const filled: UsageBucket[] = []
  for (let time = start; time <= end; time += DAY_MS) {
    const key = toDateInput(new Date(time))
    filled.push(
      byKey.get(key) ?? {
        key,
        requests: 0,
        prompt_tokens: 0,
        completion_tokens: 0,
        total_tokens: 0,
      },
    )
  }
  return filled
}