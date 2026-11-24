import { describe, expect, it } from 'vitest'

import {
  modelReasoningLevels,
  normalizeThinkingLevel,
  reasoningLevelsFor,
} from './chatModes'

describe('chat mode capabilities', () => {
  it('returns only standard when the model publishes no manifest', () => {
    expect(reasoningLevelsFor(undefined, undefined)).toEqual(['standard'])
  })

  it('derives standard and deep from the reasoning capability tag', () => {
    expect(reasoningLevelsFor(['chat', 'reasoning'], undefined)).toEqual([
      'standard',
      'deep',
    ])
  })

  it('honors explicitly declared levels in canonical order', () => {
    expect(reasoningLevelsFor(['chat', 'reasoning'], ['deep', 'fast'])).toEqual([
      'fast',
      'deep',
    ])
  })

  it('falls back to standard for a model without reasoning', () => {
    expect(
      modelReasoningLevels({
        provider_id: 'p',
        provider_name: 'Provider',
        model_id: 'm',
        display_name: 'Model',
        capabilities: ['chat'],
      }),
    ).toEqual(['standard'])
  })

  it('clamps an unsupported selection to standard', () => {
    expect(normalizeThinkingLevel('deep', ['standard'])).toBe('standard')
    expect(normalizeThinkingLevel('deep', ['standard', 'deep'])).toBe('deep')
  })
})