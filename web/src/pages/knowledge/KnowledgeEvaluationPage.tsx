import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, BarChart3, Play } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  EvalDataset,
  EvalRun,
  KnowledgeBase,
  KnowledgeProcessVersionCompare,
  Workflow,
} from '../../lib/types'
import { cn } from '../../lib/utils'
import { EvaluationRunDetailPanel } from './EvaluationRunDetailPanel'
import { OptimizationPanel } from './OptimizationPanel'

const COMPARE_KEYS = [
  'recall_at_1',
  'recall_at_3',
  'recall_at_5',
  'precision_at_5',
  'recall_at_5_docs',
  'ndcg_at_5',
  'precision_at_10',
  'recall_at_10_docs',
  'ndcg_at_10',
  'mrr',
  'citation_precision',
  'citation_recall',
  'citation_f1',
  'faithful_rate',
  'judge_avg_score',
  'latency_p95_ms',
  'success_rate',
] as const

interface VersionOption {
  value: string
  label: string
}

function versionOptions(workflows: Workflow[]): VersionOption[] {
  const options: VersionOption[] = []
  for (const workflow of workflows) {
    for (const version of workflow.versions) {
      options.push({
        value: version.id,
        label: `${workflow.name} · v${version.version}`,
      })
    }
  }
  return options
}

function metricNumber(metrics: Record<string, unknown>, key: string): number | null {
  const value = metrics[key]
  return typeof value === 'number' ? value : null
}

