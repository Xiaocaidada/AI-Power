import { describe, expect, it } from 'vitest'

import {
  defaultRange,
  fillDailyBuckets,
  rangeQuery,
  sumBuckets,
} from './usage'
import type { UsageBucket } from './types'

function bucket(key: string, partial: Partial<UsageBucket> = {}): UsageBucket {
  return {
    key,
    requests: 1,
    prompt_tokens: 10,
    completion_tokens: 5,
    total_tokens: 15,
    ...partial,
  }
}

describe('usage helpers', () => {
  it('builds a default range that ends today (UTC)', () => {
    const now = new Date('2026-11-21T10:30:00Z')

    expect(defaultRange(7, now)).toEqual({ from: '2026-11-15', to: '2026-11-21' })
    expect(defaultRange(30, now).from).toBe('2026-10-23')
  })

  it('converts a date range into UTC query bounds', () => {
    expect(rangeQuery({ from: '2026-11-01', to: '2026-11-21' })).toEqual({
      from: '2026-11-01T00:00:00Z',
      to: '2026-11-21T23:59:59Z',
    })
  })

  it('fills missing days with zero buckets', () => {
    const filled = fillDailyBuckets([bucket('2026-11-20')], {
      from: '2026-11-19',
      to: '2026-11-21',
    })

    expect(filled.map((item) => item.key)).toEqual([
      '2026-11-19',
      '2026-11-20',
      '2026-11-21',
    ])
    expect(filled[0].requests).toBe(0)
    expect(filled[1].requests).toBe(1)
    expect(filled[2].total_tokens).toBe(0)
  })

  it('keeps empty days when there is no data at all', () => {
    const filled = fillDailyBuckets([], { from: '2026-11-20', to: '2026-11-21' })

    expect(filled).toHaveLength(2)
    expect(filled.every((item) => item.requests === 0)).toBe(true)
  })

  it('sums buckets into totals', () => {
    expect(sumBuckets([bucket('a'), bucket('b', { requests: 2, total_tokens: 30 })])).toEqual({
      requests: 3,
      prompt_tokens: 20,
      completion_tokens: 10,
      total_tokens: 45,
    })
  })
})