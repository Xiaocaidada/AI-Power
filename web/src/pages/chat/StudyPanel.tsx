import { useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, Plus, Sparkles } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  StudyAnswerResult,
  StudyAttempt,
  StudySession,
  StudySessionDetail,
} from '../../lib/types'

interface StudyPanelProps {
  conversationId: string
  defaultTopic: string
  selectedSessionId: string
  onSelectSession: (sessionId: string) => void
}

function attemptAnswerValue(
  answers: Record<string, string | string[]>,
  attemptId: string,
): string | string[] {
  return answers[attemptId] ?? ''
}

export function StudyPanel({
  conversationId,
  defaultTopic,
  selectedSessionId,
  onSelectSession,
}: StudyPanelProps) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [answers, setAnswers] = useState<Record<string, string | string[]>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [quizCount, setQuizCount] = useState('5')

  const sessions = useQuery({
    queryKey: ['study-sessions', conversationId],
    queryFn: () =>
      apiRequest<StudySession[]>(
        `/study/sessions?conversation_id=${encodeURIComponent(conversationId)}`,
      ),
    staleTime: 15_000,
  })
  const detail = useQuery({
    queryKey: ['study-session', selectedSessionId],
    queryFn: () =>
      apiRequest<StudySessionDetail>(`/study/sessions/${selectedSessionId}`),
    enabled: selectedSessionId !== '',
  })

  useEffect(() => {
    const rows = sessions.data ?? []
    if (rows.length === 0) return
    if (!rows.some((item) => item.id === selectedSessionId)) {
      onSelectSession(rows[0].id)
    }
  }, [onSelectSession, selectedSessionId, sessions.data])

  useEffect(() => {
    if (detail.data === undefined) return
    const next: Record<string, string | string[]> = {}
    for (const attempt of detail.data.attempts) {
      if (attempt.status !== 'graded') continue
      try {
        const parsed = JSON.parse(attempt.answer) as unknown
        next[attempt.id] = Array.isArray(parsed)
          ? parsed.map(String)
          : attempt.answer
      } catch {
        next[attempt.id] = attempt.answer
      }
    }
    setAnswers((prev) => ({ ...next, ...prev }))
  }, [detail.data])

  const createSession = async () => {
    setBusy('create')
    setError(null)
    try {
      const created = await apiRequest<StudySession>('/study/sessions', {
        method: 'POST',
        body: {
          topic: defaultTopic.trim() || t('study.defaultTopic'),
          conversation_id: conversationId,
          level: 'intermediate',
          mode: 'guided',
          goals: '',
        },
      })
      await queryClient.invalidateQueries({
        queryKey: ['study-sessions', conversationId],
      })
      onSelectSession(created.id)
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(null)
    }
  }

  const generateQuiz = async () => {
    if (selectedSessionId === '') return
    setBusy('quiz')
    setError(null)
    try {
      await apiRequest(`/study/sessions/${selectedSessionId}/quiz`, {
        method: 'POST',
        body: { count: Number(quizCount) },
      })
      await queryClient.invalidateQueries({
        queryKey: ['study-session', selectedSessionId],
      })
      await queryClient.invalidateQueries({
        queryKey: ['study-sessions', conversationId],
      })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(null)
    }
  }

  const submitAnswer = async (attempt: StudyAttempt) => {
    const value = attemptAnswerValue(answers, attempt.id)
    if (
      (typeof value === 'string' && value.trim() === '') ||
      (Array.isArray(value) && value.length === 0)
    ) {
      return
    }
    setBusy(attempt.id)
    setError(null)
    try {
      const result = await apiRequest<StudyAnswerResult>(
        `/study/sessions/${selectedSessionId}/attempts/${attempt.id}/answer`,
        { method: 'POST', body: { answer: value } },
      )
      setAnswers((prev) => ({ ...prev, [attempt.id]: value }))
      queryClient.setQueryData<StudySessionDetail>(
        ['study-session', selectedSessionId],
        (current) =>
          current === undefined
            ? current
            : {
                ...current,
                mastery: result.mastery,
                attempts: current.attempts.map((item) =>
                  item.id === result.attempt.id ? result.attempt : item,
                ),
              },
      )
      await queryClient.invalidateQueries({
        queryKey: ['study-session', selectedSessionId],
      })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(null)
    }
  }

  const session = detail.data
  const mastery = session?.mastery ?? {}
  const pending = (session?.attempts ?? []).filter(
    (attempt) => attempt.status === 'pending',
  )
  const graded = (session?.attempts ?? []).filter(
    (attempt) => attempt.status === 'graded',
  )

  const setAnswer = (attemptId: string, value: string | string[]) => {
    setAnswers((prev) => ({ ...prev, [attemptId]: value }))
  }

  const renderOptions = (attempt: StudyAttempt) => {
    const value = attemptAnswerValue(answers, attempt.id)
    if (attempt.type === 'multiple_choice') {
      const selected = new Set(Array.isArray(value) ? value : [])
      return (
        <div className="mt-2 space-y-1">
          {attempt.options.map((option) => (
            <label key={option.id} className="flex items-start gap-2 text-xs text-ink">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={selected.has(option.id)}
                onChange={(event) => {
                  const next = new Set(selected)
                  if (event.target.checked) next.add(option.id)
                  else next.delete(option.id)
                  setAnswer(attempt.id, Array.from(next))
                }}
              />
              <span>
                {option.id}. {option.text}
              </span>
            </label>
          ))}
        </div>
      )
    }
    return (
      <div className="mt-2 space-y-1">
        {attempt.options.map((option) => (
          <label key={option.id} className="flex items-start gap-2 text-xs text-ink">
            <input
              type="radio"
              name={`study-${attempt.id}`}
              className="mt-0.5"
              checked={value === option.id}
              onChange={() => setAnswer(attempt.id, option.id)}
            />
            <span>
              {option.id}. {option.text}
            </span>
          </label>
        ))}
      </div>
    )
  }

  const renderAttempt = (attempt: StudyAttempt) => {
    const value = attemptAnswerValue(answers, attempt.id)
    const isPending = attempt.status === 'pending'
    return (
      <div
        key={attempt.id}
        className="rounded-xl border border-border bg-surface px-3 py-2.5"
      >
        <div className="flex items-start gap-2">
          <Badge tone="neutral">{attempt.type}</Badge>
          {attempt.status === 'graded' && (
            <Badge tone={attempt.score === 1 ? 'success' : 'danger'}>
              {attempt.score === 1 ? t('study.correct') : t('study.incorrect')}
            </Badge>
          )}
        </div>
        <p className="mt-1.5 text-sm text-ink">{attempt.prompt}</p>
        {isPending &&
          (attempt.type === 'short_answer' ? (
            <Input
              className="mt-2"
              value={typeof value === 'string' ? value : ''}
              onChange={(event) => setAnswer(attempt.id, event.target.value)}
              placeholder={t('study.yourAnswer')}
            />
          ) : (
            renderOptions(attempt)
          ))}
        {isPending && (
          <Button
            size="sm"
            className="mt-2"
            disabled={busy === attempt.id}
            onClick={() => void submitAnswer(attempt)}
          >
            {t('study.submit')}
          </Button>
        )}
        {!isPending && (
          <div className="mt-1.5 space-y-1 text-xs">
            <p className={attempt.score === 1 ? 'text-success' : 'text-danger'}>
              {attempt.feedback}
            </p>
            {attempt.correct_answer !== null &&
              attempt.correct_answer !== undefined && (
                <p className="text-ink-muted">
                  {t('study.correctAnswer')}: {attempt.correct_answer.join(', ')}
                </p>
              )}
          </div>
        )}
      </div>
    )
  }

  return (
    <details open className="mb-2 rounded-xl border border-border bg-surface-muted/20 px-3 py-2">
      <summary className="cursor-pointer select-none text-xs font-medium text-ink-muted">
        <BookOpen className="mr-1 inline h-3.5 w-3.5" />
        {t('study.panelTitle')}
        {session !== undefined ? ` · ${session.topic}` : ''}
        {mastery.answered !== undefined && mastery.answered > 0
          ? ` · ${t('study.accuracy', {
              percent: Math.round((mastery.accuracy ?? 0) * 100),
            })}`
          : ''}
      </summary>

      {sessions.data !== undefined && sessions.data.length === 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-ink-muted">
          <span>{t('study.noSession')}</span>
          <Button
            size="sm"
            disabled={busy === 'create'}
            onClick={() => void createSession()}
          >
            <Plus className="h-3.5 w-3.5" />
            {t('study.createSession')}
          </Button>
        </div>
      )}

      {sessions.data !== undefined && sessions.data.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <select
            className="h-8 rounded-lg border border-border bg-surface px-2 text-xs text-ink"
            value={selectedSessionId}
            onChange={(event) => onSelectSession(event.target.value)}
          >
            {sessions.data.map((item) => (
              <option key={item.id} value={item.id}>
                {item.topic} · {item.level} · {item.mode}
              </option>
            ))}
          </select>
          <Button
            variant="secondary"
            size="sm"
            disabled={busy === 'create'}
            onClick={() => void createSession()}
          >
            <Plus className="h-3.5 w-3.5" />
            {t('study.newSession')}
          </Button>
          <select
            className="h-8 rounded-lg border border-border bg-surface px-2 text-xs text-ink"
            value={quizCount}
            onChange={(event) => setQuizCount(event.target.value)}
          >
            {['3', '5', '10'].map((count) => (
              <option key={count} value={count}>
                {t('study.countQuestions', { count })}
              </option>
            ))}
          </select>
          <Button
            size="sm"
            disabled={busy === 'quiz' || selectedSessionId === ''}
            onClick={() => void generateQuiz()}
          >
            <Sparkles className="h-3.5 w-3.5" />
            {t('study.generateQuiz')}
          </Button>
        </div>
      )}

      {session !== undefined && (
        <div className="mt-2 space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-ink-muted">
            <span>
              {t('study.topic')}: {session.topic}
            </span>
            <span>
              {t('study.level')}: {session.level}
            </span>
            <span>
              {t('study.mode')}: {session.mode}
            </span>
            <span>
              {t('study.answeredCount', {
                answered: mastery.answered ?? 0,
                correct: mastery.correct ?? 0,
              })}
            </span>
          </div>
          {(mastery.weak_points ?? []).length > 0 && (
            <p className="text-[11px] text-warning">
              {t('study.weakPoints')}: {(mastery.weak_points ?? []).join('; ')}
            </p>
          )}
          {(mastery.suggestions ?? []).length > 0 && (
            <ul className="list-disc space-y-0.5 pl-4 text-[11px] text-ink-muted">
              {(mastery.suggestions ?? []).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          )}
          {(session.attempts ?? []).length === 0 && (
            <p className="text-xs text-ink-muted">{t('study.noQuiz')}</p>
          )}
          {pending.length > 0 && (
            <div className="space-y-2">{pending.map(renderAttempt)}</div>
          )}
          {graded.length > 0 && (
            <details className="text-xs text-ink-muted">
              <summary className="cursor-pointer select-none">
                {t('study.gradedHistory', { count: graded.length })}
              </summary>
              <div className="mt-1 space-y-2">{graded.map(renderAttempt)}</div>
            </details>
          )}
        </div>
      )}

      {error !== null && <p className="mt-2 text-xs text-danger">{error}</p>}
    </details>
  )
}