export function KnowledgeEvaluationPage() {
  const { id = '' } = useParams<{ id: string }>()
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [datasetChoice, setDatasetChoice] = useState('')
  const [versionChoice, setVersionChoice] = useState('')
  const [topK, setTopK] = useState(5)
  const [candidateK, setCandidateK] = useState(20)
  const [hybrid, setHybrid] = useState(true)
  const [rerank, setRerank] = useState(true)
  const [selectedRunId, setSelectedRunId] = useState('')
  const [compareIds, setCompareIds] = useState<string[]>([])
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const kb = useQuery({
    queryKey: ['knowledge-base', id],
    queryFn: () => apiRequest<KnowledgeBase>(`/knowledge-bases/${id}`),
    enabled: id !== '',
  })
  const datasets = useQuery({
    queryKey: ['eval-datasets'],
    queryFn: () => apiRequest<EvalDataset[]>('/evaluations/datasets'),
  })
  const workflows = useQuery({
    queryKey: ['knowledge-retrieval-workflows'],
    queryFn: () => apiRequest<Workflow[]>('/workflows?kind=knowledge_retrieval'),
  })
  const binding = useQuery({
    queryKey: ['knowledge-retrieval-binding', id],
    queryFn: () =>
      apiRequest<{ workflow_version_id: string | null }>(
        `/knowledge-bases/${id}/retrieval/binding`,
      ),
    enabled: id !== '',
  })
  const processComparison = useQuery({
    queryKey: ['process-version-compare', id],
    queryFn: () =>
      apiRequest<KnowledgeProcessVersionCompare>(
        `/knowledge-bases/${id}/processing/versions/compare`,
      ),
    enabled: id !== '',
  })
  const runs = useQuery({
    queryKey: ['eval-runs', id],
    queryFn: () => apiRequest<EvalRun[]>('/evaluations/runs?limit=100'),
    select: (rows) => rows.filter((run) => run.kb_id === id),
    refetchInterval: (query) => {
      const rows = query.state.data ?? []
      return rows.some(
        (run) => run.status === 'queued' || run.status === 'running',
      )
        ? 2000
        : false
    },
    enabled: id !== '',
  })

  const datasetRows = datasets.data ?? []
  const options = versionOptions(workflows.data ?? [])
  const runRows = runs.data ?? []

  useEffect(() => {
    if (datasetChoice === '' && datasetRows.length > 0) {
      setDatasetChoice(datasetRows[0].id)
    }
  }, [datasetChoice, datasetRows])

  useEffect(() => {
    if (versionChoice !== '') return
    const bound = binding.data?.workflow_version_id
    if (bound) setVersionChoice(bound)
  }, [versionChoice, binding.data])

  useEffect(() => {
    if (selectedRunId === '' && runRows.length > 0) {
      setSelectedRunId(runRows[0].id)
    }
  }, [selectedRunId, runRows])

  if (id === '' || kb.isError) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-ink-muted">
        {t('knowledgeEval.missing')}
      </div>
    )
  }
  if (kb.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner className="h-5 w-5 text-accent" />
      </div>
    )
  }

  const startRun = async () => {
    if (datasetChoice === '') return
    setStarting(true)
    setError(null)
    try {
      const created = await apiRequest<EvalRun>('/evaluations/runs', {
        method: 'POST',
        body: {
          dataset_id: datasetChoice,
          kb_id: id,
          retrieval_workflow_version_id: versionChoice === '' ? null : versionChoice,
          top_k: topK,
          candidate_k: candidateK,
          hybrid_enabled: hybrid,
          rerank_enabled: rerank,
        },
      })
      setSelectedRunId(created.id)
      await queryClient.invalidateQueries({ queryKey: ['eval-runs', id] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setStarting(false)
    }
  }

  const toggleCompare = (runId: string) => {
    setCompareIds((current) => {
      if (current.includes(runId)) {
        return current.filter((item) => item !== runId)
      }
      if (current.length >= 2) return [current[1], runId]
      return [...current, runId]
    })
  }

  const compareRuns = compareIds
    .map((runId) => runRows.find((run) => run.id === runId))
    .filter((run): run is EvalRun => run !== undefined)

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="border-b border-border bg-surface px-5 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <Link
            to={`/knowledge/${id}`}
            className="inline-flex items-center gap-1 text-xs text-ink-muted hover:text-ink"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            {t('knowledgeEval.back')}
          </Link>
          <h1 className="flex items-center gap-2 text-base font-semibold text-ink">
            <BarChart3 className="h-4 w-4 text-accent" />
            {kb.data?.name} · {t('knowledgeEval.title')}
          </h1>
          {error !== null && <span className="ml-auto text-xs text-danger">{error}</span>}
        </div>
      </header>

      <div className="grid min-h-0 flex-1 gap-4 overflow-y-auto px-5 py-4 xl:grid-cols-[22rem_minmax(0,1fr)]">
        <div className="space-y-3">
          <section className="rounded-card border border-border bg-surface p-4">
            <h2 className="text-sm font-medium text-ink">{t('knowledgeEval.start.title')}</h2>
            <div className="mt-3 space-y-2 text-[11px] text-ink-muted">
              <label className="block">
                {t('knowledgeEval.start.dataset')}
                <select
                  value={datasetChoice}
                  onChange={(event) => setDatasetChoice(event.target.value)}
                  className="mt-1 block h-8 w-full rounded-lg border border-border bg-surface px-2 text-xs text-ink"
                >
                  <option value="">{t('knowledgeEval.start.selectDataset')}</option>
                  {datasetRows.map((dataset) => (
                    <option key={dataset.id} value={dataset.id}>
                      {dataset.name} · {dataset.question_count}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                {t('knowledgeEval.start.version')}
                <select
                  value={versionChoice}
                  onChange={(event) => setVersionChoice(event.target.value)}
                  className="mt-1 block h-8 w-full rounded-lg border border-border bg-surface px-2 text-xs text-ink"
                >
                  <option value="">{t('knowledgeEval.start.builtin')}</option>
                  {options.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <div className="flex gap-2">
                <label className="flex-1">
                  Top-K
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={topK}
                    onChange={(event) => setTopK(Number(event.target.value))}
                    className="mt-1 block h-8 w-full rounded-lg border border-border bg-surface px-2 text-xs text-ink"
                  />
                </label>
                <label className="flex-1">
                  {t('knowledgeEval.start.candidates')}
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={candidateK}
                    onChange={(event) => setCandidateK(Number(event.target.value))}
                    className="mt-1 block h-8 w-full rounded-lg border border-border bg-surface px-2 text-xs text-ink"
                  />
                </label>
              </div>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={hybrid}
                  onChange={(event) => setHybrid(event.target.checked)}
                />
                {t('knowledgeEval.start.hybrid')}
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={rerank}
                  onChange={(event) => setRerank(event.target.checked)}
                />
                {t('knowledgeEval.start.rerank')}
              </label>
            </div>
            <Button
              className="mt-3"
              size="sm"
              disabled={starting || datasetChoice === ''}
              onClick={() => void startRun()}
            >
              {starting ? (
                <Spinner className="h-3.5 w-3.5" />
              ) : (
                <Play className="h-3.5 w-3.5" />
              )}
              {t('knowledgeEval.start.run')}
            </Button>
            {datasetRows.length === 0 && (
              <p className="mt-2 text-[11px] text-ink-muted">
                {t('knowledgeEval.start.noDataset')}
              </p>
            )}
          </section>

          <section className="rounded-card border border-border bg-surface p-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-medium text-ink">
                {t('knowledgeEval.history.title')}
              </h2>
              <span className="text-[10px] text-ink-muted">
                {t('knowledgeEval.history.compareHint')}
              </span>
            </div>
            <div className="mt-2 space-y-1">
              {runs.isLoading && <Spinner />}
              {runRows.length === 0 && !runs.isLoading && (
                <p className="text-[11px] text-ink-muted">
                  {t('knowledgeEval.history.empty')}
                </p>
              )}
              {runRows.map((run) => (
                <div
                  key={run.id}
                  className={cn(
                    'flex items-center gap-2 rounded-lg px-2 py-1.5 text-[11px]',
                    selectedRunId === run.id ? 'bg-accent-soft' : 'hover:bg-surface-muted',
                  )}
                >
                  <input
                    type="checkbox"
                    checked={compareIds.includes(run.id)}
                    onChange={() => toggleCompare(run.id)}
                    aria-label={t('knowledgeEval.history.compare')}
                  />
                  <button
                    type="button"
                    onClick={() => setSelectedRunId(run.id)}
                    className="min-w-0 flex-1 text-left"
                  >
                    <span className="block font-mono text-ink">{run.id.slice(0, 8)}</span>
                    <span className="block text-[10px] text-ink-muted">
                      {String(run.metrics?.retrieval_mode ?? 'builtin')} ·{' '}
                      {run.retrieval_workflow_version_id === null
                        ? t('knowledgeEval.start.builtin')
                        : run.retrieval_workflow_version_id.slice(0, 8)}
                    </span>
                  </button>
                  <Badge
                    tone={
                      run.status === 'completed'
                        ? 'success'
                        : run.status === 'failed'
                          ? 'danger'
                          : 'accent'
                    }
                  >
                    {run.status}
                  </Badge>
                </div>
              ))}
            </div>
          </section>

          <section className="rounded-card border border-border bg-surface p-4">
            <h2 className="text-sm font-medium text-ink">
              {t('knowledgeEval.processing.title')}
            </h2>
            <p className="mt-1 text-[11px] text-ink-muted">
              {t('knowledgeEval.processing.hint')}
            </p>
            {(processComparison.data?.versions ?? []).length === 0 ? (
              <p className="mt-3 text-xs text-ink-muted">
                {t('knowledgeEval.processing.empty')}
              </p>
            ) : (
              <div className="mt-3 overflow-x-auto">
                <table className="w-full text-left text-[11px]">
                  <thead className="text-ink-muted">
                    <tr>
                      <th className="py-1 pr-3 font-medium">
                        {t('knowledgeEval.processing.version')}
                      </th>
                      <th className="py-1 pr-3 font-medium">
                        {t('knowledgeEval.processing.documents')}
                      </th>
                      <th className="py-1 pr-3 font-medium">
                        {t('knowledgeEval.processing.chunks')}
                      </th>
                      <th className="py-1 pr-3 font-medium">
                        {t('knowledgeEval.processing.avgChars')}
                      </th>
                      <th className="py-1 pr-3 font-medium">
                        {t('knowledgeEval.processing.metadata')}
                      </th>
                      <th className="py-1 pr-3 font-medium">
                        {t('knowledgeEval.processing.parent')}
                      </th>
                      <th className="py-1 pr-3 font-medium">
                        {t('knowledgeEval.processing.keywords')}
                      </th>
                      <th className="py-1 pr-3 font-medium">
                        {t('knowledgeEval.processing.summary')}
                      </th>
                      <th className="py-1 font-medium">
                        {t('knowledgeEval.processing.duplicates')}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {(processComparison.data?.versions ?? []).map((metric) => (
                      <tr key={metric.version_id} className="border-t border-border">
                        <td className="py-1 pr-3 text-ink">
                          {metric.workflow_name} · v{metric.version}
                        </td>
                        <td className="py-1 pr-3 text-ink-muted">
                          {metric.document_count}
                        </td>
                        <td className="py-1 pr-3 text-ink-muted">
                          {metric.chunk_count}
                        </td>
                        <td className="py-1 pr-3 text-ink-muted">
                          {metric.avg_chunk_chars.toFixed(1)}
                        </td>
                        <td className="py-1 pr-3 text-ink-muted">
                          {(metric.metadata_coverage * 100).toFixed(0)}%
                        </td>
                        <td className="py-1 pr-3 text-ink-muted">
                          {(metric.parent_coverage * 100).toFixed(0)}%
                        </td>
                        <td className="py-1 pr-3 text-ink-muted">
                          {(metric.keyword_coverage * 100).toFixed(0)}%
                        </td>
                        <td className="py-1 pr-3 text-ink-muted">
                          {(metric.summary_coverage * 100).toFixed(0)}%
                        </td>
                        <td className="py-1 text-ink-muted">
                          {(metric.duplicate_ratio * 100).toFixed(1)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {compareRuns.length === 2 && (
            <section className="rounded-card border border-border bg-surface p-4">
              <h2 className="text-sm font-medium text-ink">
                {t('knowledgeEval.compare.title')}
              </h2>
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-left text-[11px]">
                  <thead className="text-ink-muted">
                    <tr>
                      <th className="py-1 pr-2 font-medium">
                        {t('knowledgeEval.compare.metric')}
                      </th>
                      <th className="py-1 pr-2 font-medium">
                        A · {compareRuns[0].id.slice(0, 6)}
                      </th>
                      <th className="py-1 pr-2 font-medium">
                        B · {compareRuns[1].id.slice(0, 6)}
                      </th>
                      <th className="py-1 font-medium">
                        {t('knowledgeEval.compare.delta')}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {COMPARE_KEYS.map((key) => {
                      const left = metricNumber(compareRuns[0].metrics ?? {}, key)
                      const right = metricNumber(compareRuns[1].metrics ?? {}, key)
                      const delta =
                        left !== null && right !== null ? right - left : null
                      return (
                        <tr key={key} className="border-t border-border">
                          <td className="py-1 pr-2 font-mono text-ink-muted">{key}</td>
                          <td className="py-1 pr-2 text-ink">
                            {left === null ? '—' : left.toFixed(3)}
                          </td>
                          <td className="py-1 pr-2 text-ink">
                            {right === null ? '—' : right.toFixed(3)}
                          </td>
                          <td
                            className={cn(
                              'py-1',
                              delta === null
                                ? 'text-ink-muted'
                                : delta > 0
                                  ? 'text-success'
                                  : delta < 0
                                    ? 'text-danger'
                                    : 'text-ink-muted',
                            )}
                          >
                            {delta === null
                              ? '—'
                              : `${delta > 0 ? '+' : ''}${delta.toFixed(3)}`}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </div>

        <div className="space-y-3">
          <EvaluationRunDetailPanel runId={selectedRunId} />
          <OptimizationPanel kbId={id} runs={runRows} selectedRunId={selectedRunId} />
        </div>
      </div>
    </div>
  )
}