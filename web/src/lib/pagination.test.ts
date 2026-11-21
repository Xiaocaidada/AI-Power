import { describe, expect, test } from 'vitest'

import { mergePages, pageFromItems } from './pagination'

describe('pagination helpers', () => {
  test('pageFromItems exposes a cursor only for a full page', () => {
    expect(pageFromItems([{ id: 'a' }, { id: 'b' }], 2)).toEqual({
      items: [{ id: 'a' }, { id: 'b' }],
      next: 'b',
    })
    expect(pageFromItems([{ id: 'a' }], 2).next).toBeNull()
  })

  test('mergePages keeps order and drops duplicate ids', () => {
    const pages = [
      { items: [{ id: 'c' }, { id: 'b' }] },
      { items: [{ id: 'b' }, { id: 'a' }] },
    ]

    expect(mergePages(pages).map((item) => item.id)).toEqual(['c', 'b', 'a'])
    expect(mergePages(undefined)).toEqual([])
  })
})