import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  CheckCircle2,
  Link2,
  Play,
  Plus,
  RefreshCw,
  Save,
  Workflow as WorkflowIcon,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { KnowledgeBuilderPanel } from './KnowledgeBuilderPanel'
import { StudioCanvas } from '../studio/StudioCanvas'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Spinner } from '../../components/ui/spinner'
import {
  clearLocalDraft,
  clearWorkflowDraft,
  localDraftKey,
  readLocalDraft,
  saveWorkflowDraft,
  writeLocalDraft,
} from '../../lib/canvasDraft'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  DocumentItem,
  KnowledgeBase,
  KnowledgeProcessArtifact,
  KnowledgeProcessBinding,
  KnowledgeProcessPreview,
  RunAccepted,
  Workflow,
  WorkflowCatalog,
  WorkflowDefinition,
  WorkflowVersion,
} from '../../lib/types'
import { cn } from '../../lib/utils'

type Tab = 'canvas' | 'run' | 'builder'

const EMPTY_DEFINITION: WorkflowDefinition = {
  nodes: [
    { id: 'start', type: 'start', config: {}, ui: { x: 80, y: 120 } },
    { id: 'out', type: 'output', config: {}, ui: { x: 560, y: 120 } },
  ],
  edges: [{ from: 'start', to: 'out' }],
}

