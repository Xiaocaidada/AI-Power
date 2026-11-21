import { Check, Copy, Quote } from 'lucide-react'
import { useState } from 'react'
import ReactMarkdown from 'react-markdown'

import { Badge } from '../../components/ui/badge'
import { useI18n } from '../../lib/i18n'
import type { AgentActivity, Citation } from '../../lib/types'

export interface DisplayMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  status: string
  citations: Citation[]
  streaming?: boolean
  errorCode?: string
  provider_id?: string | null
  model?: string | null
  prompt_tokens?: number | null
  completion_tokens?: number | null
  request_id?: string | null
  agentActivity?: AgentActivity[]
}

interface MessageItemProps {
  message: DisplayMessage
  onOpenCitations: (citations: Citation[]) => void
  onResend?: () => void
  onOpenTrace?: (requestId: string) => void
}

export function MessageItem({
  message,
  onOpenCitations,
  onResend,
  onOpenTrace,
}: MessageItemProps) {
  const { t } = useI18n()
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }

  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-surface-muted px-4 py-2.5 text-sm leading-6 text-ink">
          {message.content}
        </div>
      </div>
    )
  }

  const interrupted =
    message.status === 'cancelled' || (message.status === 'streaming' && !message.streaming)
  const failed = message.status === 'failed'
  const hasTokens =
    message.prompt_tokens !== null && message.prompt_tokens !== undefined
      ? true
      : message.completion_tokens !== null && message.completion_tokens !== undefined

  return (
    <div className="space-y-2">
      {message.content !== '' &&
        (message.streaming ? (
          <p className="whitespace-pre-wrap text-[15px] leading-7 text-ink">
            {message.content}
            <span className="ml-0.5 inline-block h-4 w-[2px] animate-pulse bg-accent align-text-bottom" />
          </p>
        ) : (
          <div className="markdown text-[15px] text-ink">
            <ReactMarkdown>{message.content}</ReactMarkdown>
          </div>
        ))}

      {message.streaming && message.content === '' && (
        <p className="text-sm text-ink-muted">{t('chat.generating')}</p>
      )}

      {interrupted && <Badge tone="warning">{t('chat.interrupted')}</Badge>}

      {failed && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
          <span>{t('chat.failed')}</span>
          {message.errorCode !== undefined && (
            <code className="font-mono text-xs opacity-80">{message.errorCode}</code>
          )}
          {onResend !== undefined && (
            <button
              type="button"
              className="ml-auto text-xs font-medium underline underline-offset-2"
              onClick={onResend}
            >
              {t('chat.resend')}
            </button>
          )}
        </div>
      )}

      {message.agentActivity !== undefined && message.agentActivity.length > 0 && (
        <details className="rounded-lg border border-border bg-surface-muted/40 px-3 py-2">
          <summary className="cursor-pointer select-none text-xs font-medium text-ink-muted">
            {t('chat.agentFlow', {
              count: message.agentActivity.filter((item) => item.type === 'tool_result').length,
            })}
          </summary>
          <ul className="mt-2 space-y-1 text-xs text-ink-muted">
            {message.agentActivity.map((item) => (
              <li
                key={item.id}
                className={item.ok === false || item.status === 'failed' ? 'text-danger' : ''}
              >
                {item.type === 'agent_start' && t('chat.agentStarted', { agent: item.agent })}
                {item.type === 'agent_end' &&
                  (item.status === 'failed'
                    ? t('chat.agentFailed', { agent: item.agent })
                    : t('chat.agentFinished', {
                        agent: item.agent,
                        ms: Math.round(item.duration_ms ?? 0),
                      }))}
                {item.type === 'tool_call' && (
                  <span className="font-mono">
                    {item.agent} · {item.tool}
                  </span>
                )}
                {item.type === 'tool_result' &&
                  (item.ok === false
                    ? t('chat.toolFailed', { tool: item.tool ?? '', code: item.error_code ?? '' })
                    : t('chat.toolDone', {
                        tool: item.tool ?? '',
                        ms: Math.round(item.duration_ms ?? 0),
                      }))}
              </li>
            ))}
          </ul>
        </details>
      )}

      {message.citations.length > 0 && (
        <button
          type="button"
          onClick={() => onOpenCitations(message.citations)}
          className="inline-flex items-center gap-1.5 rounded-full bg-citation-soft px-2.5 py-1 text-xs font-medium text-citation hover:bg-citation-soft/70"
        >
          <Quote className="h-3 w-3" />
          {t('chat.citations')} {message.citations.length}
        </button>
      )}

      {(message.provider_id !== null && message.provider_id !== undefined) ||
      hasTokens ||
      message.content !== '' ? (
        <div className="flex flex-wrap items-center gap-3 text-[11px] text-ink-muted">
          {message.model !== null && message.model !== undefined && (
            <span className="font-mono">
              {message.provider_id} · {message.model}
            </span>
          )}
          {hasTokens && (
            <span>
              {t('chat.tokens', {
                prompt: message.prompt_tokens ?? 0,
                completion: message.completion_tokens ?? 0,
              })}
            </span>
          )}
          {message.content !== '' && (
            <button
              type="button"
              className="inline-flex items-center gap-1 hover:text-ink"
              onClick={() => void copy()}
            >
              {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
              {copied ? t('common.copied') : t('common.copy')}
            </button>
          )}
          {message.request_id !== null &&
            message.request_id !== undefined &&
            onOpenTrace !== undefined && (
              <button
                type="button"
                className="inline-flex items-center gap-1 hover:text-ink"
                onClick={() => onOpenTrace(message.request_id as string)}
              >
                {t('trace.view')}
              </button>
            )}
        </div>
      ) : null}
    </div>
  )
}