import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Archive,
  Download,
  Link2,
  MoreHorizontal,
  Quote,
  SlidersHorizontal,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'

import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { Textarea } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { uploadChatAttachment } from '../../lib/attachments'
import {
  THINKING_LEVELS,
  modelReasoningLevels,
  modeLabelKey,
  normalizeThinkingLevel,
  thinkingLabelKey,
} from '../../lib/chatModes'
import { errorTextKey } from '../../lib/errorText'
import { ApiError } from '../../lib/errors'
import {
  downloadConversationExport,
  type ConversationExportFormat,
} from '../../lib/exportConversation'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import {
  streamChat,
  streamRegenerate,
  streamReply,
  type SseEvent,
} from '../../lib/sse'
import type {
  AgentActivity,
  ChatAttachment,
  ChatMode,
  ChatModeMeta,
  ChatUsage,
  Citation,
  ConversationDetail,
  KnowledgeBase,
  ModelEntry,
  PersonalModel,
  SearchProvider,
  ThinkingLevel,
  WebSource,
} from '../../lib/types'
import { isModeImplemented, useChatModes } from '../../lib/useChatModes'
import { ChatSettingsDialog } from './ChatSettingsDialog'
import { CitationDrawer } from './CitationDrawer'
import { Composer } from './Composer'
import { MessageItem, type DisplayMessage } from './MessageItem'
import { ModeSelector } from './ModeSelector'
import { ReuseDialog } from './ReuseDialog'
import { ShareDialog } from './ShareDialog'
import { StudyPanel } from './StudyPanel'
import { TraceDialog } from './TraceDialog'

