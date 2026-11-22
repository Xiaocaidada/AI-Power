import { describe, expect, it } from 'vitest'

import { formatBytes, formatTime } from './format'

describe('formatTime', () => {
  it('renders a zero-padded local time', () => {
    const value = new Date(2026, 10, 22, 9, 5).toISOString()
    expect(formatTime(value, 'en')).toBe('09:05')
  })
})

describe('formatBytes', () => {
  it('formats bytes, kilobytes and megabytes', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(1536)).toBe('1.5 KB')
    expect(formatBytes(20 * 1024 * 1024)).toBe('20 MB')
  })
})