export function KnowledgeStudioPage() {
  const { id = '' } = useParams<{ id: string }>()
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<Tab>('canvas')
  const [workflowId, setWorkflowId] = useState('')
  const [definition, setDefinition] = useState<WorkflowDefinition>(EMPTY_DEFINITION)
  const [seed, setSeed] = useState(0)
  const [saving, setSaving] = useState(false)
  const [binding, setBinding] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [documentId, setDocumentId] = useState('')
  const [runId, setRunId] = useState('')
  const [draftRestored, setDraftRestored] = useState(false)

  const kb = useQuery({
    queryKey: ['knowledge-base', id],
    queryFn: () => apiRequest<KnowledgeBase>(`/knowledge-bases/${id}`),
    enabled: id !== '',
  })
  const documents = useQuery({
    queryKey: ['knowledge-studio-documents', id],
    queryFn: () =>
      apiRequest<DocumentItem[]>(`/knowledge-bases/${id}/documents?limit=100`),
    enabled: id !== '',
  })
  const catalog = useQuery({
    queryKey: ['knowledge-process-catalog'],
    queryFn: () =>
      apiRequest<WorkflowCatalog>('/workflows/catalog?kind=knowledge_process'),
    staleTime: 300_000,
  })
  const workflows = useQuery({
    queryKey: ['knowledge-process-workflows'],
    queryFn: () => apiRequest<Workflow[]>('/workflows?kind=knowledge_process'),
  })
  const currentBinding = useQuery({
    queryKey: ['knowledge-processing-binding', id],
    queryFn: () =>
      apiRequest<KnowledgeProcessBinding>(`/knowledge-bases/${id}/processing/binding`),
    enabled: id !== '',
  })
  const workflow = useQuery({
    queryKey: ['knowledge-process-workflow', workflowId],
    queryFn: () => apiRequest<Workflow>(`/workflows/${workflowId}`),
    enabled: workflowId !== '',
  })
  const preview = useQuery({
    queryKey: ['knowledge-process-preview', runId],
    queryFn: () =>
      apiRequest<KnowledgeProcessPreview>(
        `/knowledge-bases/${id}/processing/runs/${runId}/preview`,
      ),
    enabled: id !== '' && runId !== '',
    refetchInterval: (query) =>
      query.state.data?.run.status === 'queued' ||
      query.state.data?.run.status === 'running'
        ? 1200
        : false,
  })

  useEffect(() => {
    if (workflowId !== '') return
    const bound = currentBinding.data?.workflow_id
    if (bound) {
      setWorkflowId(bound)
      return
    }
    const first = workflows.data?.[0]
    if (first) setWorkflowId(first.id)
  }, [workflowId, currentBinding.data, workflows.data])

  const latestVersion = workflow.data?.versions[0]
  const canvasLocalKey = localDraftKey(`knowledge_process:${id}`)
  useEffect(() => {
    const remoteDraft = workflow.data?.draft_definition ?? null
    const localDraft = readLocalDraft(canvasLocalKey)
    const chosen = remoteDraft ?? localDraft ?? latestVersion?.definition
    if (chosen === undefined || chosen === null) return
    setDefinition(chosen)
    setSeed((value) => value + 1)
    setDraftRestored(remoteDraft !== null || localDraft !== null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflowId, latestVersion?.id])

  useEffect(() => {
    if (documentId !== '') return
    const first = documents.data?.find((item) => item.status === 'ready')
    if (first) setDocumentId(first.id)
  }, [documentId, documents.data])

  const autosaveCanvas = useCallback(
    async (next: WorkflowDefinition) => {
      if (workflowId !== '') {
        await saveWorkflowDraft(workflowId, next)
      } else {
        writeLocalDraft(canvasLocalKey, next)
      }
    },
    [workflowId, canvasLocalKey],
  )

  if (id === '' || kb.isError) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-ink-muted">
        {t('knowledgeStudio.missing')}
      </div>
    )
  }
  if (kb.isLoading || catalog.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner className="h-5 w-5 text-accent" />
      </div>
    )
  }

  const refreshWorkflows = async () => {
    await queryClient.invalidateQueries({ queryKey: ['knowledge-process-workflows'] })
  }

  const restoreCanvasVersion = async (version: number) => {
    if (workflowId === '') return
    const restored = await apiRequest<WorkflowVersion>(
      `/workflows/${workflowId}/versions/${version}/restore`,
      { method: 'POST' },
    )
    setDefinition(restored.definition)
    setSeed((value) => value + 1)
    setDraftRestored(false)
    await queryClient.invalidateQueries({
      queryKey: ['knowledge-process-workflow', workflowId],
    })
    await refreshWorkflows()
  }

  const discardCanvasDraft = async () => {
    if (workflowId !== '') {
      await clearWorkflowDraft(workflowId)
      await queryClient.invalidateQueries({
        queryKey: ['knowledge-process-workflow', workflowId],
      })
    }
    clearLocalDraft(canvasLocalKey)
    setDefinition(latestVersion?.definition ?? EMPTY_DEFINITION)
    setSeed((value) => value + 1)
    setDraftRestored(false)
  }

  const createFromTemplate = async (index: number) => {
    const template = catalog.data?.templates?.[index]
    if (template === undefined) return
    setError(null)
    try {
      const created = await apiRequest<Workflow>('/workflows', {
        method: 'POST',
        body: {
          name: template.name,
          description: template.description,
          kind: 'knowledge_process',
          definition: template.definition,
        },
      })
      setWorkflowId(created.id)
      setDefinition(created.versions[0]?.definition ?? template.definition)
      setSeed((value) => value + 1)
      await refreshWorkflows()
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    }
  }

  const saveCanvas = async (next: WorkflowDefinition) => {
    if (workflowId === '') return
    setSaving(true)
    setError(null)
    try {
      await apiRequest(`/workflows/${workflowId}/versions`, {
        method: 'POST',
        body: { definition: next },
      })
      clearLocalDraft(canvasLocalKey)
      setDraftRestored(false)
      await queryClient.invalidateQueries({
        queryKey: ['knowledge-process-workflow', workflowId],
      })
      await refreshWorkflows()
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setSaving(false)
    }
  }

  const bindWorkflow = async () => {
    if (latestVersion === undefined) return
    setBinding(true)
    setError(null)
    try {
      await apiRequest(`/knowledge-bases/${id}/processing/binding`, {
        method: 'PUT',
        body: { workflow_version_id: latestVersion.id },
      })
      await queryClient.invalidateQueries({
        queryKey: ['knowledge-processing-binding', id],
      })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBinding(false)
    }
  }

  const startRun = async () => {
    if (workflowId === '' || documentId === '') return
    setError(null)
    try {
      const accepted = await apiRequest<RunAccepted>(`/workflows/${workflowId}/runs`, {
        method: 'POST',
        body: { document_id: documentId },
      })
      setRunId(accepted.run_id)
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    }
  }

  const applyRun = async () => {
    if (runId === '') return
    setError(null)
    try {
      await apiRequest(`/knowledge-bases/${id}/processing/runs/${runId}/apply`, {
        method: 'POST',
      })
      await queryClient.invalidateQueries({
        queryKey: ['knowledge-process-preview', runId],
      })
      await queryClient.invalidateQueries({
        queryKey: ['knowledge-studio-documents', id],
      })
      await queryClient.invalidateQueries({ queryKey: ['knowledge-base', id] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    }
  }

  const refreshPreview = () =>
    queryClient.invalidateQueries({ queryKey: ['knowledge-process-preview', runId] })

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="border-b border-border bg-surface px-5 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <Link
            to={`/knowledge/${id}`}
            className="inline-flex items-center gap-1 text-xs text-ink-muted hover:text-ink"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            {t('knowledgeStudio.back')}
          </Link>
          <h1 className="flex items-center gap-2 text-base font-semibold text-ink">
            <WorkflowIcon className="h-4 w-4 text-accent" />
            {kb.data?.name} · {t('knowledgeStudio.title')}
          </h1>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <select
              value={workflowId}
              onChange={(event) => setWorkflowId(event.target.value)}
              className="h-8 rounded-lg border border-border bg-surface px-2 text-xs text-ink"
            >
              <option value="">{t('knowledgeStudio.selectWorkflow')}</option>
              {(workflows.data ?? []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
            <Button
              size="sm"
              variant="secondary"
              disabled={binding || latestVersion === undefined}
              onClick={() => void bindWorkflow()}
            >
              <Link2 className="h-3.5 w-3.5" />
              {t('knowledgeStudio.bind')}
            </Button>
            {currentBinding.data?.workflow_version_id === latestVersion?.id &&
              latestVersion !== undefined && (
                <Badge tone="success">{t('knowledgeStudio.bound')}</Badge>
              )}
          </div>
        </div>
        <div className="mt-3 flex gap-1">
          {(['canvas', 'run', 'builder'] as const).map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setTab(item)}
              className={cn(
                'rounded-md px-3 py-1.5 text-xs',
                tab === item
                  ? 'bg-accent-soft text-accent'
                  : 'text-ink-muted hover:bg-surface-muted hover:text-ink',
              )}
            >
              {t(`knowledgeStudio.tab.${item}`)}
            </button>
          ))}
          {error !== null && <span className="ml-3 text-xs text-danger">{error}</span>}
        </div>
      </header>

      {tab === 'canvas' && (
        <div className="flex min-h-0 flex-1 flex-col">
          {workflowId === '' ? (
            <div className="flex flex-1 items-center justify-center p-8">
              <div className="max-w-2xl text-center">
                <p className="text-sm font-medium text-ink">
                  {t('knowledgeStudio.noWorkflow')}
                </p>
                <p className="mt-1 text-xs text-ink-muted">
                  {t('knowledgeStudio.noWorkflowLead')}
                </p>
                <div className="mt-4 flex flex-wrap justify-center gap-2">
                  {(catalog.data?.templates ?? []).map((template, index) => (
                    <Button
                      key={template.name}
                      size="sm"
                      variant="secondary"
                      onClick={() => void createFromTemplate(index)}
                    >
                      <Plus className="h-3.5 w-3.5" />
                      {template.name}
                    </Button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col">
              {draftRestored && (
                <div className="flex flex-wrap items-center gap-2 border-b border-border bg-warning/10 px-4 py-2 text-xs text-warning">
                  <span>{t('studio.draftRestored')}</span>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => void discardCanvasDraft()}
                  >
                    {t('studio.discardDraft')}
                  </Button>
                </div>
              )}
              <div className="min-h-0 flex-1">
                <StudioCanvas
                  initialDefinition={definition}
                  seed={seed}
                  catalog={catalog.data}
                  resources={{
                    models: [],
                    knowledgeBases: [],
                    agents: [],
                    plugins: [],
                    projects: [],
                    mcpServers: [],
                    databaseConnections: [],
                  }}
                  versions={workflow.data?.versions ?? []}
                  saving={saving}
                  error={error}
                  onSave={(next) => void saveCanvas(next)}
                  onRestoreVersion={(version) =>
                    void restoreCanvasVersion(version)
                  }
                  onAutosave={autosaveCanvas}
                />
              </div>
            </div>
          )}
        </div>
      )}

      {tab === 'builder' && (
        <KnowledgeBuilderPanel
          scope="knowledge_process"
          workflowId={workflowId}
          definition={definition}
          lastRunId={runId === '' ? null : runId}
          onApply={(next) => {
            setDefinition(next)
            setSeed((value) => value + 1)
            setTab('canvas')
            void saveCanvas(next)
          }}
        />
      )}

      {tab === 'run' && (
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <div className="grid gap-4 xl:grid-cols-[24rem_minmax(0,1fr)]">
            <section className="rounded-card border border-border bg-surface p-4">
              <h2 className="text-sm font-medium text-ink">
                {t('knowledgeStudio.runTitle')}
              </h2>
              <p className="mt-1 text-xs text-ink-muted">
                {t('knowledgeStudio.runLead')}
              </p>
              <label className="mt-3 block text-xs text-ink-muted">
                {t('knowledgeStudio.document')}
                <select
                  value={documentId}
                  onChange={(event) => setDocumentId(event.target.value)}
                  className="mt-1 h-9 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink"
                >
                  <option value="">{t('knowledgeStudio.selectDocument')}</option>
                  {(documents.data ?? []).map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.filename} · {item.status}
                    </option>
                  ))}
                </select>
              </label>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  disabled={workflowId === '' || documentId === ''}
                  onClick={() => void startRun()}
                >
                  <Play className="h-3.5 w-3.5" />
                  {t('knowledgeStudio.run')}
                </Button>
                {preview.data?.run.status === 'completed' && !preview.data.applied && (
                  <Button size="sm" variant="secondary" onClick={() => void applyRun()}>
                    <Save className="h-3.5 w-3.5" />
                    {t('knowledgeStudio.apply')}
                  </Button>
                )}
                {preview.data !== undefined && (
                  <Button size="sm" variant="ghost" onClick={() => void refreshPreview()}>
                    <RefreshCw className="h-3.5 w-3.5" />
                    {t('knowledgeStudio.refresh')}
                  </Button>
                )}
              </div>
              {preview.data !== undefined && (
                <div className="mt-3 space-y-1 text-xs text-ink-muted">
                  <p>
                    {t('knowledgeStudio.runStatus')}:{' '}
                    <Badge
                      tone={
                        preview.data.run.status === 'completed'
                          ? 'success'
                          : preview.data.run.status === 'failed'
                            ? 'danger'
                            : 'neutral'
                      }
                    >
                      {preview.data.run.status}
                    </Badge>
                  </p>
                  {typeof preview.data.run.output_payload.page_count === 'number' && (
                    <p>
                      {t('knowledgeStudio.pages', {
                        count: Number(preview.data.run.output_payload.page_count),
                      })}
                    </p>
                  )}
                  {typeof preview.data.run.output_payload.draft_count === 'number' && (
                    <p>
                      {t('knowledgeStudio.drafts', {
                        count: Number(preview.data.run.output_payload.draft_count),
                      })}
                    </p>
                  )}
                  {preview.data.applied && (
                    <p className="flex items-center gap-1 text-success">
                      <CheckCircle2 className="h-3 w-3" />
                      {t('knowledgeStudio.applied')}
                    </p>
                  )}
                  {preview.data.run.error_code && (
                    <p className="text-danger">{preview.data.run.error_code}</p>
                  )}
                </div>
              )}
            </section>

            <section className="space-y-3">
              {preview.isLoading && <Spinner />}
              {preview.data === undefined ? (
                <p className="rounded-card border border-dashed border-border px-4 py-12 text-center text-sm text-ink-muted">
                  {t('knowledgeStudio.previewEmpty')}
                </p>
              ) : (
                <>
                  <div className="rounded-card border border-border bg-surface p-4">
                    <h3 className="text-sm font-medium text-ink">
                      {t('knowledgeStudio.timeline')}
                    </h3>
                    <div className="mt-2 space-y-1">
                      {preview.data.run.nodes.map((node) => (
                        <div
                          key={node.id}
                          className="flex items-center gap-2 rounded-lg bg-surface-muted px-3 py-1.5 text-xs"
                        >
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
                          <span className="text-ink">{node.node_id}</span>
                          <span className="text-ink-muted">{node.node_type}</span>
                          <span className="ml-auto text-ink-muted">
                            {node.output_summary}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                  {preview.data.artifacts.map((artifact) => (
                    <ArtifactCard key={artifact.node_id} artifact={artifact} />
                  ))}
                  {preview.data.drafts.length > 0 && (
                    <div className="rounded-card border border-border bg-surface p-4">
                      <h3 className="text-sm font-medium text-ink">
                        {t('knowledgeStudio.stagedChunks', {
                          count: preview.data.draft_count,
                        })}
                      </h3>
                      <div className="mt-2 space-y-1">
                        {preview.data.drafts.slice(0, 12).map((draft) => (
                          <div
                            key={draft.chunk_index}
                            className="rounded-lg bg-surface-muted px-3 py-1.5 text-[11px] text-ink"
                          >
                            <span className="mr-2 text-ink-muted">
                              #{draft.chunk_index} · p{draft.page_no ?? '-'}
                            </span>
                            {draft.text}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}
            </section>
          </div>
        </div>
      )}
    </div>
  )
}

function ArtifactCard({ artifact }: { artifact: KnowledgeProcessArtifact }) {
  const { t } = useI18n()
  const payload = artifact.payload
  const text = typeof payload.text === 'string' ? payload.text : ''
  const chunks = Array.isArray(payload.chunks) ? payload.chunks : []
  return (
    <div className="rounded-card border border-border bg-surface p-4">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium text-ink">{artifact.kind}</h3>
        <span className="text-[10px] text-ink-muted">{artifact.node_id}</span>
      </div>
      {text !== '' && (
        <pre className="mt-2 max-h-72 overflow-y-auto whitespace-pre-wrap rounded-lg bg-surface-muted p-3 text-[11px] text-ink">
          {text}
        </pre>
      )}
      {chunks.length > 0 && (
        <div className="mt-2 space-y-1">
          {chunks.slice(0, 20).map((chunk, index) => {
            const raw = chunk as Record<string, unknown>
            const meta =
              raw.meta !== null && typeof raw.meta === 'object'
                ? (raw.meta as Record<string, unknown>)
                : {}
            const keywords = Array.isArray(meta.keywords)
              ? meta.keywords.join(', ')
              : ''
            return (
              <div
                key={index}
                className="rounded-lg bg-surface-muted px-3 py-1.5 text-[11px] text-ink"
              >
                <p>{String(raw.text ?? '')}</p>
                {(keywords !== '' || typeof meta.summary === 'string') && (
                  <p className="mt-1 text-[10px] text-ink-muted">
                    {keywords !== '' && <span>Keywords: {keywords}</span>}
                    {typeof meta.summary === 'string' && meta.summary !== '' && (
                      <span className="ml-2">Summary: {meta.summary}</span>
                    )}
                  </p>
                )}
              </div>
            )
          })}
        </div>
      )}
      {text === '' && chunks.length === 0 && (
        <pre className="mt-2 max-h-40 overflow-y-auto rounded-lg bg-surface-muted p-3 text-[11px] text-ink-muted">
          {JSON.stringify(payload, null, 2)}
        </pre>
      )}
      {artifact.kind === 'chunks' && chunks.length === 0 && (
        <p className="mt-1 text-xs text-ink-muted">{t('knowledgeStudio.noChunks')}</p>
      )}
    </div>
  )
}