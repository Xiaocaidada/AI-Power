import { afterEach, describe, expect, test } from 'vitest'

import { applyTheme, storedTheme } from './theme'

describe('theme helpers', () => {
  afterEach(() => {
    localStorage.clear()
    document.documentElement.classList.remove('dark')
    delete document.documentElement.dataset.theme
  })

  test('applyTheme stores the theme and toggles the dark class', () => {
    applyTheme('dark')

    expect(localStorage.getItem('ai_power_theme')).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  test('storedTheme prefers a saved value', () => {
    localStorage.setItem('ai_power_theme', 'light')

    expect(storedTheme()).toBe('light')
  })
})