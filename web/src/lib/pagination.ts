export const PAGE_SIZE = 20

export interface CursorPage<T> {
  items: T[]
  next: string | null
}

export function pageFromItems<T extends { id: string }>(
  items: T[],
  limit: number,
): CursorPage<T> {
  const next = items.length === limit ? items[items.length - 1].id : null
  return { items, next }
}

export function mergePages<T extends { id: string }>(
  pages: { items: T[] }[] | undefined,
): T[] {
  if (pages === undefined) return []
  const seen = new Set<string>()
  const merged: T[] = []
  for (const page of pages) {
    for (const item of page.items) {
      if (seen.has(item.id)) continue
      seen.add(item.id)
      merged.push(item)
    }
  }
  return merged
}