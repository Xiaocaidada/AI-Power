export type TimeGroupKey = 'today' | 'yesterday' | 'week' | 'earlier'

const DAY_MS = 24 * 60 * 60 * 1000
const GROUP_ORDER: TimeGroupKey[] = ['today', 'yesterday', 'week', 'earlier']

export function conversationTimeGroup(
  value: string | null | undefined,
  now: Date = new Date(),
): TimeGroupKey {
  if (value === null || value === undefined) return 'earlier'
  const time = new Date(value).getTime()
  if (Number.isNaN(time)) return 'earlier'
  const startOfToday = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate(),
  ).getTime()
  if (time >= startOfToday) return 'today'
  if (time >= startOfToday - DAY_MS) return 'yesterday'
  if (time >= startOfToday - 6 * DAY_MS) return 'week'
  return 'earlier'
}

export function groupConversationsByTime<
  T extends { updated_at?: string | null; created_at: string },
>(
  items: T[],
  now: Date = new Date(),
): { key: TimeGroupKey; items: T[] }[] {
  const buckets = new Map<TimeGroupKey, T[]>(
    GROUP_ORDER.map((key) => [key, []]),
  )
  for (const item of items) {
    const key = conversationTimeGroup(item.updated_at ?? item.created_at, now)
    buckets.get(key)?.push(item)
  }
  return GROUP_ORDER.map((key) => ({ key, items: buckets.get(key) ?? [] })).filter(
    (group) => group.items.length > 0,
  )
}