import { describe, expect, it } from 'vitest'

import {
  modelReasoningLevels,
  modelThinkingSpecs,
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

  it('honors user-configured levels in their declared order', () => {
    expect(reasoningLevelsFor(['chat', 'reasoning'], ['deep', 'fast'])).toEqual([
      'deep',
      'fast',
    ])
    expect(reasoningLevelsFor(['chat', 'reasoning'], ['minimal', 'xhigh'])).toEqual([
      'minimal',
      'xhigh',
    ])
  })

  it('uses configured thinking labels when present', () => {
    const model = {
      provider_id: 'p',
      provider_name: 'Provider',
      model_id: 'm',
      display_name: 'Model',
      capabilities: ['chat', 'reasoning'],
      reasoning_levels: ['low', 'high'],
      thinking_config: [
        { id: 'low', label: '轻量' },
        { id: 'high', label: '深度' },
      ],
    }
    expect(modelReasoningLevels(model)).toEqual(['low', 'high'])
    expect(modelThinkingSpecs(model)).toEqual([
      { id: 'low', label: '轻量' },
      { id: 'high', label: '深度' },
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

  it('clamps an unsupported selection to the first supported level', () => {
    expect(normalizeThinkingLevel('deep', ['standard'])).toBe('standard')
    expect(normalizeThinkingLevel('deep', ['standard', 'deep'])).toBe('deep')
    expect(normalizeThinkingLevel('standard', ['low', 'high'])).toBe('low')
  })
})