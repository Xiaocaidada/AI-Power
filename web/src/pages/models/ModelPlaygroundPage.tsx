import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Server } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import { streamChat } from '../../lib/sse'
import type {
  ChatUsage,
  Citation,
  Conversation,
  ConversationDetail,
  MarketModel,
} from '../../lib/types'
import { CitationDrawer } from '../chat/CitationDrawer'
import { Composer } from '../chat/Composer'
import { MessageItem, type DisplayMessage } from '../chat/MessageItem'

export function ModelPlaygroundPage() {
  const { t } = useI18n()
  const { slug = '' } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const conversationId = searchParams.get('conversation')
  const [messages, setMessages] = useState<DisplayMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerCitations, setDrawerCitations] = useState<Citation[]>([])
  const abortRef = useRef<AbortController | null>(null)
  const loadedConversation = useRef<string | null>(null)
  const bottomRef = useRef<HTMLDivElement | null>(null)

  const model = useQuery({
    queryKey: ['market-model', slug],
    queryFn: () => apiRequest<MarketModel>(`/market/models/${slug}`, { auth: false }),
    enabled: slug !== '',
  })
  const conversation = useQuery({
    queryKey: ['playground-conversation', conversationId],
    queryFn: () => apiRequest<ConversationDetail>(`/conversations/${conversationId}`),
    enabled: conversationId !== null,
  })

  useEffect(() => {
    if (conversationId === null || conversation.data === undefined) return
    if (loadedConversation.current === conversationId) return
    loadedConversation.current = conversationId
    setMessages(
      conversation.data.messages.map((message) => ({
        id: message.id,
        role: message.role,
        content: message.content,
        status: message.status,
        citations: message.citations,
        provider_id: message.provider_id,
        model: message.model,
        prompt_tokens: message.prompt_tokens,
        completion_tokens: message.completion_tokens,
        request_id: message.request_id,
      })),
    )
  }, [conversation.data, conversationId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  const updateAssistant = (id: string, patch: Partial<DisplayMessage>) => {
    setMessages((previous) =>
      previous.map((message) => (message.id === id ? { ...message, ...patch } : message)),
    )
  }

  const send = async (content: string) => {
    if (model.data === undefined || content.trim() === '') return
    setError(null)
    setInput('')
    const assistantId = `playground-${Date.now()}`
    setMessages((previous) => [
      ...previous,
      {
        id: `user-${Date.now()}`,
        role: 'user',
        content,
        status: 'completed',
        citations: [],
      },
      {
        id: assistantId,
        role: 'assistant',
        content: '',
        status: 'streaming',
        citations: [],
        streaming: true,
        provider_id: model.data.provider_id,
        model: model.data.model_id,
      },
    ])
    setStreaming(true)
    const controller = new AbortController()
    abortRef.current = controller
    let targetConversation = conversationId
    try {
      if (targetConversation === null) {
        const created = await apiRequest<Conversation>('/conversations', {
          method: 'POST',
          body: {
            provider_id: model.data.provider_id,
            model: model.data.model_id,
          },
        })
        targetConversation = created.id
        setSearchParams({ conversation: created.id }, { replace: true })
        loadedConversation.current = created.id
      }
      const usageRef: { current: ChatUsage | null } = { current: null }
      let failure: string | null = null
      await streamChat({
        conversationId: targetConversation,
        content,
        signal: controller.signal,
        onEvent: (event) => {
          const data = event.data as Record<string, unknown>
          if (event.event === 'citation') {
            const citation = data as unknown as Citation
            setMessages((previous) =>
              previous.map((message) =>
                message.id === assistantId
                  ? { ...message, citations: [...message.citations, citation] }
                  : message,
              ),
            )
          } else if (event.event === 'delta') {
            setMessages((previous) =>
              previous.map((message) =>
                message.id === assistantId
                  ? { ...message, content: message.content + String(data.text ?? '') }
                  : message,
              ),
            )
          } else if (event.event === 'usage') {
            usageRef.current = data as unknown as ChatUsage
          } else if (event.event === 'error') {
            failure = String(data.code ?? 'internal_error')
          }
        },
      })
      if (failure !== null) {
        updateAssistant(assistantId, {
          status: 'failed',
          streaming: false,
          errorCode: failure,
        })
      } else {
        updateAssistant(assistantId, {
          status: 'completed',
          streaming: false,
          prompt_tokens: usageRef.current?.prompt_tokens ?? null,
          completion_tokens: usageRef.current?.completion_tokens ?? null,
        })
      }
    } catch (caught) {
      if (controller.signal.aborted) {
        updateAssistant(assistantId, { status: 'cancelled', streaming: false })
      } else {
        setError(t(errorTextKey(caught)))
        updateAssistant(assistantId, { status: 'failed', streaming: false })
      }
    } finally {
      setStreaming(false)
      abortRef.current = null
    }
  }

  if (model.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner className="h-6 w-6 text-accent" />
      </div>
    )
  }

  if (model.isError || model.data === undefined) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3">
        <p className="text-sm text-ink-muted">{t('models.detailMissing')}</p>
        <Button variant="secondary" onClick={() => navigate('/models')}>
          {t('models.backToMarket')}
        </Button>
      </div>
    )
  }

  const detail = model.data

  return (
    <div className="flex min-h-[calc(100dvh-4rem)] flex-col">
      <header className="border-b border-border bg-surface px-4 py-3 sm:px-6">
        <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center gap-3">
          <Link
            to={`/models/${detail.slug}`}
            className="inline-flex items-center gap-1 text-xs text-ink-muted hover:text-ink"
          >
            <ArrowLeft className="h-3 w-3" />
            {t('models.backToDetail')}
          </Link>
          <div className="ml-2 min-w-0">
            <p className="truncate text-sm font-medium text-ink">{detail.name}</p>
            <p className="truncate text-xs text-ink-muted">
              {detail.provider_name} · {detail.model_id}
            </p>
          </div>
          <div className="ml-auto flex flex-wrap gap-1">
            {detail.capabilities.slice(0, 4).map((capability) => (
              <Badge key={capability} tone="neutral">
                {capability}
              </Badge>
            ))}
          </div>
        </div>
      </header>

      {!detail.available ? (
        <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
          <Server className="h-6 w-6 text-ink-muted" />
          <p className="text-sm text-ink-muted">{t('models.configRequired')}</p>
          <Button onClick={() => navigate('/settings/providers')}>
            {t('models.configure')}
          </Button>
        </div>
      ) : (
        <>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-8">
              {messages.length === 0 && (
                <div className="py-12 text-center">
                  <p className="text-sm text-ink-muted">{t('models.playgroundEmpty')}</p>
                </div>
              )}
              {messages.map((message) => (
                <MessageItem
                  key={message.id}
                  message={message}
                  onOpenCitations={(citations) => {
                    setDrawerCitations(citations)
                    setDrawerOpen(true)
                  }}
                />
              ))}
              <div ref={bottomRef} />
            </div>
          </div>
          <div className="shrink-0 border-t border-border bg-canvas px-4 py-3">
            <div className="mx-auto w-full max-w-3xl">
              {error !== null && (
                <p role="alert" className="mb-2 rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
                  {error}
                </p>
              )}
              <Composer
                value={input}
                onValueChange={setInput}
                onSend={send}
                streaming={streaming}
                onStop={() => abortRef.current?.abort()}
              />
            </div>
          </div>
        </>
      )}

      <CitationDrawer
        open={drawerOpen}
        citations={drawerCitations}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  )
}