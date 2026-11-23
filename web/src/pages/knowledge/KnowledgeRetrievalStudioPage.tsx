import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  Link2,
  Play,
  Plus,
  Search,
  Workflow as WorkflowIcon,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  KnowledgeBase,
  KnowledgeProcessBinding,
  KnowledgeRetrievalTestResult,
  Workflow,
  WorkflowCatalog,
  WorkflowDefinition,
} from '../../lib/types'
import { cn } from '../../lib/utils'
import { KnowledgeBuilderPanel } from './KnowledgeBuilderPanel'
import { StudioCanvas } from '../studio/StudioCanvas'

type Tab = 'canvas' | 'test' | 'builder'

const EMPTY_DEFINITION: WorkflowDefinition = {
  nodes: [
    { id: 'start', type: 'start', config: {}, ui: { x: 80, y: 120 } },
    {
      id: 'hybrid',
      type: 'hybrid_search',
      config: { top_k: 10, candidate_k: 20 },
      ui: { x: 280, y: 120 },
    },
    { id: 'out', type: 'output', config: {}, ui: { x: 500, y: 120 } },
  ],
  edges: [
    { from: 'start', to: 'hybrid' },
    { from: 'hybrid', to: 'out' },
  ],
}

export function KnowledgeRetrievalStudioPage() {
  const { id = '' } = useParams<{ id: string }>()
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<Tab>('canvas')
  const [workflowId, setWorkflowId] = useState('')
  const [definition, setDefinition] = useState<WorkflowDefinition>(EMPTY_DEFINITION)
  const [seed, setSeed] = useState(0)
  const [saving, setSaving] = useState(false)
  const [binding, setBinding] = useState(false)
  const [query, setQuery] = useState('')
  const [testing, setTesting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const kb = useQuery({
    queryKey: ['knowledge-base', id],
    queryFn: () => apiRequest<KnowledgeBase>(`/knowledge-bases/${id}`),
    enabled: id !== '',
  })
  const catalog = useQuery({
    queryKey: ['knowledge-retrieval-catalog'],
    queryFn: () =>
      apiRequest<WorkflowCatalog>('/workflows/catalog?kind=knowledge_retrieval'),
    staleTime: 300_000,
  })
  const workflows = useQuery({
    queryKey: ['knowledge-retrieval-workflows'],
    queryFn: () => apiRequest<Workflow[]>('/workflows?kind=knowledge_retrieval'),
  })
  const currentBinding = useQuery({
    queryKey: ['knowledge-retrieval-binding', id],
    queryFn: () =>
      apiRequest<KnowledgeProcessBinding>(`/knowledge-bases/${id}/retrieval/binding`),
    enabled: id !== '',
  })
  const workflow = useQuery({
    queryKey: ['knowledge-retrieval-workflow', workflowId],
    queryFn: () => apiRequest<Workflow>(`/workflows/${workflowId}`),
    enabled: workflowId !== '',
  })
  const testResult = useQuery({
    queryKey: ['knowledge-retrieval-test', id, query],
    queryFn: () =>
      apiRequest<KnowledgeRetrievalTestResult>(
        `/knowledge-bases/${id}/retrieval/test`,
        {
          method: 'POST',
          body: {
            query,
            workflow_version_id: workflow.data?.versions[0]?.id ?? null,
          },
        },
      ),
    enabled: false,
    retry: false,
  })

  const latestVersion = workflow.data?.versions[0]

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

  useEffect(() => {
    if (latestVersion === undefined) return
    setDefinition(latestVersion.definition)
    setSeed((value) => value + 1)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [latestVersion?.id])

  if (id === '' || kb.isError) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-ink-muted">
        {t('retrievalStudio.missing')}
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
    await queryClient.invalidateQueries({
      queryKey: ['knowledge-retrieval-workflows'],
    })
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
          kind: 'knowledge_retrieval',
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
      await queryClient.invalidateQueries({
        queryKey: ['knowledge-retrieval-workflow', workflowId],
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
      await apiRequest(`/knowledge-bases/${id}/retrieval/binding`, {
        method: 'PUT',
        body: { workflow_version_id: latestVersion.id },
      })
      await queryClient.invalidateQueries({
        queryKey: ['knowledge-retrieval-binding', id],
      })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBinding(false)
    }
  }

  const runTest = async () => {
    if (query.trim() === '') return
    setTesting(true)
    setError(null)
    try {
      await testResult.refetch()
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="border-b border-border bg-surface px-5 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <Link
            to={`/knowledge/${id}`}
            className="inline-flex items-center gap-1 text-xs text-ink-muted hover:text-ink"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            {t('retrievalStudio.back')}
          </Link>
          <h1 className="flex items-center gap-2 text-base font-semibold text-ink">
            <WorkflowIcon className="h-4 w-4 text-accent" />
            {kb.data?.name} · {t('retrievalStudio.title')}
          </h1>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <select
              value={workflowId}
              onChange={(event) => setWorkflowId(event.target.value)}
              className="h-8 rounded-lg border border-border bg-surface px-2 text-xs text-ink"
            >
              <option value="">{t('retrievalStudio.selectWorkflow')}</option>
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
              {t('retrievalStudio.bind')}
            </Button>
            {currentBinding.data?.workflow_version_id === latestVersion?.id &&
              latestVersion !== undefined && (
                <Badge tone="success">{t('retrievalStudio.bound')}</Badge>
              )}
          </div>
        </div>
        <div className="mt-3 flex gap-1">
          {(['canvas', 'test', 'builder'] as const).map((item) => (
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
              {t(`retrievalStudio.tab.${item}`)}
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
                  {t('retrievalStudio.noWorkflow')}
                </p>
                <p className="mt-1 text-xs text-ink-muted">
                  {t('retrievalStudio.noWorkflowLead')}
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
                saving={saving}
                error={error}
                onSave={(next) => void saveCanvas(next)}
              />
            </div>
          )}
        </div>
      )}

      {tab === 'builder' && (
        <KnowledgeBuilderPanel
          scope="knowledge_retrieval"
          workflowId={workflowId}
          definition={definition}
          lastRunId={null}
          onApply={(next) => {
            setDefinition(next)
            setSeed((value) => value + 1)
            setTab('canvas')
            void saveCanvas(next)
          }}
        />
      )}

      {tab === 'test' && (
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <div className="grid gap-4 xl:grid-cols-[24rem_minmax(0,1fr)]">
            <section className="rounded-card border border-border bg-surface p-4">
              <h2 className="text-sm font-medium text-ink">
                {t('retrievalStudio.testTitle')}
              </h2>
              <p className="mt-1 text-xs text-ink-muted">
                {t('retrievalStudio.testLead')}
              </p>
              <textarea
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t('retrievalStudio.queryPlaceholder')}
                className="mt-3 min-h-24 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink"
              />
              <Button
                className="mt-2"
                size="sm"
                disabled={testing || query.trim() === ''}
                onClick={() => void runTest()}
              >
                {testing ? (
                  <Spinner className="h-3.5 w-3.5" />
                ) : (
                  <Play className="h-3.5 w-3.5" />
                )}
                {t('retrievalStudio.run')}
              </Button>
              {testResult.data !== undefined && (
                <div className="mt-3 space-y-1 text-xs text-ink-muted">
                  <p>
                    {t('retrievalStudio.mode')}:{' '}
                    <Badge tone="accent">{testResult.data.mode}</Badge>
                  </p>
                  {testResult.data.rewritten_query &&
                    testResult.data.rewritten_query !== testResult.data.query && (
                      <p>
                        {t('retrievalStudio.rewritten')}:{' '}
                        {testResult.data.rewritten_query}
                      </p>
                    )}
                  <p>
                    {t('retrievalStudio.totalMs', {
                      ms: Math.round(Number(testResult.data.timings.total_ms ?? 0)),
                    })}
                  </p>
                </div>
              )}
            </section>

            <section className="space-y-3">
              {testResult.isFetching && <Spinner />}
              {testResult.data === undefined ? (
                <p className="rounded-card border border-dashed border-border px-4 py-12 text-center text-sm text-ink-muted">
                  {t('retrievalStudio.empty')}
                </p>
              ) : (
                <>
                  <div className="rounded-card border border-border bg-surface p-4">
                    <h3 className="flex items-center gap-2 text-sm font-medium text-ink">
                      <Search className="h-4 w-4" />
                      {t('retrievalStudio.results', {
                        count: testResult.data.results.length,
                      })}
                    </h3>
                    <div className="mt-2 space-y-2">
                      {testResult.data.results.map((hit, index) => (
                        <div
                          key={hit.chunk_id}
                          className="rounded-lg bg-surface-muted px-3 py-2 text-xs"
                        >
                          <div className="flex flex-wrap items-center gap-2 text-[10px] text-ink-muted">
                            <span>#{index + 1}</span>
                            <span>{hit.filename}</span>
                            <span>p{hit.page_no ?? '-'}</span>
                            {hit.vector_rank !== null && (
                              <Badge tone="neutral">v{hit.vector_rank}</Badge>
                            )}
                            {hit.lexical_rank !== null && (
                              <Badge tone="neutral">l{hit.lexical_rank}</Badge>
                            )}
                            {hit.rerank_score !== null && (
                              <Badge tone="accent">
                                {hit.rerank_score.toFixed(3)}
                              </Badge>
                            )}
                          </div>
                          <p className="mt-1 whitespace-pre-wrap text-ink">
                            {hit.text}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="rounded-card border border-border bg-surface p-4">
                    <h3 className="text-sm font-medium text-ink">
                      {t('retrievalStudio.context')}
                    </h3>
                    <pre className="mt-2 max-h-72 overflow-y-auto whitespace-pre-wrap rounded-lg bg-surface-muted p-3 text-[11px] text-ink">
                      {testResult.data.context}
                    </pre>
                  </div>
                  {testResult.data.nodes.length > 0 && (
                    <div className="rounded-card border border-border bg-surface p-4">
                      <h3 className="text-sm font-medium text-ink">
                        {t('retrievalStudio.timeline')}
                      </h3>
                      <div className="mt-2 space-y-1">
                        {testResult.data.nodes.map((node) => (
                          <div
                            key={node.node_id}
                            className="flex items-center gap-2 rounded-lg bg-surface-muted px-3 py-1.5 text-xs"
                          >
                            <Badge
                              tone={node.status === 'completed' ? 'success' : 'danger'}
                            >
                              {node.status}
                            </Badge>
                            <span className="text-ink">{node.node_id}</span>
                            <span className="text-ink-muted">{node.node_type}</span>
                            <span className="ml-auto text-ink-muted">
                              {node.count} · {node.duration_ms} ms
                            </span>
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