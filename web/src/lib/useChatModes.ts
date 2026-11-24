import { useQuery } from '@tanstack/react-query'

import { apiRequest } from './http'
import type { ChatMode, ChatModesResponse } from './types'

const FALLBACK_IMPLEMENTED: ChatMode[] = ['chat', 'agent']

export function useChatModes() {
  return useQuery({
    queryKey: ['chat-modes'],
    queryFn: () => apiRequest<ChatModesResponse>('/chat/modes'),
    staleTime: Infinity,
  })
}

export function isModeImplemented(
  mode: ChatMode,
  catalog: ChatModesResponse | undefined,
): boolean {
  const entry = catalog?.modes.find((item) => item.id === mode)
  if (entry !== undefined) return entry.implemented
  return FALLBACK_IMPLEMENTED.includes(mode)
}