import { useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Plus, RefreshCw, Star, Trash2, XCircle } from 'lucide-react'
import { useMemo, useState } from 'react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorMessage } from '../../lib/errors'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  ExternalCall,
  IntegrationConfig,
  IntegrationKind,
} from '../../lib/types'

const KINDS: IntegrationKind[] = ['image_generation', 'stt', 'tts', 'github']

interface FormState {
  name: string
  base_url: string
  credential: string
  model: string
  size: string
  voice: string
  language: string
  shared: boolean
  enabled: boolean
}

const EMPTY_FORM: FormState = {
  name: '',
  base_url: '',
  credential: '',
  model: '',
  size: '1024x1024',
  voice: 'alloy',
  language: '',
  shared: false,
  enabled: true,
}

function kindLabelKey(kind: IntegrationKind): string {
  return `integrations.kind.${kind}`
}

export function IntegrationsPage() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [kind, setKind] = useState<IntegrationKind>('image_generation')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const integrations = useQuery({
    queryKey: ['integrations'],
    queryFn: () => apiRequest<IntegrationConfig[]>('/integrations'),
  })
  const calls = useQuery({
    queryKey: ['integration-calls'],
    queryFn: () => apiRequest<ExternalCall[]>('/integrations/calls?limit=12'),
  })

  const rows = useMemo(
    () => (integrations.data ?? []).filter((item) => item.kind === kind),
    [integrations.data, kind],
  )

  const reset = (): void => {
    setEditingId(null)
    setForm(EMPTY_FORM)
  }

  const edit = (item: IntegrationConfig): void => {
    setEditingId(item.id)
    setForm({
      name: item.name,
      base_url: item.base_url,
      credential: '',
      model: item.model,
      size: String(item.options.size ?? '1024x1024'),
      voice: String(item.options.voice ?? 'alloy'),
      language: String(item.options.language ?? ''),
      shared: item.shared,
      enabled: item.enabled,
    })
  }

  const save = async (): Promise<void> => {
    setBusy(true)
    setError(null)
    const options: Record<string, unknown> =
      kind === 'image_generation'
        ? { size: form.size }
        : kind === 'tts'
          ? { voice: form.voice }
          : kind === 'stt' && form.language.trim() !== ''
            ? { language: form.language.trim() }
            : {}
    try {
      if (editingId === null) {
        await apiRequest('/integrations', {
          method: 'POST',
          body: {
            kind,
            name: form.name,
            base_url: form.base_url || null,
            credential: form.credential,
            model: form.model,
            options,
            shared: form.shared,
            enabled: form.enabled,
          },
        })
      } else {
        await apiRequest(`/integrations/${editingId}`, {
          method: 'PATCH',
          body: {
            name: form.name,
            base_url: form.base_url || null,
            credential: form.credential || null,
            model: form.model,
            options,
            shared: form.shared,
            enabled: form.enabled,
          },
        })
      }
      reset()
      await queryClient.invalidateQueries({ queryKey: ['integrations'] })
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const test = async (item: IntegrationConfig): Promise<void> => {
    setBusy(true)
    setError(null)
    try {
      const result = await apiRequest<{ status: string; error_code: string | null }>(
        `/integrations/${item.id}/test`,
        { method: 'POST' },
      )
      if (result.status !== 'ok') setError(result.error_code ?? t('integrations.testFailed'))
      await queryClient.invalidateQueries({ queryKey: ['integrations'] })
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const makeDefault = async (item: IntegrationConfig): Promise<void> => {
    setBusy(true)
    setError(null)
    try {
      await apiRequest(`/integrations/${item.id}/default`, { method: 'POST' })
      await queryClient.invalidateQueries({ queryKey: ['integrations'] })
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const remove = async (item: IntegrationConfig): Promise<void> => {
    setBusy(true)
    setError(null)
    try {
      await apiRequest(`/integrations/${item.id}`, { method: 'DELETE' })
      if (editingId === item.id) reset()
      await queryClient.invalidateQueries({ queryKey: ['integrations'] })
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-4">
        <h1 className="text-lg font-semibold">{t('integrations.title')}</h1>
        <p className="mt-1 text-sm text-ink-muted">{t('integrations.lead')}</p>
      </header>
      <div className="mx-auto grid w-full max-w-6xl gap-6 px-6 py-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-4">
          <div className="flex flex-wrap gap-1">
            {KINDS.map((item) => (
              <Button
                key={item}
                variant={item === kind ? 'primary' : 'secondary'}
                size="sm"
                onClick={() => {
                  setKind(item)
                  reset()
                }}
              >
                {t(kindLabelKey(item) as never)}
              </Button>
            ))}
          </div>

          {error !== null && (
            <p className="rounded-lg border border-danger/40 bg-danger/5 px-3 py-2 text-sm text-danger">
              {error}
            </p>
          )}

          {rows.length === 0 && (
            <div className="rounded-2xl border border-dashed border-border px-6 py-10 text-center text-sm text-ink-muted">
              {t('integrations.empty')}
            </div>
          )}

          {rows.map((item) => (
            <article key={item.id} className="rounded-2xl border border-border bg-surface p-4">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-sm font-semibold">{item.name}</h2>
                {item.is_default && <Badge tone="accent">{t('integrations.default')}</Badge>}
                {!item.enabled && <Badge tone="warning">{t('integrations.disabled')}</Badge>}
                {item.owned && <Badge tone="neutral">{t('integrations.owned')}</Badge>}
                <span className="ml-auto flex items-center gap-1">
                  {item.status === 'ok' ? (
                    <CheckCircle2 className="h-4 w-4 text-success" />
                  ) : item.status === 'error' ? (
                    <XCircle className="h-4 w-4 text-danger" />
                  ) : null}
                  {item.owned && (
                    <>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={busy}
                        onClick={() => void test(item)}
                      >
                        <RefreshCw className="h-4 w-4" />
                        {t('integrations.test')}
                      </Button>
                      {!item.is_default && (
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={busy}
                          onClick={() => void makeDefault(item)}
                        >
                          <Star className="h-4 w-4" />
                          {t('integrations.makeDefault')}
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={busy}
                        onClick={() => edit(item)}
                      >
                        {t('common.edit')}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={busy}
                        onClick={() => void remove(item)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </>
                  )}
                </span>
              </div>
              <p className="mt-2 text-xs text-ink-muted">
                {item.base_url} · {item.model || '—'} · {item.credential_hint || '—'}
              </p>
              {item.last_error !== null && (
                <p className="mt-1 text-xs text-danger">{item.last_error}</p>
              )}
            </article>
          ))}

          <section className="rounded-2xl border border-border bg-surface p-4">
            <h2 className="text-sm font-semibold">{t('integrations.calls')}</h2>
            <div className="mt-2 space-y-1 text-xs">
              {(calls.data ?? []).map((call) => (
                <div
                  key={call.id}
                  className="flex flex-wrap gap-2 rounded-lg border border-border/70 px-2 py-1.5"
                >
                  <span className="text-ink-muted">
                    {new Date(call.created_at).toLocaleString()}
                  </span>
                  <span className="font-medium">{call.operation}</span>
                  <span className="text-ink-muted">{call.provider}</span>
                  <span className={call.status === 'failed' ? 'text-danger' : 'text-success'}>
                    {call.error_code ?? call.status}
                  </span>
                  <span className="ml-auto text-ink-muted">{call.duration_ms}ms</span>
                </div>
              ))}
              {(calls.data ?? []).length === 0 && (
                <p className="text-ink-muted">{t('integrations.noCalls')}</p>
              )}
            </div>
          </section>
        </div>

        <aside className="h-fit rounded-2xl border border-border bg-surface p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">
              {editingId === null ? t('integrations.add') : t('integrations.edit')}
            </h2>
            <Button variant="ghost" size="sm" onClick={reset}>
              <Plus className="h-4 w-4" />
              {t('integrations.new')}
            </Button>
          </div>
          <div className="mt-3 space-y-2">
            <Input
              value={form.name}
              placeholder={t('integrations.name')}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
            />
            <Input
              value={form.base_url}
              placeholder={t('integrations.baseUrl')}
              onChange={(event) => setForm({ ...form, base_url: event.target.value })}
            />
            <Input
              type="password"
              value={form.credential}
              placeholder={
                editingId === null
                  ? t('integrations.credential')
                  : t('integrations.credentialKeep')
              }
              onChange={(event) => setForm({ ...form, credential: event.target.value })}
            />
            <Input
              value={form.model}
              placeholder={t('integrations.model')}
              onChange={(event) => setForm({ ...form, model: event.target.value })}
            />
            {kind === 'image_generation' && (
              <select
                className="h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm"
                value={form.size}
                onChange={(event) => setForm({ ...form, size: event.target.value })}
              >
                {['256x256', '512x512', '1024x1024', '1024x1536', '1536x1024', 'auto'].map(
                  (size) => (
                    <option key={size} value={size}>
                      {size}
                    </option>
                  ),
                )}
              </select>
            )}
            {kind === 'tts' && (
              <Input
                value={form.voice}
                placeholder={t('integrations.voice')}
                onChange={(event) => setForm({ ...form, voice: event.target.value })}
              />
            )}
            {kind === 'stt' && (
              <Input
                value={form.language}
                placeholder={t('integrations.language')}
                onChange={(event) => setForm({ ...form, language: event.target.value })}
              />
            )}
            <label className="flex items-center gap-2 text-xs text-ink-muted">
              <input
                type="checkbox"
                checked={form.shared}
                onChange={(event) => setForm({ ...form, shared: event.target.checked })}
              />
              {t('integrations.shared')}
            </label>
            <label className="flex items-center gap-2 text-xs text-ink-muted">
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={(event) => setForm({ ...form, enabled: event.target.checked })}
              />
              {t('integrations.enabled')}
            </label>
            <Button className="w-full" disabled={busy} onClick={() => void save()}>
              {busy ? <Spinner /> : null}
              {t('common.save')}
            </Button>
            <p className="text-[11px] text-ink-muted">{t('integrations.byokHint')}</p>
          </div>
        </aside>
      </div>
    </div>
  )
}