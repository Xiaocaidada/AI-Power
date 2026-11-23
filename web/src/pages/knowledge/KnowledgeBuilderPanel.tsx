import { useQuery } from '@tanstack/react-query'
import { Check, Plus, Send, Sparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  AgentBuilderMessage,
  AgentBuilderSession,
  AgentBuilderTurn,
  ModelEntry,
  PersonalModel,
  WorkflowDefinition,
} from '../../lib/types'
import { DiffView } from '../studio/StudioBuilderPanel'

type BuilderMode = 'generate' | 'modify' | 'explain' | 'fix'
type KnowledgeScope = 'knowledge_process' | 'knowledge_retrieval'

interface KnowledgeBuilderPanelProps {
  scope: KnowledgeScope
  workflowId: string
  definition: WorkflowDefinition
  lastRunId: string | null
  onApply: (definition: WorkflowDefinition) => void
}

function modelOptions(
  platform: ModelEntry[],
  personal: PersonalModel[],
): { value: string; label: string }[] {
  return [
    ...platform
      .filter((item) => item.available)
      .map((item) => ({
        value: `m:${item.provider_id}:${item.model_id}`,
        label: `${item.display_name} · ${item.provider_id}`,
      })),
    ...personal.map((item) => ({
      value: `m:${item.provider_id}:${item.model_id}`,
      label: `${item.display_name} · ${item.provider_name}`,
    })),
  ]
}

function parseChoice(choice: string): { providerId: string; model: string } {
  const [, provider, ...rest] = choice.split(':')
  return { providerId: provider ?? '', model: rest.join(':') }
}

