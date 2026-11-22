import { useQuery, useQueryClient } from '@tanstack/react-query'
import { FlaskConical, Play, Upload } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { EmptyState } from '../../components/ui/empty-state'
import { Input, Textarea } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { formatDate } from '../../lib/format'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  EvalDataset,
  EvalDatasetDetail,
  EvalMetrics,
  EvalRun,
  EvalRunDetail,
  KnowledgeBase,
  ModelEntry,
} from '../../lib/types'
import { cn } from '../../lib/utils'

const selectClass =
  'h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink focus:border-accent focus:outline-none'

interface RunForm {
  kbId: string
  topK: number
  candidateK: number
  hybrid: boolean
  rerank: boolean
  answer: boolean
  judge: boolean
  modelValue: string
  judgeModelValue: string
}

const initialForm: RunForm = {
  kbId: '',
  topK: 5,
  candidateK: 20,
  hybrid: true,
  rerank: true,
  answer: false,
  judge: false,
  modelValue: '',
  judgeModelValue: '',
}

function percent(value: unknown): string {
  return typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : '—'
}

function number(value: unknown, digits = 1): string {
  return typeof value === 'number' ? value.toFixed(digits) : '—'
}

function statusTone(status: string): 'success' | 'danger' | 'accent' | 'neutral' {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'queued' || status === 'running') return 'accent'
  return 'neutral'
}

