import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ChevronDown,
  ChevronUp,
  ListChecks,
  Pause,
  Play,
  Square,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { Textarea } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorMessage } from '../../lib/errors'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { ChatTask } from '../../lib/types'

interface ChatAgentTaskProps {
  conversationId: string
  providerId: string
  model: string
  agentId: string | null
  open: boolean
  onClose: () => void
}

function activeTask(tasks: ChatTask[]): ChatTask | null {
  const latest = tasks[0]
  if (latest === undefined) return null
  return latest.status === 'queued' ||
    latest.status === 'running' ||
    latest.status === 'waiting_approval' ||
    latest.status === 'paused' ||
    latest.status === 'failed'
    ? latest
    : null
}

export function ChatAgentTask({
  conversationId,
  providerId,
  model,
  agentId,
  open,
  onClose,
}: ChatAgentTaskProps) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [goal, setGoal] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const tasks = useQuery({
    queryKey: ['conversation-agent-tasks', conversationId],
    queryFn: () =>
      apiRequest<ChatTask[]>(`/agent-tasks?conversation_id=${conversationId}`),
    refetchInterval: 5000,
  })
  const task = activeTask(tasks.data ?? [])
  const latestStatus = tasks.data?.[0]?.status

  useEffect(() => {
    if (latestStatus !== 'completed') return
    void queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] })
  }, [conversationId, latestStatus, queryClient])

  const create = async (): Promise<void> => {
    if (goal.trim() === '') return
    setBusy(true)
    setError(null)
    try {
      await apiRequest<ChatTask>('/agent-tasks', {
        method: 'POST',
        body: {
          goal: goal.trim(),
          conversation_id: conversationId,
          provider_id: providerId,
          model,
          agent_id: agentId,
        },
      })
      setGoal('')
      onClose()
      await queryClient.invalidateQueries({
        queryKey: ['conversation-agent-tasks', conversationId],
      })
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const action = async (kind: 'confirm' | 'pause' | 'resume' | 'cancel'): Promise<void> => {
    if (task === null) return
    setBusy(true)
    setError(null)
    try {
      await apiRequest<ChatTask>(`/agent-tasks/${task.id}/${kind}`, { method: 'POST' })
      await queryClient.invalidateQueries({
        queryKey: ['conversation-agent-tasks', conversationId],
      })
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {task !== null && (
        <div className="mb-2 rounded-2xl border border-border bg-surface p-3 text-sm shadow-subtle">
          <div className="flex flex-wrap items-center gap-2">
            <ListChecks className="h-4 w-4 text-accent" />
            <span className="font-medium text-ink">{task.title}</span>
            <Badge tone={task.status === 'failed' ? 'danger' : 'warning'}>
              {t(`tasks.status.${task.status}` as never)}
            </Badge>
            <span className="ml-auto flex flex-wrap gap-1">
              {task.status === 'waiting_approval' && !task.plan.confirmed && (
                <Button size="sm" disabled={busy} onClick={() => void action('confirm')}>
                  {t('tasks.confirmPlan')}
                </Button>
              )}
              {task.status === 'running' && (
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={busy}
                  onClick={() => void action('pause')}
                >
                  <Pause className="h-3.5 w-3.5" />
                  {t('tasks.pause')}
                </Button>
              )}
              {task.status === 'paused' && (
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={busy}
                  onClick={() => void action('resume')}
                >
                  <Play className="h-3.5 w-3.5" />
                  {t('tasks.resume')}
                </Button>
              )}
              {task.status !== 'cancelled' && (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() => void action('cancel')}
                >
                  <Square className="h-3.5 w-3.5" />
                  {t('tasks.cancel')}
                </Button>
              )}
              <Link
                to={`/tasks?task=${task.id}`}
                className="rounded-md px-2 py-1 text-xs text-accent hover:underline"
              >
                {t('chat.agentTaskDetail')}
              </Link>
            </span>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {(task.plan.steps ?? []).map((step) => (
              <span
                key={step.index}
                className="rounded-full bg-surface-muted px-2 py-0.5 text-[11px] text-ink-muted"
              >
                {step.status === 'done' ? '✓ ' : step.status === 'failed' ? '✗ ' : ''}
                {step.title}
              </span>
            ))}
          </div>
          <button
            type="button"
            className="mt-2 inline-flex items-center gap-1 text-[11px] text-accent hover:underline"
            onClick={() => setExpanded((current) => !current)}
          >
            {expanded ? (
              <ChevronUp className="h-3 w-3" />
            ) : (
              <ChevronDown className="h-3 w-3" />
            )}
            {expanded ? t('chat.agentTaskCollapse') : t('chat.agentTaskExpand')}
          </button>
          {expanded && (
            <div className="mt-2 space-y-2 rounded-xl bg-surface-muted/50 p-2">
              {(task.plan.steps ?? []).map((step) => (
                <div key={step.index} className="text-xs">
                  <p className="text-ink">
                    {step.index + 1}. {step.title}
                    <span className="ml-1 text-[10px] text-ink-muted">
                      {t(`tasks.status.${step.status}` as never)}
                    </span>
                  </p>
                  {step.summary !== undefined && step.summary !== '' && (
                    <p className="mt-0.5 leading-5 text-ink-muted">{step.summary}</p>
                  )}
                  {step.error_code !== undefined && (
                    <p className="text-danger">{step.error_code}</p>
                  )}
                </div>
              ))}
              {(task.result.text ?? task.result.report) !== undefined &&
                (task.result.text ?? task.result.report) !== '' && (
                  <div>
                    <p className="text-[10px] uppercase tracking-wide text-ink-muted">
                      {t('chat.agentTaskResult')}
                    </p>
                    <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap rounded bg-surface p-1.5 text-[10px] text-ink-muted">
                      {(task.result.text ?? task.result.report ?? '').slice(0, 400)}
                    </pre>
                  </div>
                )}
              {(task.result.artifacts ?? []).length > 0 && (
                <div className="space-y-1">
                  <p className="text-[10px] uppercase tracking-wide text-ink-muted">
                    {t('chat.agentTaskArtifacts')}
                  </p>
                  {(task.result.artifacts ?? []).map((artifact, index) => (
                    <div key={`${artifact.title}-${index}`}>
                      <p className="text-xs text-ink">
                        {artifact.title} · {artifact.type}
                      </p>
                      <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap rounded bg-surface p-1.5 text-[10px] text-ink-muted">
                        {artifact.content.slice(0, 400)}
                      </pre>
                    </div>
                  ))}
                </div>
              )}
              {(task.result.tool_records ?? []).length > 0 && (
                <p className="text-[11px] text-ink-muted">
                  {t('chat.agentTaskTools', {
                    count: (task.result.tool_records ?? []).length,
                  })}
                </p>
              )}
            </div>
          )}
          {(task.plan.approvals ?? []).some((approval) => approval.status === 'pending') && (
            <p className="mt-2 text-xs text-warning">{t('chat.agentTaskApproval')}</p>
          )}
          {error !== null && <p className="mt-2 text-xs text-danger">{error}</p>}
        </div>
      )}
      <Dialog
        open={open}
        onClose={onClose}
        title={t('chat.agentTaskTitle')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button size="sm" disabled={busy || goal.trim() === ''} onClick={() => void create()}>
              {busy ? <Spinner /> : null}
              {t('chat.agentTaskCreate')}
            </Button>
          </>
        }
      >
        <div className="space-y-2">
          <Textarea
            rows={4}
            value={goal}
            placeholder={t('chat.agentTaskGoal')}
            onChange={(event) => setGoal(event.target.value)}
          />
          {error !== null && <p className="text-sm text-danger">{error}</p>}
          <p className="text-xs text-ink-muted">{t('chat.agentTaskHint')}</p>
        </div>
      </Dialog>
    </>
  )
}