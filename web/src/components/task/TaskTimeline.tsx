import { useI18n } from '../../lib/i18n'
import type { TaskEvent } from '../../lib/types'

function payloadSummary(payload: Record<string, unknown>): string {
  for (const key of ['title', 'summary', 'tool', 'section', 'question', 'status', 'message']) {
    const value = payload[key]
    if (typeof value === 'string' && value.trim() !== '') return value.slice(0, 200)
  }
  if (typeof payload.artifacts === 'number') return `artifacts: ${payload.artifacts}`
  if (typeof payload.sources === 'number') return `sources: ${payload.sources}`
  if (typeof payload.count === 'number') return `count: ${payload.count}`
  return ''
}

export function TaskTimeline({ events }: { events: TaskEvent[] }) {
  const { t } = useI18n()
  if (events.length === 0) {
    return <p className="text-sm text-ink-muted">{t('tasks.noEvents')}</p>
  }
  return (
    <ol className="space-y-1.5">
      {events.map((event) => {
        const summary = payloadSummary(event.payload)
        return (
          <li
            key={event.seq}
            className="flex flex-wrap items-baseline gap-2 rounded-lg border border-border/70 px-3 py-2 text-xs"
          >
            <span className="w-8 shrink-0 text-right font-mono text-ink-muted">
              {event.seq}
            </span>
            <span className="font-medium text-ink">{event.event}</span>
            {summary !== '' && (
              <span className="min-w-0 flex-1 truncate text-ink-muted">{summary}</span>
            )}
          </li>
        )
      })}
    </ol>
  )
}