interface PendingStream {
  user: string
  assistant: string
  citations: Citation[]
  webSources: WebSource[]
  stage: string | null
  activity: AgentActivity[]
  attachments: ChatAttachment[]
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
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [editingTitle, setEditingTitle] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')
  const [attachments, setAttachments] = useState<ChatAttachment[]>([])
  const [attaching, setAttaching] = useState(false)
  const [attachError, setAttachError] = useState<string | null>(null)
  const [editTarget, setEditTarget] = useState<DisplayMessage | null>(null)
  const [editDraft, setEditDraft] = useState('')
  const [editing, setEditing] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)
  const [editLaterCount, setEditLaterCount] = useState(0)
  const [cooldown, setCooldown] = useState(0)
  const [thinkingLevel, setThinkingLevel] = useState<ThinkingLevel>('standard')
  const [searchProviderId, setSearchProviderId] = useState('')
  const [studySessionId, setStudySessionId] = useState('')
  const [reuseMessageId, setReuseMessageId] = useState<string | null>(null)
  const [shareOpen, setShareOpen] = useState(false)
  const [modeError, setModeError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const activityIdRef = useRef(0)
  const startedRef = useRef(false)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const stickRef = useRef(true)
  const titleSavingRef = useRef(false)
  const titleCancelledRef = useRef(false)

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
  const chatModes = useChatModes()
  const platformModels = useQuery({
    queryKey: ['models'],
    queryFn: () => apiRequest<ModelEntry[]>('/models'),
    staleTime: 60_000,
  })
  const personalModels = useQuery({
    queryKey: ['provider-configs', 'models'],
    queryFn: () => apiRequest<PersonalModel[]>('/provider-configs/models'),
    staleTime: 60_000,
  })
  const searchProviders = useQuery({
    queryKey: ['search-providers'],
    queryFn: () => apiRequest<SearchProvider[]>('/search-providers'),
    staleTime: 60_000,
  })
  const enabledSearchProviders = (searchProviders.data ?? []).filter(
    (item) => item.enabled,
  )
  const hasSearchProvider = enabledSearchProviders.length > 0
  const activeMode: ChatMode = conversation.data?.default_mode ?? 'chat'
  const modeImplemented = isModeImplemented(activeMode, chatModes.data)
  const searchProviderMissing = activeMode === 'web_search' && !hasSearchProvider
  const studySessionMissing = activeMode === 'study' && studySessionId === ''
  const platformModel = (platformModels.data ?? []).find(
    (model) =>
      model.provider_id === conversation.data?.provider_id &&
      model.model_id === conversation.data?.model,
  )
  const personalModel = (personalModels.data ?? []).find(
    (model) =>
      model.provider_id === conversation.data?.provider_id &&
      model.model_id === conversation.data?.model,
  )
  const supportedThinking: ThinkingLevel[] =
    conversation.data?.provider_id === 'auto' || conversation.data === undefined
      ? ['standard']
      : modelReasoningLevels(personalModel ?? platformModel)
  const supportedThinkingKey = supportedThinking.join(',')

  const runStream = useCallback(
    async (
      request: (signal: AbortSignal, onEvent: (event: SseEvent) => void) => Promise<void>,
      userContent: string,
      pendingAttachments: ChatAttachment[] = [],
    ) => {
      if (conversationId === '') return
      setPending({
        user: userContent,
        assistant: '',
        citations: [],
        webSources: [],
        stage: null,
        activity: [],
        attachments: pendingAttachments,
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
        await request(controller.signal, (event) => {
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
          } else if (event.event === 'web_source') {
            setPending((prev) =>
              prev
                ? {
                    ...prev,
                    webSources: [...prev.webSources, data as unknown as WebSource],
                  }
                : prev,
            )
          } else if (event.event === 'stage') {
            setPending((prev) =>
              prev ? { ...prev, stage: String(data.stage ?? '') } : prev,
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

  const attachFiles = async (files: File[]) => {
    setAttachError(null)
    setAttaching(true)
    try {
      for (const file of files) {
        const uploaded = await uploadChatAttachment(file, conversationId)
        setAttachments((prev) => [...prev, uploaded])
      }
    } catch (caught) {
      setAttachError(t(errorTextKey(caught)))
    } finally {
      setAttaching(false)
    }
  }

  const start = useCallback(
    async (content: string, metaOverride?: ChatModeMeta) => {
      if (conversationId === '') return
      stickRef.current = true
      setInput('')
      const snapshot = attachments
      setAttachments([])
      const modeMeta: ChatModeMeta = metaOverride ?? {
        thinking_level: thinkingLevel,
        ...(activeMode === 'web_search' && searchProviderId !== ''
          ? { search_provider_id: searchProviderId }
          : {}),
        ...(activeMode === 'study' && studySessionId !== ''
          ? { study_session_id: studySessionId }
          : {}),
      }
      await runStream(
        (signal, onEvent) =>
          streamChat({
            conversationId,
            content,
            attachmentIds: snapshot.map((item) => item.id),
            mode: activeMode,
            modeMeta,
            signal,
            onEvent,
          }),
        content,
        snapshot,
      )
    },
    [
      activeMode,
      attachments,
      conversationId,
      runStream,
      searchProviderId,
      studySessionId,
      thinkingLevel,
    ],
  )

  const regenerate = useCallback(
    async (messageId: string) => {
      if (conversationId === '' || pending?.status === 'streaming') return
      stickRef.current = true
      await runStream(
        (signal, onEvent) =>
          streamRegenerate({ conversationId, messageId, signal, onEvent }),
        '',
      )
    },
    [conversationId, pending?.status, runStream],
  )

  useEffect(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setPending(null)
    setInput('')
    setMenuOpen(false)
    setEditingTitle(false)
    setAttachments([])
    setAttachError(null)
    setEditTarget(null)
    stickRef.current = true
  }, [conversationId])

  useEffect(() => {
    if (cooldown <= 0) return
    const timer = window.setInterval(() => {
      setCooldown((seconds) => Math.max(seconds - 1, 0))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [cooldown])

  useEffect(() => {
    setThinkingLevel((current) =>
      normalizeThinkingLevel(current, supportedThinking),
    )
  }, [supportedThinkingKey])

  useEffect(() => {
    if (conversation.data === undefined) return
    const latest = [...conversation.data.messages]
      .reverse()
      .find((message) => message.mode_meta?.thinking_level !== undefined)
    if (latest?.mode_meta?.thinking_level !== undefined) {
      setThinkingLevel(latest.mode_meta.thinking_level)
    }
  }, [conversation.data?.id])

  useEffect(() => {
    const latest = [...(conversation.data?.messages ?? [])]
      .reverse()
      .find((message) => message.mode_meta?.search_provider_id !== undefined)
    const enabled = (searchProviders.data ?? []).filter((item) => item.enabled)
    const preferred =
      latest?.mode_meta?.search_provider_id ??
      enabled.find((item) => item.is_default)?.id ??
      enabled[0]?.id ??
      ''
    if (preferred !== '') setSearchProviderId(preferred)
  }, [conversation.data?.id, searchProviders.data])

  useEffect(() => {
    const latest = [...(conversation.data?.messages ?? [])]
      .reverse()
      .find((message) => message.mode_meta?.study_session_id !== undefined)
    if (latest?.mode_meta?.study_session_id !== undefined) {
      setStudySessionId(latest.mode_meta.study_session_id)
    }
  }, [conversation.data?.id])

  const changeMode = async (next: ChatMode) => {
    if (conversation.data === undefined) return
    setModeError(null)
    try {
      await apiRequest(`/conversations/${conversationId}`, {
        method: 'PATCH',
        body: { default_mode: next },
      })
      await queryClient.invalidateQueries({
        queryKey: ['conversation', conversationId],
      })
      await queryClient.invalidateQueries({ queryKey: ['conversations'] })
    } catch (caught) {
      setModeError(t(errorTextKey(caught)))
    }
  }

  useEffect(() => {
    const state = location.state as {
      pendingMessage?: string
      pendingModeMeta?: ChatModeMeta
    } | null
    const pendingMessage = state?.pendingMessage
    if (pendingMessage === undefined || startedRef.current) return
    if (conversation.data === undefined) return
    startedRef.current = true
    if (state?.pendingModeMeta?.thinking_level !== undefined) {
      setThinkingLevel(state.pendingModeMeta.thinking_level)
    }
    if (state?.pendingModeMeta?.study_session_id !== undefined) {
      setStudySessionId(state.pendingModeMeta.study_session_id)
    }
    navigate(location.pathname, { replace: true, state: null })
    void start(pendingMessage, state?.pendingModeMeta)
  }, [conversation.data, location, navigate, start])

  const serverMessages = conversation.data?.messages ?? []
  const messageCount = serverMessages.length
  const streamLength = pending?.assistant.length ?? 0

  const setFeedback = async (messageId: string, rating: 'up' | 'down') => {
    const message = serverMessages.find((item) => item.id === messageId)
    const current = message?.feedback?.rating ?? null
    try {
      if (current === rating) {
        await apiRequest(`/messages/${messageId}/feedback`, { method: 'DELETE' })
      } else {
        await apiRequest(`/messages/${messageId}/feedback`, {
          method: 'PUT',
          body: { rating },
        })
      }
      await queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] })
    } catch {
      // Feedback is best-effort; keep the conversation usable if it fails.
    }
  }

  useEffect(() => {
    if (!stickRef.current) return
    const element = scrollRef.current
    if (element !== null) element.scrollTop = element.scrollHeight
  }, [messageCount, streamLength, pending?.status])

  const handleScroll = () => {
    const element = scrollRef.current
    if (element === null) return
    stickRef.current =
      element.scrollHeight - element.scrollTop - element.clientHeight < 96
  }

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

  const openEdit = (message: DisplayMessage) => {
    const index = serverMessages.findIndex((item) => item.id === message.id)
    setEditLaterCount(index >= 0 ? serverMessages.length - index - 1 : 0)
    setEditDraft(message.content)
    setEditError(null)
    setEditTarget(message)
  }

  const saveEdit = async () => {
    if (editTarget === null || editDraft.trim() === '') return
    const target = editTarget
    const content = editDraft.trim()
    setEditing(true)
    setEditError(null)
    try {
      await apiRequest(`/conversations/${conversationId}/messages/${target.id}`, {
        method: 'PATCH',
        body: { content },
      })
      setEditTarget(null)
      await queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] })
      await queryClient.invalidateQueries({ queryKey: ['conversations'] })
      stickRef.current = true
      await runStream(
        (signal, onEvent) =>
          streamReply({ conversationId, messageId: target.id, signal, onEvent }),
        '',
      )
    } catch (caught) {
      setEditError(t(errorTextKey(caught)))
    } finally {
      setEditing(false)
    }
  }

  const startEditingTitle = () => {
    titleCancelledRef.current = false
    setTitleDraft(conversation.data?.title ?? '')
    setEditingTitle(true)
  }

  const saveTitle = async () => {
    if (titleCancelledRef.current) {
      titleCancelledRef.current = false
      setEditingTitle(false)
      return
    }
    if (titleSavingRef.current) return
    const next = titleDraft.trim()
    setEditingTitle(false)
    if (next === '' || next === (conversation.data?.title ?? '')) return
    titleSavingRef.current = true
    try {
      await apiRequest(`/conversations/${conversationId}`, {
        method: 'PATCH',
        body: { title: next },
      })
      await queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] })
      await queryClient.invalidateQueries({ queryKey: ['conversations'] })
    } finally {
      titleSavingRef.current = false
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
          ...(pending.user === ''
            ? []
            : [
                {
                  id: 'pending-user',
                  role: 'user' as const,
                  content: pending.user,
                  status: 'completed',
                  citations: [],
                  created_at: new Date().toISOString(),
                  attachments: pending.attachments,
                },
              ]),
          {
            id: 'pending-assistant',
            role: 'assistant',
            content: pending.assistant,
            status: pending.status,
            citations: pending.citations,
            web_sources: pending.webSources,
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

  const conversationKbIds =
    conversation.data?.kb_ids ??
    (conversation.data?.kb_id === null || conversation.data?.kb_id === undefined
      ? []
      : [conversation.data.kb_id])
  const kbName = kbs.data?.find((kb) => kb.id === conversationKbIds[0])?.name
  const kbLabel =
    conversationKbIds.length > 1
      ? t('chat.knowledgeBaseCount', { count: conversationKbIds.length })
      : kbName

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border bg-surface px-3 sm:px-4">
        <div className="min-w-0 flex-1">
          {editingTitle ? (
            <input
              autoFocus
              value={titleDraft}
              maxLength={120}
              aria-label={t('chat.rename')}
              className="h-8 w-full max-w-md rounded-lg border border-border bg-surface px-2 text-sm text-ink focus:border-accent focus:outline-none"
              onChange={(event) => setTitleDraft(event.target.value)}
              onBlur={() => void saveTitle()}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault()
                  void saveTitle()
                } else if (event.key === 'Escape') {
                  titleCancelledRef.current = true
                  setEditingTitle(false)
                }
              }}
            />
          ) : (
            <button
              type="button"
              onClick={startEditingTitle}
              title={t('chat.rename')}
              className="block max-w-full truncate rounded px-1 text-left text-sm font-medium text-ink hover:bg-surface-muted"
            >
              {conversation.data?.title || t('chat.newConversation')}
            </button>
          )}
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            title={`${conversation.data?.provider_id} · ${conversation.data?.model}`}
            className="ml-1 mt-0.5 inline-flex max-w-full items-center gap-1 truncate rounded-full bg-surface-muted px-2 py-0.5 text-[11px] text-ink-muted hover:text-ink"
          >
            <span className="truncate">
              {conversation.data?.provider_id === 'auto'
                ? t('models.auto')
                : conversation.data?.model}
            </span>
            {kbLabel !== undefined && <span className="truncate">· {kbLabel}</span>}
            {conversation.data?.prompt_version_id !== null &&
            conversation.data?.prompt_version_id !== undefined ? (
              <span className="truncate">· {t('prompts.active')}</span>
            ) : null}
          </button>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {latestCitations.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => openCitations(latestCitations)}
              title={t('chat.citations')}
            >
              <Quote className="h-3.5 w-3.5" />
              {latestCitations.length}
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            aria-label={t('chat.settingsTitle')}
            title={t('chat.settingsTitle')}
            onClick={() => setSettingsOpen(true)}
          >
            <SlidersHorizontal className="h-4 w-4" />
          </Button>
          <div className="relative">
            <Button
              variant="ghost"
              size="sm"
              aria-label={t('chat.conversationMenu')}
              title={t('chat.conversationMenu')}
              onClick={() => setMenuOpen((open) => !open)}
            >
              <MoreHorizontal className="h-4 w-4" />
            </Button>
            {menuOpen && (
              <>
                <button
                  type="button"
                  aria-hidden
                  tabIndex={-1}
                  className="fixed inset-0 z-10 cursor-default"
                  onClick={() => setMenuOpen(false)}
                />
                <div className="absolute right-0 top-9 z-20 w-44 rounded-lg border border-border bg-surface py-1 text-xs shadow-xl">
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-ink-muted hover:bg-surface-muted hover:text-ink"
                    onClick={() => {
                      setMenuOpen(false)
                      setShareOpen(true)
                    }}
                  >
                    <Link2 className="h-3.5 w-3.5" />
                    {t('share.action')}
                  </button>
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-ink-muted hover:bg-surface-muted hover:text-ink"
                    onClick={() => {
                      setMenuOpen(false)
                      setExportError(null)
                      setExportOpen(true)
                    }}
                  >
                    <Download className="h-3.5 w-3.5" />
                    {t('chat.export')}
                  </button>
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-ink-muted hover:bg-surface-muted hover:text-ink"
                    onClick={() => {
                      setMenuOpen(false)
                      setConfirmArchive(true)
                    }}
                  >
                    <Archive className="h-3.5 w-3.5" />
                    {t('chat.archive')}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </header>

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="min-h-0 flex-1 overflow-y-auto"
      >
        <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6 pb-10">
          {messageCount === 0 && pending === null && (
            <p className="py-10 text-center text-sm text-ink-muted">{t('chat.emptyHint')}</p>
          )}
          {serverMessages.map((message) => (
            <MessageItem
              key={message.id}
              message={message}
              onOpenCitations={openCitations}
              onOpenTrace={setTraceRequestId}
              onRegenerate={
                message.status === 'completed'
                  ? (messageId) => void regenerate(messageId)
                  : undefined
              }
              onFeedback={(messageId, rating) => void setFeedback(messageId, rating)}
              onEdit={message.role === 'user' ? openEdit : undefined}
              onReuse={
                message.role === 'assistant' && message.status === 'completed'
                  ? setReuseMessageId
                  : undefined
              }
            />
          ))}
          {pending?.stage !== null && pending?.stage !== undefined && (
            <p className="text-xs text-ink-muted">
              {t(`chat.stage_${pending.stage}`)}
            </p>
          )}
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
          </div>
      </div>

      <div className="shrink-0 border-t border-border bg-canvas px-4 py-3">
        <div className="mx-auto w-full max-w-3xl">
          {cooldown > 0 && (
            <p role="status" className="mb-2 rounded-lg bg-warning/10 px-3 py-2 text-xs text-warning">
              {t('errors.rateLimitedWait', { seconds: cooldown })}
            </p>
          )}
          {attachError !== null && (
            <p role="alert" className="mb-2 rounded-lg bg-danger/10 px-3 py-2 text-xs text-danger">
              {attachError}
            </p>
          )}
          {modeError !== null && (
            <p role="alert" className="mb-2 rounded-lg bg-danger/10 px-3 py-2 text-xs text-danger">
              {modeError}
            </p>
          )}
          {!modeImplemented && conversation.data !== undefined && (
            <p role="status" className="mb-2 rounded-lg bg-warning/10 px-3 py-2 text-xs text-warning">
              {t('chat.modePlannedNotice', {
                mode: t(modeLabelKey(activeMode)),
              })}
            </p>
          )}
          {searchProviderMissing && (
            <p role="alert" className="mb-2 rounded-lg bg-warning/10 px-3 py-2 text-xs text-warning">
              {t('chat.searchProviderMissing')}{' '}
              <Link to="/settings/search" className="underline">
                {t('chat.searchProviderSettings')}
              </Link>
            </p>
          )}
          {activeMode === 'study' && conversation.data !== undefined && (
            <StudyPanel
              conversationId={conversationId}
              defaultTopic={conversation.data.title || t('study.defaultTopic')}
              selectedSessionId={studySessionId}
              onSelectSession={setStudySessionId}
            />
          )}
          <Composer
            value={input}
            onValueChange={setInput}
            onSend={start}
            disabled={
              cooldown > 0 ||
              !modeImplemented ||
              searchProviderMissing ||
              studySessionMissing
            }
            streaming={pending?.status === 'streaming'}
            onStop={() => abortRef.current?.abort()}
            footerStart={
              <>
                <ModeSelector
                  value={activeMode}
                  catalog={chatModes.data}
                  variant="ghost"
                  placement="top"
                  disabled={conversation.data?.agent === true}
                  onChange={(next) => void changeMode(next)}
                />
                <label className="inline-flex items-center gap-1 text-[11px] text-ink-muted">
                  <span>{t('chat.thinkingLevel')}</span>
                  <select
                    aria-label={t('chat.thinkingLevel')}
                    className="h-6 rounded-md border border-border bg-surface px-1 text-[11px] text-ink"
                    value={thinkingLevel}
                    disabled={!modeImplemented}
                    onChange={(event) =>
                      setThinkingLevel(event.target.value as ThinkingLevel)
                    }
                  >
                    {THINKING_LEVELS.map((level) => (
                      <option
                        key={level}
                        value={level}
                        disabled={!supportedThinking.includes(level)}
                      >
                        {t(thinkingLabelKey(level))}
                        {supportedThinking.includes(level)
                          ? ''
                          : ` · ${t('chat.thinkingUnsupported')}`}
                      </option>
                    ))}
                  </select>
                </label>
                {activeMode === 'web_search' && enabledSearchProviders.length > 0 && (
                  <label className="inline-flex items-center gap-1 text-[11px] text-ink-muted">
                    <span>{t('chat.searchProvider')}</span>
                    <select
                      aria-label={t('chat.searchProvider')}
                      className="h-6 max-w-40 rounded-md border border-border bg-surface px-1 text-[11px] text-ink"
                      value={searchProviderId}
                      onChange={(event) => setSearchProviderId(event.target.value)}
                    >
                      {enabledSearchProviders.map((provider) => (
                        <option key={provider.id} value={provider.id}>
                          {provider.name}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
              </>
            }
            attachments={attachments}
            attaching={attaching}
            onAttachFiles={(files) => void attachFiles(files)}
            onRemoveAttachment={(id) => {
              void apiRequest(`/attachments/${id}`, { method: 'DELETE' }).catch(() => {})
              setAttachments((prev) => prev.filter((item) => item.id !== id))
            }}
          />
        </div>
      </div>

      <CitationDrawer
        open={drawerOpen}
        citations={drawerCitations}
        onClose={() => setDrawerOpen(false)}
      />

      <TraceDialog requestId={traceRequestId} onClose={() => setTraceRequestId(null)} />

      {settingsOpen && conversation.data !== undefined && (
        <ChatSettingsDialog
          conversation={conversation.data}
          onClose={() => {
            setSettingsOpen(false)
            void queryClient.invalidateQueries({
              queryKey: ['conversation', conversationId],
            })
          }}
        />
      )}

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
        open={editTarget !== null}
        onClose={() => {
          if (!editing) setEditTarget(null)
        }}
        title={t('chat.editMessage')}
        footer={
          <>
            <Button
              variant="secondary"
              size="sm"
              disabled={editing}
              onClick={() => setEditTarget(null)}
            >
              {t('common.cancel')}
            </Button>
            <Button
              size="sm"
              disabled={editing || editDraft.trim() === ''}
              onClick={() => void saveEdit()}
            >
              {t('chat.editAndResend')}
            </Button>
          </>
        }
      >
        {editLaterCount > 0 && (
          <p className="mb-2 rounded-lg bg-warning/10 px-3 py-2 text-xs text-warning">
            {t('chat.editWarning', { count: editLaterCount })}
          </p>
        )}
        <Textarea
          className="min-h-32 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none"
          value={editDraft}
          maxLength={20000}
          onChange={(event) => setEditDraft(event.target.value)}
        />
        {editError !== null && <p className="mt-2 text-xs text-danger">{editError}</p>}
      </Dialog>

      {reuseMessageId !== null && (
        <ReuseDialog
          open
          conversationId={conversationId}
          messageId={reuseMessageId}
          onClose={() => setReuseMessageId(null)}
        />
      )}

      <ShareDialog
        open={shareOpen}
        conversationId={conversationId}
        onClose={() => setShareOpen(false)}
      />

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