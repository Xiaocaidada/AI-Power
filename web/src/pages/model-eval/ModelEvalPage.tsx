import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ClipboardList,
  Download,
  Pencil,
  Play,
  Plus,
  RotateCcw,
  Square,
  Trash2,
} from 'lucide-react'
import { useState } from 'react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { Input } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  ModelEntry,
  ModelEvalDataset,
  ModelEvalItem,
  ModelEvalQuestion,
  ModelEvalRun,
  PersonalModel,
} from '../../lib/types'

interface Choice {
  provider_id: string
  model: string
  label: string
}

export function ModelEvalPage() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [questionsJson, setQuestionsJson] = useState('[]')
  const [datasetError, setDatasetError] = useState<string | null>(null)
  const [selectedDataset, setSelectedDataset] = useState('')
  const [selectedModels, setSelectedModels] = useState<Choice[]>([])
  const [concurrency, setConcurrency] = useState('3')
  const [useRule, setUseRule] = useState(true)
  const [useAi, setUseAi] = useState(false)
  const [judgeModel, setJudgeModel] = useState('')
  const [runError, setRunError] = useState<string | null>(null)
  const [selectedRun, setSelectedRun] = useState('')
  const [scoreTarget, setScoreTarget] = useState<ModelEvalItem | null>(null)
  const [scoreValue, setScoreValue] = useState('')
  const [scoreReason, setScoreReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [questionTarget, setQuestionTarget] = useState<ModelEvalQuestion | 'new' | null>(
    null,
  )
  const [questionText, setQuestionText] = useState('')
  const [referenceAnswer, setReferenceAnswer] = useState('')
  const [scoringCriteria, setScoringCriteria] = useState('')
  const [expectedKeywords, setExpectedKeywords] = useState('')
  const [questionRegex, setQuestionRegex] = useState('')
  const [questionError, setQuestionError] = useState<string | null>(null)
  const [deleteDatasetTarget, setDeleteDatasetTarget] = useState<ModelEvalDataset | null>(
    null,
  )
  const [deleteRunTarget, setDeleteRunTarget] = useState<ModelEvalRun | null>(null)
  const [deleteQuestionTarget, setDeleteQuestionTarget] =
    useState<ModelEvalQuestion | null>(null)

  const datasets = useQuery({
    queryKey: ['model-eval-datasets'],
    queryFn: () => apiRequest<ModelEvalDataset[]>('/model-eval/datasets'),
  })
  const datasetDetail = useQuery({
    queryKey: ['model-eval-dataset', selectedDataset],
    queryFn: () =>
      apiRequest<ModelEvalDataset>(`/model-eval/datasets/${selectedDataset}`),
    enabled: selectedDataset !== '',
  })
  const runs = useQuery({
    queryKey: ['model-eval-runs'],
    queryFn: () => apiRequest<ModelEvalRun[]>('/model-eval/runs?limit=30'),
    refetchInterval: (query) =>
      (query.state.data ?? []).some(
        (run) => run.status === 'queued' || run.status === 'running',
      )
        ? 3000
        : false,
  })
  const runDetail = useQuery({
    queryKey: ['model-eval-run', selectedRun],
    queryFn: () => apiRequest<ModelEvalRun>(`/model-eval/runs/${selectedRun}`),
    enabled: selectedRun !== '',
    refetchInterval: (query) =>
      query.state.data?.status === 'running' || query.state.data?.status === 'queued'
        ? 2500
        : false,
  })
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

  const choices: Choice[] = [
    ...(platformModels.data ?? [])
      .filter((item) => item.available)
      .map((item) => ({
        provider_id: item.provider_id,
        model: item.model_id,
        label: `${item.display_name} · ${item.provider_id}`,
      })),
    ...(personalModels.data ?? []).map((item) => ({
      provider_id: item.provider_id,
      model: item.model_id,
      label: `${item.display_name} · ${item.provider_name}`,
    })),
  ]

  const createDataset = async () => {
    setDatasetError(null)
    let questions: unknown
    try {
      questions = JSON.parse(questionsJson)
      if (!Array.isArray(questions)) throw new Error('questions must be an array')
    } catch {
      setDatasetError(t('modelEval.invalidJson'))
      return
    }
    setBusy(true)
    try {
      await apiRequest('/model-eval/datasets', {
        method: 'POST',
        body: { name: name.trim(), description: description.trim(), questions },
      })
      await queryClient.invalidateQueries({ queryKey: ['model-eval-datasets'] })
      setCreateOpen(false)
      setName('')
      setDescription('')
      setQuestionsJson('[]')
    } catch (caught) {
      setDatasetError(t(errorTextKey(caught)))
    } finally {
      setBusy(false)
    }
  }

  const createRun = async () => {
    if (selectedDataset === '' || selectedModels.length === 0) return
    setBusy(true)
    setRunError(null)
    const judge = choices.find(
      (item) => `${item.provider_id}/${item.model}` === judgeModel,
    )
    try {
      await apiRequest('/model-eval/runs', {
        method: 'POST',
        body: {
          dataset_id: selectedDataset,
          models: selectedModels.map(({ provider_id, model }) => ({
            provider_id,
            model,
          })),
          concurrency: Number(concurrency) || 3,
          methods: [...(useRule ? ['rule'] : []), ...(useAi ? ['ai'] : [])],
          judge_provider_id: judge?.provider_id ?? null,
          judge_model: judge?.model ?? null,
        },
      })
      await queryClient.invalidateQueries({ queryKey: ['model-eval-runs'] })
    } catch (caught) {
      setRunError(t(errorTextKey(caught)))
    } finally {
      setBusy(false)
    }
  }

  const cancelRun = async (runId: string) => {
    await apiRequest(`/model-eval/runs/${runId}/cancel`, { method: 'POST' })
    await queryClient.invalidateQueries({ queryKey: ['model-eval-runs'] })
    await queryClient.invalidateQueries({ queryKey: ['model-eval-run', runId] })
  }

  const retryItem = async (item: ModelEvalItem) => {
    await apiRequest(`/model-eval/items/${item.id}/retry`, { method: 'POST' })
    await queryClient.invalidateQueries({ queryKey: ['model-eval-run', selectedRun] })
    await queryClient.invalidateQueries({ queryKey: ['model-eval-runs'] })
  }

  const saveScore = async () => {
    if (scoreTarget === null) return
    await apiRequest(`/model-eval/items/${scoreTarget.id}/scores`, {
      method: 'POST',
      body: {
        score: scoreValue.trim() === '' ? null : Number(scoreValue),
        passed: null,
        reason: scoreReason,
      },
    })
    setScoreTarget(null)
    await queryClient.invalidateQueries({ queryKey: ['model-eval-run', selectedRun] })
  }

  const exportDataset = async () => {
    if (selectedDataset === '') return
    const data = await apiRequest<Record<string, unknown>>(
      `/model-eval/datasets/${selectedDataset}/export`,
    )
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = 'model-eval-dataset.json'
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
  }

  const openQuestion = (question: ModelEvalQuestion | 'new') => {
    setQuestionTarget(question)
    setQuestionError(null)
    if (question === 'new') {
      setQuestionText('')
      setReferenceAnswer('')
      setScoringCriteria('')
      setExpectedKeywords('')
      setQuestionRegex('')
    } else {
      setQuestionText(question.question)
      setReferenceAnswer(question.reference_answer)
      setScoringCriteria(question.scoring_criteria)
      setExpectedKeywords(question.expected_keywords.join(', '))
      setQuestionRegex(question.regex)
    }
  }

  const saveQuestion = async () => {
    if (questionTarget === null || selectedDataset === '') return
    if (questionText.trim() === '') {
      setQuestionError(t('modelEval.questionRequired'))
      return
    }
    setBusy(true)
    setQuestionError(null)
    const body = {
      question: questionText.trim(),
      reference_answer: referenceAnswer,
      scoring_criteria: scoringCriteria,
      expected_keywords: expectedKeywords
        .split(',')
        .map((item) => item.trim())
        .filter((item) => item !== ''),
      regex: questionRegex,
    }
    try {
      if (questionTarget === 'new') {
        await apiRequest(`/model-eval/datasets/${selectedDataset}/questions`, {
          method: 'POST',
          body,
        })
      } else {
        await apiRequest(`/model-eval/questions/${questionTarget.id}`, {
          method: 'PATCH',
          body,
        })
      }
      await queryClient.invalidateQueries({
        queryKey: ['model-eval-dataset', selectedDataset],
      })
      await queryClient.invalidateQueries({ queryKey: ['model-eval-datasets'] })
      setQuestionTarget(null)
    } catch (caught) {
      setQuestionError(t(errorTextKey(caught)))
    } finally {
      setBusy(false)
    }
  }

  const deleteQuestion = async () => {
    if (deleteQuestionTarget === null) return
    setBusy(true)
    try {
      await apiRequest(`/model-eval/questions/${deleteQuestionTarget.id}`, {
        method: 'DELETE',
      })
      await queryClient.invalidateQueries({
        queryKey: ['model-eval-dataset', selectedDataset],
      })
      await queryClient.invalidateQueries({ queryKey: ['model-eval-datasets'] })
      setDeleteQuestionTarget(null)
      setQuestionError(null)
    } catch (caught) {
      setQuestionError(t(errorTextKey(caught)))
      setDeleteQuestionTarget(null)
    } finally {
      setBusy(false)
    }
  }

  const deleteDataset = async () => {
    if (deleteDatasetTarget === null) return
    setBusy(true)
    try {
      await apiRequest(`/model-eval/datasets/${deleteDatasetTarget.id}`, {
        method: 'DELETE',
      })
      await queryClient.invalidateQueries({ queryKey: ['model-eval-datasets'] })
      if (selectedDataset === deleteDatasetTarget.id) setSelectedDataset('')
      setDeleteDatasetTarget(null)
    } finally {
      setBusy(false)
    }
  }

  const deleteRun = async () => {
    if (deleteRunTarget === null) return
    setBusy(true)
    try {
      await apiRequest(`/model-eval/runs/${deleteRunTarget.id}`, { method: 'DELETE' })
      await queryClient.invalidateQueries({ queryKey: ['model-eval-runs'] })
      if (selectedRun === deleteRunTarget.id) setSelectedRun('')
      setDeleteRunTarget(null)
    } finally {
      setBusy(false)
    }
  }

  const run = runDetail.data

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-4">
        <h1 className="flex items-center gap-2 text-lg font-semibold">
          <ClipboardList className="h-5 w-5 text-accent" />
          {t('modelEval.title')}
        </h1>
        <p className="mt-1 text-sm text-ink-muted">{t('modelEval.lead')}</p>
      </header>

      <div className="mx-auto grid w-full max-w-7xl gap-4 px-6 py-6 lg:grid-cols-[1fr_1.2fr]">
        <section className="space-y-3">
          <div className="rounded-card border border-border bg-surface">
            <div className="flex items-center justify-between border-b border-border px-4 py-2">
              <p className="text-sm font-medium">{t('modelEval.datasets')}</p>
              <Button size="sm" variant="ghost" onClick={() => setCreateOpen(true)}>
                + {t('common.create')}
              </Button>
            </div>
            <div className="max-h-56 divide-y divide-border overflow-y-auto">
              {(datasets.data ?? []).map((dataset) => (
                <div key={dataset.id} className="flex items-center">
                  <button
                    type="button"
                    onClick={() => setSelectedDataset(dataset.id)}
                    className={`min-w-0 flex-1 px-4 py-2 text-left ${
                      selectedDataset === dataset.id
                        ? 'bg-accent-soft text-accent'
                        : 'hover:bg-surface-muted'
                    }`}
                  >
                    <span className="block truncate text-xs font-medium">
                      {dataset.name}
                    </span>
                    <span className="text-[10px] text-ink-muted">
                      {dataset.question_count} questions
                    </span>
                  </button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={t('common.delete')}
                    onClick={() => setDeleteDatasetTarget(dataset)}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
              ))}
              {datasets.data !== undefined && datasets.data.length === 0 && (
                <p className="px-4 py-4 text-xs text-ink-muted">{t('modelEval.noDatasets')}</p>
              )}
            </div>
          </div>

          {selectedDataset !== '' && (
            <div className="rounded-card border border-border bg-surface">
              <div className="flex items-center justify-between border-b border-border px-4 py-2">
                <p className="text-sm font-medium">{t('modelEval.questions')}</p>
                <Button size="sm" variant="ghost" onClick={() => openQuestion('new')}>
                  <Plus className="h-3 w-3" />
                  {t('modelEval.addQuestion')}
                </Button>
              </div>
              {datasetDetail.isLoading && <Spinner className="m-3" />}
              <div className="max-h-64 divide-y divide-border overflow-y-auto">
                {(datasetDetail.data?.questions ?? []).map((question) => (
                  <div key={question.id} className="px-4 py-2">
                    <div className="flex items-start gap-2">
                      <p className="min-w-0 flex-1 text-xs text-ink">
                        {question.question}
                      </p>
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={t('common.edit')}
                        onClick={() => openQuestion(question)}
                      >
                        <Pencil className="h-3 w-3" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={t('common.delete')}
                        onClick={() => setDeleteQuestionTarget(question)}
                      >
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </div>
                    {question.expected_keywords.length > 0 && (
                      <p className="mt-0.5 text-[10px] text-ink-muted">
                        {t('modelEval.keywords')}: {question.expected_keywords.join(', ')}
                      </p>
                    )}
                  </div>
                ))}
                {datasetDetail.data !== undefined &&
                  (datasetDetail.data.questions ?? []).length === 0 && (
                    <p className="px-4 py-3 text-xs text-ink-muted">
                      {t('modelEval.noQuestions')}
                    </p>
                  )}
              </div>
              {questionError !== null && questionTarget === null && (
                <p className="px-4 py-2 text-xs text-danger">{questionError}</p>
              )}
            </div>
          )}

          <div className="rounded-card border border-border bg-surface p-4">
            <p className="text-sm font-medium">{t('modelEval.newRun')}</p>
            <p className="mt-1 text-[11px] text-ink-muted">
              {selectedDataset === ''
                ? t('modelEval.selectDataset')
                : t('modelEval.selectedDataset', {
                    id:
                      datasets.data?.find((item) => item.id === selectedDataset)?.name ?? '',
                  })}
            </p>
            <div className="mt-2 max-h-48 space-y-1 overflow-y-auto">
              {choices.map((choice) => {
                const key = `${choice.provider_id}/${choice.model}`
                const active = selectedModels.some(
                  (item) => `${item.provider_id}/${item.model}` === key,
                )
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() =>
                      setSelectedModels((prev) =>
                        active
                          ? prev.filter(
                              (item) => `${item.provider_id}/${item.model}` !== key,
                            )
                          : [...prev, choice],
                      )
                    }
                    className={`block w-full truncate rounded px-2 py-1 text-left text-[11px] ${
                      active
                        ? 'bg-accent-soft text-accent'
                        : 'text-ink-muted hover:bg-surface-muted'
                    }`}
                  >
                    {choice.label}
                  </button>
                )
              })}
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-ink-muted">
              <label>
                {t('modelEval.concurrency')}
                <Input
                  className="mt-1"
                  value={concurrency}
                  onChange={(event) => setConcurrency(event.target.value)}
                />
              </label>
              <label>
                {t('modelEval.judge')}
                <select
                  value={judgeModel}
                  onChange={(event) => setJudgeModel(event.target.value)}
                  className="mt-1 h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink"
                >
                  <option value="">{t('modelEval.noJudge')}</option>
                  {choices.map((choice) => (
                    <option
                      key={`${choice.provider_id}/${choice.model}`}
                      value={`${choice.provider_id}/${choice.model}`}
                    >
                      {choice.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="mt-2 flex gap-4 text-xs text-ink-muted">
              <label className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={useRule}
                  onChange={(event) => setUseRule(event.target.checked)}
                />
                {t('modelEval.rule')}
              </label>
              <label className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={useAi}
                  onChange={(event) => setUseAi(event.target.checked)}
                />
                {t('modelEval.ai')}
              </label>
            </div>
            {runError !== null && <p className="mt-2 text-xs text-danger">{runError}</p>}
            <div className="mt-3 flex gap-2">
              <Button
                size="sm"
                disabled={
                  busy || selectedDataset === '' || selectedModels.length === 0
                }
                onClick={() => void createRun()}
              >
                <Play className="h-3.5 w-3.5" />
                {t('modelEval.start')}
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={selectedDataset === ''}
                onClick={() => void exportDataset()}
              >
                <Download className="h-3.5 w-3.5" />
                {t('modelEval.export')}
              </Button>
            </div>
          </div>
        </section>

        <section className="rounded-card border border-border bg-surface">
          <p className="border-b border-border px-4 py-2 text-sm font-medium">
            {t('modelEval.runs')}
          </p>
          {runs.isLoading && <Spinner className="m-4" />}
          <div className="max-h-[32rem] divide-y divide-border overflow-y-auto">
            {(runs.data ?? []).map((item) => (
              <div key={item.id} className="flex items-center gap-2 px-4 py-2">
                <button
                  type="button"
                  onClick={() => setSelectedRun(item.id)}
                  className="min-w-0 flex-1 text-left"
                >
                  <p className="truncate text-xs font-medium text-ink">{item.name}</p>
                  <p className="text-[10px] text-ink-muted">
                    {item.progress_done}/{item.progress_total} · {item.status}
                    {item.current_model ? ` · ${item.current_model}` : ''}
                  </p>
                </button>
                <Badge
                  tone={
                    item.status === 'completed'
                      ? 'success'
                      : item.status === 'failed'
                        ? 'danger'
                        : 'neutral'
                  }
                >
                  {item.status}
                </Badge>
                {(item.status === 'queued' || item.status === 'running') && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => void cancelRun(item.id)}
                  >
                    <Square className="h-3 w-3" />
                  </Button>
                )}
                {item.status !== 'queued' && item.status !== 'running' && (
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={t('common.delete')}
                    onClick={() => setDeleteRunTarget(item)}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                )}
              </div>
            ))}
            {runs.data !== undefined && runs.data.length === 0 && (
              <p className="px-4 py-4 text-xs text-ink-muted">{t('modelEval.noRuns')}</p>
            )}
          </div>
        </section>
      </div>

      {run !== undefined && (
        <div className="border-t border-border px-6 py-4">
          <div className="mx-auto max-w-7xl">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="text-sm font-medium">{run.name}</p>
                <p className="text-[11px] text-ink-muted">
                  {run.progress_done}/{run.progress_total} · failed {run.progress_failed}
                </p>
              </div>
              <Badge tone={run.status === 'completed' ? 'success' : 'neutral'}>
                {run.status}
              </Badge>
            </div>
            {run.metrics !== null && run.metrics !== undefined && (
              <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                {Object.entries(
                  (run.metrics.models ?? {}) as Record<
                    string,
                    Record<string, number | null>
                  >,
                ).map(([model, metrics]) => (
                  <div
                    key={model}
                    className="rounded-card border border-border bg-surface p-3 text-xs"
                  >
                    <p className="truncate font-medium text-ink">{model}</p>
                    <p className="mt-1 text-ink-muted">
                      success{' '}
                      {metrics.success_rate !== null
                        ? `${Math.round((metrics.success_rate ?? 0) * 100)}%`
                        : '—'}
                    </p>
                    <p className="text-ink-muted">
                      rule{' '}
                      {metrics.rule_pass_rate !== null
                        ? `${Math.round((metrics.rule_pass_rate ?? 0) * 100)}%`
                        : '—'}{' '}
                      · AI {metrics.ai_avg_score?.toFixed(2) ?? '—'} (
                      {metrics.ai_scored ?? 0}/{metrics.completed ?? 0}) · manual{' '}
                      {metrics.manual_avg_score?.toFixed(2) ?? '—'}
                    </p>
                    <p className="text-ink-muted">
                      TTFT {metrics.avg_ttft_ms?.toFixed(0) ?? '—'} ms · ~$
                      {(metrics.cost ?? 0).toFixed(6)}
                    </p>
                  </div>
                ))}
              </div>
            )}
            <div className="mt-3 space-y-2">
              {(run.items ?? []).map((item) => (
                <div
                  key={item.id}
                  className="rounded-card border border-border bg-surface p-3"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={item.status === 'completed' ? 'success' : 'danger'}>
                      {item.status}
                    </Badge>
                    <span className="text-xs font-medium text-ink">{item.model}</span>
                    <span className="text-[10px] text-ink-muted">{item.provider_id}</span>
                    <span className="ml-auto flex gap-2 text-[10px] text-ink-muted">
                      {item.scores.map((score) => (
                        <span key={score.method}>
                          {score.method}: {score.score ?? '—'}
                          {score.passed !== null
                            ? ` (${score.passed ? 'pass' : 'fail'})`
                            : ''}
                        </span>
                      ))}
                    </span>
                  </div>
                  <p className="mt-1 truncate text-xs text-ink-muted">{item.question}</p>
                  <p className="mt-1 max-h-24 overflow-y-auto whitespace-pre-wrap text-xs text-ink">
                    {item.answer || item.error_code || '—'}
                  </p>
                  {item.scores.some((score) => score.reason !== '') && (
                    <ul className="mt-1 space-y-0.5 text-[10px] text-ink-muted">
                      {item.scores.map((score, index) =>
                        score.reason === '' ? null : (
                          <li key={`${score.method}-${index}`}>
                            <span className="font-medium">{score.method}</span>:{' '}
                            {score.reason}
                          </li>
                        ),
                      )}
                    </ul>
                  )}
                  <div className="mt-2 flex gap-2">
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => {
                        setScoreTarget(item)
                        setScoreValue('')
                        setScoreReason('')
                      }}
                    >
                      {t('modelEval.manualScore')}
                    </Button>
                    {item.status === 'failed' && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => void retryItem(item)}
                      >
                        <RotateCcw className="h-3 w-3" />
                        {t('modelEval.retry')}
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      <Dialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title={t('modelEval.newDataset')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setCreateOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              size="sm"
              disabled={busy || name.trim() === ''}
              onClick={() => void createDataset()}
            >
              {t('common.create')}
            </Button>
          </>
        }
      >
        <div className="space-y-2">
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={t('modelEval.name')}
          />
          <Input
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder={t('modelEval.description')}
          />
          <textarea
            value={questionsJson}
            onChange={(event) => setQuestionsJson(event.target.value)}
            className="min-h-40 w-full rounded-lg border border-border bg-surface px-3 py-2 font-mono text-[11px]"
            placeholder={'[{"question":"...","reference_answer":"...","scoring_criteria":"...","expected_keywords":["..."],"regex":""}]'}
          />
          <p className="text-[10px] text-ink-muted">{t('modelEval.jsonHint')}</p>
          {datasetError !== null && (
            <p className="text-xs text-danger">{datasetError}</p>
          )}
        </div>
      </Dialog>

      <Dialog
        open={scoreTarget !== null}
        onClose={() => setScoreTarget(null)}
        title={t('modelEval.manualScore')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setScoreTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button size="sm" onClick={() => void saveScore()}>
              {t('common.save')}
            </Button>
          </>
        }
      >
        <div className="space-y-2">
          <Input
            value={scoreValue}
            onChange={(event) => setScoreValue(event.target.value)}
            placeholder={t('modelEval.scorePlaceholder')}
          />
          <Input
            value={scoreReason}
            onChange={(event) => setScoreReason(event.target.value)}
            placeholder={t('modelEval.reason')}
          />
        </div>
      </Dialog>

      <Dialog
        open={questionTarget !== null}
        onClose={() => setQuestionTarget(null)}
        title={
          questionTarget === 'new'
            ? t('modelEval.addQuestion')
            : t('modelEval.editQuestion')
        }
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setQuestionTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button size="sm" disabled={busy} onClick={() => void saveQuestion()}>
              {t('common.save')}
            </Button>
          </>
        }
      >
        <div className="space-y-2">
          <textarea
            value={questionText}
            onChange={(event) => setQuestionText(event.target.value)}
            placeholder={t('modelEval.question')}
            className="min-h-20 w-full rounded-lg border border-border bg-surface px-3 py-2 text-xs"
          />
          <textarea
            value={referenceAnswer}
            onChange={(event) => setReferenceAnswer(event.target.value)}
            placeholder={t('modelEval.reference')}
            className="min-h-16 w-full rounded-lg border border-border bg-surface px-3 py-2 text-xs"
          />
          <textarea
            value={scoringCriteria}
            onChange={(event) => setScoringCriteria(event.target.value)}
            placeholder={t('modelEval.criteria')}
            className="min-h-16 w-full rounded-lg border border-border bg-surface px-3 py-2 text-xs"
          />
          <Input
            value={expectedKeywords}
            onChange={(event) => setExpectedKeywords(event.target.value)}
            placeholder={t('modelEval.keywordsPlaceholder')}
          />
          <Input
            value={questionRegex}
            onChange={(event) => setQuestionRegex(event.target.value)}
            placeholder={t('modelEval.regexPlaceholder')}
          />
          {questionError !== null && (
            <p className="text-xs text-danger">{questionError}</p>
          )}
        </div>
      </Dialog>

      <Dialog
        open={deleteQuestionTarget !== null}
        onClose={() => setDeleteQuestionTarget(null)}
        title={t('modelEval.deleteQuestion')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setDeleteQuestionTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              size="sm"
              variant="danger"
              disabled={busy}
              onClick={() => void deleteQuestion()}
            >
              {t('common.delete')}
            </Button>
          </>
        }
      >
        <p className="text-sm text-ink-muted">
          {t('modelEval.confirmDelete')} “{deleteQuestionTarget?.question}”
        </p>
      </Dialog>

      <Dialog
        open={deleteDatasetTarget !== null}
        onClose={() => setDeleteDatasetTarget(null)}
        title={t('modelEval.deleteDataset')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setDeleteDatasetTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              size="sm"
              variant="danger"
              disabled={busy}
              onClick={() => void deleteDataset()}
            >
              {t('common.delete')}
            </Button>
          </>
        }
      >
        <p className="text-sm text-ink-muted">
          {t('modelEval.confirmDelete')} “{deleteDatasetTarget?.name}”
        </p>
      </Dialog>

      <Dialog
        open={deleteRunTarget !== null}
        onClose={() => setDeleteRunTarget(null)}
        title={t('modelEval.deleteRun')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setDeleteRunTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              size="sm"
              variant="danger"
              disabled={busy}
              onClick={() => void deleteRun()}
            >
              {t('common.delete')}
            </Button>
          </>
        }
      >
        <p className="text-sm text-ink-muted">
          {t('modelEval.confirmDelete')} “{deleteRunTarget?.name}”
        </p>
      </Dialog>
    </div>
  )
}