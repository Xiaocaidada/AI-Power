import { describe, expect, it } from 'vitest'

import { conversationTimeGroup, groupConversationsByTime } from './conversationGroups'

const now = new Date('2026-11-22T12:00:00')

describe('conversationTimeGroup', () => {
  it('classifies today, yesterday, this week and older timestamps', () => {
    expect(conversationTimeGroup('2026-11-22T08:00:00', now)).toBe('today')
    expect(conversationTimeGroup('2026-11-21T23:59:00', now)).toBe('yesterday')
    expect(conversationTimeGroup('2026-11-18T10:00:00', now)).toBe('week')
    expect(conversationTimeGroup('2026-11-01T10:00:00', now)).toBe('earlier')
  })

  it('falls back to earlier for missing or invalid timestamps', () => {
    expect(conversationTimeGroup(null, now)).toBe('earlier')
    expect(conversationTimeGroup(undefined, now)).toBe('earlier')
    expect(conversationTimeGroup('not-a-date', now)).toBe('earlier')
  })
})

describe('groupConversationsByTime', () => {
  it('keeps input order inside groups and drops empty groups', () => {
    const groups = groupConversationsByTime(
      [
        { id: 'a', created_at: '2026-11-22T09:00:00' },
        { id: 'b', created_at: '2026-11-20T09:00:00', updated_at: '2026-11-22T10:00:00' },
        { id: 'c', created_at: '2026-11-10T09:00:00' },
      ],
      now,
    )

    expect(groups.map((group) => group.key)).toEqual(['today', 'earlier'])
    expect(groups[0]?.items.map((item) => item.id)).toEqual(['a', 'b'])
    expect(groups[1]?.items.map((item) => item.id)).toEqual(['c'])
  })
})