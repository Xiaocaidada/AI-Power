import { useQuery } from '@tanstack/react-query'
import { Plus, Send, Sparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { PopoverSelect } from '../../components/ui/popover-select'
import {
  applyBuilderSelection,
  defaultBuilderSelection,
  edgeChangeKey,
  nodeChangeKey,
} from '../../lib/builderApply'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { streamBuilderTurn } from '../../lib/sse'
import { useI18n } from '../../lib/i18n'
import type {
  AgentBuilderDiff,
  AgentBuilderMessage,
  AgentBuilderSession,
  AgentBuilderTurn,
  WorkflowDefinition,
} from '../../lib/types'
import type { ModelChoice } from './types'

type BuilderMode = 'modify' | 'explain' | 'fix'

interface StudioBuilderPanelProps {
  agentId: string
  workflowId: string | null
  definition: WorkflowDefinition
  models: ModelChoice[]
  sessionId: string
  onSessionId: (id: string) => void
  onApply: (definition: WorkflowDefinition) => void
  lastRunId: string | null
}

function shortValue(value: unknown): string {
  const text = typeof value === 'string' ? value : JSON.stringify(value ?? null)
  return text.length > 80 ? `${text.slice(0, 77)}…` : text
}

export function DiffView({
  diff,
  selection,
  onToggle,
}: {
  diff: AgentBuilderDiff
  selection?: Set<string>
  onToggle?: (key: string) => void
}) {
  const { t } = useI18n()
  const groups = [
    {
      label: t('studio.builderAddedNodes'),
      items: diff.added_nodes.map((item) => ({
        key: nodeChangeKey('add', item.id),
        label: `${item.id} · ${item.type}`,
      })),
    },
    {
      label: t('studio.builderRemovedNodes'),
      items: diff.removed_nodes.map((item) => ({
        key: nodeChangeKey('remove', item.id),
        label: `${item.id} · ${item.type}`,
      })),
    },
    {
      label: t('studio.builderAddedEdges'),
      items: diff.added_edges.map((item) => ({
        key: edgeChangeKey('add', item),
        label: `${item.from} → ${item.to}${item.when ? ` (${item.when})` : ''}`,
      })),
    },
    {
      label: t('studio.builderRemovedEdges'),
      items: diff.removed_edges.map((item) => ({
        key: edgeChangeKey('remove', item),
        label: `${item.from} → ${item.to}${item.when ? ` (${item.when})` : ''}`,
      })),
    },
  ].filter((group) => group.items.length > 0)
  return (
    <div className="space-y-2">
      {groups.map((group) => (
        <div key={group.label}>
          <p className="text-[11px] font-medium text-ink">{group.label}</p>
          <ul className="mt-0.5 space-y-0.5 text-[10px] text-ink-muted">
            {group.items.map((item) => (
              <li key={item.key} className="flex items-center gap-1.5 font-mono">
                {selection !== undefined && onToggle !== undefined && (
                  <input
                    type="checkbox"
                    checked={selection.has(item.key)}
                    onChange={() => onToggle(item.key)}
                  />
                )}
                {item.label}
              </li>
            ))}
          </ul>
        </div>
      ))}
      {diff.updated_nodes.length > 0 && (
        <div>
          <p className="text-[11px] font-medium text-ink">
            {t('studio.builderUpdatedNodes')}
          </p>
          <div className="mt-1 space-y-1">
            {diff.updated_nodes.map((node) => (
              <div key={node.id} className="rounded-md bg-surface-muted px-2 py-1">
                <p className="font-mono text-[10px] text-ink">
                  {node.id} · {node.type}
                </p>
                {node.changes.map((change) => (
                  <p key={change.field} className="text-[10px] text-ink-muted">
                    {change.field}: {shortValue(change.before)} → {shortValue(change.after)}
                  </p>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export function StudioBuilderPanel({
  agentId,
  workflowId,
  definition,
  models,
  sessionId,
  onSessionId,
  onApply,
  lastRunId,
}: StudioBuilderPanelProps) {
  const { t } = useI18n()
  const [mode, setMode] = useState<BuilderMode>('modify')
  const [choice, setChoice] = useState('')
  const [prompt, setPrompt] = useState('')
  const [messages, setMessages] = useState<AgentBuilderMessage[]>([])
  const [turn, setTurn] = useState<AgentBuilderTurn | null>(null)
  const [selection, setSelection] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(false)
  const [stage, setStage] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [newSession, setNewSession] = useState(false)
  const controllerRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const skipSessionLoad = useRef(false)

  const sessionQuery = useQuery({
    queryKey: ['builder-session', sessionId],
    queryFn: () =>
      apiRequest<AgentBuilderSession>(`/agent-builder/sessions/${sessionId}`),
    enabled: sessionId !== '',
  })
  const sessionsQuery = useQuery({
    queryKey: ['builder-sessions', agentId],
    queryFn: () =>
      apiRequest<AgentBuilderSession[]>(
        `/agent-builder/sessions?agent_id=${encodeURIComponent(agentId)}`,
      ),
    enabled: sessionId === '' && !newSession,
  })

  useEffect(() => {
    if (sessionId === '' && sessionsQuery.data !== undefined) {
      const latest = sessionsQuery.data[0]
      if (latest !== undefined) onSessionId(latest.id)
    }
  }, [onSessionId, sessionId, sessionsQuery.data])

  useEffect(() => {
    if (sessionQuery.data === undefined) return
    if (skipSessionLoad.current) {
      skipSessionLoad.current = false
      return
    }
    const session = sessionQuery.data
    setMessages(session.messages)
    setChoice(`${session.provider_id}/${session.model}`)
    const lastMessage = session.messages[session.messages.length - 1]
    if (lastMessage?.kind === 'apply') {
      setTurn(null)
      return
    }
    const lastAssistant = [...session.messages]
      .reverse()
      .find(
        (item) =>
          item.role === 'assistant' &&
          item.kind !== 'apply' &&
          item.definition !== null &&
          item.definition !== undefined,
      )
    if (lastAssistant?.definition) {
      setTurn({
        session_id: session.id,
        message: lastAssistant.content,
        definition: lastAssistant.definition,
        diff: lastAssistant.diff ?? null,
        missing_resources: lastAssistant.missing_resources ?? [],
        suggestions: lastAssistant.suggestions ?? [],
      })
    }
  }, [sessionQuery.data])

  useEffect(() => {
    if (models.length === 0) return
    const options = new Set(models.map((item) => `${item.provider_id}/${item.model}`))
    if (choice === '' || !options.has(choice)) {
      setChoice(`${models[0].provider_id}/${models[0].model}`)
    }
  }, [choice, models])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [messages])

  useEffect(() => {
    setSelection(
      turn?.diff ? defaultBuilderSelection(turn.diff) : new Set<string>(),
    )
  }, [turn])

  const currentDefinition = turn?.definition ?? definition

  const ensureSession = async (): Promise<string> => {
    if (sessionId !== '') return sessionId
    if (choice === '') throw new Error(t('studio.builderNoModel'))
    const [providerId, ...rest] = choice.split('/')
    const created = await apiRequest<AgentBuilderSession>('/agent-builder/sessions', {
      method: 'POST',
      body: {
        agent_id: agentId,
        workflow_id: workflowId,
        provider_id: providerId,
        model: rest.join('/'),
        draft_definition: definition,
      },
    })
    setNewSession(false)
    skipSessionLoad.current = true
    onSessionId(created.id)
    return created.id
  }

  const send = async () => {
    if (prompt.trim() === '') return
    if (mode === 'fix' && lastRunId === null) {
      setError(t('studio.builderFixNeedsRun'))
      return
    }
    setLoading(true)
    setError(null)
    const controller = new AbortController()
    controllerRef.current = controller
    try {
      const id = await ensureSession()
      let result: AgentBuilderTurn | undefined
      let failure: string | null = null
      setStage('preparing')
      await streamBuilderTurn({
        sessionId: id,
        signal: controller.signal,
        body: {
          kind: mode,
          prompt: prompt.trim(),
          current_definition: currentDefinition,
          run_id: mode === 'fix' ? lastRunId : null,
        },
        onEvent: (event) => {
          const data = event.data as Record<string, unknown>
          if (event.event === 'stage') {
            setStage(String(data.stage ?? ''))
          } else if (event.event === 'result') {
            result = event.data as AgentBuilderTurn
          } else if (event.event === 'error') {
            failure = String(data.message ?? data.code ?? '')
          }
        },
      })
      if (failure !== null) {
        setError(failure)
        return
      }
      if (result === undefined) {
        setError(t('errors.generic'))
        return
      }
      const userMessage: AgentBuilderMessage = {
        role: 'user',
        kind: mode,
        content: prompt.trim(),
      }
      const assistantMessage: AgentBuilderMessage = {
        role: 'assistant',
        kind: mode,
        content: result.message,
        definition: result.definition,
        diff: result.diff,
        missing_resources: result.missing_resources,
        suggestions: result.suggestions,
        clarification: result.clarification,
      }
      setMessages((prev) => [...prev, userMessage, assistantMessage])
      setTurn(result)
      setPrompt('')
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === 'AbortError') {
        setError(t('studio.builderCancelled'))
      } else {
        setError(t(errorTextKey(caught)))
      }
    } finally {
      controllerRef.current = null
      setLoading(false)
    }
  }

  const cancelGeneration = () => {
    controllerRef.current?.abort()
  }

  const apply = async () => {
    if (turn?.definition === null || turn?.definition === undefined) return
    const applied =
      turn.diff !== null
        ? applyBuilderSelection(definition, turn.definition, turn.diff, selection)
        : turn.definition
    setLoading(true)
    setError(null)
    try {
      if (sessionId !== '') {
        const updated = await apiRequest<AgentBuilderSession>(
          `/agent-builder/sessions/${sessionId}/apply`,
          { method: 'POST', body: { definition: applied } },
        )
        setMessages(updated.messages)
      }
      onApply(applied)
      setTurn(null)
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setLoading(false)
    }
  }

  const startNew = () => {
    onSessionId('')
    setMessages([])
    setTurn(null)
    setError(null)
    setNewSession(true)
  }

  const modes: { key: BuilderMode; label: string }[] = [
    { key: 'modify', label: t('studio.builderModeModify') },
    { key: 'explain', label: t('studio.builderModeExplain') },
    { key: 'fix', label: t('studio.builderModeFix') },
  ]

  return (
    <div className="flex h-full min-h-0">
      <section className="flex min-w-0 flex-1 flex-col border-r border-border">
        <div className="flex flex-wrap items-center gap-2 border-b border-border bg-surface px-4 py-2">
          <Sparkles className="h-4 w-4 text-accent" />
          <span className="text-sm font-medium text-ink">{t('studio.builderChat')}</span>
          <div className="ml-2 flex rounded-lg border border-border p-0.5">
            {modes.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setMode(item.key)}
                className={`rounded-md px-2.5 py-1 text-[11px] ${
                  mode === item.key ? 'bg-accent-soft text-accent' : 'text-ink-muted'
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-2">
            <PopoverSelect
              label={t('studio.builderModel')}
              value={choice}
              options={models.map((item) => ({
                value: `${item.provider_id}/${item.model}`,
                label: item.label,
              }))}
              onChange={setChoice}
            />
            <Button variant="ghost" size="sm" onClick={startNew}>
              <Plus className="h-3.5 w-3.5" />
              {t('studio.builderNewSession')}
            </Button>
          </div>
        </div>

        <div ref={scrollRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
          {messages.length === 0 && (
            <div className="rounded-card border border-dashed border-border p-4">
              <p className="text-sm font-medium text-ink">{t('studio.builderTitle')}</p>
              <p className="mt-1 text-xs text-ink-muted">{t('studio.builderLead')}</p>
              <p className="mt-2 text-[11px] text-ink-muted">
                {t('studio.builderPlaceholder')}
              </p>
            </div>
          )}
          {messages.map((message, index) => (
            <div
              key={`${message.created_at ?? index}-${index}`}
              className={
                message.role === 'user'
                  ? 'ml-auto max-w-[85%] rounded-2xl rounded-br-sm bg-accent px-3 py-2 text-sm text-[rgb(var(--accent-ink))]'
                  : 'mr-auto max-w-[90%] rounded-2xl rounded-bl-sm border border-border bg-surface px-3 py-2 text-sm text-ink'
              }
            >
              <p className="whitespace-pre-wrap">{message.content}</p>
              {message.role === 'assistant' && message.clarification && (
                <p className="mt-1 text-[11px] text-warning">
                  {t('studio.builderNeedsClarification')}: {message.clarification}
                </p>
              )}
              {message.role === 'assistant' && message.kind !== 'apply' && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {message.definition && <Badge tone="accent">{t('studio.builderHasPatch')}</Badge>}
                  {message.suggestions?.length ? (
                    <Badge tone="neutral">
                      {message.suggestions.length} {t('studio.builderSuggestions')}
                    </Badge>
                  ) : null}
                </div>
              )}
            </div>
          ))}
        </div>

        <div className="border-t border-border bg-surface px-4 py-3">
          {mode === 'fix' && lastRunId === null && (
            <p className="mb-2 text-[11px] text-warning">{t('studio.builderFixNeedsRun')}</p>
          )}
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder={t('studio.builderPrompt')}
            className="min-h-20 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink"
          />
          <div className="mt-2 flex items-center gap-3">
            <Button
              size="sm"
              disabled={loading || prompt.trim() === ''}
              onClick={() => void send()}
            >
              <Send className="h-3.5 w-3.5" />
              {loading
                ? stage !== ''
                  ? t(`studio.builderStage.${stage}`)
                  : t('studio.builderGenerating')
                : t('studio.builderSend')}
            </Button>
            {loading && (
              <Button size="sm" variant="secondary" onClick={cancelGeneration}>
                {t('studio.builderCancel')}
              </Button>
            )}
            {lastRunId !== null && mode === 'fix' && (
              <span className="text-[10px] text-ink-muted">run {lastRunId.slice(0, 8)}</span>
            )}
            {error !== null && <p className="text-xs text-danger">{error}</p>}
          </div>
        </div>
      </section>

      <aside className="w-[22rem] shrink-0 overflow-y-auto bg-surface px-4 py-4">
        <p className="text-sm font-medium text-ink">{t('studio.builderResult')}</p>
        {turn === null ? (
          <p className="mt-2 text-xs text-ink-muted">{t('studio.builderEmpty')}</p>
        ) : (
          <div className="mt-3 space-y-3">
            {turn.message && <p className="text-xs text-ink">{turn.message}</p>}
            {turn.missing_resources.length > 0 && (
              <div className="rounded-lg border border-warning/40 bg-warning/10 p-2">
                <p className="text-xs font-medium text-warning">
                  {t('studio.missingResources')}
                </p>
                <ul className="mt-1 list-inside list-disc text-[11px] text-ink">
                  {turn.missing_resources.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            )}
            {turn.suggestions.length > 0 && (
              <div>
                <p className="text-[11px] font-medium text-ink">
                  {t('studio.builderSuggestions')}
                </p>
                <ul className="mt-1 list-inside list-disc text-[11px] text-ink-muted">
                  {turn.suggestions.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            )}
            {turn.diff !== null && (
              <div className="rounded-lg border border-border p-2">
                <p className="mb-2 text-[11px] font-medium text-ink">
                  {t('studio.builderDiff')}
                </p>
                <DiffView
                  diff={turn.diff}
                  selection={selection}
                  onToggle={(key) =>
                    setSelection((current) => {
                      const next = new Set(current)
                      if (next.has(key)) next.delete(key)
                      else next.add(key)
                      return next
                    })
                  }
                />
                <p className="mt-2 text-[10px] text-ink-muted">
                  {t('studio.builderPartialHint')}
                </p>
              </div>
            )}
            {turn.clarification !== null &&
              turn.clarification !== undefined && (
                <div className="rounded-lg border border-warning/40 bg-warning/10 p-2 text-[11px] text-warning">
                  {t('studio.builderNeedsClarification')}: {turn.clarification}
                </div>
              )}
            {turn.definition !== null && (
              <div className="rounded-lg border border-border bg-surface-muted p-2">
                <p className="text-[10px] text-ink-muted">
                  {turn.definition.nodes.length} {t('studio.nodes')} ·{' '}
                  {turn.definition.edges.length} {t('studio.edges')}
                </p>
                <Button className="mt-2" size="sm" disabled={loading} onClick={() => void apply()}>
                  {t('studio.applyToCanvas')}
                </Button>
              </div>
            )}
          </div>
        )}
      </aside>
    </div>
  )
}