export function EvaluationPage() {
  const { t, language } = useI18n()
  const queryClient = useQueryClient()
  const [selectedDatasetId, setSelectedDatasetId] = useState('')
  const [selectedRunId, setSelectedRunId] = useState('')
  const [compareIds, setCompareIds] = useState<string[]>([])
  const [form, setForm] = useState<RunForm>(initialForm)
  const [importOpen, setImportOpen] = useState(false)
  const [importName, setImportName] = useState('')
  const [importKbId, setImportKbId] = useState('')
  const [bundleText, setBundleText] = useState('')
  const [importError, setImportError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)

  const datasets = useQuery({
    queryKey: ['eval-datasets'],
    queryFn: () => apiRequest<EvalDataset[]>('/evaluations/datasets'),
  })
  const kbs = useQuery({
    queryKey: ['kbs'],
    queryFn: () => apiRequest<KnowledgeBase[]>('/knowledge-bases'),
  })
  const models = useQuery({
    queryKey: ['models'],
    queryFn: () => apiRequest<ModelEntry[]>('/models'),
    enabled: form.answer,
  })
  const datasetDetail = useQuery({
    queryKey: ['eval-dataset', selectedDatasetId],
    queryFn: () =>
      apiRequest<EvalDatasetDetail>(`/evaluations/datasets/${selectedDatasetId}`),
    enabled: selectedDatasetId !== '',
  })
  const runs = useQuery({
    queryKey: ['eval-runs', selectedDatasetId],
    queryFn: () =>
      apiRequest<EvalRun[]>(
        `/evaluations/runs${selectedDatasetId ? `?dataset_id=${selectedDatasetId}` : ''}`,
      ),
    refetchInterval: (query) =>
      query.state.data?.some((run) => run.status === 'queued' || run.status === 'running')
        ? 2000
        : false,
  })
  const runDetail = useQuery({
    queryKey: ['eval-run', selectedRunId],
    queryFn: () => apiRequest<EvalRunDetail>(`/evaluations/runs/${selectedRunId}`),
    enabled: selectedRunId !== '',
    refetchInterval: (query) =>
      query.state.data?.status === 'queued' || query.state.data?.status === 'running'
        ? 2000
        : false,
  })
  const compare = useQuery({
    queryKey: ['eval-compare', compareIds],
    queryFn: () =>
      apiRequest<{ runs: EvalRun[] }>(
        `/evaluations/compare?${compareIds.map((id) => `ids=${id}`).join('&')}`,
      ),
    enabled: compareIds.length === 2,
  })

  useEffect(() => {
    if (selectedDatasetId === '' && datasets.data !== undefined && datasets.data.length > 0) {
      setSelectedDatasetId(datasets.data[0].id)
    }
  }, [datasets.data, selectedDatasetId])

  useEffect(() => {
    if (form.kbId !== '' || kbs.data === undefined || kbs.data.length === 0) return
    setForm((previous) => ({ ...previous, kbId: kbs.data[0].id }))
  }, [form.kbId, kbs.data])

  useEffect(() => {
    if (selectedRunId !== '' || runs.data === undefined || runs.data.length === 0) return
    setSelectedRunId(runs.data[0].id)
  }, [runs.data, selectedRunId])

  const selectedDataset = datasets.data?.find((item) => item.id === selectedDatasetId)
  const selectedRun = runDetail.data
  const availableModels = useMemo(
    () => (models.data ?? []).filter((model) => model.available),
    [models.data],
  )
  const answerModel = useMemo(
    () =>
      availableModels.find(
        (model) => `${model.provider_id}::${model.model_id}` === form.modelValue,
      ),
    [availableModels, form.modelValue],
  )
  const judgeModel = useMemo(
    () =>
      form.judgeModelValue === ''
        ? answerModel
        : availableModels.find(
            (model) => `${model.provider_id}::${model.model_id}` === form.judgeModelValue,
          ),
    [answerModel, availableModels, form.judgeModelValue],
  )

  const openImport = () => {
    setImportName(`评测集 ${new Date().toLocaleDateString()}`)
    setImportKbId(kbs.data?.[0]?.id ?? '')
    setBundleText('')
    setImportError(null)
    setImportOpen(true)
  }

  const doImport = async () => {
    setImportError(null)
    if (importName.trim() === '' || importKbId === '' || bundleText.trim() === '') {
      setImportError(t('evaluation.importRequired'))
      return
    }
    try {
      const bundle = JSON.parse(bundleText)
      const created = await apiRequest<EvalDatasetDetail>('/evaluations/datasets/import', {
        method: 'POST',
        body: { name: importName.trim(), kb_id: importKbId, bundle },
      })
      await queryClient.invalidateQueries({ queryKey: ['eval-datasets'] })
      setSelectedDatasetId(created.id)
      setSelectedRunId('')
      setCompareIds([])
      setForm((previous) => ({ ...previous, kbId: importKbId }))
      setImportOpen(false)
    } catch (caught) {
      setImportError(t(errorTextKey(caught)))
    }
  }

  const startRun = async () => {
    if (selectedDatasetId === '' || form.kbId === '') {
      setActionError(t('evaluation.runForm.kbRequired'))
      return
    }
    if (form.answer && answerModel === undefined) {
      setActionError(t('evaluation.runForm.modelRequired'))
      return
    }
    setActionError(null)
    setStarting(true)
    try {
      const run = await apiRequest<EvalRun>('/evaluations/runs', {
        method: 'POST',
        body: {
          dataset_id: selectedDatasetId,
          kb_id: form.kbId,
          top_k: form.topK,
          candidate_k: form.candidateK,
          hybrid_enabled: form.hybrid,
          rerank_enabled: form.rerank,
          answer_enabled: form.answer,
          judge_enabled: form.judge,
          provider_id: answerModel?.provider_id ?? null,
          model: answerModel?.model_id ?? null,
          judge_provider_id: judgeModel?.provider_id ?? null,
          judge_model: judgeModel?.model_id ?? null,
        },
      })
      await queryClient.invalidateQueries({ queryKey: ['eval-runs'] })
      setSelectedRunId(run.id)
    } catch (caught) {
      setActionError(t(errorTextKey(caught)))
    } finally {
      setStarting(false)
    }
  }

  const toggleCompare = (runId: string) => {
    setCompareIds((previous) => {
      if (previous.includes(runId)) return previous.filter((id) => id !== runId)
      if (previous.length >= 2) return [previous[1], runId]
      return [...previous, runId]
    })
  }

  const metrics = selectedRun?.metrics ?? null

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-border bg-surface px-6 py-4">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            <FlaskConical className="h-5 w-5 text-accent" />
            {t('evaluation.title')}
          </h1>
          <p className="mt-1 text-sm text-ink-muted">{t('evaluation.lead')}</p>
        </div>
        <Button onClick={openImport}>
          <Upload className="h-4 w-4" />
          {t('evaluation.import')}
        </Button>
      </header>

      <div className="space-y-6 px-6 py-6">
        {actionError !== null && (
          <p role="alert" className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
            {actionError}
          </p>
        )}

        <section>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold">{t('evaluation.datasets')}</h2>
            <span className="text-xs text-ink-muted">
              {t('evaluation.datasetCount', { count: datasets.data?.length ?? 0 })}
            </span>
          </div>
          {datasets.isLoading && (
            <div className="flex items-center gap-2 text-sm text-ink-muted">
              <Spinner />
              {t('common.loading')}
            </div>
          )}
          {datasets.isSuccess && (datasets.data?.length ?? 0) === 0 && (
            <EmptyState
              title={t('evaluation.noDatasets')}
              description={t('evaluation.noDatasetsLead')}
            >
              <Button onClick={openImport}>
                <Upload className="h-4 w-4" />
                {t('evaluation.import')}
              </Button>
            </EmptyState>
          )}
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {datasets.data?.map((dataset) => (
              <button
                key={dataset.id}
                type="button"
                className={cn(
                  'rounded-card border p-4 text-left transition-colors',
                  dataset.id === selectedDatasetId
                    ? 'border-accent bg-accent-soft/40'
                    : 'border-border bg-surface hover:border-accent/40',
                )}
                onClick={() => {
                  setSelectedDatasetId(dataset.id)
                  setSelectedRunId('')
                  setCompareIds([])
                }}
              >
                <span className="block truncate text-sm font-medium text-ink">{dataset.name}</span>
                <span className="mt-1 block text-xs text-ink-muted">
                  {t('evaluation.questionCount', { count: dataset.question_count })} ·{' '}
                  {formatDate(dataset.created_at, language)}
                </span>
                {dataset.description !== '' && (
                  <span className="mt-2 block line-clamp-2 text-xs text-ink-muted">
                    {dataset.description}
                  </span>
                )}
              </button>
            ))}
          </div>
        </section>

        {selectedDataset !== undefined && (
          <section className="grid gap-4 xl:grid-cols-[360px_1fr]">
            <form
              className="h-fit rounded-card border border-border bg-surface p-4"
              onSubmit={(event) => {
                event.preventDefault()
                void startRun()
              }}
            >
              <h2 className="text-sm font-semibold">{t('evaluation.runForm.title')}</h2>
              <p className="mt-1 text-xs text-ink-muted">{selectedDataset.name}</p>
              <label className="mt-3 block text-xs text-ink-muted">
                <span className="mb-1 block">{t('evaluation.knowledgeBase')}</span>
                <select
                  className={selectClass}
                  value={form.kbId}
                  onChange={(event) => setForm({ ...form, kbId: event.target.value })}
                >
                  <option value="">{t('evaluation.chooseKb')}</option>
                  {(kbs.data ?? []).map((kb) => (
                    <option key={kb.id} value={kb.id}>
                      {kb.name}
                    </option>
                  ))}
                </select>
              </label>
              <div className="mt-3 grid grid-cols-2 gap-3">
                <label className="text-xs text-ink-muted">
                  <span className="mb-1 block">{t('evaluation.runForm.topK')}</span>
                  <Input
                    type="number"
                    min={1}
                    max={20}
                    value={form.topK}
                    onChange={(event) =>
                      setForm({ ...form, topK: Number(event.target.value) || 1 })
                    }
                  />
                </label>
                <label className="text-xs text-ink-muted">
                  <span className="mb-1 block">{t('evaluation.runForm.candidateK')}</span>
                  <Input
                    type="number"
                    min={1}
                    max={100}
                    value={form.candidateK}
                    onChange={(event) =>
                      setForm({ ...form, candidateK: Number(event.target.value) || 1 })
                    }
                  />
                </label>
              </div>
              <div className="mt-3 space-y-2 text-sm">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={form.hybrid}
                    onChange={(event) => setForm({ ...form, hybrid: event.target.checked })}
                  />
                  {t('evaluation.runForm.hybrid')}
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={form.rerank}
                    onChange={(event) => setForm({ ...form, rerank: event.target.checked })}
                  />
                  {t('evaluation.runForm.rerank')}
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={form.answer}
                    onChange={(event) =>
                      setForm({
                        ...form,
                        answer: event.target.checked,
                        judge: event.target.checked ? form.judge : false,
                      })
                    }
                  />
                  {t('evaluation.runForm.answer')}
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={form.judge}
                    disabled={!form.answer}
                    onChange={(event) => setForm({ ...form, judge: event.target.checked })}
                  />
                  {t('evaluation.runForm.judge')}
                </label>
              </div>
              {form.answer && (
                <div className="mt-3 space-y-3">
                  <label className="block text-xs text-ink-muted">
                    <span className="mb-1 block">{t('evaluation.runForm.model')}</span>
                    <select
                      className={selectClass}
                      value={form.modelValue}
                      onChange={(event) => setForm({ ...form, modelValue: event.target.value })}
                    >
                      <option value="">{t('evaluation.runForm.chooseModel')}</option>
                      {availableModels.map((model) => (
                        <option
                          key={`${model.provider_id}::${model.model_id}`}
                          value={`${model.provider_id}::${model.model_id}`}
                        >
                          {model.display_name} · {model.provider_id}
                        </option>
                      ))}
                    </select>
                  </label>
                  {form.judge && (
                    <label className="block text-xs text-ink-muted">
                      <span className="mb-1 block">{t('evaluation.runForm.judgeModel')}</span>
                      <select
                        className={selectClass}
                        value={form.judgeModelValue}
                        onChange={(event) =>
                          setForm({ ...form, judgeModelValue: event.target.value })
                        }
                      >
                        <option value="">{t('evaluation.runForm.sameModel')}</option>
                        {availableModels.map((model) => (
                          <option
                            key={`${model.provider_id}::${model.model_id}`}
                            value={`${model.provider_id}::${model.model_id}`}
                          >
                            {model.display_name} · {model.provider_id}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                </div>
              )}
              <p className="mt-3 text-xs text-ink-muted">{t('evaluation.runForm.judgeHint')}</p>
              <Button className="mt-4 w-full" type="submit" disabled={starting}>
                {starting ? <Spinner /> : <Play className="h-4 w-4" />}
                {t('evaluation.runForm.start')}
              </Button>
              {(datasetDetail.data?.questions.length ?? 0) > 0 && (
                <div className="mt-4 border-t border-border pt-3">
                  <p className="text-xs font-medium text-ink-muted">
                    {t('evaluation.runForm.preview')}
                  </p>
                  <ul className="mt-1 space-y-1 text-xs text-ink-muted">
                    {datasetDetail.data?.questions.slice(0, 3).map((question) => (
                      <li key={question.id} className="truncate">
                        · {question.question}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </form>

            <div className="space-y-4">
              <div className="rounded-card border border-border bg-surface">
                <div className="flex items-center justify-between border-b border-border px-4 py-3">
                  <h2 className="text-sm font-semibold">{t('evaluation.runs.title')}</h2>
                  <span className="text-xs text-ink-muted">
                    {t('evaluation.runs.compareHint')}
                  </span>
                </div>
                {runs.isLoading && (
                  <div className="flex items-center gap-2 px-4 py-4 text-sm text-ink-muted">
                    <Spinner />
                    {t('common.loading')}
                  </div>
                )}
                {runs.isSuccess && (runs.data?.length ?? 0) === 0 && (
                  <p className="px-4 py-4 text-sm text-ink-muted">{t('evaluation.runs.empty')}</p>
                )}
                <div className="divide-y divide-border">
                  {runs.data?.map((run) => {
                    const runMetrics = (run.metrics ?? {}) as EvalMetrics
                    return (
                      <div
                        key={run.id}
                        className={cn(
                          'flex flex-wrap items-center gap-3 px-4 py-3',
                          run.id === selectedRunId && 'bg-accent-soft/30',
                        )}
                      >
                        <input
                          type="checkbox"
                          checked={compareIds.includes(run.id)}
                          onChange={() => toggleCompare(run.id)}
                          aria-label={t('evaluation.runs.selectCompare')}
                        />
                        <button
                          type="button"
                          className="min-w-0 flex-1 text-left"
                          onClick={() => setSelectedRunId(run.id)}
                        >
                          <span className="flex flex-wrap items-center gap-2">
                            <Badge tone={statusTone(run.status)}>{run.status}</Badge>
                            <span className="text-xs text-ink-muted">
                              {formatDate(run.created_at, language)}
                            </span>
                            <span className="text-xs text-ink-muted">
                              {t('evaluation.runs.progress', {
                                done: run.progress_done,
                                total: run.progress_total,
                              })}
                            </span>
                          </span>
                          <span className="mt-1 block text-xs text-ink-muted">
                            {t('evaluation.runs.summary', {
                              recall: percent(runMetrics.recall_at_1),
                              mrr: number(runMetrics.mrr, 3),
                            })}
                          </span>
                        </button>
                      </div>
                    )
                  })}
                </div>
              </div>

              {selectedRun !== undefined && <RunDetail run={selectedRun} metrics={metrics} />}
            </div>
          </section>
        )}

        {compareIds.length === 2 && (
          <ComparePanel
            runs={compare.data?.runs ?? []}
            loading={compare.isLoading}
            onClear={() => setCompareIds([])}
          />
        )}
      </div>

      <Dialog
        open={importOpen}
        onClose={() => setImportOpen(false)}
        title={t('evaluation.importTitle')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setImportOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button size="sm" onClick={() => void doImport()}>
              {t('evaluation.importAction')}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <label className="block text-xs text-ink-muted">
            <span className="mb-1 block">{t('evaluation.name')}</span>
            <Input value={importName} onChange={(event) => setImportName(event.target.value)} />
          </label>
          <label className="block text-xs text-ink-muted">
            <span className="mb-1 block">{t('evaluation.knowledgeBase')}</span>
            <select
              className={selectClass}
              value={importKbId}
              onChange={(event) => setImportKbId(event.target.value)}
            >
              <option value="">{t('evaluation.chooseKb')}</option>
              {(kbs.data ?? []).map((kb) => (
                <option key={kb.id} value={kb.id}>
                  {kb.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-xs text-ink-muted">
            <span className="mb-1 block">{t('evaluation.bundle')}</span>
            <Textarea
              rows={10}
              className="font-mono text-xs"
              value={bundleText}
              placeholder={t('evaluation.bundlePlaceholder')}
              onChange={(event) => setBundleText(event.target.value)}
            />
          </label>
          <p className="text-xs text-ink-muted">{t('evaluation.importHint')}</p>
          {importError !== null && <p className="text-xs text-danger">{importError}</p>}
        </div>
      </Dialog>
    </div>
  )
}

function RunDetail({ run, metrics }: { run: EvalRunDetail; metrics: EvalMetrics | null }) {
  const { t } = useI18n()
  const config = run.config as Record<string, unknown>
  return (
    <div className="rounded-card border border-border bg-surface">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <Badge tone={statusTone(run.status)}>{run.status}</Badge>
        <span className="text-xs text-ink-muted">
          {t('evaluation.runs.progress', {
            done: run.progress_done,
            total: run.progress_total,
          })}
        </span>
        {run.error_code !== null && <Badge tone="danger">{run.error_code}</Badge>}
        <span className="ml-auto text-xs text-ink-muted">
          {t('evaluation.detail.config', {
            topK: String(config.top_k ?? '—'),
            hybrid: String(config.hybrid_enabled ?? false),
            rerank: String(config.rerank_enabled ?? false),
          })}
        </span>
      </div>
      <div className="grid gap-3 px-4 py-4 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label={t('evaluation.detail.recall1')} value={percent(metrics?.recall_at_1)} />
        <Metric label={t('evaluation.detail.recall3')} value={percent(metrics?.recall_at_3)} />
        <Metric label={t('evaluation.detail.recall5')} value={percent(metrics?.recall_at_5)} />
        <Metric label={t('evaluation.detail.mrr')} value={number(metrics?.mrr, 3)} />
        <Metric label={t('evaluation.detail.p95')} value={`${number(metrics?.latency_p95_ms)} ms`} />
        <Metric label={t('evaluation.detail.cost')} value={`$${number(metrics?.cost, 6)}`} />
        <Metric
          label={t('evaluation.detail.judgeAvg')}
          value={metrics?.judge_avg_score === null ? '—' : number(metrics?.judge_avg_score, 2)}
        />
        <Metric
          label={t('evaluation.detail.judgePass')}
          value={percent(metrics?.judge_pass_rate)}
        />
      </div>
      {run.items.length === 0 ? (
        <p className="px-4 pb-4 text-sm text-ink-muted">{t('evaluation.detail.noItems')}</p>
      ) : (
        <div className="overflow-x-auto border-t border-border">
          <table className="w-full min-w-[760px] text-left text-xs">
            <thead className="text-ink-muted">
              <tr>
                <th className="px-4 py-2 font-medium">{t('evaluation.detail.question')}</th>
                <th className="px-4 py-2 font-medium">{t('evaluation.detail.rank')}</th>
                <th className="px-4 py-2 font-medium">{t('evaluation.detail.latency')}</th>
                <th className="px-4 py-2 font-medium">{t('evaluation.detail.judge')}</th>
                <th className="px-4 py-2 font-medium">{t('evaluation.detail.answer')}</th>
              </tr>
            </thead>
            <tbody>
              {run.items.map((item) => (
                <tr key={item.id} className="border-t border-border align-top">
                  <td className="max-w-[260px] px-4 py-2 text-ink">{item.question_text}</td>
                  <td className="px-4 py-2 text-ink-muted">
                    {item.hit_rank === null ? t('evaluation.detail.miss') : `#${item.hit_rank}`}
                  </td>
                  <td className="px-4 py-2 text-ink-muted">
                    {item.latency_ms === null ? '—' : `${item.latency_ms.toFixed(1)} ms`}
                  </td>
                  <td className="px-4 py-2 text-ink-muted">
                    {item.judge_score === null ? (
                      (item.judge_error ?? '—')
                    ) : (
                      <span title={item.judge_reason ?? ''}>
                        {item.judge_score}/5 · {item.judge_faithful ? '✓' : '✗'}
                      </span>
                    )}
                  </td>
                  <td className="max-w-[360px] px-4 py-2 text-ink-muted">
                    {item.answer === null ? (
                      '—'
                    ) : (
                      <details>
                        <summary className="cursor-pointer text-ink">
                          {item.answer.slice(0, 80)}
                        </summary>
                        <p className="mt-1 whitespace-pre-wrap">{item.answer}</p>
                      </details>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-ink-muted">{label}</p>
      <p className="mt-1 text-sm font-semibold text-ink">{value}</p>
    </div>
  )
}

function ComparePanel({
  runs,
  loading,
  onClear,
}: {
  runs: EvalRun[]
  loading: boolean
  onClear: () => void
}) {
  const { t } = useI18n()
  const keys = [
    'recall_at_1',
    'recall_at_3',
    'recall_at_5',
    'mrr',
    'latency_p95_ms',
    'judge_avg_score',
    'judge_pass_rate',
  ] as const
  if (loading || runs.length !== 2) {
    return (
      <div className="flex items-center gap-2 text-sm text-ink-muted">
        <Spinner />
        {t('common.loading')}
      </div>
    )
  }
  const [first, second] = runs
  return (
    <section className="rounded-card border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">{t('evaluation.compare.title')}</h2>
        <Button variant="ghost" size="sm" onClick={onClear}>
          {t('evaluation.compare.clear')}
        </Button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-left text-sm">
          <thead className="text-xs text-ink-muted">
            <tr>
              <th className="px-4 py-2 font-medium">{t('evaluation.compare.metric')}</th>
              <th className="px-4 py-2 font-medium">A · {first.id.slice(0, 8)}</th>
              <th className="px-4 py-2 font-medium">B · {second.id.slice(0, 8)}</th>
              <th className="px-4 py-2 font-medium">{t('evaluation.compare.delta')}</th>
            </tr>
          </thead>
          <tbody>
            {keys.map((key) => {
              const left = first.metrics?.[key]
              const right = second.metrics?.[key]
              const delta =
                typeof left === 'number' && typeof right === 'number' ? right - left : null
              return (
                <tr key={key} className="border-t border-border">
                  <td className="px-4 py-2 text-ink-muted">{key}</td>
                  <td className="px-4 py-2">{typeof left === 'number' ? left : '—'}</td>
                  <td className="px-4 py-2">{typeof right === 'number' ? right : '—'}</td>
                  <td
                    className={cn(
                      'px-4 py-2',
                      delta === null
                        ? 'text-ink-muted'
                        : delta > 0
                          ? 'text-success'
                          : delta < 0
                            ? 'text-danger'
                            : 'text-ink-muted',
                    )}
                  >
                    {delta === null ? '—' : `${delta > 0 ? '+' : ''}${delta.toFixed(3)}`}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}