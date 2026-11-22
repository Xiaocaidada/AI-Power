import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Ban, Play } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Textarea } from '../../components/ui/input'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import { streamRunEvents } from '../../lib/sse'
import type {
  CollaborationRun,
  KnowledgeBase,
  ModelEntry,
  RunAccepted,
} from '../../lib/types'
import { cn } from '../../lib/utils'

interface LiveStep {
  key: string
  role: string
  status: string
  output?: string
  durationMs?: number
}

function statusTone(status: string): 'success' | 'danger' | 'accent' | 'neutral' {
  if (status === 'completed' || status === 'accept') return 'success'
  if (status === 'failed' || status === 'revise') return 'danger'
  if (status === 'queued' || status === 'running') return 'accent'
  return 'neutral'
}

export function CollaborationsPage() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const queryRun = searchParams.get('run')
  const [activeRunId, setActiveRunId] = useState<string | null>(queryRun)
  const [input, setInput] = useState('比较一下知识库里的两种方案，并给出建议。')
  const [modelKey, setModelKey] = useState('')
  const [kbId, setKbId] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [steps, setSteps] = useState<LiveStep[]>([])
  const [plan, setPlan] = useState<{ id: string; agent: string; task: string }[]>([])
  const [finalOutput, setFinalOutput] = useState('')
  const [runResult, setRunResult] = useState<CollaborationRun | null>(null)
  const [error, setError] = useState<string | null>(null)

  const models = useQuery({
    queryKey: ['models'],
    queryFn: () => apiRequest<ModelEntry[]>('/models'),
    staleTime: 60_000,
  })
  const kbs = useQuery({
    queryKey: ['kbs'],
    queryFn: () => apiRequest<KnowledgeBase[]>('/knowledge-bases'),
    staleTime: 60_000,
  })
  const runs = useQuery({
    queryKey: ['collaboration-runs'],
    queryFn: () => apiRequest<CollaborationRun[]>('/collaborations/runs?limit=20'),
  })
  const available = (models.data ?? []).filter((model) => model.available)
  const selected = available.find((model) => `${model.provider_id}|${model.model_id}` === modelKey)
  const activeModel = selected ?? available[0]

  useEffect(() => {
    setActiveRunId(queryRun)
  }, [queryRun])

  const upsert = (next: LiveStep) => {
    setSteps((previous) => {
      const index = previous.findIndex((step) => step.key === next.key)
      if (index === -1) return [...previous, next]
      const copy = [...previous]
      copy[index] = { ...copy[index], ...next }
      return copy
    })
  }

  useEffect(() => {
    if (activeRunId === null) return
    const controller = new AbortController()
    setStreaming(true)
    setError(null)
    setSteps([])
    setPlan([])
    setFinalOutput('')
    setRunResult(null)
    streamRunEvents({
      path: `/collaborations/runs/${activeRunId}/events`,
      signal: controller.signal,
      onEvent: (event) => {
        const data = event.data as Record<string, unknown>
        if (event.event === 'planner_start') {
          upsert({ key: 'planner', role: 'planner', status: 'running' })
        } else if (event.event === 'planner_end') {
          setPlan((data.tasks as { id: string; agent: string; task: string }[]) ?? [])
          upsert({ key: 'planner', role: 'planner', status: 'completed' })
        } else if (event.event === 'worker_start') {
          upsert({
            key: `worker-${String(data.task_id)}`,
            role: 'worker',
            status: 'running',
          })
        } else if (event.event === 'worker_end') {
          upsert({
            key: `worker-${String(data.task_id)}`,
            role: 'worker',
            status: String(data.status),
            output: data.output === undefined ? undefined : String(data.output),
            durationMs: Number(data.duration_ms ?? 0),
          })
        } else if (event.event === 'critic_start') {
          upsert({
            key: `critic-${String(data.round)}`,
            role: 'critic',
            status: 'running',
          })
        } else if (event.event === 'critic_end') {
          upsert({
            key: `critic-${String(data.round)}`,
            role: 'critic',
            status: String(data.verdict),
            durationMs: Number(data.duration_ms ?? 0),
            output: data.feedback === undefined ? undefined : String(data.feedback),
          })
        } else if (event.event === 'collaboration_end') {
          if (data.output !== undefined) setFinalOutput(String(data.output))
          if (data.error_code !== undefined) setError(String(data.error_code))
        }
      },
    })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(t(errorTextKey(caught)))
      })
      .finally(() => {
        if (controller.signal.aborted) return
        setStreaming(false)
        void apiRequest<CollaborationRun>(`/collaborations/runs/${activeRunId}`)
          .then(setRunResult)
          .catch(() => undefined)
        void queryClient.invalidateQueries({ queryKey: ['collaboration-runs'] })
      })
    return () => controller.abort()
  }, [activeRunId, queryClient, t])

  const openRun = (runId: string) => {
    setActiveRunId(runId)
    setSearchParams({ run: runId })
  }

  const run = async () => {
    if (activeModel === undefined || input.trim() === '') return
    setSubmitting(true)
    setError(null)
    try {
      const created = await apiRequest<RunAccepted>('/collaborations/runs', {
        method: 'POST',
        body: {
          input: input.trim(),
          provider_id: activeModel.provider_id,
          model: activeModel.model_id,
          kb_id: kbId === '' ? null : kbId,
        },
      })
      openRun(created.run_id)
      await queryClient.invalidateQueries({ queryKey: ['collaboration-runs'] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setSubmitting(false)
    }
  }

  const cancel = async () => {
    if (activeRunId === null) return
    try {
      await apiRequest(`/collaborations/runs/${activeRunId}/cancel`, { method: 'POST' })
      await queryClient.invalidateQueries({ queryKey: ['collaboration-runs'] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    }
  }

  const activeRun = (runs.data ?? []).find((item) => item.id === activeRunId)
  const activeStatus = activeRun?.status ?? runResult?.status
  const canCancel = activeStatus === 'queued' || activeStatus === 'running'

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-4">
        <h1 className="text-lg font-semibold">{t('collaboration.title')}</h1>
        <p className="mt-1 text-sm text-ink-muted">{t('collaboration.lead')}</p>
      </header>

      <div className="mx-auto w-full max-w-4xl space-y-5 px-6 py-6">
        <section className="rounded-card border border-border bg-surface p-4">
          <Textarea
            className="min-h-24 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder={t('collaboration.input')}
          />
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <label className="text-xs text-ink-muted">
              <span className="mb-1 block">{t('collaboration.model')}</span>
              <select
                className="h-9 rounded-lg border border-border bg-surface px-2 text-sm"
                value={modelKey}
                onChange={(event) => setModelKey(event.target.value)}
              >
                {available.map((model) => (
                  <option
                    key={`${model.provider_id}|${model.model_id}`}
                    value={`${model.provider_id}|${model.model_id}`}
                  >
                    {model.display_name} · {model.provider_id}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-ink-muted">
              <span className="mb-1 block">{t('collaboration.kb')}</span>
              <select
                className="h-9 rounded-lg border border-border bg-surface px-2 text-sm"
                value={kbId}
                onChange={(event) => setKbId(event.target.value)}
              >
                <option value="">{t('collaboration.noKb')}</option>
                {(kbs.data ?? []).map((kb) => (
                  <option key={kb.id} value={kb.id}>
                    {kb.name}
                  </option>
                ))}
              </select>
            </label>
            <Button
              size="sm"
              disabled={submitting || activeModel === undefined}
              onClick={() => void run()}
            >
              <Play className="h-3.5 w-3.5" />
              {submitting ? t('collaboration.running') : t('collaboration.run')}
            </Button>
            {canCancel && activeRunId !== null && (
              <Button variant="secondary" size="sm" onClick={() => void cancel()}>
                <Ban className="h-3.5 w-3.5" />
                {t('runs.cancel')}
              </Button>
            )}
            {activeStatus !== undefined && (
              <span className="text-xs text-ink-muted">
                {activeStatus}
                {streaming ? ` · ${t('collaboration.running')}` : ''}
              </span>
            )}
          </div>
          {error !== null && (
            <p role="alert" className="mt-3 rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
              {error}
            </p>
          )}
        </section>

        <section className="rounded-card border border-border bg-surface p-4">
          <h2 className="text-sm font-medium">{t('runs.history')}</h2>
          {(runs.data?.length ?? 0) === 0 ? (
            <p className="mt-2 text-sm text-ink-muted">{t('runs.empty')}</p>
          ) : (
            <ul className="mt-2 divide-y divide-border text-sm">
              {runs.data?.map((item) => (
                <li key={item.id} className="flex flex-wrap items-center gap-2 py-2">
                  <button
                    type="button"
                    onClick={() => openRun(item.id)}
                    className={cn(
                      'flex flex-1 flex-wrap items-center gap-2 text-left',
                      item.id === activeRunId ? 'text-accent' : 'text-ink',
                    )}
                  >
                    <span className="font-mono text-xs">{item.id.slice(0, 8)}</span>
                    <Badge tone={statusTone(item.status)}>{item.status}</Badge>
                    <span className="text-xs text-ink-muted">
                      {item.rounds} rounds · {item.prompt_tokens + item.completion_tokens} tokens
                    </span>
                  </button>
                  {(item.status === 'queued' || item.status === 'running') && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        void apiRequest(`/collaborations/runs/${item.id}/cancel`, {
                          method: 'POST',
                        }).then(() =>
                          queryClient.invalidateQueries({ queryKey: ['collaboration-runs'] }),
                        )
                      }}
                    >
                      <Ban className="h-3 w-3" />
                      {t('runs.cancel')}
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        {plan.length > 0 && (
          <section className="rounded-card border border-border bg-surface p-4">
            <h2 className="text-sm font-medium">{t('collaboration.plan')}</h2>
            <ul className="mt-2 space-y-1 text-sm">
              {plan.map((task) => (
                <li key={task.id} className="flex flex-wrap items-center gap-2">
                  <Badge tone="accent">{task.agent}</Badge>
                  <span className="font-mono text-xs text-ink-muted">{task.id}</span>
                  <span className="text-ink">{task.task}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="rounded-card border border-border bg-surface p-4">
          <h2 className="text-sm font-medium">{t('collaboration.timeline')}</h2>
          {steps.length === 0 && (
            <p className="mt-2 text-sm text-ink-muted">{t('collaboration.noRun')}</p>
          )}
          <ol className="mt-3 space-y-2">
            {steps.map((step) => (
              <li key={step.key} className="rounded-lg border border-border px-3 py-2 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge
                    tone={
                      step.role === 'planner'
                        ? 'accent'
                        : step.role === 'critic'
                          ? 'warning'
                          : 'neutral'
                    }
                  >
                    {step.role}
                  </Badge>
                  <span className="font-mono text-xs text-ink-muted">{step.key}</span>
                  <span
                    className={
                      step.status === 'failed' || step.status === 'revise'
                        ? 'text-xs text-danger'
                        : 'text-xs text-ink-muted'
                    }
                  >
                    {step.status}
                  </span>
                  {step.durationMs !== undefined && (
                    <span className="text-[11px] text-ink-muted">
                      {Math.round(step.durationMs)} ms
                    </span>
                  )}
                </div>
                {step.output !== undefined && step.output !== '' && (
                  <p className="mt-1 line-clamp-3 text-xs text-ink-muted">{step.output}</p>
                )}
              </li>
            ))}
          </ol>
          {runResult !== null && (
            <p className="mt-2 text-[11px] text-ink-muted">
              {runResult.status} · {runResult.rounds} rounds ·{' '}
              {runResult.prompt_tokens + runResult.completion_tokens} tokens
            </p>
          )}
        </section>

        {finalOutput !== '' && (
          <section className="rounded-card border border-border bg-surface p-4">
            <h2 className="text-sm font-medium">{t('collaboration.output')}</h2>
            <p className="mt-2 whitespace-pre-wrap text-sm text-ink">{finalOutput}</p>
          </section>
        )}
      </div>
    </div>
  )
}