import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, Download, Quote } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'

import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { ApiError } from '../../lib/errors'
import {
  downloadConversationExport,
  type ConversationExportFormat,
} from '../../lib/exportConversation'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import { streamChat } from '../../lib/sse'
import type {
  AgentActivity,
  ChatUsage,
  Citation,
  ConversationDetail,
  KnowledgeBase,
} from '../../lib/types'
import { CitationDrawer } from './CitationDrawer'
import { Composer } from './Composer'
import { MessageItem, type DisplayMessage } from './MessageItem'
import { TraceDialog } from './TraceDialog'

interface PendingStream {
  user: string
  assistant: string
  citations: Citation[]
  activity: AgentActivity[]
  status: 'streaming' | 'failed' | 'cancelled'
  errorCode?: string
  usage: ChatUsage | null
}

export function ChatPage() {
  const { id } = useParams<{ id: string }>()
  const conversationId = id ?? ''
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const { t } = useI18n()

  const [pending, setPending] = useState<PendingStream | null>(null)
  const [input, setInput] = useState('')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerCitations, setDrawerCitations] = useState<Citation[]>([])
  const [confirmArchive, setConfirmArchive] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)
  const [traceRequestId, setTraceRequestId] = useState<string | null>(null)
  const [cooldown, setCooldown] = useState(0)
  const abortRef = useRef<AbortController | null>(null)
  const activityIdRef = useRef(0)
  const startedRef = useRef(false)
  const bottomRef = useRef<HTMLDivElement | null>(null)

  const conversation = useQuery({
    queryKey: ['conversation', conversationId],
    queryFn: () => apiRequest<ConversationDetail>(`/conversations/${conversationId}`),
    enabled: conversationId !== '',
  })
  const kbs = useQuery({
    queryKey: ['kbs'],
    queryFn: () => apiRequest<KnowledgeBase[]>('/knowledge-bases'),
    staleTime: 60_000,
  })

  const start = useCallback(
    async (content: string) => {
      if (conversationId === '') return
      setInput('')
      setPending({
        user: content,
        assistant: '',
        citations: [],
        activity: [],
        status: 'streaming',
        usage: null,
      })
      const controller = new AbortController()
      abortRef.current = controller
      let failedCode: string | null = null
      const appendActivity = (item: Omit<AgentActivity, 'id'>) => {
        activityIdRef.current += 1
        const entry: AgentActivity = { ...item, id: `activity-${activityIdRef.current}` }
        setPending((prev) =>
          prev ? { ...prev, activity: [...prev.activity, entry] } : prev,
        )
      }

      try {
        await streamChat({
          conversationId,
          content,
          signal: controller.signal,
          onEvent: (event) => {
            const data = event.data as Record<string, unknown> | null
            if (data === null) return
            const agent = String(data.agent ?? 'agent')
            const depth = typeof data.depth === 'number' ? data.depth : 0
            if (event.event === 'agent_start') {
              appendActivity({ type: 'agent_start', agent, depth })
            } else if (event.event === 'agent_end') {
              appendActivity({
                type: 'agent_end',
                agent,
                depth,
                status: String(data.status ?? 'completed'),
                duration_ms:
                  typeof data.duration_ms === 'number' ? data.duration_ms : undefined,
              })
            } else if (event.event === 'tool_call') {
              appendActivity({
                type: 'tool_call',
                agent,
                depth,
                tool: String(data.tool ?? ''),
                arguments: data.arguments as Record<string, unknown> | undefined,
              })
            } else if (event.event === 'tool_result') {
              appendActivity({
                type: 'tool_result',
                agent,
                depth,
                tool: String(data.tool ?? ''),
                ok: data.ok === true,
                output: String(data.output ?? ''),
                error_code:
                  data.error_code === null || data.error_code === undefined
                    ? null
                    : String(data.error_code),
                duration_ms:
                  typeof data.duration_ms === 'number' ? data.duration_ms : undefined,
              })
            } else if (event.event === 'citation') {
              setPending((prev) =>
                prev ? { ...prev, citations: [...prev.citations, data as unknown as Citation] } : prev,
              )
            } else if (event.event === 'delta') {
              setPending((prev) =>
                prev ? { ...prev, assistant: prev.assistant + String(data.text ?? '') } : prev,
              )
            } else if (event.event === 'usage') {
              setPending((prev) => (prev ? { ...prev, usage: data as unknown as ChatUsage } : prev))
            } else if (event.event === 'error') {
              failedCode = String(data.code ?? 'internal_error')
              setPending((prev) =>
                prev ? { ...prev, status: 'failed', errorCode: failedCode ?? undefined } : prev,
              )
            }
          },
        })

        if (failedCode === null) {
          await queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] })
          await queryClient.invalidateQueries({ queryKey: ['conversations'] })
          await queryClient.invalidateQueries({ queryKey: ['usage'] })
          setPending(null)
        }
      } catch (caught) {
        if (controller.signal.aborted) {
          setPending((prev) => (prev ? { ...prev, status: 'cancelled' } : prev))
          await queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] })
          setPending(null)
        } else {
          const code =
            caught instanceof ApiError ? (caught.code ?? `http_${caught.status}`) : 'network'
          if (caught instanceof ApiError && caught.status === 429) {
            setCooldown(caught.retryAfter ?? 60)
          }
          setPending((prev) => (prev ? { ...prev, status: 'failed', errorCode: code } : prev))
        }
      } finally {
        abortRef.current = null
      }
    },
    [conversationId, queryClient],
  )

  useEffect(() => {
    if (cooldown <= 0) return
    const timer = window.setInterval(() => {
      setCooldown((seconds) => Math.max(seconds - 1, 0))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [cooldown])

  useEffect(() => {
    const pendingMessage = (location.state as { pendingMessage?: string } | null)?.pendingMessage
    if (pendingMessage === undefined || startedRef.current) return
    startedRef.current = true
    navigate(location.pathname, { replace: true, state: null })
    void start(pendingMessage)
  }, [location, navigate, start])

  const serverMessages = conversation.data?.messages ?? []
  const messageCount = serverMessages.length
  const streamLength = pending?.assistant.length ?? 0

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [messageCount, streamLength, pending?.status])

  const lastAssistant = [...serverMessages]
    .reverse()
    .find((message) => message.role === 'assistant' && message.citations.length > 0)
  const latestCitations =
    pending !== null && pending.citations.length > 0
      ? pending.citations
      : (lastAssistant?.citations ?? [])

  const openCitations = (citations: Citation[]) => {
    setDrawerCitations(citations)
    setDrawerOpen(true)
  }

  const exportConversation = async (format: ConversationExportFormat) => {
    if (conversationId === '') return
    setExporting(true)
    setExportError(null)
    try {
      await downloadConversationExport(conversationId, format)
      setExportOpen(false)
    } catch (caught) {
      setExportError(t(errorTextKey(caught)))
    } finally {
      setExporting(false)
    }
  }

  const archive = async () => {
    if (conversationId === '') return
    try {
      await apiRequest(`/conversations/${conversationId}`, { method: 'DELETE' })
      await queryClient.invalidateQueries({ queryKey: ['conversations'] })
      navigate('/chat', { replace: true })
    } catch {
      setConfirmArchive(false)
    }
  }

  if (conversation.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner className="h-6 w-6 text-accent" />
      </div>
    )
  }

  if (conversation.isError) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3">
        <p className="text-sm text-ink-muted">{t('chat.loadError')}</p>
        <Button variant="secondary" onClick={() => void conversation.refetch()}>
          {t('common.retry')}
        </Button>
      </div>
    )
  }

  const streamMessages: DisplayMessage[] =
    pending !== null
      ? [
          {
            id: 'pending-user',
            role: 'user',
            content: pending.user,
            status: 'completed',
            citations: [],
          },
          {
            id: 'pending-assistant',
            role: 'assistant',
            content: pending.assistant,
            status: pending.status,
            citations: pending.citations,
            agentActivity: pending.activity,
            streaming: pending.status === 'streaming',
            errorCode: pending.errorCode,
            provider_id: conversation.data?.provider_id,
            model: conversation.data?.model,
            prompt_tokens: pending.usage?.prompt_tokens ?? null,
            completion_tokens: pending.usage?.completion_tokens ?? null,
          },
        ]
      : []

  const kbName = kbs.data?.find((kb) => kb.id === conversation.data?.kb_id)?.name

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border bg-surface px-4">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-ink">
            {conversation.data?.title || t('chat.newConversation')}
          </p>
          <p className="truncate text-xs text-ink-muted">
            {conversation.data?.provider_id} · {conversation.data?.model}
            {kbName !== undefined ? ` · ${kbName}` : ''}
            {conversation.data?.prompt_version_id !== null &&
            conversation.data?.prompt_version_id !== undefined
              ? ` · ${t('prompts.active')}`
              : ''}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {latestCitations.length > 0 && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => openCitations(latestCitations)}
            >
              <Quote className="h-3.5 w-3.5" />
              {t('chat.citations')} {latestCitations.length}
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            aria-label={t('chat.export')}
            onClick={() => {
              setExportError(null)
              setExportOpen(true)
            }}
          >
            <Download className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            aria-label={t('chat.archive')}
            onClick={() => setConfirmArchive(true)}
          >
            <Archive className="h-4 w-4" />
          </Button>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6">
          {messageCount === 0 && pending === null && (
            <p className="py-10 text-center text-sm text-ink-muted">{t('chat.emptyHint')}</p>
          )}
          {serverMessages.map((message) => (
            <MessageItem
              key={message.id}
              message={message}
              onOpenCitations={openCitations}
              onOpenTrace={setTraceRequestId}
            />
          ))}
          {streamMessages.map((message) =>
            message.role === 'assistant' ? (
              <MessageItem
                key={message.id}
                message={message}
                onOpenCitations={openCitations}
                onResend={
                  pending?.status === 'failed'
                    ? () => {
                        if (pending !== null) void start(pending.user)
                      }
                    : undefined
                }
              />
            ) : (
              <MessageItem key={message.id} message={message} onOpenCitations={openCitations} />
            ),
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="shrink-0 border-t border-border bg-canvas px-4 py-3">
        <div className="mx-auto w-full max-w-3xl">
          {cooldown > 0 && (
            <p role="status" className="mb-2 rounded-lg bg-warning/10 px-3 py-2 text-xs text-warning">
              {t('errors.rateLimitedWait', { seconds: cooldown })}
            </p>
          )}
          <Composer
            value={input}
            onValueChange={setInput}
            onSend={start}
            disabled={cooldown > 0}
            streaming={pending?.status === 'streaming'}
            onStop={() => abortRef.current?.abort()}
          />
        </div>
      </div>

      <CitationDrawer
        open={drawerOpen}
        citations={drawerCitations}
        onClose={() => setDrawerOpen(false)}
      />

      <TraceDialog requestId={traceRequestId} onClose={() => setTraceRequestId(null)} />

      <Dialog
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        title={t('chat.exportTitle')}
        footer={
          <Button variant="secondary" size="sm" onClick={() => setExportOpen(false)}>
            {t('common.cancel')}
          </Button>
        }
      >
        <p className="text-sm text-ink-muted">{t('chat.exportHint')}</p>
        {exportError !== null && (
          <p role="alert" className="mt-3 rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
            {exportError}
          </p>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          <Button
            size="sm"
            disabled={exporting}
            onClick={() => void exportConversation('markdown')}
          >
            <Download className="h-3.5 w-3.5" />
            {t('chat.exportMarkdown')}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            disabled={exporting}
            onClick={() => void exportConversation('json')}
          >
            <Download className="h-3.5 w-3.5" />
            {t('chat.exportJson')}
          </Button>
        </div>
      </Dialog>

      <Dialog
        open={confirmArchive}
        onClose={() => setConfirmArchive(false)}
        title={t('chat.archive')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setConfirmArchive(false)}>
              {t('common.cancel')}
            </Button>
            <Button variant="danger" size="sm" onClick={() => void archive()}>
              {t('common.confirm')}
            </Button>
          </>
        }
      >
        {t('chat.archiveConfirm')}
      </Dialog>
    </div>
  )
}