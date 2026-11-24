import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Ban, Play, Plus } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { ReviewInbox } from '../../components/ReviewInbox'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { EmptyState } from '../../components/ui/empty-state'
import { Textarea } from '../../components/ui/input'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import { streamRunEvents } from '../../lib/sse'
import type {
  KnowledgeBase,
  RunAccepted,
  Workflow,
  WorkflowRun,
} from '../../lib/types'
import { cn } from '../../lib/utils'

const SAMPLE_DEFINITION = JSON.stringify(
  {
    nodes: [
      {
        id: 'draft',
        type: 'llm',
        config: {
          provider_id: 'local-qwen',
          model: 'qwen2.5-7b-instruct',
          prompt: 'Draft a concise answer for: {{input}}',
        },
      },
      {
        id: 'check',
        type: 'condition',
        config: { left: '{{draft}}', operator: 'not_empty', right: '' },
      },
      {
        id: 'final',
        type: 'llm',
        config: {
          provider_id: 'local-qwen',
          model: 'qwen2.5-7b-instruct',
          prompt: 'Improve this answer:\n{{draft}}',
        },
      },
      {
        id: 'fallback',
        type: 'llm',
        config: {
          provider_id: 'local-qwen',
          model: 'qwen2.5-7b-instruct',
          prompt: 'The draft was empty. Answer: {{input}}',
        },
      },
    ],
    edges: [
      { from: 'draft', to: 'check' },
      { from: 'check', to: 'final', when: 'true' },
      { from: 'check', to: 'fallback', when: 'false' },
    ],
  },
  null,
  2,
)

interface NodeState {
  nodeId: string
  nodeType: string
  status: string
  attempts?: number
  durationMs?: number
  output?: string
}

function statusTone(status: string): 'success' | 'danger' | 'accent' | 'neutral' {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'queued' || status === 'running') return 'accent'
  return 'neutral'
}

