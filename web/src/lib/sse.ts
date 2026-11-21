import { API_BASE } from './config'
import { toApiError } from './errors'
import { getAccessToken } from './tokens'

export interface SseEvent {
  event: string
  data: unknown
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
    const dataLines: string[] = []
    for (const line of block.split('\n')) {
      if (line === '' || line.startsWith(':')) continue
      const colon = line.indexOf(':')
      const field = colon === -1 ? line : line.slice(0, colon)
      let value = colon === -1 ? '' : line.slice(colon + 1)
      if (value.startsWith(' ')) value = value.slice(1)
      if (field === 'event') event = value
      else if (field === 'data') dataLines.push(value)
    }
    if (dataLines.length === 0) return
    const raw = dataLines.join('\n')
    let data: unknown = raw
    try {
      data = JSON.parse(raw)
    } catch {
      data = raw
    }
    this.onEvent({ event, data })
  }
}

export interface StreamChatOptions {
  conversationId: string
  content: string
  signal?: AbortSignal
  onEvent: SseHandler
}

export interface StreamWorkflowOptions {
  workflowId: string
  input: string
  kbId?: string | null
  version?: number
  signal?: AbortSignal
  onEvent: SseHandler
}

async function streamResponse(
  url: string,
  body: unknown,
  signal: AbortSignal | undefined,
  onEvent: SseHandler,
): Promise<void> {
  const token = getAccessToken()
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token !== null ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  })
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

export async function streamWorkflowRun({
  workflowId,
  input,
  kbId,
  version,
  signal,
  onEvent,
}: StreamWorkflowOptions): Promise<void> {
  return streamResponse(
    `${API_BASE}/workflows/${workflowId}/runs`,
    { input, kb_id: kbId ?? null, version: version ?? null },
    signal,
    onEvent,
  )
}

export async function streamChat({
  conversationId,
  content,
  signal,
  onEvent,
}: StreamChatOptions): Promise<void> {
  return streamResponse(
    `${API_BASE}/conversations/${conversationId}/messages`,
    { content },
    signal,
    onEvent,
  )
}