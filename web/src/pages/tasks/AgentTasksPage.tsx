import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, Check, Pause, Play, RefreshCw, Square, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { useSearchParams } from 'react-router-dom'

import {
  TaskPlanEditor,
  type EditableTaskStep,
} from '../../components/task/TaskPlanEditor'
import { TaskTimeline } from '../../components/task/TaskTimeline'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Input, Textarea } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorMessage } from '../../lib/errors'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import { streamTaskEvents } from '../../lib/sse'
import type {
  ChatTask,
  ChatTaskPlanStep,
  CustomAgent,
  KnowledgeBase,
  ModelEntry,
  PersonalModel,
  TaskEvent,
} from '../../lib/types'

function toDraftSteps(steps: ChatTaskPlanStep[]): EditableTaskStep[] {
  return steps.map((step) => ({
    title: step.title,
    detail: step.detail ?? '',
    query: step.query ?? '',
  }))
}

function statusTone(status: string): 'neutral' | 'accent' | 'warning' | 'danger' {
  if (status === 'completed') return 'accent'
  if (status === 'failed' || status === 'cancelled') return 'danger'
  if (status === 'waiting_approval' || status === 'paused') return 'warning'
  return 'neutral'
}

export function AgentTasksPage() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const [goal, setGoal] = useState('')
  const [agentId, setAgentId] = useState('')
  const [modelValue, setModelValue] = useState('auto::auto')
  const [selectedId, setSelectedId] = useState<string | null>(
    () => searchParams.get('task'),
  )
  const [draftSteps, setDraftSteps] = useState<EditableTaskStep[]>([])
  const [events, setEvents] = useState<TaskEvent[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [approvalNote, setApprovalNote] = useState('')
  const [saveKbId, setSaveKbId] = useState('')
  const [streamKey, setStreamKey] = useState(0)

  const tasks = useQuery({
    queryKey: ['agent-tasks'],
    queryFn: () => apiRequest<ChatTask[]>('/agent-tasks'),
  })
  const agents = useQuery({
    queryKey: ['agents', 'all'],
    queryFn: () => apiRequest<CustomAgent[]>('/agents?scope=all'),
  })
  const kbs = useQuery({
    queryKey: ['knowledge-bases'],
    queryFn: () => apiRequest<KnowledgeBase[]>('/knowledge-bases'),
  })
  const platformModels = useQuery({
    queryKey: ['models'],
    queryFn: () => apiRequest<ModelEntry[]>('/models'),
  })
  const personalModels = useQuery({
    queryKey: ['provider-configs', 'models'],
    queryFn: () => apiRequest<PersonalModel[]>('/provider-configs/models'),
  })

  const modelChoices = useMemo(() => {
    const choices = [{ value: 'auto::auto', label: t('tasks.autoModel') }]
    for (const model of personalModels.data ?? []) {
      choices.push({
        value: `${model.provider_id}::${model.model_id}`,
        label: `${model.display_name} · ${model.provider_name}`,
      })
    }
    for (const model of platformModels.data ?? []) {
      if (model.available) {
        choices.push({
          value: `${model.provider_id}::${model.model_id}`,
          label: `${model.display_name} · ${model.provider_id}`,
        })
      }
    }
    return choices
  }, [personalModels.data, platformModels.data, t])

  const customAgents = (agents.data ?? []).filter(
    (agent) => !agent.builtin && !agent.archived && agent.enabled,
  )
  const selected = useMemo(
    () => (tasks.data ?? []).find((task) => task.id === selectedId) ?? null,
    [selectedId, tasks.data],
  )
  const planLocked = selected?.plan.confirmed === true || selected?.status !== 'waiting_approval'

  useEffect(() => {
    if (selected !== null) setDraftSteps(toDraftSteps(selected.plan.steps ?? []))
  }, [selected?.id, selected?.plan.steps])

  useEffect(() => {
    if (selectedId === null) return
    setEvents([])
    const controller = new AbortController()
    void streamTaskEvents({
      taskId: selectedId,
      signal: controller.signal,
      onEvent: (event) => {
        if (event.data === null || typeof event.data !== 'object') return
        const seq = Number(event.id ?? 0)
        setEvents((previous) => [
          ...previous,
          {
            seq: Number.isFinite(seq) && seq > 0 ? seq : previous.length + 1,
            event: event.event,
            payload: event.data as Record<string, unknown>,
            created_at: '',
          },
        ])
        if (['task_completed', 'task_failed', 'approval_required'].includes(event.event)) {
          void queryClient.invalidateQueries({ queryKey: ['agent-tasks'] })
        }
      },
    }).catch(() => undefined)
    return () => controller.abort()
  }, [selectedId, streamKey, queryClient])

  const refresh = async (): Promise<void> => {
    await queryClient.invalidateQueries({ queryKey: ['agent-tasks'] })
    setStreamKey((value) => value + 1)
    setEvents([])
  }

  const create = async (): Promise<void> => {
    if (goal.trim() === '') return
    setBusy(true)
    setError(null)
    const [providerId, model] = modelValue.split('::')
    try {
      const task = await apiRequest<ChatTask>('/agent-tasks', {
        method: 'POST',
        body: {
          goal: goal.trim(),
          agent_id: agentId === '' ? null : agentId,
          provider_id: providerId,
          model,
          max_steps: 8,
        },
      })
      setGoal('')
      setSelectedId(task.id)
      await queryClient.invalidateQueries({ queryKey: ['agent-tasks'] })
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const savePlan = async (): Promise<boolean> => {
    if (selected === null) return false
    const steps = draftSteps.filter((step) => step.title.trim() !== '')
    if (steps.length === 0) {
      setError(t('tasks.stepsRequired'))
      return false
    }
    await apiRequest<ChatTask>(`/agent-tasks/${selected.id}/plan`, {
      method: 'PATCH',
      body: {
        steps: steps.map((step) => ({
          title: step.title.trim(),
          detail: step.detail.trim() || step.title.trim(),
        })),
      },
    })
    return true
  }

  const onSavePlan = async (): Promise<void> => {
    setBusy(true)
    setError(null)
    try {
      if (await savePlan()) await refresh()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const confirmPlan = async (): Promise<void> => {
    if (selected === null) return
    setBusy(true)
    setError(null)
    try {
      if (!(await savePlan())) return
      await apiRequest<ChatTask>(`/agent-tasks/${selected.id}/confirm`, { method: 'POST' })
      await refresh()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const control = async (action: 'pause' | 'resume' | 'cancel' | 'retry'): Promise<void> => {
    if (selected === null) return
    setBusy(true)
    setError(null)
    try {
      await apiRequest<ChatTask>(`/chat-tasks/${selected.id}/${action}`, { method: 'POST' })
      await refresh()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const decide = async (approvalId: string, decision: 'approve' | 'reject'): Promise<void> => {
    if (selected === null) return
    setBusy(true)
    setError(null)
    try {
      await apiRequest<ChatTask>(`/agent-tasks/${selected.id}/approval`, {
        method: 'POST',
        body: { approval_id: approvalId, decision, note: approvalNote },
      })
      setApprovalNote('')
      await refresh()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const saveToKnowledge = async (): Promise<void> => {
    if (selected === null || saveKbId === '') return
    setBusy(true)
    setError(null)
    try {
      await apiRequest(`/agent-tasks/${selected.id}/save-to-knowledge`, {
        method: 'POST',
        body: { kb_id: saveKbId, title: selected.title },
      })
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const pendingApprovals = (selected?.plan.approvals ?? []).filter(
    (approval) => approval.status === 'pending',
  )
  const text = selected?.result.text ?? ''
  const artifacts = selected?.result.artifacts ?? []

  return (
    <div className="flex h-full min-h-0">
      <aside className="w-80 shrink-0 overflow-y-auto border-r border-border bg-surface px-4 py-5">
        <h1 className="text-lg font-semibold">{t('agentTasks.title')}</h1>
        <p className="mt-1 text-xs text-ink-muted">{t('agentTasks.lead')}</p>
        <div className="mt-4 space-y-2">
          <Textarea
            rows={3}
            value={goal}
            placeholder={t('agentTasks.goalPlaceholder')}
            onChange={(event) => setGoal(event.target.value)}
          />
          <select
            className="h-9 w-full rounded-lg border border-border bg-surface px-2 text-sm"
            value={agentId}
            onChange={(event) => setAgentId(event.target.value)}
          >
            <option value="">{t('agentTasks.defaultTools')}</option>
            {customAgents.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.icon} {agent.name}
              </option>
            ))}
          </select>
          <select
            className="h-9 w-full rounded-lg border border-border bg-surface px-2 text-sm"
            value={modelValue}
            onChange={(event) => setModelValue(event.target.value)}
          >
            {modelChoices.map((choice) => (
              <option key={choice.value} value={choice.value}>
                {choice.label}
              </option>
            ))}
          </select>
          <Button className="w-full" disabled={busy || goal.trim() === ''} onClick={() => void create()}>
            <Bot className="h-4 w-4" />
            {t('agentTasks.create')}
          </Button>
        </div>
        <div className="mt-5 space-y-1">
          {(tasks.data ?? []).map((task) => (
            <button
              key={task.id}
              type="button"
              className={`w-full rounded-xl border px-3 py-2 text-left text-sm ${
                task.id === selectedId
                  ? 'border-accent bg-accent/5'
                  : 'border-border hover:bg-surface-muted'
              }`}
              onClick={() => setSelectedId(task.id)}
            >
              <span className="block truncate font-medium">{task.title}</span>
              <span className="mt-1 flex items-center gap-2">
                <Badge tone={statusTone(task.status)}>
                  {t(`tasks.status.${task.status}` as never)}
                </Badge>
                <span className="text-[11px] text-ink-muted">
                  {new Date(task.created_at).toLocaleString()}
                </span>
              </span>
            </button>
          ))}
          {tasks.data !== undefined && tasks.data.length === 0 && (
            <p className="text-xs text-ink-muted">{t('agentTasks.empty')}</p>
          )}
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-y-auto px-6 py-5">
        {error !== null && (
          <p className="mb-3 rounded-lg border border-danger/40 bg-danger/5 px-3 py-2 text-sm text-danger">
            {error}
          </p>
        )}
        {selected === null ? (
          <div className="rounded-2xl border border-dashed border-border px-6 py-16 text-center text-sm text-ink-muted">
            {t('agentTasks.selectHint')}
          </div>
        ) : (
          <div className="space-y-5">
            <header className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-semibold">{selected.title}</h2>
              <Badge tone={statusTone(selected.status)}>
                {t(`tasks.status.${selected.status}` as never)}
              </Badge>
              {selected.error_code !== null && (
                <span className="text-xs text-danger">{selected.error_code}</span>
              )}
              <span className="ml-auto flex flex-wrap gap-1">
                {selected.status === 'running' && (
                  <Button variant="secondary" size="sm" disabled={busy} onClick={() => void control('pause')}>
                    <Pause className="h-4 w-4" />
                    {t('tasks.pause')}
                  </Button>
                )}
                {(selected.status === 'paused' || selected.status === 'waiting_approval') && (
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={busy || selected.plan.confirmed !== true || pendingApprovals.length > 0}
                    onClick={() => void control('resume')}
                  >
                    <Play className="h-4 w-4" />
                    {t('tasks.resume')}
                  </Button>
                )}
                {!['completed', 'failed', 'cancelled'].includes(selected.status) && (
                  <Button variant="secondary" size="sm" disabled={busy} onClick={() => void control('cancel')}>
                    <Square className="h-4 w-4" />
                    {t('tasks.cancel')}
                  </Button>
                )}
                {selected.status === 'failed' && (
                  <Button variant="secondary" size="sm" disabled={busy} onClick={() => void control('retry')}>
                    <RefreshCw className="h-4 w-4" />
                    {t('tasks.retry')}
                  </Button>
                )}
              </span>
            </header>

            {pendingApprovals.length > 0 && (
              <section className="space-y-2 rounded-2xl border border-warning/40 bg-warning/5 p-4">
                <h3 className="text-sm font-semibold">{t('agentTasks.approvals')}</h3>
                {pendingApprovals.map((approval) => (
                  <div key={approval.id} className="rounded-xl border border-border bg-surface p-3">
                    <p className="text-sm font-medium">
                      {approval.tool}
                      <Badge tone="warning" className="ml-2">
                        {approval.risk}
                      </Badge>
                    </p>
                    <pre className="mt-1 max-h-32 overflow-auto rounded bg-surface-muted p-2 text-[11px]">
                      {JSON.stringify(approval.arguments, null, 2)}
                    </pre>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <Input
                        className="h-8 max-w-xs text-xs"
                        value={approvalNote}
                        placeholder={t('agentTasks.approvalNote')}
                        onChange={(event) => setApprovalNote(event.target.value)}
                      />
                      <Button size="sm" disabled={busy} onClick={() => void decide(approval.id, 'approve')}>
                        <Check className="h-4 w-4" />
                        {t('agentTasks.approve')}
                      </Button>
                      <Button
                        variant="secondary"
                        size="sm"
                        disabled={busy}
                        onClick={() => void decide(approval.id, 'reject')}
                      >
                        <X className="h-4 w-4" />
                        {t('agentTasks.reject')}
                      </Button>
                    </div>
                  </div>
                ))}
              </section>
            )}

            <section className="rounded-2xl border border-border bg-surface p-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold">{t('tasks.plan')}</h3>
                {selected.plan.confirmed === true && (
                  <Badge tone="accent">{t('tasks.planConfirmed')}</Badge>
                )}
              </div>
              <div className="mt-3">
                {planLocked ? (
                  <ol className="space-y-2">
                    {(selected.plan.steps ?? []).map((step) => (
                      <li key={step.index} className="rounded-xl border border-border px-3 py-2 text-sm">
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{step.title}</span>
                          <Badge
                            tone={
                              step.status === 'done'
                                ? 'accent'
                                : step.status === 'failed'
                                  ? 'danger'
                                  : 'neutral'
                            }
                          >
                            {t(`tasks.stepStatus.${step.status}` as never)}
                          </Badge>
                        </div>
                        {(step.detail ?? '') !== '' && (
                          <p className="mt-1 text-xs text-ink-muted">{step.detail}</p>
                        )}
                      </li>
                    ))}
                  </ol>
                ) : (
                  <>
                    <TaskPlanEditor steps={draftSteps} disabled={busy} onChange={setDraftSteps} />
                    <div className="mt-3 flex gap-2">
                      <Button variant="secondary" size="sm" disabled={busy} onClick={() => void onSavePlan()}>
                        {t('tasks.savePlan')}
                      </Button>
                      <Button size="sm" disabled={busy} onClick={() => void confirmPlan()}>
                        {t('tasks.confirmPlan')}
                      </Button>
                    </div>
                  </>
                )}
              </div>
            </section>

            <section className="rounded-2xl border border-border bg-surface p-4">
              <h3 className="text-sm font-semibold">{t('tasks.timeline')}</h3>
              <div className="mt-3 max-h-72 overflow-y-auto">
                <TaskTimeline events={events} />
              </div>
            </section>

            {text !== '' && (
              <section className="rounded-2xl border border-border bg-surface p-4">
                <h3 className="text-sm font-semibold">{t('agentTasks.output')}</h3>
                <div className="markdown mt-2 text-sm text-ink">
                  <ReactMarkdown>{text}</ReactMarkdown>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3">
                  <select
                    className="h-8 rounded-lg border border-border bg-surface px-2 text-xs"
                    value={saveKbId}
                    onChange={(event) => setSaveKbId(event.target.value)}
                  >
                    <option value="">{t('research.selectKb')}</option>
                    {(kbs.data ?? []).map((kb) => (
                      <option key={kb.id} value={kb.id}>
                        {kb.name}
                      </option>
                    ))}
                  </select>
                  <Button variant="secondary" size="sm" disabled={busy || saveKbId === ''} onClick={() => void saveToKnowledge()}>
                    {t('research.saveToKb')}
                  </Button>
                </div>
              </section>
            )}

            {artifacts.length > 0 && (
              <section className="space-y-2 rounded-2xl border border-border bg-surface p-4">
                <h3 className="text-sm font-semibold">{t('agentTasks.artifacts')}</h3>
                {artifacts.map((artifact, index) => (
                  <div key={index} className="rounded-xl border border-border">
                    <div className="flex items-center gap-2 border-b border-border px-3 py-1.5 text-xs text-ink-muted">
                      <span>{artifact.title}</span>
                      <Badge tone="neutral">{artifact.language}</Badge>
                    </div>
                    <pre className="max-h-64 overflow-auto p-3 text-xs">
                      <code>{artifact.content}</code>
                    </pre>
                  </div>
                ))}
              </section>
            )}
          </div>
        )}
        {busy && (
          <div className="mt-3 flex items-center gap-2 text-xs text-ink-muted">
            <Spinner />
            {t('common.loading')}
          </div>
        )}
      </main>
    </div>
  )
}