export function WorkflowsPage() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const queryWorkflow = searchParams.get('workflow')
  const queryRun = searchParams.get('run')
  const [selectedId, setSelectedId] = useState<string | null>(queryWorkflow)
  const [activeRunId, setActiveRunId] = useState<string | null>(queryRun)
  const [createOpen, setCreateOpen] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [memoryExtract, setMemoryExtract] = useState(false)
  const [definitionText, setDefinitionText] = useState(SAMPLE_DEFINITION)
  const [runInput, setRunInput] = useState('用三句话介绍这个平台')
  const [kbId, setKbId] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [nodeStates, setNodeStates] = useState<NodeState[]>([])
  const [runResult, setRunResult] = useState<WorkflowRun | null>(null)
  const [runOutput, setRunOutput] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const workflows = useQuery({
    queryKey: ['workflows'],
    queryFn: () => apiRequest<Workflow[]>('/workflows'),
  })
  const kbs = useQuery({
    queryKey: ['kbs'],
    queryFn: () => apiRequest<KnowledgeBase[]>('/knowledge-bases'),
    staleTime: 60_000,
  })
  const runs = useQuery({
    queryKey: ['workflow-runs', selectedId],
    queryFn: () => apiRequest<WorkflowRun[]>(`/workflows/${selectedId}/runs?limit=20`),
    enabled: selectedId !== null,
  })
  const selected = (workflows.data ?? []).find((item) => item.id === selectedId) ?? null

  useEffect(() => {
    setSelectedId(queryWorkflow)
    setActiveRunId(queryRun)
  }, [queryWorkflow, queryRun])

  const upsertNode = (next: NodeState) => {
    setNodeStates((previous) => {
      const index = previous.findIndex((item) => item.nodeId === next.nodeId)
      if (index === -1) return [...previous, next]
      const copy = [...previous]
      copy[index] = { ...copy[index], ...next }
      return copy
    })
  }

  const selectWorkflow = (workflowId: string) => {
    setSelectedId(workflowId)
    setActiveRunId(null)
    setSearchParams({ workflow: workflowId })
  }

  const openRun = (workflowId: string, runId: string) => {
    setSelectedId(workflowId)
    setActiveRunId(runId)
    setSearchParams({ workflow: workflowId, run: runId })
  }

  useEffect(() => {
    if (activeRunId === null) return
    const controller = new AbortController()
    setStreaming(true)
    setError(null)
    setNodeStates([])
    setRunResult(null)
    setRunOutput(null)
    streamRunEvents({
      path: `/workflows/runs/${activeRunId}/events`,
      signal: controller.signal,
      onEvent: (event) => {
        const data = event.data as Record<string, unknown>
        if (event.event === 'node_start') {
          upsertNode({
            nodeId: String(data.node_id),
            nodeType: String(data.node_type),
            status: 'running',
          })
        } else if (event.event === 'node_end') {
          upsertNode({
            nodeId: String(data.node_id),
            nodeType: '',
            status: String(data.status),
            attempts: Number(data.attempts ?? 1),
            durationMs: Number(data.duration_ms ?? 0),
            output: data.output === undefined ? undefined : String(data.output),
          })
        } else if (event.event === 'workflow_end') {
          if (data.output !== undefined) setRunOutput(String(data.output))
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
        void apiRequest<WorkflowRun>(`/workflows/runs/${activeRunId}`)
          .then(setRunResult)
          .catch(() => undefined)
        void queryClient.invalidateQueries({ queryKey: ['workflow-runs', selectedId] })
      })
    return () => controller.abort()
  }, [activeRunId, queryClient, selectedId, t])

  const create = async () => {
    setError(null)
    let definition: unknown
    try {
      definition = JSON.parse(definitionText)
    } catch {
      setError(t('workflows.invalidJson'))
      return
    }
    try {
      const created = await apiRequest<Workflow>('/workflows', {
        method: 'POST',
        body: {
          name: name.trim(),
          description: description.trim(),
          definition,
          memory_extract_enabled: memoryExtract,
        },
      })
      await queryClient.invalidateQueries({ queryKey: ['workflows'] })
      setSelectedId(created.id)
      setSearchParams({ workflow: created.id })
      setCreateOpen(false)
      setName('')
      setDescription('')
      setMemoryExtract(false)
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    }
  }

  const toggleMemoryExtract = async (enabled: boolean) => {
    if (selected === null) return
    setError(null)
    try {
      await apiRequest(`/workflows/${selected.id}`, {
        method: 'PATCH',
        body: { memory_extract_enabled: enabled },
      })
      await queryClient.invalidateQueries({ queryKey: ['workflows'] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    }
  }

  const run = async () => {
    if (selected === null || runInput.trim() === '') return
    setSubmitting(true)
    setError(null)
    try {
      const created = await apiRequest<RunAccepted>(`/workflows/${selected.id}/runs`, {
        method: 'POST',
        body: { input: runInput.trim(), kb_id: kbId === '' ? null : kbId },
      })
      openRun(selected.id, created.run_id)
      await queryClient.invalidateQueries({ queryKey: ['workflow-runs', selected.id] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setSubmitting(false)
    }
  }

  const cancel = async () => {
    if (activeRunId === null) return
    try {
      await apiRequest(`/workflows/runs/${activeRunId}/cancel`, { method: 'POST' })
      await queryClient.invalidateQueries({ queryKey: ['workflow-runs', selectedId] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    }
  }

  const activeRun = (runs.data ?? []).find((item) => item.id === activeRunId)
  const activeStatus = activeRun?.status ?? runResult?.status
  const canCancel = activeStatus === 'queued' || activeStatus === 'running'

  return (
    <div className="flex min-h-0 flex-1">
      <aside className="w-72 shrink-0 overflow-y-auto border-r border-border bg-surface p-3">
        <div className="flex items-center justify-between">
          <h1 className="text-sm font-semibold">{t('workflows.title')}</h1>
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" />
            {t('workflows.create')}
          </Button>
        </div>
        <div className="mt-3 space-y-1">
          {(workflows.data ?? []).map((workflow) => (
            <button
              key={workflow.id}
              type="button"
              onClick={() => selectWorkflow(workflow.id)}
              className={cn(
                'block w-full rounded-lg px-3 py-2 text-left text-sm',
                selectedId === workflow.id
                  ? 'bg-accent-soft font-medium text-accent'
                  : 'text-ink-muted hover:bg-surface-muted hover:text-ink',
              )}
            >
              <span className="block truncate">{workflow.name}</span>
              <span className="text-[11px] text-ink-muted">
                {t('workflows.version', { version: workflow.versions[0]?.version ?? 1 })} ·{' '}
                {workflow.versions[0]?.definition.nodes.length ?? 0} {t('workflows.nodes')}
              </span>
            </button>
          ))}
          {workflows.data !== undefined && workflows.data.length === 0 && (
            <p className="px-3 py-2 text-xs text-ink-muted">{t('workflows.empty')}</p>
          )}
        </div>
      </aside>

      <div className="min-h-0 flex-1 overflow-y-auto p-6">
        {selected === null ? (
          <EmptyState title={t('workflows.selectTitle')} description={t('workflows.selectHint')} />
        ) : (
          <div className="mx-auto w-full max-w-4xl space-y-5">
            <header>
              <h2 className="text-lg font-semibold">{selected.name}</h2>
              <p className="mt-1 text-sm text-ink-muted">{selected.description}</p>
              <label className="mt-2 flex items-start gap-2 text-xs text-ink">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={selected.memory_extract_enabled}
                  onChange={(event) =>
                    void toggleMemoryExtract(event.target.checked)
                  }
                />
                <span>
                  <span className="font-medium">
                    {t('workflows.memoryExtract')}
                  </span>
                  <span className="block text-ink-muted">
                    {t('workflows.memoryExtractHint')}
                  </span>
                </span>
              </label>
            </header>

            <section className="rounded-card border border-border bg-surface p-4">
              <h3 className="text-sm font-medium">{t('workflows.run')}</h3>
              <div className="mt-3 grid gap-3 sm:grid-cols-[1fr_220px]">
                <Textarea
                  className="min-h-20 rounded-lg border border-border bg-surface px-3 py-2 text-sm"
                  value={runInput}
                  onChange={(event) => setRunInput(event.target.value)}
                  placeholder={t('workflows.input')}
                />
                <select
                  className="h-10 rounded-lg border border-border bg-surface px-2 text-sm"
                  value={kbId}
                  onChange={(event) => setKbId(event.target.value)}
                >
                  <option value="">{t('workflows.noKb')}</option>
                  {(kbs.data ?? []).map((kb) => (
                    <option key={kb.id} value={kb.id}>
                      {kb.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <Button size="sm" disabled={submitting} onClick={() => void run()}>
                  <Play className="h-3.5 w-3.5" />
                  {submitting ? t('workflows.running') : t('workflows.runButton')}
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
                    {streaming ? ` · ${t('workflows.running')}` : ''}
                  </span>
                )}
                {runResult !== null && (
                  <span className="text-xs text-ink-muted">
                    {Math.round(runResult.total_ms ?? 0)} ms ·{' '}
                    {runResult.prompt_tokens + runResult.completion_tokens} tokens
                  </span>
                )}
              </div>
              {error !== null && (
                <p
                  role="alert"
                  className="mt-3 rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger"
                >
                  {error}
                </p>
              )}
            </section>

            <ReviewInbox />

            <section className="rounded-card border border-border bg-surface p-4">
              <h3 className="text-sm font-medium">{t('runs.history')}</h3>
              {(runs.data?.length ?? 0) === 0 ? (
                <p className="mt-2 text-sm text-ink-muted">{t('runs.empty')}</p>
              ) : (
                <ul className="mt-2 divide-y divide-border text-sm">
                  {runs.data?.map((item) => (
                    <li key={item.id} className="flex flex-wrap items-center gap-2 py-2">
                      <button
                        type="button"
                        onClick={() => openRun(item.workflow_id, item.id)}
                        className={cn(
                          'flex flex-1 flex-wrap items-center gap-2 text-left',
                          item.id === activeRunId ? 'text-accent' : 'text-ink',
                        )}
                      >
                        <span className="font-mono text-xs">{item.id.slice(0, 8)}</span>
                        <Badge tone={statusTone(item.status)}>{item.status}</Badge>
                        <span className="text-xs text-ink-muted">
                          {item.prompt_tokens + item.completion_tokens} tokens
                        </span>
                      </button>
                      {(item.status === 'queued' || item.status === 'running') && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            void apiRequest(`/workflows/runs/${item.id}/cancel`, {
                              method: 'POST',
                            }).then(() =>
                              queryClient.invalidateQueries({
                                queryKey: ['workflow-runs', selectedId],
                              }),
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

            <section className="rounded-card border border-border bg-surface p-4">
              <h3 className="text-sm font-medium">{t('workflows.timeline')}</h3>
              {nodeStates.length === 0 && (
                <p className="mt-2 text-sm text-ink-muted">{t('workflows.noRun')}</p>
              )}
              <ol className="mt-3 space-y-2">
                {nodeStates.map((node) => (
                  <li
                    key={node.nodeId}
                    className="rounded-lg border border-border px-3 py-2 text-sm"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs text-ink">{node.nodeId}</span>
                      <Badge tone={statusTone(node.status)}>{node.status}</Badge>
                      {node.durationMs !== undefined && node.status !== 'skipped' && (
                        <span className="text-[11px] text-ink-muted">
                          {Math.round(node.durationMs)} ms
                          {node.attempts !== undefined && node.attempts > 1
                            ? ` · ${t('workflows.attempts', { count: node.attempts })}`
                            : ''}
                        </span>
                      )}
                    </div>
                    {node.output !== undefined && node.output !== '' && (
                      <p className="mt-1 line-clamp-3 text-xs text-ink-muted">{node.output}</p>
                    )}
                  </li>
                ))}
              </ol>
            </section>

            {runOutput !== null && (
              <section className="rounded-card border border-border bg-surface p-4">
                <h3 className="text-sm font-medium">{t('workflows.output')}</h3>
                <p className="mt-2 whitespace-pre-wrap text-sm text-ink">{runOutput}</p>
              </section>
            )}
          </div>
        )}
      </div>

      <Dialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title={t('workflows.create')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setCreateOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button size="sm" onClick={() => void create()}>
              {t('common.create')}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <input
            className="h-10 w-full rounded-lg border border-border bg-surface px-3 text-sm"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={t('workflows.name')}
          />
          <input
            className="h-10 w-full rounded-lg border border-border bg-surface px-3 text-sm"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder={t('workflows.description')}
          />
          <label className="flex items-start gap-2 text-xs text-ink">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={memoryExtract}
              onChange={(event) => setMemoryExtract(event.target.checked)}
            />
            <span>
              <span className="font-medium">{t('workflows.memoryExtract')}</span>
              <span className="block text-ink-muted">
                {t('workflows.memoryExtractHint')}
              </span>
            </span>
          </label>
          <Textarea
            className="min-h-64 w-full rounded-lg border border-border bg-surface px-3 py-2 font-mono text-xs"
            value={definitionText}
            onChange={(event) => setDefinitionText(event.target.value)}
            spellCheck={false}
          />
          <p className="text-xs text-ink-muted">{t('workflows.definitionHint')}</p>
        </div>
      </Dialog>
    </div>
  )
}