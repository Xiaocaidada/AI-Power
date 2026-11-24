import { useQuery } from '@tanstack/react-query'
import { Play } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { ReviewInbox } from '../../components/ReviewInbox'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  CustomAgent,
  RunAccepted,
  WorkflowDefinition,
  WorkflowRun,
} from '../../lib/types'

interface StudioRunPanelProps {
  agent: CustomAgent
  workflowId: string | null
  definition?: WorkflowDefinition
  onRunId: (runId: string) => void
}

export function StudioRunPanel({
  agent,
  workflowId,
  definition,
  onRunId,
}: StudioRunPanelProps) {
  const { t } = useI18n()
  const [input, setInput] = useState('')
  const [startNodeId, setStartNodeId] = useState('')
  const [nodeOutputs, setNodeOutputs] = useState('{}')
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
    if (
      workflowId === null ||
      (input.trim() === '' && startNodeId === '')
    ) {
      return
    }
    setLoading(true)
    setError(null)
    let outputs: Record<string, string> = {}
    try {
      outputs =
        nodeOutputs.trim() === ''
          ? {}
          : (JSON.parse(nodeOutputs) as Record<string, string>)
    } catch {
      setError(t('studio.debugInvalidJson'))
      setLoading(false)
      return
    }
    try {
      const accepted = await apiRequest<RunAccepted>(
        `/workflows/${workflowId}/runs`,
        {
          method: 'POST',
          body: {
            input: input.trim(),
            ...(startNodeId !== '' ? { start_node_id: startNodeId } : {}),
            ...(startNodeId !== '' ? { node_outputs: outputs } : {}),
          },
        },
      )
      setRunId(accepted.run_id)
      onRunId(accepted.run_id)
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
              <label className="mt-3 block text-xs text-ink-muted">
                {t('studio.runStartNode')}
                <select
                  value={startNodeId}
                  onChange={(event) => setStartNodeId(event.target.value)}
                  className="mt-1 h-9 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink"
                >
                  <option value="">{t('studio.runFromStart')}</option>
                  {(definition?.nodes ?? []).map((node) => (
                    <option key={node.id} value={node.id}>
                      {node.id} · {node.type}
                    </option>
                  ))}
                </select>
              </label>
              {startNodeId !== '' && (
                <label className="mt-2 block text-xs text-ink-muted">
                  {t('studio.runNodeOutputs')}
                  <textarea
                    value={nodeOutputs}
                    onChange={(event) => setNodeOutputs(event.target.value)}
                    className="mt-1 min-h-20 w-full rounded-lg border border-border bg-surface px-2 py-1.5 font-mono text-[11px] text-ink"
                  />
                  <span className="mt-0.5 block text-[10px] text-ink-muted">
                    {t('studio.runNodeOutputsHint')}
                  </span>
                </label>
              )}
              <div className="mt-3 flex items-center gap-3">
                <Button
                  size="sm"
                  disabled={
                    loading || (input.trim() === '' && startNodeId === '')
                  }
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

        <section className="space-y-4">
          <ReviewInbox runId={runId === '' ? undefined : runId} />
          <div className="rounded-card border border-border bg-surface p-4">
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
          </div>
        </section>
      </div>
    </div>
  )
}