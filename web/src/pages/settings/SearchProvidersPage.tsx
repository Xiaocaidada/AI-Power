import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Search, Trash2, Zap } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { Input } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { SearchProvider, SearchProviderTestResult } from '../../lib/types'

const PROVIDERS = ['tavily', 'brave', 'serper', 'searxng'] as const

interface FormState {
  provider: (typeof PROVIDERS)[number]
  name: string
  base_url: string
  api_key: string
  max_results: number
  timeout_seconds: number
  shared: boolean
  enabled: boolean
}

const EMPTY_FORM: FormState = {
  provider: 'tavily',
  name: '',
  base_url: '',
  api_key: '',
  max_results: 5,
  timeout_seconds: 15,
  shared: false,
  enabled: true,
}

function statusTone(status: string): 'success' | 'danger' | 'neutral' {
  if (status === 'ok') return 'success'
  if (status === 'error') return 'danger'
  return 'neutral'
}

export function SearchProvidersPage() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<SearchProvider | null>(null)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<
    Record<string, SearchProviderTestResult>
  >({})

  const providers = useQuery({
    queryKey: ['search-providers'],
    queryFn: () => apiRequest<SearchProvider[]>('/search-providers'),
  })

  const openCreate = () => {
    setEditTarget(null)
    setForm(EMPTY_FORM)
    setError(null)
    setDialogOpen(true)
  }

  const openEdit = (provider: SearchProvider) => {
    setEditTarget(provider)
    setForm({
      provider: provider.provider,
      name: provider.name,
      base_url: provider.base_url,
      api_key: '',
      max_results: provider.max_results,
      timeout_seconds: provider.timeout_seconds,
      shared: provider.shared,
      enabled: provider.enabled,
    })
    setError(null)
    setDialogOpen(true)
  }

  const save = async () => {
    setSaving(true)
    setError(null)
    const body: Record<string, unknown> = {
      name: form.name,
      base_url: form.base_url || null,
      max_results: form.max_results,
      timeout_seconds: form.timeout_seconds,
      shared: form.shared,
      enabled: form.enabled,
    }
    if (form.api_key.trim() !== '') body.api_key = form.api_key.trim()
    try {
      if (editTarget === null) {
        await apiRequest('/search-providers', {
          method: 'POST',
          body: { ...body, provider: form.provider },
        })
      } else {
        await apiRequest(`/search-providers/${editTarget.id}`, {
          method: 'PATCH',
          body,
        })
      }
      setDialogOpen(false)
      await queryClient.invalidateQueries({ queryKey: ['search-providers'] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setSaving(false)
    }
  }

  const test = async (provider: SearchProvider) => {
    setError(null)
    try {
      const result = await apiRequest<SearchProviderTestResult>(
        `/search-providers/${provider.id}/test`,
        { method: 'POST' },
      )
      setTestResults((prev) => ({ ...prev, [provider.id]: result }))
      await queryClient.invalidateQueries({ queryKey: ['search-providers'] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    }
  }

  const makeDefault = async (provider: SearchProvider) => {
    setError(null)
    try {
      await apiRequest(`/search-providers/${provider.id}/default`, {
        method: 'POST',
      })
      await queryClient.invalidateQueries({ queryKey: ['search-providers'] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    }
  }

  const remove = async (provider: SearchProvider) => {
    if (!window.confirm(t('searchProviders.deleteConfirm', { name: provider.name }))) {
      return
    }
    setError(null)
    try {
      await apiRequest(`/search-providers/${provider.id}`, { method: 'DELETE' })
      await queryClient.invalidateQueries({ queryKey: ['search-providers'] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    }
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-surface px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold">{t('searchProviders.title')}</h1>
          <p className="mt-1 text-sm text-ink-muted">{t('searchProviders.lead')}</p>
        </div>
        <Button size="sm" onClick={openCreate}>
          <Plus className="h-3.5 w-3.5" />
          {t('searchProviders.add')}
        </Button>
      </header>

      <div className="mx-auto w-full max-w-5xl space-y-4 px-6 py-6">
        {providers.isLoading && (
          <div className="flex items-center gap-2 text-sm text-ink-muted">
            <Spinner />
            {t('common.loading')}
          </div>
        )}
        {providers.data !== undefined && providers.data.length === 0 && (
          <div className="rounded-2xl border border-dashed border-border bg-surface px-6 py-10 text-center">
            <Search className="mx-auto h-6 w-6 text-ink-muted" />
            <p className="mt-3 text-sm text-ink">{t('searchProviders.empty')}</p>
            <p className="mt-1 text-xs text-ink-muted">
              {t('searchProviders.emptyHint')}
            </p>
          </div>
        )}

        {providers.data?.map((provider) => {
          const testResult = testResults[provider.id]
          return (
            <div
              key={provider.id}
              className="rounded-2xl border border-border bg-surface p-5"
            >
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-sm font-semibold text-ink">{provider.name}</h2>
                <Badge tone="accent">{provider.provider}</Badge>
                {provider.is_default && (
                  <Badge tone="success">{t('searchProviders.default')}</Badge>
                )}
                {provider.shared && (
                  <Badge tone="neutral">{t('searchProviders.shared')}</Badge>
                )}
                {!provider.enabled && (
                  <Badge tone="warning">{t('searchProviders.disabled')}</Badge>
                )}
                <Badge tone={statusTone(provider.status)}>
                  {provider.status === 'ok'
                    ? t('searchProviders.statusOk')
                    : provider.status === 'error'
                      ? t('searchProviders.statusError')
                      : t('searchProviders.statusUnknown')}
                </Badge>
              </div>
              <dl className="mt-3 grid gap-1 text-xs text-ink-muted sm:grid-cols-2">
                <div>
                  <span className="text-ink">{t('searchProviders.baseUrl')}:</span>{' '}
                  {provider.base_url || '—'}
                </div>
                <div>
                  <span className="text-ink">{t('searchProviders.apiKey')}:</span>{' '}
                  {provider.api_key_hint || '—'}
                </div>
                <div>
                  <span className="text-ink">{t('searchProviders.maxResults')}:</span>{' '}
                  {provider.max_results}
                </div>
                <div>
                  <span className="text-ink">{t('searchProviders.timeout')}:</span>{' '}
                  {provider.timeout_seconds}s
                </div>
              </dl>
              {provider.last_error !== null && (
                <p className="mt-2 text-xs text-danger">{provider.last_error}</p>
              )}
              {testResult !== undefined && (
                <p
                  className={`mt-2 text-xs ${testResult.status === 'ok' ? 'text-success' : 'text-danger'}`}
                >
                  {testResult.status === 'ok'
                    ? t('searchProviders.testOk', {
                        count: testResult.result_count,
                      })
                    : t('searchProviders.testFailed', {
                        code: testResult.error_code ?? 'error',
                      })}
                </p>
              )}
              <div className="mt-4 flex flex-wrap gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => void test(provider)}
                >
                  <Zap className="h-3.5 w-3.5" />
                  {t('searchProviders.test')}
                </Button>
                {provider.owned && (
                  <>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => openEdit(provider)}
                    >
                      {t('common.edit')}
                    </Button>
                    {!provider.is_default && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => void makeDefault(provider)}
                      >
                        {t('searchProviders.makeDefault')}
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => void remove(provider)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      {t('common.delete')}
                    </Button>
                  </>
                )}
              </div>
            </div>
          )
        })}

        {error !== null && <p className="text-sm text-danger">{error}</p>}
      </div>

      <Dialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        title={
          editTarget === null
            ? t('searchProviders.add')
            : t('searchProviders.edit', { name: editTarget.name })
        }
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setDialogOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              size="sm"
              disabled={
                saving ||
                (editTarget === null &&
                  form.api_key.trim() === '' &&
                  form.provider !== 'searxng')
              }
              onClick={() => void save()}
            >
              {t('common.save')}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <label className="block text-xs text-ink-muted">
            {t('searchProviders.provider')}
            <select
              className="mt-1 h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink"
              value={form.provider}
              disabled={editTarget !== null}
              onChange={(event) =>
                setForm((prev) => ({
                  ...prev,
                  provider: event.target.value as FormState['provider'],
                }))
              }
            >
              {PROVIDERS.map((provider) => (
                <option key={provider} value={provider}>
                  {provider}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-xs text-ink-muted">
            {t('searchProviders.name')}
            <Input
              className="mt-1"
              value={form.name}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, name: event.target.value }))
              }
              placeholder="Tavily"
            />
          </label>
          <label className="block text-xs text-ink-muted">
            {t('searchProviders.baseUrl')}
            <Input
              className="mt-1"
              value={form.base_url}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, base_url: event.target.value }))
              }
              placeholder={
                form.provider === 'searxng'
                  ? 'https://searx.example.com'
                  : t('searchProviders.baseUrlOptional')
              }
            />
          </label>
          {form.provider !== 'searxng' && (
            <label className="block text-xs text-ink-muted">
              {t('searchProviders.apiKey')}
              <Input
                className="mt-1"
                type="password"
                value={form.api_key}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, api_key: event.target.value }))
                }
                placeholder={
                  editTarget === null
                    ? 'tvly-...'
                    : t('searchProviders.apiKeyKeep')
                }
              />
            </label>
          )}
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-xs text-ink-muted">
              {t('searchProviders.maxResults')}
              <Input
                className="mt-1"
                type="number"
                min="1"
                max="20"
                value={form.max_results}
                onChange={(event) =>
                  setForm((prev) => ({
                    ...prev,
                    max_results: Number(event.target.value),
                  }))
                }
              />
            </label>
            <label className="block text-xs text-ink-muted">
              {t('searchProviders.timeout')}
              <Input
                className="mt-1"
                type="number"
                min="3"
                max="60"
                value={form.timeout_seconds}
                onChange={(event) =>
                  setForm((prev) => ({
                    ...prev,
                    timeout_seconds: Number(event.target.value),
                  }))
                }
              />
            </label>
          </div>
          <label className="flex items-center gap-2 text-xs text-ink">
            <input
              type="checkbox"
              checked={form.shared}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, shared: event.target.checked }))
              }
            />
            {t('searchProviders.sharedHint')}
          </label>
          <label className="flex items-center gap-2 text-xs text-ink">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, enabled: event.target.checked }))
              }
            />
            {t('searchProviders.enabled')}
          </label>
          {error !== null && <p className="text-xs text-danger">{error}</p>}
        </div>
      </Dialog>
    </div>
  )
}