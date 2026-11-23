import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Eye, RotateCcw, Square, ThumbsDown, ThumbsUp, Trophy } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { Link, useParams } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Spinner } from '../../components/ui/spinner'
import { ApiError } from '../../lib/errors'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import { streamArenaResponse } from '../../lib/sse'
import type { ArenaResponse, ArenaRound } from '../../lib/types'

interface ColumnProps {
  round: ArenaRound
  response: ArenaResponse
  stopAllToken: number
  onVote: (responseId: string) => void
  onChanged: () => void
}

function ArenaColumn({ round, response, stopAllToken, onVote, onChanged }: ColumnProps) {
  const { t } = useI18n()
  const [item, setItem] = useState<ArenaResponse>(response)
  const [streaming, setStreaming] = useState(false)
  const controllerRef = useRef<AbortController | null>(null)
  const startedAttemptRef = useRef<number | null>(null)

  useEffect(() => {
    setItem(response)
  }, [response])

  const start = async () => {
    if (controllerRef.current !== null) return
    setStreaming(true)
    setItem((prev) => ({ ...prev, status: 'streaming', content: '', error_code: null }))
    const controller = new AbortController()
    controllerRef.current = controller
    try {
      await streamArenaResponse({
        roundId: round.id,
        responseId: item.id,
        signal: controller.signal,
        onEvent: (event) => {
          const data = event.data as Record<string, unknown> | null
          if (data === null) return
          if (event.event === 'delta') {
            setItem((prev) => ({
              ...prev,
              content: prev.content + String(data.text ?? ''),
            }))
          } else if (event.event === 'usage') {
            setItem((prev) => ({
              ...prev,
              prompt_tokens:
                typeof data.prompt_tokens === 'number' ? data.prompt_tokens : null,
              completion_tokens:
                typeof data.completion_tokens === 'number' ? data.completion_tokens : null,
              cost: typeof data.cost === 'number' ? data.cost : 0,
            }))
          } else if (event.event === 'done') {
            setItem((prev) => ({
              ...prev,
              status: 'completed',
              ttft_ms: typeof data.ttft_ms === 'number' ? data.ttft_ms : null,
              total_ms: typeof data.total_ms === 'number' ? data.total_ms : null,
              prompt_tokens:
                typeof data.prompt_tokens === 'number' ? data.prompt_tokens : null,
              completion_tokens:
                typeof data.completion_tokens === 'number' ? data.completion_tokens : null,
              cost: typeof data.cost === 'number' ? data.cost : 0,
            }))
          } else if (event.event === 'error') {
            setItem((prev) => ({
              ...prev,
              status: 'failed',
              error_code: String(data.code ?? 'internal_error'),
            }))
          }
        },
      })
    } catch (caught) {
      if (controller.signal.aborted) {
        setItem((prev) => ({ ...prev, status: 'cancelled' }))
      } else {
        setItem((prev) => ({
          ...prev,
          status: 'failed',
          error_code: caught instanceof ApiError ? (caught.code ?? 'error') : 'network',
        }))
      }
    } finally {
      controllerRef.current = null
      setStreaming(false)
      onChanged()
    }
  }

  useEffect(() => {
    if (item.status !== 'queued') return
    if (startedAttemptRef.current === item.attempt) return
    startedAttemptRef.current = item.attempt
    void start()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.status, item.attempt])

  useEffect(() => {
    if (stopAllToken > 0) controllerRef.current?.abort()
  }, [stopAllToken])

  useEffect(
    () => () => {
      controllerRef.current?.abort()
    },
    [],
  )

  const retry = async () => {
    const updated = await apiRequest<ArenaResponse>(
      `/arena/rounds/${round.id}/responses/${item.id}/retry`,
      { method: 'POST' },
    )
    setItem(updated)
    startedAttemptRef.current = null
    void start()
  }

  const setFeedback = async (value: 'helpful' | 'unhelpful') => {
    const updated = await apiRequest<ArenaResponse>(
      `/arena/rounds/${round.id}/responses/${item.id}/feedback`,
      {
        method: 'PUT',
        body: { feedback: item.feedback === value ? null : value },
      },
    )
    setItem(updated)
  }

  const masked = round.blind && !round.revealed
  const title = masked ? item.label : `${item.model ?? item.label}`
  const subtitle = masked ? t('arena.blindLabel') : (item.provider_id ?? '')

  return (
    <article className="flex min-h-0 flex-col rounded-card border border-border bg-surface">
      <header className="border-b border-border px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-ink">{title}</p>
            <p className="truncate text-[11px] text-ink-muted">{subtitle}</p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <Badge
              tone={
                item.status === 'completed'
                  ? 'success'
                  : item.status === 'failed'
                    ? 'danger'
                    : item.status === 'cancelled'
                      ? 'warning'
                      : 'neutral'
              }
            >
              {item.status}
            </Badge>
            {streaming ? (
              <Button
                variant="ghost"
                size="sm"
                aria-label={t('arena.stop')}
                onClick={() => controllerRef.current?.abort()}
              >
                <Square className="h-3.5 w-3.5" />
              </Button>
            ) : (
              <Button
                variant="ghost"
                size="sm"
                aria-label={t('arena.retry')}
                disabled={item.status === 'streaming'}
                onClick={() => void retry()}
              >
                <RotateCcw className="h-3.5 w-3.5" />
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              aria-label={t('arena.vote')}
              className={round.vote_response_id === item.id ? 'text-accent' : ''}
              onClick={() => onVote(item.id)}
            >
              <Trophy className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      </header>

      <div className="min-h-[18rem] flex-1 overflow-y-auto px-4 py-3">
        {item.content !== '' ? (
          <div className="markdown text-sm text-ink">
            <ReactMarkdown>{item.content}</ReactMarkdown>
          </div>
        ) : (
          <p className="text-xs text-ink-muted">
            {item.status === 'failed'
              ? t('arena.failed', { code: item.error_code ?? '' })
              : item.status === 'cancelled'
                ? t('arena.cancelled')
                : t('arena.generating')}
          </p>
        )}
      </div>

      <footer className="border-t border-border px-4 py-2 text-[11px] text-ink-muted">
        <div className="flex flex-wrap items-center justify-between gap-1 pb-1.5">
          <span>{t('arena.feedback')}</span>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              aria-label={t('arena.helpful')}
              aria-pressed={item.feedback === 'helpful'}
              className={item.feedback === 'helpful' ? 'text-accent' : ''}
              onClick={() => void setFeedback('helpful')}
            >
              <ThumbsUp className="h-3.5 w-3.5" />
              <span className="ml-1 text-[10px]">{t('arena.helpful')}</span>
            </Button>
            <Button
              variant="ghost"
              size="sm"
              aria-label={t('arena.unhelpful')}
              aria-pressed={item.feedback === 'unhelpful'}
              className={item.feedback === 'unhelpful' ? 'text-danger' : ''}
              onClick={() => void setFeedback('unhelpful')}
            >
              <ThumbsDown className="h-3.5 w-3.5" />
              <span className="ml-1 text-[10px]">{t('arena.unhelpful')}</span>
            </Button>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-1">
          <span>TTFT {item.ttft_ms !== null ? `${item.ttft_ms} ms` : '—'}</span>
          <span>Total {item.total_ms !== null ? `${item.total_ms} ms` : '—'}</span>
          <span>
            Tokens{' '}
            {item.prompt_tokens !== null || item.completion_tokens !== null
              ? `${item.prompt_tokens ?? 0} + ${item.completion_tokens ?? 0}`
              : '—'}
          </span>
          <span>Cost {item.prompt_tokens !== null ? `~$${item.cost.toFixed(6)}` : '—'}</span>
        </div>
      </footer>
    </article>
  )
}

export function ArenaDetailPage() {
  const { id = '' } = useParams<{ id: string }>()
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [stopAllToken, setStopAllToken] = useState(0)

  const roundQuery = useQuery({
    queryKey: ['arena-round', id],
    queryFn: () => apiRequest<ArenaRound>(`/arena/rounds/${id}`),
    enabled: id !== '',
  })
  const round = roundQuery.data

  const vote = async (responseId: string) => {
    if (round === undefined) return
    await apiRequest(`/arena/rounds/${id}/vote`, {
      method: 'POST',
      body: { response_id: responseId },
    })
    await queryClient.invalidateQueries({ queryKey: ['arena-round', id] })
    await queryClient.invalidateQueries({ queryKey: ['arena-rounds'] })
  }

  const reveal = async () => {
    await apiRequest(`/arena/rounds/${id}/reveal`, { method: 'POST' })
    await queryClient.invalidateQueries({ queryKey: ['arena-round', id] })
  }

  if (roundQuery.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner className="h-6 w-6 text-accent" />
      </div>
    )
  }
  if (roundQuery.isError || round === undefined) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3">
        <p className="text-sm text-ink-muted">{t('arena.loadError')}</p>
        <Link to="/arena" className="text-sm text-accent">
          {t('arena.back')}
        </Link>
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-surface px-6 py-3">
        <div className="min-w-0">
          <Link to="/arena" className="text-xs text-accent">
            {t('arena.back')}
          </Link>
          <h1 className="truncate text-sm font-medium text-ink">{round.prompt}</h1>
          <p className="mt-0.5 text-[11px] text-ink-muted">
            {round.blind ? t('arena.blindShort') : t('arena.modelsCount', { count: round.responses.length })}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {round.blind && !round.revealed && (
            <Button variant="secondary" size="sm" onClick={() => void reveal()}>
              <Eye className="h-3.5 w-3.5" />
              {t('arena.reveal')}
            </Button>
          )}
          <Button variant="secondary" size="sm" onClick={() => setStopAllToken((value) => value + 1)}>
            <Square className="h-3.5 w-3.5" />
            {t('arena.stopAll')}
          </Button>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-x-auto overflow-y-hidden p-4">
        <div
          className={`grid h-full min-h-[28rem] gap-3 ${
            round.responses.length === 2
              ? 'grid-cols-2'
              : round.responses.length === 3
                ? 'grid-cols-3'
                : 'grid-cols-4'
          }`}
        >
          {round.responses.map((response) => (
            <ArenaColumn
              key={`${response.id}-${response.attempt}-${round.revealed}`}
              round={round}
              response={response}
              stopAllToken={stopAllToken}
              onVote={(responseId) => void vote(responseId)}
              onChanged={() => {
                void queryClient.invalidateQueries({ queryKey: ['arena-round', id] })
              }}
            />
          ))}
        </div>
      </div>
    </div>
  )
}