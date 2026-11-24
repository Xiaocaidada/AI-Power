import { describe, expect, test } from 'vitest'

import {
  buildGenerationSettings,
  generationDraft,
} from './agentSettings'

describe('agent generation settings', () => {
  test('round-trips stored values into editable text', () => {
    expect(
      generationDraft({ temperature: 0.4, max_tokens: 2048, top_p: 0.9 }),
    ).toEqual({ temperature: '0.4', maxTokens: '2048', topP: '0.9' })
  })

  test('omits blank fields and clamps to server limits', () => {
    expect(
      buildGenerationSettings({
        temperature: '9',
        maxTokens: '999999',
        topP: '-2',
      }),
    ).toEqual({ temperature: 2, max_tokens: 32768, top_p: 0 })
    expect(
      buildGenerationSettings({ temperature: '', maxTokens: '', topP: '' }),
    ).toEqual({})
  })

  test('ignores non-numeric values', () => {
    expect(
      buildGenerationSettings({
        temperature: 'hot',
        maxTokens: 'many',
        topP: 'high',
      }),
    ).toEqual({})
  })
})