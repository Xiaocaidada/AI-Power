import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, Plug, Settings2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { Input } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { formatDate } from '../../lib/format'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { Plugin, PluginCall } from '../../lib/types'

export function PluginsPage() {
  const { t, language } = useI18n()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [configuring, setConfiguring] = useState<Plugin | null>(null)

  const plugins = useQuery({
    queryKey: ['plugins'],
    queryFn: () => apiRequest<Plugin[]>('/plugins'),
    staleTime: 60_000,
  })
  const calls = useQuery({
    queryKey: ['plugin-calls'],
    queryFn: () => apiRequest<PluginCall[]>('/plugins/calls'),
  })

  const visible = (plugins.data ?? []).filter((plugin) => {
    if (category !== '' && plugin.category !== category) return false
    if (search.trim() !== '') {
      const term = search.trim().toLowerCase()
      return (
        plugin.name.toLowerCase().includes(term) ||
        plugin.description.toLowerCase().includes(term)
      )
    }
    return true
  })
  const categories = [...new Set((plugins.data ?? []).map((plugin) => plugin.category))]

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['plugins'] })
    void queryClient.invalidateQueries({ queryKey: ['plugin-calls'] })
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-4">
        <h1 className="text-lg font-semibold">{t('plugins.title')}</h1>
        <p className="mt-1 text-sm text-ink-muted">{t('plugins.lead')}</p>
      </header>

      <div className="space-y-5 px-6 py-6">
        <div className="flex flex-wrap gap-2">
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t('plugins.search')}
            className="h-9 w-full max-w-xs rounded-lg border border-border bg-surface px-3 text-sm text-ink focus:border-accent focus:outline-none"
          />
          <select
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            className="h-9 rounded-lg border border-border bg-surface px-2 text-sm text-ink"
          >
            <option value="">{t('plugins.allCategories')}</option>
            {categories.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </div>

        {plugins.isLoading && <Spinner />}
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {visible.map((plugin) => (
            <article
              key={plugin.id}
              className="flex flex-col rounded-2xl border border-border bg-surface p-5"
            >
              <div className="flex items-start justify-between gap-2">
                <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent-soft text-accent">
                  <Plug className="h-4 w-4" />
                </span>
                <div className="flex flex-wrap justify-end gap-1">
                  {plugin.sensitive && (
                    <Badge tone="warning">{t('plugins.sensitive')}</Badge>
                  )}
                  <Badge
                    tone={
                      plugin.configured && plugin.config_enabled
                        ? 'success'
                        : plugin.configured
                          ? 'neutral'
                          : 'warning'
                    }
                  >
                    {plugin.configured && plugin.config_enabled
                      ? t('plugins.enabled')
                      : plugin.configured
                        ? t('plugins.disabled')
                        : t('plugins.unconfigured')}
                  </Badge>
                </div>
              </div>
              <h2 className="mt-3 text-base font-semibold text-ink">{plugin.name}</h2>
              <p className="mt-1 line-clamp-2 min-h-10 text-sm leading-5 text-ink-muted">
                {plugin.description || t('plugins.noDescription')}
              </p>
              <div className="mt-2 flex flex-wrap gap-1">
                <Badge tone="neutral">{plugin.category}</Badge>
                <Badge tone="neutral">{plugin.method}</Badge>
                {plugin.credential_hint !== '' && (
                  <Badge tone="neutral">{plugin.credential_hint}</Badge>
                )}
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant={plugin.configured ? 'secondary' : 'primary'}
                  onClick={() => setConfiguring(plugin)}
                >
                  <Settings2 className="h-3 w-3" />
                  {t('plugins.configure')}
                </Button>
                {plugin.docs_url !== '' && (
                  <a
                    href={plugin.docs_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex h-8 items-center gap-1 rounded-lg border border-border px-2.5 text-xs text-ink-muted hover:text-ink"
                  >
                    <ExternalLink className="h-3 w-3" />
                    {t('plugins.docs')}
                  </a>
                )}
              </div>
            </article>
          ))}
        </div>
        {plugins.data !== undefined && visible.length === 0 && (
          <p className="rounded-2xl border border-dashed border-border px-6 py-16 text-center text-sm text-ink-muted">
            {t('plugins.empty')}
          </p>
        )}

        <section className="rounded-2xl border border-border bg-surface">
          <h2 className="border-b border-border px-5 py-3 text-sm font-semibold text-ink">
            {t('plugins.calls')}
          </h2>
          <div className="divide-y divide-border">
            {(calls.data ?? []).slice(0, 20).map((call) => (
              <div
                key={call.id}
                className="flex flex-wrap items-center gap-3 px-5 py-2.5 text-xs"
              >
                <Badge tone={call.status === 'ok' ? 'success' : 'danger'}>
                  {call.status}
                </Badge>
                <span className="min-w-0 flex-1 truncate font-mono text-ink-muted">
                  {call.request_summary}
                </span>
                <span className="text-ink-muted">{call.latency_ms} ms</span>
                <span className="text-ink-muted">
                  {formatDate(call.created_at, language)}
                </span>
              </div>
            ))}
            {calls.data !== undefined && calls.data.length === 0 && (
              <p className="px-5 py-8 text-center text-sm text-ink-muted">
                {t('plugins.noCalls')}
              </p>
            )}
          </div>
        </section>
      </div>

      {configuring !== null && (
        <PluginConfigDialog
          plugin={configuring}
          onClose={() => setConfiguring(null)}
          onSaved={() => {
            setConfiguring(null)
            refresh()
          }}
        />
      )}
    </div>
  )
}

function PluginConfigDialog({
  plugin,
  onClose,
  onSaved,
}: {
  plugin: Plugin
  onClose: () => void
  onSaved: () => void
}) {
  const { t } = useI18n()
  const [enabled, setEnabled] = useState(plugin.config_enabled)
  const [credential, setCredential] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const formId = 'plugin-config-form'

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await apiRequest(`/plugins/${plugin.id}`, {
        method: 'PATCH',
        body: {
          enabled,
          credential: credential === '' ? null : credential,
        },
      })
      onSaved()
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title={t('plugins.configureTitle', { name: plugin.name })}
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button size="sm" type="submit" form={formId} disabled={saving}>
            {t('common.save')}
          </Button>
        </>
      }
    >
      <form id={formId} className="space-y-3" onSubmit={(event) => void submit(event)}>
        <p className="text-xs text-ink-muted">{plugin.description}</p>
        <label className="flex items-center gap-2 text-sm text-ink">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => setEnabled(event.target.checked)}
          />
          {t('plugins.enableForWorkspace')}
        </label>
        {plugin.auth_type === 'bearer' && (
          <label className="block text-xs text-ink-muted">
            {t('plugins.credential')}
            <Input
              className="mt-1"
              type="password"
              value={credential}
              placeholder={plugin.credential_hint || t('plugins.credentialPlaceholder')}
              onChange={(event) => setCredential(event.target.value)}
            />
          </label>
        )}
        {error !== null && <p className="text-xs text-danger">{error}</p>}
      </form>
    </Dialog>
  )
}