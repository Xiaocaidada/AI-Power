import { useQuery, useQueryClient } from '@tanstack/react-query'
import { FlaskConical, Pause, Play, RefreshCw, Square } from 'lucide-react'
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
  KnowledgeBase,
  ModelEntry,
  PersonalModel,
  Project,
  SearchProvider,
  TaskEvent,
} from '../../lib/types'

const SECTION_KEYS = ['background', 'method', 'findings', 'comparison', 'conclusion'] as const

interface ModelChoice {
  value: string
  label: string
}

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

export function ResearchPage() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const [topic, setTopic] = useState('')
  const [scope, setScope] = useState<'web' | 'knowledge' | 'hybrid'>('web')
  const [modelValue, setModelValue] = useState('auto::auto')
  const [language, setLanguage] = useState<'zh' | 'en'>('zh')
  const [searchProviderId, setSearchProviderId] = useState('')
  const [kbId, setKbId] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(
    () => searchParams.get('task'),
  )
  const [draftSteps, setDraftSteps] = useState<EditableTaskStep[]>([])
  const [events, setEvents] = useState<TaskEvent[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [followup, setFollowup] = useState('')
  const [regenerateSection, setRegenerateSection] = useState<string>('findings')
  const [regenerateNote, setRegenerateNote] = useState('')
  const [saveKbId, setSaveKbId] = useState('')
  const [saveProjectId, setSaveProjectId] = useState('')
  const [streamKey, setStreamKey] = useState(0)

  const tasks = useQuery({
    queryKey: ['research-tasks'],
    queryFn: () => apiRequest<ChatTask[]>('/research/tasks'),
  })
  const kbs = useQuery({
    queryKey: ['knowledge-bases'],
    queryFn: () => apiRequest<KnowledgeBase[]>('/knowledge-bases'),
  })
  const projects = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiRequest<Project[]>('/projects'),
  })
  const searchProviders = useQuery({
    queryKey: ['search-providers'],
    queryFn: () => apiRequest<SearchProvider[]>('/search-providers'),
  })
  const platformModels = useQuery({
    queryKey: ['models'],
    queryFn: () => apiRequest<ModelEntry[]>('/models'),
  })
  const personalModels = useQuery({
    queryKey: ['provider-configs', 'models'],
    queryFn: () => apiRequest<PersonalModel[]>('/provider-configs/models'),
  })

  const modelChoices = useMemo<ModelChoice[]>(() => {
    const choices: ModelChoice[] = [{ value: 'auto::auto', label: t('tasks.autoModel') }]
    for (const model of personalModels.data ?? []) {
      choices.push({
        value: `${model.provider_id}::${model.model_id}`,
        label: `${model.display_name} · ${model.provider_name}`,
      })
    }
    for (const model of platformModels.data ?? []) {
      if (!model.available) continue
      choices.push({
        value: `${model.provider_id}::${model.model_id}`,
        label: `${model.display_name} · ${model.provider_id}`,
      })
    }
    return choices
  }, [personalModels.data, platformModels.data, t])

  const selected = useMemo(
    () => (tasks.data ?? []).find((task) => task.id === selectedId) ?? null,
    [selectedId, tasks.data],
  )
  const enabledSearch = (searchProviders.data ?? []).filter((item) => item.enabled)
  const needsKnowledge = scope === 'knowledge' || scope === 'hybrid'
  const planLocked = selected?.plan.confirmed === true || selected?.status !== 'waiting_approval'

  useEffect(() => {
    if (selected !== null) {
      setDraftSteps(toDraftSteps(selected.plan.steps ?? []))
    }
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
        if (event.event === 'task_completed' || event.event === 'task_failed') {
          void queryClient.invalidateQueries({ queryKey: ['research-tasks'] })
        }
      },
    }).catch(() => undefined)
    return () => controller.abort()
  }, [selectedId, streamKey, queryClient])

  const refresh = async (): Promise<void> => {
    await queryClient.invalidateQueries({ queryKey: ['research-tasks'] })
    setStreamKey((value) => value + 1)
    setEvents([])
  }

  const create = async (): Promise<void> => {
    if (topic.trim() === '') return
    setBusy(true)
    setError(null)
    const [providerId, model] = modelValue.split('::')
    try {
      const task = await apiRequest<ChatTask>('/research/tasks', {
        method: 'POST',
        body: {
          topic: topic.trim(),
          provider_id: providerId,
          model,
          scope,
          language,
          kb_ids: needsKnowledge && kbId !== '' ? [kbId] : [],
          search_provider_id: searchProviderId === '' ? null : searchProviderId,
          max_steps: 5,
        },
      })
      setTopic('')
      setSelectedId(task.id)
      await queryClient.invalidateQueries({ queryKey: ['research-tasks'] })
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
    await apiRequest<ChatTask>(`/research/tasks/${selected.id}/plan`, {
      method: 'PATCH',
      body: {
        steps: steps.map((step) => ({
          title: step.title.trim(),
          query: step.query.trim() || step.title.trim(),
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
      await apiRequest<ChatTask>(`/research/tasks/${selected.id}/confirm`, { method: 'POST' })
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

  const runFollowup = async (): Promise<void> => {
    if (selected === null || followup.trim() === '') return
    setBusy(true)
    setError(null)
    try {
      await apiRequest(`/research/tasks/${selected.id}/followup`, {
        method: 'POST',
        body: { question: followup.trim() },
      })
      setFollowup('')
      await queryClient.invalidateQueries({ queryKey: ['research-tasks'] })
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const regenerate = async (): Promise<void> => {
    if (selected === null) return
    setBusy(true)
    setError(null)
    try {
      await apiRequest(`/research/tasks/${selected.id}/sections/${regenerateSection}/regenerate`, {
        method: 'POST',
        body: { section: regenerateSection, instruction: regenerateNote.trim() },
      })
      setRegenerateNote('')
      await queryClient.invalidateQueries({ queryKey: ['research-tasks'] })
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
      await apiRequest(`/research/tasks/${selected.id}/save-to-knowledge`, {
        method: 'POST',
        body: { kb_id: saveKbId, title: selected.title },
      })
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const saveToProject = async (): Promise<void> => {
    if (selected === null || saveProjectId === '') return
    setBusy(true)
    setError(null)
    try {
      await apiRequest(`/research/tasks/${selected.id}/save-to-project`, {
        method: 'POST',
        body: {
          project_id: saveProjectId,
          kb_id: saveKbId === '' ? null : saveKbId,
          title: selected.title,
        },
      })
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const report = selected?.result.report ?? ''
  const sources = selected?.result.sources ?? []
  const conflicts = selected?.result.conflicts ?? []
  const followups = selected?.result.followups ?? []

  return (
    <div className="flex h-full min-h-0">
      <aside className="w-80 shrink-0 overflow-y-auto border-r border-border bg-surface px-4 py-5">
        <h1 className="text-lg font-semibold">{t('research.title')}</h1>
        <p className="mt-1 text-xs text-ink-muted">{t('research.lead')}</p>
        <div className="mt-4 space-y-2">
          <Textarea
            rows={3}
            value={topic}
            placeholder={t('research.topicPlaceholder')}
            onChange={(event) => setTopic(event.target.value)}
          />
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
          <select
            className="h-9 w-full rounded-lg border border-border bg-surface px-2 text-sm"
            value={scope}
            onChange={(event) => setScope(event.target.value as typeof scope)}
          >
            <option value="web">{t('research.scopeWeb')}</option>
            <option value="knowledge">{t('research.scopeKnowledge')}</option>
            <option value="hybrid">{t('research.scopeHybrid')}</option>
          </select>
          {scope !== 'knowledge' && (
            <select
              className="h-9 w-full rounded-lg border border-border bg-surface px-2 text-sm"
              value={searchProviderId}
              onChange={(event) => setSearchProviderId(event.target.value)}
            >
              <option value="">{t('research.defaultSearch')}</option>
              {enabledSearch.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.name}
                </option>
              ))}
            </select>
          )}
          {needsKnowledge && (
            <select
              className="h-9 w-full rounded-lg border border-border bg-surface px-2 text-sm"
              value={kbId}
              onChange={(event) => setKbId(event.target.value)}
            >
              <option value="">{t('research.selectKb')}</option>
              {(kbs.data ?? []).map((kb) => (
                <option key={kb.id} value={kb.id}>
                  {kb.name}
                </option>
              ))}
            </select>
          )}
          <select
            className="h-9 w-full rounded-lg border border-border bg-surface px-2 text-sm"
            value={language}
            onChange={(event) => setLanguage(event.target.value as typeof language)}
          >
            <option value="zh">{t('research.languageZh')}</option>
            <option value="en">{t('research.languageEn')}</option>
          </select>
          <Button className="w-full" disabled={busy || topic.trim() === ''} onClick={() => void create()}>
            <FlaskConical className="h-4 w-4" />
            {t('research.create')}
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
            <p className="text-xs text-ink-muted">{t('research.empty')}</p>
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
            {t('research.selectHint')}
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
                    disabled={busy || selected.plan.confirmed !== true}
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
                          {step.error_code !== undefined && (
                            <span className="text-[11px] text-danger">{step.error_code}</span>
                          )}
                          <span className="ml-auto text-[11px] text-ink-muted">
                            {step.query ?? ''}
                          </span>
                        </div>
                        {step.summary !== undefined && step.summary !== '' && (
                          <p className="mt-1 line-clamp-3 text-xs text-ink-muted">{step.summary}</p>
                        )}
                      </li>
                    ))}
                  </ol>
                ) : (
                  <>
                    <TaskPlanEditor
                      steps={draftSteps}
                      disabled={busy}
                      showQuery
                      onChange={setDraftSteps}
                    />
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

            {report !== '' && (
              <section className="rounded-2xl border border-border bg-surface p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-sm font-semibold">{t('research.report')}</h3>
                  <span className="ml-auto flex flex-wrap items-center gap-1">
                    <select
                      className="h-8 rounded-lg border border-border bg-surface px-2 text-xs"
                      value={regenerateSection}
                      onChange={(event) => setRegenerateSection(event.target.value)}
                    >
                      {SECTION_KEYS.map((key) => (
                        <option key={key} value={key}>
                          {t(`research.section.${key}` as never)}
                        </option>
                      ))}
                    </select>
                    <Input
                      className="h-8 w-48 text-xs"
                      value={regenerateNote}
                      placeholder={t('research.regenerateHint')}
                      onChange={(event) => setRegenerateNote(event.target.value)}
                    />
                    <Button variant="secondary" size="sm" disabled={busy} onClick={() => void regenerate()}>
                      {t('research.regenerate')}
                    </Button>
                  </span>
                </div>
                <div className="markdown mt-3 text-sm text-ink">
                  <ReactMarkdown>{report}</ReactMarkdown>
                </div>
              </section>
            )}

            {conflicts.length > 0 && (
              <section className="rounded-2xl border border-warning/40 bg-warning/5 p-4">
                <h3 className="text-sm font-semibold">{t('research.conflicts')}</h3>
                <ul className="mt-2 space-y-2 text-sm">
                  {conflicts.map((conflict) => (
                    <li key={conflict.topic}>
                      <p className="font-medium">{conflict.topic}</p>
                      <p className="text-ink-muted">{conflict.positions}</p>
                      <p className="text-xs text-ink-muted">
                        {conflict.sources.map((index) => `[${index}]`).join(' ')}
                      </p>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {sources.length > 0 && (
              <section className="rounded-2xl border border-border bg-surface p-4">
                <h3 className="text-sm font-semibold">{t('research.sources')}</h3>
                <ol className="mt-2 space-y-1 text-sm">
                  {sources.map((source) => (
                    <li key={`${source.index}-${source.url}`} className="flex gap-2">
                      <span className="text-ink-muted">[{source.index}]</span>
                      {source.kind === 'web' ? (
                        <a
                          className="min-w-0 flex-1 truncate text-accent hover:underline"
                          href={source.url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {source.title}
                        </a>
                      ) : (
                        <span className="min-w-0 flex-1 truncate">{source.title}</span>
                      )}
                      <span className="text-xs text-ink-muted">{source.site || source.kind}</span>
                    </li>
                  ))}
                </ol>
              </section>
            )}

            {selected.status === 'completed' && (
              <section className="rounded-2xl border border-border bg-surface p-4">
                <h3 className="text-sm font-semibold">{t('research.followup')}</h3>
                <div className="mt-2 flex gap-2">
                  <Input
                    value={followup}
                    placeholder={t('research.followupPlaceholder')}
                    onChange={(event) => setFollowup(event.target.value)}
                  />
                  <Button size="sm" disabled={busy || followup.trim() === ''} onClick={() => void runFollowup()}>
                    {t('research.ask')}
                  </Button>
                </div>
                <ul className="mt-3 space-y-2 text-sm">
                  {followups.map((item, index) => (
                    <li key={index} className="rounded-xl border border-border px-3 py-2">
                      <p className="font-medium">{item.question}</p>
                      <div className="markdown mt-1 text-ink-muted">
                        <ReactMarkdown>{item.answer}</ReactMarkdown>
                      </div>
                    </li>
                  ))}
                </ul>
                <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-3">
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
                  <select
                    className="h-8 rounded-lg border border-border bg-surface px-2 text-xs"
                    value={saveProjectId}
                    onChange={(event) => setSaveProjectId(event.target.value)}
                  >
                    <option value="">{t('research.selectProject')}</option>
                    {(projects.data ?? []).map((project) => (
                      <option key={project.id} value={project.id}>
                        {project.name}
                      </option>
                    ))}
                  </select>
                  <Button variant="secondary" size="sm" disabled={busy || saveProjectId === ''} onClick={() => void saveToProject()}>
                    {t('research.saveToProject')}
                  </Button>
                </div>
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