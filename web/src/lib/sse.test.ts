import { describe, expect, it } from 'vitest'

import { SseParser, type SseEvent } from './sse'

function collect(chunks: string[]): SseEvent[] {
  const events: SseEvent[] = []
  const parser = new SseParser((event) => events.push(event))
  for (const chunk of chunks) parser.push(chunk)
  parser.flush()
  return events
}

describe('SseParser', () => {
  it('reassembles an event split across chunks', () => {
    const events = collect(['event: delta\nda', 'ta: {"text":"你', '好"}\n\n'])

    expect(events).toEqual([{ event: 'delta', data: { text: '你好' } }])
  })

  it('handles CRLF, comments, and multiple events in one chunk', () => {
    const events = collect([
      ': keep-alive\r\nevent: meta\r\ndata: {"message_id":"m1"}\r\n\r\n',
      'event: citation\r\ndata: {"index":1}\r\n\r\n',
    ])

    expect(events).toEqual([
      { event: 'meta', data: { message_id: 'm1' } },
      { event: 'citation', data: { index: 1 } },
    ])
  })

  it('joins multi-line data and keeps non-JSON payloads as strings', () => {
    const events = collect(['event: note\ndata: first\ndata: second\n\n'])

    expect(events).toEqual([{ event: 'note', data: 'first\nsecond' }])
  })

  it('flushes a trailing block without the final blank line', () => {
    const events = collect(['event: done\ndata: {"finish_reason":"stop"}'])

    expect(events).toEqual([{ event: 'done', data: { finish_reason: 'stop' } }])
  })
})