import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  MessageSquare,
  Play,
  RotateCcw,
  Square,
  Workflow as WorkflowIcon,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Spinner } from '../../components/ui/spinner'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import { streamChat, streamRunEvents } from '../../lib/sse'
import type {
  AgentRun,
  Conversation,
  CustomAgent,
  RunAccepted,
} from '../../lib/types'

interface ChatLine {
  role: 'user' | 'assistant'
  content: string
}

interface WorkflowNodeState {
  id: string
  type: string
  status: string
  output: string
}

type Mode = 'chat' | 'workflow'

export function AgentExperiencePage() {
  const { id = '' } = useParams<{ id: string }>()
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [mode, setMode] = useState<Mode>('chat')
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [conversationId, setConversationId] = useState('')
  const [messages, setMessages] = useState<ChatLine[]>([])
  const [activity, setActivity] = useState<string[]>([])
  const chatController = useRef<AbortController | null>(null)

  const [runId, setRunId] = useState('')
  const [runStatus, setRunStatus] = useState('')
  const [runOutput, setRunOutput] = useState('')
  const [lastRunInput, setLastRunInput] = useState('')
  const [nodes, setNodes] = useState<WorkflowNodeState[]>([])
  const runController = useRef<AbortController | null>(null)

  const agentQuery = useQuery({
    queryKey: ['agent-experience', id],
    queryFn: () => apiRequest<CustomAgent>(`/agents/${id}`),
    enabled: id !== '',
  })
  const runsQuery = useQuery({
    queryKey: ['agent-runs', id],
    queryFn: () => apiRequest<AgentRun[]>(`/agents/${id}/runs?limit=10`),
    enabled: id !== '',
  })
  const agent = agentQuery.data

  useEffect(() => {
    if (agent === undefined) return
    setMode(agent.mode === 'workflow' ? 'workflow' : 'chat')
  }, [agent])

  useEffect(
    () => () => {
      chatController.current?.abort()
      runController.current?.abort()
    },
    [],
  )

  if (agentQuery.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner className="h-6 w-6 text-accent" />
      </div>
    )
  }
  if (agentQuery.isError || agent === undefined) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3">
        <p className="text-sm text-ink-muted">{t('agents.missing')}</p>
        <Link to="/agents" className="text-sm text-accent">
          {t('agents.back')}
        </Link>
      </div>
    )
  }

  const refreshRuns = () =>
    queryClient.invalidateQueries({ queryKey: ['agent-runs', id] })

  const sendChat = async () => {
    if (input.trim() === '') return
    const content = input.trim()
    setInput('')
    setError(null)
    setBusy(true)
    setMessages((prev) => [
      ...prev,
      { role: 'user', content },
      { role: 'assistant', content: '' },
    ])
    const controller = new AbortController()
    chatController.current = controller
    try {
      let activeConversation = conversationId
      if (activeConversation === '') {
        const created = await apiRequest<Conversation>('/conversations', {
          method: 'POST',
          body: { custom_agent_id: agent.id },
        })
        activeConversation = created.id
        setConversationId(activeConversation)
      }
      await streamChat({
        conversationId: activeConversation,
        content,
        signal: controller.signal,
        onEvent: (event) => {
          const data = event.data as Record<string, unknown> | null
          if (data === null) return
          if (event.event === 'delta') {
            const text = String(data.text ?? '')
            setMessages((prev) => {
              const next = [...prev]
              const last = next[next.length - 1]
              if (last?.role === 'assistant') {
                next[next.length - 1] = { ...last, content: last.content + text }
              }
              return next
            })
          } else if (event.event === 'tool_call') {
            setActivity((prev) => [
              ...prev,
              `${String(data.agent ?? 'agent')} → ${String(data.tool ?? 'tool')}`,
            ])
          } else if (event.event === 'tool_result') {
            setActivity((prev) => [
              ...prev,
              `${String(data.tool ?? 'tool')} ${data.ok === false ? 'failed' : 'done'}`,
            ])
          } else if (event.event === 'error') {
            setError(String(data.message ?? data.code ?? 'error'))
          }
        },
      })
    } catch (caught) {
      if (!controller.signal.aborted) {
        setError(caught instanceof Error ? caught.message : t('errors.generic'))
      }
    } finally {
      chatController.current = null
      setBusy(false)
      refreshRuns()
    }
  }

  const startWorkflow = async (override?: string) => {
    const content = (override ?? input).trim()
    if (agent.workflow_id === null || content === '') return
    setLastRunInput(content)
    setInput('')
    setError(null)
    setBusy(true)
    setRunOutput('')
    setNodes([])
    setRunStatus('running')
    const controller = new AbortController()
    runController.current = controller
    try {
      await apiRequest(`/agents/${agent.id}/use`, { method: 'POST' })
      const accepted = await apiRequest<RunAccepted>(
        `/workflows/${agent.workflow_id}/runs`,
        { method: 'POST', body: { input: content } },
      )
      setRunId(accepted.run_id)
      await streamRunEvents({
        path: `/workflows/runs/${accepted.run_id}/events`,
        signal: controller.signal,
        onEvent: (event) => {
          const data = event.data as Record<string, unknown> | null
          if (data === null) return
          if (event.event === 'node_start') {
            const nodeId = String(data.node_id ?? '')
            setNodes((prev) => [
              ...prev.filter((item) => item.id !== nodeId),
              {
                id: nodeId,
                type: String(data.node_type ?? ''),
                status: 'running',
                output: '',
              },
            ])
          } else if (event.event === 'node_end') {
            const nodeId = String(data.node_id ?? '')
            setNodes((prev) =>
              prev.map((item) =>
                item.id === nodeId
                  ? {
                      ...item,
                      status: String(data.status ?? ''),
                      output: String(data.output ?? ''),
                    }
                  : item,
              ),
            )
          } else if (event.event === 'workflow_end') {
            setRunStatus(String(data.status ?? ''))
            setRunOutput(String(data.output ?? ''))
          }
        },
      })
    } catch (caught) {
      if (!controller.signal.aborted) {
        setError(caught instanceof Error ? caught.message : t('errors.generic'))
        setRunStatus('failed')
      }
    } finally {
      runController.current = null
      setBusy(false)
      refreshRuns()
    }
  }

  const stop = async () => {
    if (mode === 'chat') {
      chatController.current?.abort()
      return
    }
    runController.current?.abort()
    if (runId !== '') {
      try {
        await apiRequest(`/workflows/runs/${runId}/cancel`, { method: 'POST' })
      } catch {
        // 运行可能已经结束
      }
    }
    setRunStatus('cancelled')
  }

  const newChat = () => {
    chatController.current?.abort()
    setConversationId('')
    setMessages([])
    setActivity([])
  }

  const supportsWorkflow = agent.workflow_id !== null
  const modes: Mode[] = supportsWorkflow ? ['chat', 'workflow'] : ['chat']

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-4">
        <Link
          to="/agents"
          className="inline-flex items-center gap-1 text-xs text-ink-muted hover:text-ink"
        >
          <ArrowLeft className="h-3 w-3" />
          {t('agents.back')}
        </Link>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-accent-soft text-2xl">
            {agent.icon}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-lg font-semibold text-ink">{agent.name}</h1>
              <Badge tone="neutral">{agent.mode}</Badge>
              {agent.published && <Badge tone="success">{t('agents.published')}</Badge>}
            </div>
            <p className="text-sm text-ink-muted">{agent.description}</p>
          </div>
          <div className="flex gap-1">
            {modes.map((item) => (
              <Button
                key={item}
                size="sm"
                variant={mode === item ? 'primary' : 'secondary'}
                onClick={() => setMode(item)}
              >
                {item === 'chat' ? (
                  <MessageSquare className="h-3.5 w-3.5" />
                ) : (
                  <WorkflowIcon className="h-3.5 w-3.5" />
                )}
                {item === 'chat' ? t('agents.experienceChat') : t('agents.experienceWorkflow')}
              </Button>
            ))}
          </div>
        </div>
      </header>

      <div className="grid gap-4 px-6 py-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <section className="rounded-card border border-border bg-surface p-4">
          <div className="min-h-[24rem] space-y-3">
            {mode === 'chat' ? (
              <>
                {messages.length === 0 && (
                  <p className="text-sm text-ink-muted">
                    {agent.welcome_message || t('agents.experienceLead')}
                  </p>
                )}
                {messages.map((message, index) => (
                  <div
                    key={`${index}-${message.role}`}
                    className={
                      message.role === 'user'
                        ? 'ml-auto max-w-[85%] rounded-2xl rounded-br-sm bg-accent px-3 py-2 text-sm text-[rgb(var(--accent-ink))]'
                        : 'mr-auto max-w-[90%] whitespace-pre-wrap rounded-2xl rounded-bl-sm border border-border bg-canvas px-3 py-2 text-sm text-ink'
                    }
                  >
                    {message.content || (busy ? '…' : '')}
                  </div>
                ))}
                {activity.length > 0 && (
                  <div className="rounded-lg bg-surface-muted px-3 py-2">
                    <p className="text-[11px] font-medium text-ink">
                      {t('agents.experienceTools')}
                    </p>
                    <ul className="mt-1 space-y-0.5 text-[10px] text-ink-muted">
                      {activity.map((item, index) => (
                        <li key={`${item}-${index}`}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            ) : (
              <>
                {runStatus === '' && (
                  <p className="text-sm text-ink-muted">{t('agents.experienceLead')}</p>
                )}
                {nodes.map((node) => (
                  <div
                    key={node.id}
                    className="rounded-lg border border-border bg-surface-muted px-3 py-2"
                  >
                    <div className="flex items-center gap-2">
                      <Badge
                        tone={
                          node.status === 'completed'
                            ? 'success'
                            : node.status === 'failed'
                              ? 'danger'
                              : 'neutral'
                        }
                      >
                        {node.status}
                      </Badge>
                      <span className="text-xs font-medium text-ink">{node.id}</span>
                      <span className="text-[10px] text-ink-muted">{node.type}</span>
                    </div>
                    {node.output && (
                      <p className="mt-1 max-h-20 overflow-y-auto whitespace-pre-wrap text-[11px] text-ink-muted">
                        {node.output}
                      </p>
                    )}
                  </div>
                ))}
                {runOutput !== '' && (
                  <div className="rounded-lg border border-border bg-canvas p-3">
                    <p className="text-[11px] font-medium text-ink">
                      {t('agents.experienceOutput')}
                    </p>
                    <p className="mt-1 whitespace-pre-wrap text-sm text-ink">{runOutput}</p>
                  </div>
                )}
              </>
            )}
            {error !== null && <p className="text-xs text-danger">{error}</p>}
          </div>

          <div className="mt-4 border-t border-border pt-3">
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder={
                mode === 'chat' ? t('agents.experienceInput') : t('agents.experienceTask')
              }
              className="min-h-20 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink"
            />
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                disabled={
                  busy ||
                  input.trim() === '' ||
                  (mode === 'workflow' && !supportsWorkflow)
                }
                onClick={() => void (mode === 'chat' ? sendChat() : startWorkflow())}
              >
                <Play className="h-3.5 w-3.5" />
                {mode === 'chat' ? t('agents.experienceSend') : t('agents.experienceRun')}
              </Button>
              {busy && (
                <Button size="sm" variant="secondary" onClick={() => void stop()}>
                  <Square className="h-3.5 w-3.5" />
                  {t('arena.stop')}
                </Button>
              )}
              {mode === 'chat' && messages.length > 0 && !busy && (
                <Button size="sm" variant="ghost" onClick={newChat}>
                  <RotateCcw className="h-3.5 w-3.5" />
                  {t('agents.experienceNewChat')}
                </Button>
              )}
              {mode === 'workflow' && runId !== '' && !busy && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => void startWorkflow(lastRunInput)}
                  disabled={lastRunInput === ''}
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  {t('agents.experienceRerun')}
                </Button>
              )}
            </div>
          </div>
        </section>

        <aside className="rounded-card border border-border bg-surface">
          <p className="border-b border-border px-4 py-2 text-sm font-medium text-ink">
            {t('agents.experienceHistory')}
          </p>
          <div className="max-h-[32rem] divide-y divide-border overflow-y-auto">
            {(runsQuery.data ?? []).map((run) => (
              <div key={`${run.kind}-${run.id}`} className="px-4 py-2">
                <div className="flex items-center gap-2">
                  <Badge tone={run.status === 'completed' ? 'success' : 'neutral'}>
                    {run.status}
                  </Badge>
                  <span className="text-[10px] text-ink-muted">{run.kind}</span>
                  <span className="ml-auto text-[10px] text-ink-muted">
                    {run.duration_ms !== null ? `${run.duration_ms.toFixed(0)} ms` : ''}
                  </span>
                </div>
                <p className="mt-1 truncate text-xs text-ink">{run.input || run.title}</p>
                <p className="line-clamp-2 text-[10px] text-ink-muted">
                  {run.output || run.error_code || ''}
                </p>
                {run.href && (
                  <Link to={run.href} className="text-[10px] text-accent">
                    {t('agents.experienceOpen')}
                  </Link>
                )}
              </div>
            ))}
            {runsQuery.data !== undefined && runsQuery.data.length === 0 && (
              <p className="px-4 py-4 text-xs text-ink-muted">{t('agents.noHistory')}</p>
            )}
          </div>
        </aside>
      </div>
    </div>
  )
}