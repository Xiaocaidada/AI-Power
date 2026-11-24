import type { GenerationSettings } from './types'

export interface GenerationDraft {
  temperature: string
  maxTokens: string
  topP: string
}

function text(value: number | null | undefined): string {
  return value === null || value === undefined ? '' : String(value)
}

export function generationDraft(settings: GenerationSettings): GenerationDraft {
  return {
    temperature: text(settings.temperature),
    maxTokens: text(settings.max_tokens),
    topP: text(settings.top_p),
  }
}

function bounded(value: string, min: number, max: number): number | undefined {
  if (value.trim() === '') return undefined
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return undefined
  return Math.max(min, Math.min(max, parsed))
}

export function buildGenerationSettings(
  draft: GenerationDraft,
): GenerationSettings {
  const result: GenerationSettings = {}
  const temperature = bounded(draft.temperature, 0, 2)
  const maxTokens = bounded(draft.maxTokens, 1, 32768)
  const topP = bounded(draft.topP, 0, 1)
  if (temperature !== undefined) result.temperature = temperature
  if (maxTokens !== undefined) result.max_tokens = Math.round(maxTokens)
  if (topP !== undefined) result.top_p = topP
  return result
}