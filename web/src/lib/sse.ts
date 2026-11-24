import { API_BASE } from './config'
import { toApiError } from './errors'
import { getAccessToken } from './tokens'
import type { ChatMode, ChatModeMeta } from './types'
import { getActiveWorkspaceId } from './workspace'

export interface SseEvent {
  event: string
  data: unknown
  id?: string
}

export type SseHandler = (event: SseEvent) => void

export class SseParser {
  private buffer = ''

  constructor(private readonly onEvent: SseHandler) {}

  push(chunk: string): void {
    this.buffer = (this.buffer + chunk).replace(/\r\n/g, '\n')
    let boundary = this.buffer.indexOf('\n\n')
    while (boundary !== -1) {
      this.parseBlock(this.buffer.slice(0, boundary))
      this.buffer = this.buffer.slice(boundary + 2)
      boundary = this.buffer.indexOf('\n\n')
    }
  }

  flush(): void {
    const rest = this.buffer
    this.buffer = ''
    if (rest.trim() !== '') this.parseBlock(rest)
  }

  private parseBlock(block: string): void {
    let event = 'message'
    let id: string | undefined
    const dataLines: string[] = []
    for (const line of block.split('\n')) {
      if (line === '' || line.startsWith(':')) continue
      const colon = line.indexOf(':')
      const field = colon === -1 ? line : line.slice(0, colon)
      let value = colon === -1 ? '' : line.slice(colon + 1)
      if (value.startsWith(' ')) value = value.slice(1)
      if (field === 'event') event = value
      else if (field === 'data') dataLines.push(value)
      else if (field === 'id') id = value
    }
    if (dataLines.length === 0) return
    const raw = dataLines.join('\n')
    let data: unknown = raw
    try {
      data = JSON.parse(raw)
    } catch {
      data = raw
    }
    this.onEvent({ event, data, id })
  }
}

export interface StreamChatOptions {
  conversationId: string
  content: string
  attachmentIds?: string[]
  mode?: ChatMode
  modeMeta?: ChatModeMeta
  signal?: AbortSignal
  onEvent: SseHandler
}


async function readSse(response: Response, onEvent: SseHandler): Promise<void> {
  if (!response.ok) throw await toApiError(response)
  if (response.body === null) throw new Error('Streaming is not supported by this browser')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  const parser = new SseParser(onEvent)
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    parser.push(decoder.decode(value, { stream: true }))
  }
  parser.flush()
}

async function streamResponse(
  url: string,
  body: unknown,
  signal: AbortSignal | undefined,
  onEvent: SseHandler,
): Promise<void> {
  const token = getAccessToken()
  const workspaceId = getActiveWorkspaceId()
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token !== null ? { Authorization: `Bearer ${token}` } : {}),
      ...(workspaceId !== null ? { 'X-Workspace-Id': workspaceId } : {}),
    },
    body: JSON.stringify(body),
    signal,
  })
  await readSse(response, onEvent)
}

const RUN_TERMINAL_EVENTS = new Set(['workflow_end', 'collaboration_end'])
const RUN_RECONNECT_LIMIT = 5

export interface StreamRunOptions {
  path: string
  after?: number
  signal?: AbortSignal
  onEvent: SseHandler
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export async function streamRunEvents({
  path,
  after = 0,
  signal,
  onEvent,
}: StreamRunOptions): Promise<void> {
  let cursor = after
  let attempts = 0
  while (!signal?.aborted) {
    const token = getAccessToken()
    let terminal = false
    try {
      const response = await fetch(`${API_BASE}${path}?after=${cursor}`, {
        method: 'GET',
        headers: token !== null ? { Authorization: `Bearer ${token}` } : {},
        signal,
      })
      await readSse(response, (event) => {
        if (event.id !== undefined) {
          const parsed = Number(event.id)
          if (Number.isFinite(parsed)) cursor = parsed
        }
        if (RUN_TERMINAL_EVENTS.has(event.event)) terminal = true
        onEvent(event)
      })
    } catch (error) {
      if (signal?.aborted) throw error
      attempts += 1
      if (attempts > RUN_RECONNECT_LIMIT) throw error
      await wait(500 * attempts)
      continue
    }
    if (terminal || signal?.aborted) return
    attempts += 1
    if (attempts > RUN_RECONNECT_LIMIT) return
    await wait(500 * attempts)
  }
}


export async function streamChat({
  conversationId,
  content,
  attachmentIds = [],
  mode,
  modeMeta,
  signal,
  onEvent,
}: StreamChatOptions): Promise<void> {
  return streamResponse(
    `${API_BASE}/conversations/${conversationId}/messages`,
    {
      content,
      attachment_ids: attachmentIds,
      ...(mode !== undefined ? { mode } : {}),
      ...(modeMeta !== undefined ? { mode_meta: modeMeta } : {}),
    },
    signal,
    onEvent,
  )
}

export interface StreamBuilderTurnOptions {
  sessionId: string
  body: Record<string, unknown>
  signal?: AbortSignal
  onEvent: SseHandler
}

export async function streamBuilderTurn({
  sessionId,
  body,
  signal,
  onEvent,
}: StreamBuilderTurnOptions): Promise<void> {
  return streamResponse(
    `${API_BASE}/agent-builder/sessions/${sessionId}/messages/stream`,
    body,
    signal,
    onEvent,
  )
}

export interface StreamRegenerateOptions {
  conversationId: string
  messageId: string
  signal?: AbortSignal
  onEvent: SseHandler
}

export async function streamRegenerate({
  conversationId,
  messageId,
  signal,
  onEvent,
}: StreamRegenerateOptions): Promise<void> {
  return streamResponse(
    `${API_BASE}/conversations/${conversationId}/messages/${messageId}/regenerate`,
    {},
    signal,
    onEvent,
  )
}

export interface StreamReplyOptions {
  conversationId: string
  messageId: string
  signal?: AbortSignal
  onEvent: SseHandler
}

export async function streamReply({
  conversationId,
  messageId,
  signal,
  onEvent,
}: StreamReplyOptions): Promise<void> {
  return streamResponse(
    `${API_BASE}/conversations/${conversationId}/messages/${messageId}/reply`,
    {},
    signal,
    onEvent,
  )
}

export interface StreamPromptOutputOptions {
  experimentId: string
  outputId: string
  signal?: AbortSignal
  onEvent: SseHandler
}

export async function streamPromptOutput({
  experimentId,
  outputId,
  signal,
  onEvent,
}: StreamPromptOutputOptions): Promise<void> {
  return streamResponse(
    `${API_BASE}/prompt-lab/experiments/${experimentId}/outputs/${outputId}/stream`,
    {},
    signal,
    onEvent,
  )
}

export interface StreamArenaResponseOptions {
  roundId: string
  responseId: string
  signal?: AbortSignal
  onEvent: SseHandler
}

export async function streamArenaResponse({
  roundId,
  responseId,
  signal,
  onEvent,
}: StreamArenaResponseOptions): Promise<void> {
  return streamResponse(
    `${API_BASE}/arena/rounds/${roundId}/responses/${responseId}/stream`,
    {},
    signal,
    onEvent,
  )
}