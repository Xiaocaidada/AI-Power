import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Check,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react'
import { useState } from 'react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { EmptyState } from '../../components/ui/empty-state'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  AgentMemory,
  MemoryEvalCase,
  MemoryEvalRun,
  MemoryOptimization,
  MemoryQuality,
  MemorySemanticResult,
} from '../../lib/types'

const STATUS_TONE: Record<string, 'neutral' | 'success' | 'warning' | 'danger'> = {
  pending: 'warning',
  applied: 'success',
  dismissed: 'neutral',
  rolled_back: 'neutral',
}

const ACTIONABLE_KINDS = new Set([
  'merge_duplicates',
  'resolve_conflict',
  'expire_memory',
  'archive_memory',
  'recategorize',
])

export function MemoryQualityPanel() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [busy, setBusy] = useState('')
  const [semanticMessage, setSemanticMessage] = useState<string | null>(null)
  const [caseName, setCaseName] = useState('')
  const [caseQuery, setCaseQuery] = useState('')
  const [caseNotes, setCaseNotes] = useState('')
  const [expectedIds, setExpectedIds] = useState<string[]>([])
  const [topK, setTopK] = useState(5)
  const [latestRun, setLatestRun] = useState<MemoryEvalRun | null>(null)

  const quality = useQuery({
    queryKey: ['memory-quality'],
    queryFn: () => apiRequest<MemoryQuality>('/memories/quality'),
  })
  const memories = useQuery({
    queryKey: ['memories', 'quality-options'],
    queryFn: () => apiRequest<AgentMemory[]>('/memories?status=active&limit=200'),
    staleTime: 30_000,
  })
  const cases = useQuery({
    queryKey: ['memory-eval-cases'],
    queryFn: () => apiRequest<MemoryEvalCase[]>('/memories/eval/cases'),
  })
  const runs = useQuery({
    queryKey: ['memory-eval-runs'],
    queryFn: () => apiRequest<MemoryEvalRun[]>('/memories/eval/runs?limit=5'),
  })

  const refreshQuality = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['memory-quality'] }),
      queryClient.invalidateQueries({ queryKey: ['memories'] }),
      queryClient.invalidateQueries({ queryKey: ['memory-stats'] }),
      queryClient.invalidateQueries({ queryKey: ['memory-graph'] }),
    ])
  }

  const analyze = async () => {
    setBusy('analyze')
    try {
      await apiRequest<MemoryQuality>('/memories/quality/analyze', {
        method: 'POST',
      })
      await refreshQuality()
    } finally {
      setBusy('')
    }
  }

  const analyzeSemantics = async () => {
    setBusy('semantic')
    setSemanticMessage(null)
    try {
      const result = await apiRequest<MemorySemanticResult>(
        '/memories/quality/semantic',
        { method: 'POST', body: { limit: 12 } },
      )
      setSemanticMessage(
        t('memory.quality.semanticResult', {
          checked: result.pairs_checked,
          contradictions: result.contradictions,
          created: result.created,
        }),
      )
      await refreshQuality()
    } catch (caught) {
      setSemanticMessage(t(errorTextKey(caught)))
    } finally {
      setBusy('')
    }
  }

  const act = async (
    suggestion: MemoryOptimization,
    action: 'apply' | 'rollback' | 'dismiss',
  ) => {
    setBusy(suggestion.id)
    try {
      await apiRequest(`/memories/optimizations/${suggestion.id}/${action}`, {
        method: 'POST',
      })
      await refreshQuality()
    } finally {
      setBusy('')
    }
  }

  const addCase = async () => {
    if (caseQuery.trim() === '') return
    setBusy('case')
    try {
      await apiRequest('/memories/eval/cases', {
        method: 'POST',
        body: {
          name: caseName.trim(),
          query: caseQuery.trim(),
          expected_memory_ids: expectedIds,
          notes: caseNotes.trim(),
        },
      })
      setCaseName('')
      setCaseQuery('')
      setCaseNotes('')
      setExpectedIds([])
      await queryClient.invalidateQueries({ queryKey: ['memory-eval-cases'] })
    } finally {
      setBusy('')
    }
  }

  const deleteCase = async (caseId: string) => {
    await apiRequest(`/memories/eval/cases/${caseId}`, { method: 'DELETE' })
    await queryClient.invalidateQueries({ queryKey: ['memory-eval-cases'] })
  }

  const runEval = async () => {
    setBusy('eval')
    try {
      const run = await apiRequest<MemoryEvalRun>('/memories/eval/run', {
        method: 'POST',
        body: { top_k: topK },
      })
      setLatestRun(run)
      await queryClient.invalidateQueries({ queryKey: ['memory-eval-runs'] })
    } finally {
      setBusy('')
    }
  }

  const analysis = quality.data?.analysis
  const suggestions = quality.data?.suggestions ?? []
  const activeRun = latestRun ?? (runs.data ?? [])[0] ?? null
  const memoryOptions = memories.data ?? []

  return (
    <div className="space-y-5">
      <section className="rounded-card border border-border bg-surface p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-sm font-medium text-ink">
              {t('memory.quality.analysis')}
            </h2>
            <p className="mt-0.5 text-[11px] text-ink-muted">
              {t('memory.quality.analysisHint')}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              disabled={busy === 'semantic'}
              onClick={() => void analyzeSemantics()}
            >
              <Sparkles className="h-3.5 w-3.5" />
              {busy === 'semantic'
                ? t('memory.quality.semanticRunning')
                : t('memory.quality.semanticAnalyze')}
            </Button>
            <Button
              size="sm"
              disabled={busy === 'analyze'}
              onClick={() => void analyze()}
            >
              <RefreshCw className="h-3.5 w-3.5" />
              {t('memory.quality.analyze')}
            </Button>
          </div>
        </div>
        {semanticMessage !== null && (
          <p className="mt-2 text-xs text-ink-muted">{semanticMessage}</p>
        )}
        {analysis === undefined ? (
          <div className="flex justify-center py-6">
            <Spinner />
          </div>
        ) : (
          <div className="mt-3 grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
            {(
              [
                ['total', analysis.total],
                ['duplicates', analysis.duplicates],
                ['conflicts', analysis.conflicts],
                ['expired', analysis.expired],
                ['unused', analysis.unused],
                ['incomplete', analysis.incomplete],
                ['orphans', analysis.orphans],
                ['relationAnomalies', analysis.relation_anomalies ?? 0],
                ['projectGaps', analysis.project_gaps ?? 0],
              ] as const
            ).map(([key, value]) => (
              <div key={key} className="rounded-lg bg-surface-muted px-3 py-2">
                <p className="text-[10px] uppercase tracking-wide text-ink-muted">
                  {t(`memory.quality.${key}`)}
                </p>
                <p className="mt-0.5 text-lg font-semibold text-ink">{value}</p>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="rounded-card border border-border bg-surface">
        <div className="border-b border-border px-4 py-3">
          <h2 className="text-sm font-medium text-ink">
            {t('memory.quality.suggestions')}
          </h2>
          <p className="mt-0.5 text-[11px] text-ink-muted">
            {t('memory.quality.suggestionsHint')}
          </p>
        </div>
        {suggestions.length === 0 ? (
          <div className="px-4 py-8">
            <EmptyState
              title={t('memory.quality.noSuggestions')}
              description={t('memory.quality.noSuggestionsLead')}
            />
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {suggestions.map((suggestion) => (
              <li key={suggestion.id} className="px-4 py-3">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge tone="accent">
                    {t(`memory.quality.kind.${suggestion.kind}`)}
                  </Badge>
                  <Badge tone={STATUS_TONE[suggestion.status] ?? 'neutral'}>
                    {t(`memory.quality.status.${suggestion.status}`)}
                  </Badge>
                  <span className="text-sm font-medium text-ink">
                    {suggestion.title}
                  </span>
                  <span className="ml-auto text-[10px] text-ink-muted">
                    {suggestion.memory_ids.length}{' '}
                    {t('memory.quality.memoryCount')}
                  </span>
                </div>
                <p className="mt-1 text-xs text-ink-muted">{suggestion.reason}</p>
                <p className="mt-0.5 text-[11px] text-ink-muted">
                  {t('memory.quality.expected')}: {suggestion.expected_effect}
                </p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {suggestion.status === 'pending' && (
                    <>
                      {ACTIONABLE_KINDS.has(suggestion.kind) && (
                        <Button
                          size="sm"
                          disabled={busy === suggestion.id}
                          onClick={() => void act(suggestion, 'apply')}
                        >
                          <Check className="h-3 w-3" />
                          {t('memory.quality.apply')}
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={busy === suggestion.id}
                        onClick={() => void act(suggestion, 'dismiss')}
                      >
                        <X className="h-3 w-3" />
                        {t('memory.quality.dismiss')}
                      </Button>
                    </>
                  )}
                  {suggestion.status === 'applied' && (
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={busy === suggestion.id}
                      onClick={() => void act(suggestion, 'rollback')}
                    >
                      <RotateCcw className="h-3 w-3" />
                      {t('memory.quality.rollback')}
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="rounded-card border border-border bg-surface">
        <div className="border-b border-border px-4 py-3">
          <h2 className="text-sm font-medium text-ink">{t('memory.quality.evalTitle')}</h2>
          <p className="mt-0.5 text-[11px] text-ink-muted">
            {t('memory.quality.evalHint')}
          </p>
        </div>
        <div className="grid gap-3 px-4 py-3 lg:grid-cols-2">
          <div className="space-y-2">
            <input
              value={caseName}
              onChange={(event) => setCaseName(event.target.value)}
              placeholder={t('memory.quality.caseName')}
              className="h-9 w-full rounded-lg border border-border bg-surface px-3 text-sm text-ink"
            />
            <input
              value={caseQuery}
              onChange={(event) => setCaseQuery(event.target.value)}
              placeholder={t('memory.quality.caseQuery')}
              className="h-9 w-full rounded-lg border border-border bg-surface px-3 text-sm text-ink"
            />
            <select
              multiple
              value={expectedIds}
              onChange={(event) =>
                setExpectedIds(
                  Array.from(event.target.selectedOptions).map(
                    (option) => option.value,
                  ),
                )
              }
              className="h-28 w-full rounded-lg border border-border bg-surface px-2 py-1 text-sm text-ink"
            >
              {memoryOptions.map((memory) => (
                <option key={memory.id} value={memory.id}>
                  {memory.title || memory.content.slice(0, 40)}
                </option>
              ))}
            </select>
            <input
              value={caseNotes}
              onChange={(event) => setCaseNotes(event.target.value)}
              placeholder={t('memory.quality.caseNotes')}
              className="h-9 w-full rounded-lg border border-border bg-surface px-3 text-sm text-ink"
            />
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                disabled={busy === 'case' || caseQuery.trim() === ''}
                onClick={() => void addCase()}
              >
                <Plus className="h-3.5 w-3.5" />
                {t('memory.quality.addCase')}
              </Button>
              <label className="ml-auto flex items-center gap-1.5 text-xs text-ink-muted">
                {t('memory.quality.topK')}
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={topK}
                  onChange={(event) => setTopK(Number(event.target.value) || 5)}
                  className="h-8 w-16 rounded-lg border border-border bg-surface px-2 text-ink"
                />
              </label>
              <Button
                size="sm"
                variant="secondary"
                disabled={busy === 'eval' || (cases.data ?? []).length === 0}
                onClick={() => void runEval()}
              >
                <Play className="h-3.5 w-3.5" />
                {t('memory.quality.runEval')}
              </Button>
            </div>
          </div>

          <div className="space-y-2">
            {(cases.data ?? []).length === 0 && (
              <p className="text-xs text-ink-muted">{t('memory.quality.noCases')}</p>
            )}
            <ul className="space-y-1">
              {(cases.data ?? []).map((item) => (
                <li
                  key={item.id}
                  className="flex flex-wrap items-center gap-2 rounded-lg bg-surface-muted px-2 py-1.5 text-xs"
                >
                  <span className="min-w-0 flex-1 truncate text-ink">
                    {item.name || item.query}
                  </span>
                  <span className="text-ink-muted">
                    {item.expected_memory_ids.length}{' '}
                    {t('memory.quality.expectedCount')}
                  </span>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={t('common.delete')}
                    onClick={() => void deleteCase(item.id)}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {activeRun !== null && (
          <div className="border-t border-border px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-xs font-medium text-ink">
                {t('memory.quality.latestRun')}
              </p>
              <Badge tone="neutral">
                {t('memory.quality.casesCount', { count: activeRun.cases_count })}
              </Badge>
              <Badge tone="accent">
                Precision {activeRun.metrics.precision?.toFixed(3) ?? '—'}
              </Badge>
              <Badge tone="success">
                Recall {activeRun.metrics.recall?.toFixed(3) ?? '—'}
              </Badge>
              <Badge tone="warning">
                MRR {activeRun.metrics.mrr?.toFixed(3) ?? '—'}
              </Badge>
              <span className="text-[11px] text-ink-muted">
                {activeRun.duration_ms.toFixed(0)} ms
              </span>
            </div>
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-left text-[11px]">
                <thead className="text-ink-muted">
                  <tr>
                    <th className="py-1 pr-3 font-medium">#</th>
                    <th className="py-1 pr-3 font-medium">Query</th>
                    <th className="py-1 pr-3 font-medium">
                      {t('memory.quality.expectedCount')}
                    </th>
                    <th className="py-1 pr-3 font-medium">Recall</th>
                    <th className="py-1 pr-3 font-medium">MRR</th>
                  </tr>
                </thead>
                <tbody>
                  {activeRun.results.map((result, index) => (
                    <tr key={result.case_id} className="border-t border-border">
                      <td className="py-1 pr-3 text-ink-muted">{index + 1}</td>
                      <td className="py-1 pr-3 text-ink">{result.query}</td>
                      <td className="py-1 pr-3 text-ink-muted">
                        {result.hits.length}/{result.expected_ids.length}
                      </td>
                      <td className="py-1 pr-3 text-ink-muted">
                        {result.recall.toFixed(2)}
                      </td>
                      <td className="py-1 pr-3 text-ink-muted">
                        {result.mrr.toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}