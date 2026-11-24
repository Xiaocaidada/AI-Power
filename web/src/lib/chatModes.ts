import type { ChatMode, ModelEntry, PersonalModel, ThinkingLevel } from './types'

export const CHAT_MODES: ChatMode[] = [
  'chat',
  'web_search',
  'deep_research',
  'study',
  'agent',
]

export const THINKING_LEVELS: ThinkingLevel[] = ['fast', 'standard', 'deep']

const VALID_LEVELS = new Set<string>(THINKING_LEVELS)

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

const THINKING_LABEL_KEYS: Record<ThinkingLevel, string> = {
  fast: 'chat.thinkingFast',
  standard: 'chat.thinkingStandard',
  deep: 'chat.thinkingDeep',
}

export function modeLabelKey(mode: ChatMode): string {
  return MODE_LABEL_KEYS[mode]
}

export function modeHintKey(mode: ChatMode): string {
  return MODE_HINT_KEYS[mode]
}

export function thinkingLabelKey(level: ThinkingLevel): string {
  return THINKING_LABEL_KEYS[level]
}

export function reasoningLevelsFor(
  capabilities: string[] | undefined,
  declared: string[] | undefined,
): ThinkingLevel[] {
  const explicit = (declared ?? []).filter((item): item is ThinkingLevel =>
    VALID_LEVELS.has(item),
  )
  if (explicit.length > 0) {
    return THINKING_LEVELS.filter((level) => explicit.includes(level))
  }
  if (capabilities?.includes('reasoning')) return ['standard', 'deep']
  return ['standard']
}

export function modelReasoningLevels(
  model: ModelEntry | PersonalModel | undefined,
): ThinkingLevel[] {
  if (model === undefined) return ['standard']
  const capabilities =
    'capabilities' in model ? model.capabilities : undefined
  return reasoningLevelsFor(capabilities, model.reasoning_levels)
}

export function normalizeThinkingLevel(
  current: ThinkingLevel,
  supported: ThinkingLevel[],
): ThinkingLevel {
  return supported.includes(current) ? current : 'standard'
}