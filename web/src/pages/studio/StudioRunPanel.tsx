import { useQuery } from '@tanstack/react-query'
import { Play } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { CustomAgent, RunAccepted, WorkflowRun } from '../../lib/types'

interface StudioRunPanelProps {
  agent: CustomAgent
  workflowId: string | null
}

export function StudioRunPanel({ agent, workflowId }: StudioRunPanelProps) {
  const { t } = useI18n()
  const [input, setInput] = useState('')
  const [runId, setRunId] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = useQuery({
    queryKey: ['studio-run', runId],
    queryFn: () => apiRequest<WorkflowRun>(`/workflows/runs/${runId}`),
    enabled: runId !== '',
    refetchInterval: (query) =>
      query.state.data?.status === 'running' || query.state.data?.status === 'queued'
        ? 1200
        : false,
  })

  const start = async () => {
    if (workflowId === null || input.trim() === '') return
    setLoading(true)
    setError(null)
    try {
      const accepted = await apiRequest<RunAccepted>(
        `/workflows/${workflowId}/runs`,
        { method: 'POST', body: { input: input.trim() } },
      )
      setRunId(accepted.run_id)
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto grid w-full max-w-6xl gap-4 px-6 py-6 lg:grid-cols-[1fr_1.2fr]">
        <section className="rounded-card border border-border bg-surface p-4">
          <h2 className="text-sm font-medium text-ink">{t('studio.runTitle')}</h2>
          <p className="mt-1 text-xs text-ink-muted">{t('studio.runLead')}</p>
          {workflowId === null ? (
            <div className="mt-3 space-y-2 text-xs text-ink-muted">
              <p>{t('studio.runNoWorkflow')}</p>
              <Link to={`/chat?agent=${agent.id}`} className="text-accent">
                {t('studio.openChat')}
              </Link>
            </div>
          ) : (
            <>
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder={t('studio.runInput')}
                className="mt-3 min-h-36 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink"
              />
              <div className="mt-3 flex items-center gap-3">
                <Button
                  size="sm"
                  disabled={loading || input.trim() === ''}
                  onClick={() => void start()}
                >
                  <Play className="h-3.5 w-3.5" />
                  {t('studio.runStart')}
                </Button>
                {error !== null && <p className="text-xs text-danger">{error}</p>}
              </div>
              <p className="mt-3 text-[11px] text-ink-muted">
                {t('studio.openChatHint')}{' '}
                <Link to={`/chat?agent=${agent.id}`} className="text-accent">
                  {t('studio.openChat')}
                </Link>
              </p>
            </>
          )}
        </section>

        <section className="rounded-card border border-border bg-surface p-4">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-ink">{t('studio.runTimeline')}</p>
            {run.data !== undefined && (
              <Badge
                tone={
                  run.data.status === 'completed'
                    ? 'success'
                    : run.data.status === 'failed'
                      ? 'danger'
                      : 'neutral'
                }
              >
                {run.data.status}
              </Badge>
            )}
          </div>
          {run.data === undefined ? (
            <p className="mt-2 text-xs text-ink-muted">{t('studio.runEmpty')}</p>
          ) : (
            <div className="mt-3 space-y-2">
              {run.data.nodes.map((node) => (
                <div
                  key={node.id}
                  className="rounded-lg border border-border bg-surface-muted px-3 py-2"
                >
                  <div className="flex items-center gap-2">
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
                    <span className="text-xs font-medium text-ink">{node.node_id}</span>
                    <span className="text-[10px] text-ink-muted">{node.node_type}</span>
                    <span className="ml-auto text-[10px] text-ink-muted">
                      {node.duration_ms?.toFixed(0) ?? '—'} ms
                    </span>
                  </div>
                  <p className="mt-1 max-h-20 overflow-y-auto whitespace-pre-wrap text-[11px] text-ink-muted">
                    {node.output_summary || node.error_code || '—'}
                  </p>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}