import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, RotateCcw, Sparkles, X } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  EvalRun,
  KnowledgeOptimization,
  KnowledgeOptimizationDetail,
  ModelEntry,
  PersonalModel,
} from '../../lib/types'
import { DiffView } from '../studio/StudioBuilderPanel'

interface OptimizationPanelProps {
  kbId: string
  runs: EvalRun[]
  selectedRunId: string
}

type ConfirmAction = 'apply' | 'rollback'

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

function statusTone(status: string): 'accent' | 'success' | 'neutral' | 'warning' {
  if (status === 'applied') return 'success'
  if (status === 'reverted') return 'warning'
  if (status === 'proposed') return 'accent'
  return 'neutral'
}

export function OptimizationPanel({
  kbId,
  runs,
  selectedRunId,
}: OptimizationPanelProps) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [runId, setRunId] = useState(selectedRunId)
  const [choice, setChoice] = useState('')
  const [generating, setGenerating] = useState(false)
  const [busyId, setBusyId] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<{ action: ConfirmAction; id: string } | null>(
    null,
  )
  const [expanded, setExpanded] = useState('')

  const completed = runs.filter((run) => run.status === 'completed')
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
  const optimizations = useQuery({
    queryKey: ['knowledge-optimizations', kbId],
    queryFn: () =>
      apiRequest<KnowledgeOptimization[]>(`/knowledge-bases/${kbId}/optimizations`),
    enabled: kbId !== '',
  })
  const options = modelOptions(
    platformModels.data ?? [],
    personalModels.data ?? [],
  )

  useEffect(() => {
    if (runId === '' && selectedRunId !== '') setRunId(selectedRunId)
  }, [runId, selectedRunId])

  useEffect(() => {
    if (choice === '' && options.length > 0) setChoice(options[0].value)
  }, [choice, options])

  const refresh = async () => {
    await queryClient.invalidateQueries({
      queryKey: ['knowledge-optimizations', kbId],
    })
    await queryClient.invalidateQueries({
      queryKey: ['knowledge-retrieval-binding', kbId],
    })
    await queryClient.invalidateQueries({ queryKey: ['knowledge-retrieval-workflows'] })
  }

  const generate = async () => {
    if (runId === '' || choice === '') return
    setGenerating(true)
    setError(null)
    try {
      const parsed = parseChoice(choice)
      const created = await apiRequest<KnowledgeOptimizationDetail>(
        `/knowledge-bases/${kbId}/optimizations`,
        {
          method: 'POST',
          body: {
            eval_run_id: runId,
            provider_id: parsed.providerId,
            model: parsed.model,
          },
        },
      )
      setExpanded(created.id)
      await refresh()
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setGenerating(false)
    }
  }

  const act = async (id: string, action: 'apply' | 'rollback' | 'dismiss') => {
    setBusyId(id)
    setError(null)
    try {
      await apiRequest(`/knowledge-bases/${kbId}/optimizations/${id}/${action}`, {
        method: 'POST',
      })
      await refresh()
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusyId('')
      setConfirm(null)
    }
  }

  return (
    <section className="rounded-card border border-border bg-surface p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Sparkles className="h-4 w-4 text-accent" />
        <h2 className="text-sm font-medium text-ink">
          {t('knowledgeEval.optimize.title')}
        </h2>
      </div>
      <p className="mt-1 text-xs text-ink-muted">{t('knowledgeEval.optimize.lead')}</p>

      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="text-[11px] text-ink-muted">
          {t('knowledgeEval.optimize.run')}
          <select
            value={runId}
            onChange={(event) => setRunId(event.target.value)}
            className="mt-1 block h-8 max-w-72 rounded-lg border border-border bg-surface px-2 text-xs text-ink"
          >
            <option value="">{t('knowledgeEval.optimize.selectRun')}</option>
            {completed.map((run) => (
              <option key={run.id} value={run.id}>
                {run.id.slice(0, 8)} ·{' '}
                {String(run.metrics?.retrieval_mode ?? 'builtin')} ·{' '}
                {run.retrieval_workflow_version_id === null
                  ? t('knowledgeEval.optimize.builtin')
                  : t('knowledgeEval.optimize.workflow')}
              </option>
            ))}
          </select>
        </label>
        <label className="text-[11px] text-ink-muted">
          {t('knowledgeEval.optimize.model')}
          <select
            value={choice}
            onChange={(event) => setChoice(event.target.value)}
            className="mt-1 block h-8 max-w-64 rounded-lg border border-border bg-surface px-2 text-xs text-ink"
          >
            {options.length === 0 && (
              <option value="">{t('knowledgeEval.optimize.noModel')}</option>
            )}
            {options.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <Button
          size="sm"
          disabled={generating || runId === '' || choice === ''}
          onClick={() => void generate()}
        >
          {generating ? (
            <Spinner className="h-3.5 w-3.5" />
          ) : (
            <Sparkles className="h-3.5 w-3.5" />
          )}
          {t('knowledgeEval.optimize.generate')}
        </Button>
      </div>
      {error !== null && <p className="mt-2 text-xs text-danger">{error}</p>}

      <div className="mt-3 space-y-2">
        {optimizations.isLoading && <Spinner />}
        {optimizations.data?.length === 0 && (
          <p className="text-xs text-ink-muted">{t('knowledgeEval.optimize.empty')}</p>
        )}
        {(optimizations.data ?? []).map((row) => (
          <article key={row.id} className="rounded-lg border border-border p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={statusTone(row.status)}>{row.status}</Badge>
              <p className="min-w-0 flex-1 truncate text-xs font-medium text-ink">
                {row.summary}
              </p>
              <span className="text-[10px] text-ink-muted">
                {row.eval_run_id === null ? '—' : row.eval_run_id.slice(0, 8)}
              </span>
              {row.applied_version_id !== null && (
                <Badge tone="neutral">v · {row.applied_version_id.slice(0, 8)}</Badge>
              )}
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  setExpanded((current) => (current === row.id ? '' : row.id))
                }
              >
                {expanded === row.id
                  ? t('knowledgeEval.optimize.collapse')
                  : t('knowledgeEval.optimize.expand')}
              </Button>
            </div>
            {expanded === row.id && (
              <OptimizationBody
                kbId={kbId}
                optimizationId={row.id}
                busy={busyId === row.id}
                onConfirm={setConfirm}
                onDismiss={(id) => void act(id, 'dismiss')}
              />
            )}
          </article>
        ))}
      </div>

      <Dialog
        open={confirm !== null}
        title={
          confirm?.action === 'rollback'
            ? t('knowledgeEval.optimize.rollbackTitle')
            : t('knowledgeEval.optimize.applyTitle')
        }
        onClose={() => setConfirm(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirm(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              disabled={busyId !== ''}
              onClick={() => {
                if (confirm !== null) void act(confirm.id, confirm.action)
              }}
            >
              {t('common.confirm')}
            </Button>
          </>
        }
      >
        {confirm?.action === 'rollback'
          ? t('knowledgeEval.optimize.rollbackHint')
          : t('knowledgeEval.optimize.applyHint')}
      </Dialog>
    </section>
  )
}

function OptimizationBody({
  kbId,
  optimizationId,
  busy,
  onConfirm,
  onDismiss,
}: {
  kbId: string
  optimizationId: string
  busy: boolean
  onConfirm: (value: { action: ConfirmAction; id: string }) => void
  onDismiss: (id: string) => void
}) {
  const { t } = useI18n()
  const detail = useQuery({
    queryKey: ['knowledge-optimization', kbId, optimizationId],
    queryFn: () =>
      apiRequest<KnowledgeOptimizationDetail>(
        `/knowledge-bases/${kbId}/optimizations/${optimizationId}`,
      ),
  })
  if (detail.isLoading || detail.data === undefined) {
    return <Spinner className="mt-2" />
  }
  const row = detail.data
  return (
    <div className="mt-2 space-y-2">
      {row.rationale !== '' && (
        <p className="whitespace-pre-wrap text-[11px] text-ink-muted">{row.rationale}</p>
      )}
      {row.suggestions.length > 0 && (
        <ul className="space-y-1">
          {row.suggestions.map((item, index) => (
            <li key={`${index}-${item.title}`} className="rounded-md bg-surface-muted px-2 py-1">
              <p className="text-[11px] font-medium text-ink">{item.title}</p>
              {item.detail !== '' && (
                <p className="text-[10px] text-ink-muted">{item.detail}</p>
              )}
            </li>
          ))}
        </ul>
      )}
      {row.diff !== null && (
        <div className="rounded-md border border-border bg-canvas p-2">
          <DiffView diff={row.diff} />
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {row.status === 'proposed' && (
          <>
            <Button
              size="sm"
              disabled={busy || row.proposed_definition === null}
              onClick={() => onConfirm({ action: 'apply', id: row.id })}
            >
              <Check className="h-3.5 w-3.5" />
              {t('knowledgeEval.optimize.apply')}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={busy}
              onClick={() => onDismiss(row.id)}
            >
              <X className="h-3.5 w-3.5" />
              {t('knowledgeEval.optimize.dismiss')}
            </Button>
          </>
        )}
        {row.status === 'applied' && (
          <Button
            size="sm"
            variant="secondary"
            disabled={busy}
            onClick={() => onConfirm({ action: 'rollback', id: row.id })}
          >
            <RotateCcw className="h-3.5 w-3.5" />
            {t('knowledgeEval.optimize.rollback')}
          </Button>
        )}
        {row.status === 'proposed' && row.proposed_definition === null && (
          <span className="self-center text-[10px] text-ink-muted">
            {t('knowledgeEval.optimize.suggestionsOnly')}
          </span>
        )}
      </div>
    </div>
  )
}