import { describe, expect, it } from 'vitest'

import { en } from '../locales/en'
import { zh } from '../locales/zh'

function flattenKeys(value: unknown, prefix = ''): string[] {
  if (value === null || typeof value !== 'object') return [prefix]
  return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) =>
    flattenKeys(child, prefix === '' ? key : `${prefix}.${key}`),
  )
}

describe('i18n dictionaries', () => {
  it('have identical key sets', () => {
    expect(flattenKeys(en).sort()).toEqual(flattenKeys(zh).sort())
  })
})