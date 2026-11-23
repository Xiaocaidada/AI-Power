import { useQuery } from '@tanstack/react-query'

import { Badge } from '../../components/ui/badge'
import { Spinner } from '../../components/ui/spinner'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { EvalRunAnalysis, EvalRunDetail } from '../../lib/types'

function percent(value: unknown): string {
  return typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : '—'
}

function fixed(value: unknown, digits = 3): string {
  return typeof value === 'number' ? value.toFixed(digits) : '—'
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border px-3 py-2">
      <p className="text-[10px] uppercase tracking-wide text-ink-muted">{label}</p>
      <p className="mt-1 text-sm font-semibold text-ink">{value}</p>
    </div>
  )
}

function InsightList({
  title,
  items,
}: {
  title: string
  items: EvalRunAnalysis['worst_questions']
}) {
  return (
    <div className="rounded-card border border-border bg-surface p-3">
      <p className="text-xs font-medium text-ink">{title}</p>
      {items.length === 0 ? (
        <p className="mt-1 text-[11px] text-ink-muted">—</p>
      ) : (
        <ul className="mt-1 space-y-1">
          {items.map((item) => (
            <li
              key={item.question_id}
              className="flex flex-wrap items-center gap-2 rounded-md bg-surface-muted px-2 py-1 text-[11px]"
            >
              <span className="min-w-0 flex-1 truncate text-ink">
                {item.question_text}
              </span>
              <Badge tone={item.hit_rank === null ? 'danger' : 'success'}>
                {item.hit_rank === null ? 'miss' : `#${item.hit_rank}`}
              </Badge>
              <span className="text-ink-muted">NDCG {fixed(item.ndcg_at_5)}</span>
              {item.error_code !== null && (
                <Badge tone="danger">{item.error_code}</Badge>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function EvaluationRunDetailPanel({ runId }: { runId: string }) {
  const { t } = useI18n()
  const detail = useQuery({
    queryKey: ['eval-run', runId],
    queryFn: () => apiRequest<EvalRunDetail>(`/evaluations/runs/${runId}`),
    enabled: runId !== '',
  })
  const analysis = useQuery({
    queryKey: ['eval-run-analysis', runId],
    queryFn: () => apiRequest<EvalRunAnalysis>(`/evaluations/runs/${runId}/analysis`),
    enabled: runId !== '' && detail.data?.status === 'completed',
  })

  if (runId === '') {
    return (
      <p className="rounded-card border border-dashed border-border px-4 py-10 text-center text-sm text-ink-muted">
        {t('knowledgeEval.detail.empty')}
      </p>
    )
  }
  if (detail.isLoading || detail.data === undefined) {
    return (
      <div className="flex items-center justify-center py-10">
        <Spinner />
      </div>
    )
  }

  const run = detail.data
  const metrics = run.metrics ?? {}
  return (
    <div className="space-y-3">
      <section className="rounded-card border border-border bg-surface p-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={run.status === 'completed' ? 'success' : 'accent'}>
            {run.status}
          </Badge>
          <span className="text-xs text-ink-muted">
            {t('knowledgeEval.detail.progress', {
              done: run.progress_done,
              total: run.progress_total,
            })}
          </span>
          <span className="text-xs text-ink-muted">
            {t('knowledgeEval.detail.mode')}:{' '}
            {String(metrics.retrieval_mode ?? 'builtin')}
          </span>
          {run.error_code !== null && <Badge tone="danger">{run.error_code}</Badge>}
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
          <Metric
            label={t('knowledgeEval.metric.recall1')}
            value={percent(metrics.recall_at_1)}
          />
          <Metric
            label={t('knowledgeEval.metric.recall5')}
            value={percent(metrics.recall_at_5)}
          />
          <Metric
            label={t('knowledgeEval.metric.precision5')}
            value={fixed(metrics.precision_at_5)}
          />
          <Metric
            label={t('knowledgeEval.metric.recallDocs5')}
            value={fixed(metrics.recall_at_5_docs)}
          />
          <Metric
            label={t('knowledgeEval.metric.ndcg5')}
            value={fixed(metrics.ndcg_at_5)}
          />
          <Metric label={t('knowledgeEval.metric.mrr')} value={fixed(metrics.mrr)} />
          <Metric
            label={t('knowledgeEval.metric.precision10')}
            value={fixed(metrics.precision_at_10)}
          />
          <Metric
            label={t('knowledgeEval.metric.ndcg10')}
            value={fixed(metrics.ndcg_at_10)}
          />
          <Metric
            label={t('knowledgeEval.metric.p95')}
            value={`${fixed(metrics.latency_p95_ms, 1)} ms`}
          />
          <Metric
            label={t('knowledgeEval.metric.success')}
            value={percent(metrics.success_rate)}
          />
          <Metric
            label={t('knowledgeEval.metric.cost')}
            value={`$${fixed(metrics.cost, 6)}`}
          />
          <Metric
            label={t('knowledgeEval.metric.items')}
            value={String(run.items.length)}
          />
        </div>
      </section>

      {analysis.data !== undefined && (
        <>
          <section className="rounded-card border border-border bg-surface p-4">
            <h3 className="text-sm font-medium text-ink">
              {t('knowledgeEval.detail.nodeTiming')}
            </h3>
            {analysis.data.node_timing.length === 0 ? (
              <p className="mt-1 text-[11px] text-ink-muted">
                {t('knowledgeEval.detail.builtinNoTrace')}
              </p>
            ) : (
              <div className="mt-2 overflow-x-auto">
                <table className="w-full min-w-[520px] text-left text-xs">
                  <thead className="text-ink-muted">
                    <tr>
                      <th className="py-1 pr-3 font-medium">
                        {t('knowledgeEval.detail.node')}
                      </th>
                      <th className="py-1 pr-3 font-medium">
                        {t('knowledgeEval.detail.runs')}
                      </th>
                      <th className="py-1 pr-3 font-medium">
                        {t('knowledgeEval.detail.failures')}
                      </th>
                      <th className="py-1 pr-3 font-medium">
                        {t('knowledgeEval.detail.avgMs')}
                      </th>
                      <th className="py-1 font-medium">
                        {t('knowledgeEval.detail.avgCount')}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {analysis.data.node_timing.map((row) => (
                      <tr key={row.node_type} className="border-t border-border">
                        <td className="py-1 pr-3 font-mono text-ink">
                          {row.node_type}
                        </td>
                        <td className="py-1 pr-3 text-ink-muted">{row.runs}</td>
                        <td
                          className={
                            row.failures > 0
                              ? 'py-1 pr-3 text-danger'
                              : 'py-1 pr-3 text-ink-muted'
                          }
                        >
                          {row.failures}
                        </td>
                        <td className="py-1 pr-3 text-ink-muted">{row.avg_ms}</td>
                        <td className="py-1 text-ink-muted">{row.avg_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <div className="grid gap-3 lg:grid-cols-2">
            <InsightList
              title={t('knowledgeEval.detail.worst')}
              items={analysis.data.worst_questions}
            />
            <InsightList
              title={t('knowledgeEval.detail.missed')}
              items={analysis.data.missed_questions}
            />
          </div>
        </>
      )}

      <section className="overflow-x-auto rounded-card border border-border bg-surface">
        <table className="w-full min-w-[760px] text-left text-xs">
          <thead className="text-ink-muted">
            <tr>
              <th className="px-3 py-2 font-medium">
                {t('knowledgeEval.detail.question')}
              </th>
              <th className="px-3 py-2 font-medium">
                {t('knowledgeEval.detail.rank')}
              </th>
              <th className="px-3 py-2 font-medium">P@5</th>
              <th className="px-3 py-2 font-medium">R@5</th>
              <th className="px-3 py-2 font-medium">NDCG@5</th>
              <th className="px-3 py-2 font-medium">
                {t('knowledgeEval.detail.latency')}
              </th>
              <th className="px-3 py-2 font-medium">
                {t('knowledgeEval.detail.error')}
              </th>
            </tr>
          </thead>
          <tbody>
            {run.items.map((item) => (
              <tr key={item.id} className="border-t border-border align-top">
                <td className="max-w-[280px] px-3 py-2 text-ink">
                  {item.question_text}
                </td>
                <td className="px-3 py-2 text-ink-muted">
                  {item.hit_rank === null ? '—' : `#${item.hit_rank}`}
                </td>
                <td className="px-3 py-2 text-ink-muted">
                  {fixed(item.precision_at_5)}
                </td>
                <td className="px-3 py-2 text-ink-muted">{fixed(item.recall_at_5)}</td>
                <td className="px-3 py-2 text-ink-muted">{fixed(item.ndcg_at_5)}</td>
                <td className="px-3 py-2 text-ink-muted">
                  {item.latency_ms === null
                    ? '—'
                    : `${item.latency_ms.toFixed(1)} ms`}
                </td>
                <td className="px-3 py-2">
                  {item.error_code === null ? (
                    <span className="text-ink-muted">—</span>
                  ) : (
                    <Badge tone="danger">{item.error_code}</Badge>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}