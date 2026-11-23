import {
  Check,
  Copy,
  FileText,
  Image as ImageIcon,
  Pencil,
  Quote,
  RotateCcw,
  ThumbsDown,
  ThumbsUp,
} from 'lucide-react'
import { useState } from 'react'
import ReactMarkdown from 'react-markdown'

import { Badge } from '../../components/ui/badge'
import { downloadChatAttachment } from '../../lib/attachments'
import { formatTime } from '../../lib/format'
import { useI18n } from '../../lib/i18n'
import type {
  AgentActivity,
  ChatAttachment,
  Citation,
  MessageFeedback,
  MessageMemoryRef,
} from '../../lib/types'

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
  memory_refs?: MessageMemoryRef[]
  reply_to_message_id?: string | null
  feedback?: MessageFeedback | null
  agentActivity?: AgentActivity[]
  created_at?: string
  attachments?: ChatAttachment[]
}

interface MessageItemProps {
  message: DisplayMessage
  onOpenCitations: (citations: Citation[]) => void
  onResend?: () => void
  onOpenTrace?: (requestId: string) => void
  onRegenerate?: (messageId: string) => void
  onFeedback?: (messageId: string, rating: 'up' | 'down') => void
  onEdit?: (message: DisplayMessage) => void
}

export function MessageItem({
  message,
  onOpenCitations,
  onResend,
  onOpenTrace,
  onRegenerate,
  onFeedback,
  onEdit,
}: MessageItemProps) {
  const { t, language } = useI18n()
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
      <div className="group flex flex-col items-end gap-1">
        <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-surface-muted px-4 py-2.5 text-sm leading-6 text-ink">
          {message.content}
        </div>
        {(message.attachments ?? []).length > 0 && (
          <div className="flex max-w-[80%] flex-wrap justify-end gap-1.5">
            {(message.attachments ?? []).map((attachment) => (
              <button
                key={attachment.id}
                type="button"
                onClick={() => void downloadChatAttachment(attachment)}
                className="inline-flex max-w-[14rem] items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 py-1 text-[11px] text-ink-muted hover:text-ink"
              >
                {attachment.kind === 'image' ? (
                  <ImageIcon className="h-3 w-3" />
                ) : (
                  <FileText className="h-3 w-3" />
                )}
                <span className="truncate">{attachment.filename}</span>
              </button>
            ))}
          </div>
        )}
        <div className="flex items-center gap-2 text-[11px] text-ink-muted opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
          {message.created_at !== undefined && (
            <span>{formatTime(message.created_at, language)}</span>
          )}
          <button
            type="button"
            className="inline-flex items-center gap-1 hover:text-ink"
            onClick={() => void copy()}
          >
            {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
            {copied ? t('common.copied') : t('common.copy')}
          </button>
          {onEdit !== undefined && message.status === 'completed' && (
            <button
              type="button"
              className="inline-flex items-center gap-1 hover:text-ink"
              onClick={() => onEdit(message)}
            >
              <Pencil className="h-3 w-3" />
              {t('chat.editMessage')}
            </button>
          )}
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
  const hasMemories = (message.memory_refs?.length ?? 0) > 0
  const hasDetails =
    (message.model !== null && message.model !== undefined) ||
    hasTokens ||
    hasMemories

  return (
    <div className="group space-y-2">
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

      {message.content !== '' && (
        <div className="flex flex-wrap items-center gap-3 text-[11px] text-ink-muted">
          <button
            type="button"
            className="inline-flex items-center gap-1 hover:text-ink"
            onClick={() => void copy()}
          >
            {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
            {copied ? t('common.copied') : t('common.copy')}
          </button>
          {message.status === 'completed' && onRegenerate !== undefined && (
            <button
              type="button"
              className="inline-flex items-center gap-1 hover:text-ink"
              onClick={() => onRegenerate(message.id)}
            >
              <RotateCcw className="h-3 w-3" />
              {t('chat.regenerate')}
            </button>
          )}
          {message.status === 'completed' && onFeedback !== undefined && (
            <span className="inline-flex items-center gap-1">
              <button
                type="button"
                aria-label={t('chat.feedbackUp')}
                title={t('chat.feedbackUp')}
                className={
                  message.feedback?.rating === 'up' ? 'text-accent' : 'hover:text-ink'
                }
                onClick={() => onFeedback(message.id, 'up')}
              >
                <ThumbsUp className="h-3 w-3" />
              </button>
              <button
                type="button"
                aria-label={t('chat.feedbackDown')}
                title={t('chat.feedbackDown')}
                className={
                  message.feedback?.rating === 'down' ? 'text-danger' : 'hover:text-ink'
                }
                onClick={() => onFeedback(message.id, 'down')}
              >
                <ThumbsDown className="h-3 w-3" />
              </button>
            </span>
          )}
          {message.created_at !== undefined && (
            <span className="ml-auto opacity-0 transition-opacity group-hover:opacity-100">
              {formatTime(message.created_at, language)}
            </span>
          )}
        </div>
      )}

      {(hasDetails ||
        (message.request_id !== null &&
          message.request_id !== undefined &&
          onOpenTrace !== undefined)) && (
        <details className="text-[11px] text-ink-muted">
          <summary className="cursor-pointer select-none hover:text-ink">
            {t('chat.runDetails')}
          </summary>
          <div className="mt-1 flex flex-wrap items-center gap-3">
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
          {hasMemories && (
            <div className="mt-1 flex flex-wrap items-center gap-1">
              <span>{t('chat.memoryUsed')}:</span>
              {(message.memory_refs ?? []).map((ref) => (
                <span
                  key={ref.id}
                  className="rounded-full bg-surface-muted px-2 py-0.5 text-[10px] text-ink-muted"
                  title={`${ref.category} · ${ref.relevance}`}
                >
                  {ref.title || ref.id.slice(0, 8)}
                </span>
              ))}
            </div>
          )}
        </details>
      )}
    </div>
  )
}