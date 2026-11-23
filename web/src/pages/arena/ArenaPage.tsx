import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Swords, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { Button } from '../../components/ui/button'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { formatDate } from '../../lib/format'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { ArenaRound, ModelEntry, PersonalModel } from '../../lib/types'

interface Choice {
  provider_id: string
  model: string
  label: string
}

export function ArenaPage() {
  const { t, language } = useI18n()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [prompt, setPrompt] = useState('')
  const [blind, setBlind] = useState(false)
  const [temperature, setTemperature] = useState('')
  const [maxTokens, setMaxTokens] = useState('')
  const [selected, setSelected] = useState<Choice[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const models = useQuery({
    queryKey: ['models'],
    queryFn: () => apiRequest<ModelEntry[]>('/models'),
    staleTime: 60_000,
  })
  const personal = useQuery({
    queryKey: ['provider-configs', 'models'],
    queryFn: () => apiRequest<PersonalModel[]>('/provider-configs/models'),
    staleTime: 60_000,
  })
  const history = useQuery({
    queryKey: ['arena-rounds'],
    queryFn: () => apiRequest<ArenaRound[]>('/arena/rounds?limit=30'),
  })

  const options: Choice[] = [
    ...(models.data ?? [])
      .filter((item) => item.available)
      .map((item) => ({
        provider_id: item.provider_id,
        model: item.model_id,
        label: `${item.display_name} · ${item.provider_id}`,
      })),
    ...(personal.data ?? []).map((item) => ({
      provider_id: item.provider_id,
      model: item.model_id,
      label: `${item.display_name} · ${item.provider_name}`,
    })),
  ]
  const selectedKeys = new Set(selected.map((item) => `${item.provider_id}/${item.model}`))

  const toggle = (choice: Choice) => {
    const key = `${choice.provider_id}/${choice.model}`
    setSelected((prev) => {
      if (prev.some((item) => `${item.provider_id}/${item.model}` === key)) {
        return prev.filter((item) => `${item.provider_id}/${item.model}` !== key)
      }
      if (prev.length >= 4) return prev
      return [...prev, choice]
    })
    setError(null)
  }

  const create = async () => {
    if (prompt.trim() === '') return
    if (selected.length < 2) {
      setError(t('arena.minModels'))
      return
    }
    setBusy(true)
    setError(null)
    try {
      const round = await apiRequest<ArenaRound>('/arena/rounds', {
        method: 'POST',
        body: {
          prompt: prompt.trim(),
          models: selected.map(({ provider_id, model }) => ({ provider_id, model })),
          blind,
          generation_settings: {
            ...(temperature.trim() ? { temperature: Number(temperature) } : {}),
            ...(maxTokens.trim() ? { max_tokens: Number(maxTokens) } : {}),
          },
        },
      })
      await queryClient.invalidateQueries({ queryKey: ['arena-rounds'] })
      navigate(`/arena/${round.id}`)
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(false)
    }
  }

  const removeRound = async (round: ArenaRound) => {
    await apiRequest(`/arena/rounds/${round.id}`, { method: 'DELETE' })
    await queryClient.invalidateQueries({ queryKey: ['arena-rounds'] })
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-4">
        <h1 className="flex items-center gap-2 text-lg font-semibold">
          <Swords className="h-5 w-5 text-accent" />
          {t('arena.title')}
        </h1>
        <p className="mt-1 text-sm text-ink-muted">{t('arena.lead')}</p>
      </header>

      <div className="mx-auto grid w-full max-w-6xl gap-6 px-6 py-6 lg:grid-cols-[1.4fr_1fr]">
        <section className="space-y-4">
          <div className="rounded-card border border-border bg-surface p-4">
            <p className="text-sm font-medium text-ink">{t('arena.selectModels')}</p>
            <p className="mt-0.5 text-xs text-ink-muted">
              {t('arena.selectHint', { count: selected.length })}
            </p>
            <div className="mt-3 grid gap-1.5 sm:grid-cols-2">
              {options.map((choice) => {
                const key = `${choice.provider_id}/${choice.model}`
                const active = selectedKeys.has(key)
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => toggle(choice)}
                    className={`truncate rounded-lg border px-3 py-2 text-left text-xs ${
                      active
                        ? 'border-accent/40 bg-accent-soft text-accent'
                        : 'border-border text-ink-muted hover:bg-surface-muted hover:text-ink'
                    }`}
                  >
                    {choice.label}
                  </button>
                )
              })}
            </div>
            {options.length === 0 && (
              <p className="mt-2 text-xs text-ink-muted">{t('chat.noProviders')}</p>
            )}
          </div>

          <div className="rounded-card border border-border bg-surface p-4">
            <textarea
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder={t('arena.promptPlaceholder')}
              className="min-h-28 w-full resize-none rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none"
            />
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              <label className="text-xs text-ink-muted">
                Temperature
                <input
                  value={temperature}
                  onChange={(event) => setTemperature(event.target.value)}
                  inputMode="decimal"
                  className="mt-1 h-9 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink"
                />
              </label>
              <label className="text-xs text-ink-muted">
                Max tokens
                <input
                  value={maxTokens}
                  onChange={(event) => setMaxTokens(event.target.value)}
                  inputMode="numeric"
                  className="mt-1 h-9 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink"
                />
              </label>
            </div>
            <label className="mt-3 flex items-center gap-2 text-xs text-ink-muted">
              <input
                type="checkbox"
                checked={blind}
                onChange={(event) => setBlind(event.target.checked)}
              />
              {t('arena.blindMode')}
            </label>
            {error !== null && <p className="mt-2 text-xs text-danger">{error}</p>}
            <div className="mt-4 flex justify-end">
              <Button disabled={busy || prompt.trim() === ''} onClick={() => void create()}>
                {busy && <Spinner />}
                {t('arena.start')}
              </Button>
            </div>
          </div>
        </section>

        <section className="rounded-card border border-border bg-surface">
          <h2 className="border-b border-border px-4 py-3 text-sm font-medium">
            {t('arena.history')}
          </h2>
          {history.isLoading && <Spinner className="m-4" />}
          <div className="divide-y divide-border">
            {(history.data ?? []).map((round) => (
              <div key={round.id} className="flex items-center gap-2 px-4 py-3">
                <Link to={`/arena/${round.id}`} className="min-w-0 flex-1">
                  <p className="truncate text-sm text-ink">{round.prompt}</p>
                  <p className="mt-0.5 text-[11px] text-ink-muted">
                    {round.blind
                      ? t('arena.blindShort')
                      : round.responses.map((item) => item.model ?? item.label).join(' · ')}{' '}
                    · {formatDate(round.created_at, language)}
                  </p>
                </Link>
                <button
                  type="button"
                  aria-label={t('common.delete')}
                  className="rounded p-1 text-ink-muted hover:text-danger"
                  onClick={() => void removeRound(round)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
            {history.data !== undefined && history.data.length === 0 && (
              <p className="px-4 py-6 text-xs text-ink-muted">{t('arena.empty')}</p>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}