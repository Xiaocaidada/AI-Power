import type {
  ChatMode,
  ModelEntry,
  PersonalModel,
  ThinkingLevel,
  ThinkingLevelSpec,
} from './types'

export const CHAT_MODES: ChatMode[] = [
  'chat',
  'web_search',
  'deep_research',
  'study',
  'agent',
]

export const THINKING_LEVELS: ThinkingLevel[] = ['fast', 'standard', 'deep']

const MODE_LABEL_KEYS: Record<ChatMode, string> = {
  chat: 'chat.modeChat',
  web_search: 'chat.modeWebSearch',
  deep_research: 'chat.modeDeepResearch',
  study: 'chat.modeStudy',
  agent: 'chat.modeAgent',
}

const MODE_HINT_KEYS: Record<ChatMode, string> = {
  chat: 'chat.modeChatHint',
  web_search: 'chat.modeWebSearchHint',
  deep_research: 'chat.modeDeepResearchHint',
  study: 'chat.modeStudyHint',
  agent: 'chat.modeAgentHint',
}

const THINKING_LABEL_KEYS: Record<string, string> = {
  fast: 'chat.thinkingFast',
  standard: 'chat.thinkingStandard',
  deep: 'chat.thinkingDeep',
  minimal: 'chat.thinkingMinimal',
  low: 'chat.thinkingLow',
  medium: 'chat.thinkingMedium',
  high: 'chat.thinkingHigh',
  xhigh: 'chat.thinkingXhigh',
  max: 'chat.thinkingMax',
}

export function modeLabelKey(mode: ChatMode): string {
  return MODE_LABEL_KEYS[mode]
}

export function modeHintKey(mode: ChatMode): string {
  return MODE_HINT_KEYS[mode]
}

export function thinkingLabelKey(level: ThinkingLevel): string | null {
  return THINKING_LABEL_KEYS[level] ?? null
}

export function reasoningLevelsFor(
  capabilities: string[] | undefined,
  declared: string[] | undefined,
): ThinkingLevel[] {
  const explicit: string[] = []
  for (const item of declared ?? []) {
    const level = item.trim().toLowerCase()
    if (level !== '' && !explicit.includes(level)) explicit.push(level)
  }
  if (explicit.length > 0) return explicit
  if (capabilities?.includes('reasoning')) return ['standard', 'deep']
  return ['standard']
}

function declaredThinkingLevels(
  model: ModelEntry | PersonalModel,
): string[] | undefined {
  const configured = model.thinking_config ?? []
  if (configured.length > 0) return configured.map((item) => item.id)
  return model.reasoning_levels
}

export function modelReasoningLevels(
  model: ModelEntry | PersonalModel | undefined,
): ThinkingLevel[] {
  if (model === undefined) return ['standard']
  const capabilities =
    'capabilities' in model ? model.capabilities : undefined
  return reasoningLevelsFor(capabilities, declaredThinkingLevels(model))
}

export function modelThinkingSpecs(
  model: ModelEntry | PersonalModel | undefined,
): ThinkingLevelSpec[] {
  if (model === undefined) return []
  const configured = model.thinking_config ?? []
  if (configured.length > 0) return configured
  return (model.reasoning_levels ?? []).map((id) => ({ id, label: '' }))
}

export function normalizeThinkingLevel(
  current: ThinkingLevel,
  supported: ThinkingLevel[],
): ThinkingLevel {
  if (supported.includes(current)) return current
  return supported[0] ?? 'standard'
}