export function KnowledgeBuilderPanel({
  scope,
  workflowId,
  definition,
  lastRunId,
  onApply,
}: KnowledgeBuilderPanelProps) {
  const { t } = useI18n()
  const [sessionId, setSessionId] = useState('')
  const [choice, setChoice] = useState('')
  const [mode, setMode] = useState<BuilderMode>('modify')
  const [prompt, setPrompt] = useState('')
  const [messages, setMessages] = useState<AgentBuilderMessage[]>([])
  const [turn, setTurn] = useState<AgentBuilderTurn | null>(null)
  const [loading, setLoading] = useState(false)
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)

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
  const sessions = useQuery({
    queryKey: ['knowledge-builder-sessions', scope, workflowId],
    queryFn: () =>
      apiRequest<AgentBuilderSession[]>(
        `/agent-builder/sessions?${new URLSearchParams({
          scope,
          ...(workflowId !== '' ? { workflow_id: workflowId } : {}),
        }).toString()}`,
      ),
    enabled: workflowId !== '',
  })

  const options = modelOptions(
    platformModels.data ?? [],
    personalModels.data ?? [],
  )

  useEffect(() => {
    if (choice === '' && options.length > 0) setChoice(options[0].value)
  }, [choice, options])

  useEffect(() => {
    if (sessionId !== '' || sessions.data === undefined) return
    const latest = sessions.data[0]
    if (latest === undefined) return
    setSessionId(latest.id)
    setMessages(latest.messages)
    const option = options.find(
      (item) => item.value === `m:${latest.provider_id}:${latest.model}`,
    )
    if (option) setChoice(option.value)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessions.data, sessionId])

  useEffect(() => {
    if (scrollRef.current !== null) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages.length, turn])

  const ensureSession = async (): Promise<string> => {
    if (sessionId !== '') return sessionId
    if (choice === '') throw new Error(t('knowledgeBuilder.noModel'))
    const parsed = parseChoice(choice)
    const created = await apiRequest<AgentBuilderSession>('/agent-builder/sessions', {
      method: 'POST',
      body: {
        scope,
        workflow_id: workflowId === '' ? null : workflowId,
        provider_id: parsed.providerId,
        model: parsed.model,
        draft_definition: definition,
      },
    })
    setSessionId(created.id)
    return created.id
  }

  const send = async () => {
    if (prompt.trim() === '' || workflowId === '') return
    setLoading(true)
    setError(null)
    setTurn(null)
    try {
      const active = await ensureSession()
      const body = {
        kind: mode,
        prompt: prompt.trim(),
        current_definition: definition,
        ...(mode === 'fix' && lastRunId !== null ? { run_id: lastRunId } : {}),
      }
      const result = await apiRequest<AgentBuilderTurn>(
        `/agent-builder/sessions/${active}/messages`,
        { method: 'POST', body },
      )
      setMessages((current) => [
        ...current,
        { role: 'user', kind: mode, content: prompt.trim() },
        {
          role: 'assistant',
          kind: mode,
          content: result.message,
          summary: result.message,
          definition: result.definition,
          diff: result.diff,
          missing_resources: result.missing_resources,
          suggestions: result.suggestions,
        },
      ])
      setTurn(result)
      setPrompt('')
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setLoading(false)
    }
  }

  const apply = async () => {
    if (turn?.definition === null || turn?.definition === undefined) return
    setApplying(true)
    setError(null)
    try {
      const active = await ensureSession()
      await apiRequest(`/agent-builder/sessions/${active}/apply`, {
        method: 'POST',
        body: { definition: turn.definition },
      })
      onApply(turn.definition)
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setApplying(false)
    }
  }

  const newSession = () => {
    setSessionId('')
    setMessages([])
    setTurn(null)
  }

  if (workflowId === '') {
    return (
      <div className="flex flex-1 items-center justify-center p-8 text-sm text-ink-muted">
        {t('knowledgeBuilder.needWorkflow')}
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1">
      <section className="flex min-w-0 flex-1 flex-col p-4">
        <div className="flex flex-wrap items-center gap-2">
          <Sparkles className="h-4 w-4 text-accent" />
          <p className="text-sm font-medium text-ink">{t('knowledgeBuilder.title')}</p>
          <select
            value={choice}
            onChange={(event) => setChoice(event.target.value)}
            className="ml-auto h-8 max-w-64 rounded-lg border border-border bg-surface px-2 text-xs text-ink"
          >
            {options.length === 0 && (
              <option value="">{t('knowledgeBuilder.noModel')}</option>
            )}
            {options.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
          <Button size="sm" variant="secondary" onClick={newSession}>
            <Plus className="h-3.5 w-3.5" />
            {t('knowledgeBuilder.newSession')}
          </Button>
        </div>

        <div
          ref={scrollRef}
          className="mt-3 min-h-0 flex-1 space-y-2 overflow-y-auto rounded-card border border-border bg-surface p-3"
        >
          {messages.length === 0 && (
            <p className="text-xs text-ink-muted">{t('knowledgeBuilder.lead')}</p>
          )}
          {messages.map((message, index) => (
            <div
              key={`${index}-${message.role}`}
              className={
                message.role === 'user'
                  ? 'ml-auto max-w-[85%] rounded-xl rounded-br-sm bg-accent px-3 py-2 text-xs text-[rgb(var(--accent-ink))]'
                  : 'mr-auto max-w-[90%] whitespace-pre-wrap rounded-xl rounded-bl-sm bg-surface-muted px-3 py-2 text-xs text-ink'
              }
            >
              {message.content}
            </div>
          ))}
          {turn?.diff && (
            <div className="rounded-lg border border-border bg-canvas p-3">
              <p className="text-xs font-medium text-ink">
                {t('knowledgeBuilder.diff')}
              </p>
              <div className="mt-2">
                <DiffView diff={turn.diff} />
              </div>
            </div>
          )}
          {turn !== null && turn.missing_resources.length > 0 && (
            <div className="rounded-lg bg-warning/10 px-3 py-2 text-xs text-warning">
              {t('knowledgeBuilder.missing')}: {turn.missing_resources.join(', ')}
            </div>
          )}
          {turn !== null && turn.suggestions.length > 0 && (
            <div className="rounded-lg bg-surface-muted px-3 py-2">
              <p className="text-xs font-medium text-ink">
                {t('knowledgeBuilder.suggestions')}
              </p>
              <ul className="mt-1 list-inside list-disc text-[11px] text-ink-muted">
                {turn.suggestions.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          )}
          {error !== null && <p className="text-xs text-danger">{error}</p>}
        </div>

        <div className="mt-3 rounded-card border border-border bg-surface p-3">
          <div className="flex flex-wrap gap-1">
            {(
              [
                'generate',
                'modify',
                'explain',
                ...(lastRunId !== null ? (['fix'] as const) : []),
              ] as BuilderMode[]
            ).map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => setMode(item)}
                className={
                  mode === item
                    ? 'rounded-md bg-accent-soft px-2.5 py-1 text-[11px] text-accent'
                    : 'rounded-md px-2.5 py-1 text-[11px] text-ink-muted hover:bg-surface-muted'
                }
              >
                {t(`knowledgeBuilder.mode.${item}`)}
              </button>
            ))}
          </div>
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder={t('knowledgeBuilder.placeholder')}
            className="mt-2 min-h-20 w-full rounded-lg border border-border bg-surface px-3 py-2 text-xs text-ink"
          />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              disabled={loading || prompt.trim() === ''}
              onClick={() => void send()}
            >
              {loading ? (
                <Spinner className="h-3.5 w-3.5" />
              ) : (
                <Send className="h-3.5 w-3.5" />
              )}
              {t('knowledgeBuilder.send')}
            </Button>
            {turn?.definition !== null && turn?.definition !== undefined && (
              <Button
                size="sm"
                variant="secondary"
                disabled={applying}
                onClick={() => void apply()}
              >
                <Check className="h-3.5 w-3.5" />
                {t('knowledgeBuilder.apply')}
              </Button>
            )}
            {mode === 'fix' && lastRunId === null && (
              <Badge tone="warning">{t('knowledgeBuilder.fixHint')}</Badge>
            )}
          </div>
        </div>
      </section>
    </div>
  )
}