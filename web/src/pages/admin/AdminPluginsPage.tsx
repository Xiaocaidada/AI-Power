import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { Navigate } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Input, Textarea } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { Plugin } from '../../lib/types'
import { useAuthStore } from '../../store/auth'

interface Draft {
  slug: string
  name: string
  description: string
  category: string
  docs_url: string
  endpoint_url: string
  method: 'GET' | 'POST'
  auth_type: 'none' | 'bearer'
  sensitive: boolean
  enabled: boolean
  timeout_seconds: string
  parameters: string
}

function draftFrom(plugin: Plugin | null): Draft {
  return {
    slug: plugin?.slug ?? '',
    name: plugin?.name ?? '',
    description: plugin?.description ?? '',
    category: plugin?.category ?? 'general',
    docs_url: plugin?.docs_url ?? '',
    endpoint_url: plugin?.endpoint_url ?? '',
    method: (plugin?.method as 'GET' | 'POST') ?? 'POST',
    auth_type: (plugin?.auth_type as 'none' | 'bearer') ?? 'none',
    sensitive: plugin?.sensitive ?? false,
    enabled: plugin?.enabled ?? true,
    timeout_seconds: String(plugin?.timeout_seconds ?? 10),
    parameters: JSON.stringify(
      plugin?.parameters ?? { type: 'object', properties: {}, required: [] },
      null,
      2,
    ),
  }
}

export function AdminPluginsPage() {
  const { t } = useI18n()
  const user = useAuthStore((state) => state.user)
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<Plugin | null | undefined>()
  const isAdmin = user?.role === 'admin'

  const plugins = useQuery({
    queryKey: ['admin-plugins'],
    queryFn: () => apiRequest<Plugin[]>('/admin/plugins'),
    enabled: isAdmin,
  })

  if (!isAdmin) return <Navigate to="/chat" replace />

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['admin-plugins'] })

  const remove = async (plugin: Plugin) => {
    if (!window.confirm(t('adminPlugins.deleteConfirm'))) return
    await apiRequest(`/admin/plugins/${plugin.id}`, { method: 'DELETE' })
    await refresh()
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-surface px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold">{t('adminPlugins.title')}</h1>
          <p className="mt-1 text-sm text-ink-muted">{t('adminPlugins.lead')}</p>
        </div>
        <Button size="sm" onClick={() => setEditing(null)}>
          <Plus className="h-3.5 w-3.5" />
          {t('adminPlugins.new')}
        </Button>
      </header>

      <div className="space-y-3 px-6 py-6">
        {plugins.isLoading && <Spinner />}
        {(plugins.data ?? []).map((plugin) => (
          <article
            key={plugin.id}
            className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3"
          >
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-ink">{plugin.name}</p>
              <p className="truncate text-xs text-ink-muted">
                {plugin.slug} · {plugin.method} · {plugin.endpoint_url}
              </p>
            </div>
            {plugin.sensitive && <Badge tone="warning">{t('plugins.sensitive')}</Badge>}
            <Badge tone={plugin.enabled ? 'success' : 'neutral'}>
              {plugin.enabled ? t('adminPlugins.enabled') : t('adminPlugins.disabled')}
            </Badge>
            <div className="flex gap-1">
              <Button size="sm" variant="secondary" onClick={() => setEditing(plugin)}>
                <Pencil className="h-3 w-3" />
                {t('common.edit')}
              </Button>
              <Button size="sm" variant="secondary" onClick={() => void remove(plugin)}>
                <Trash2 className="h-3 w-3" />
                {t('common.delete')}
              </Button>
            </div>
          </article>
        ))}
        {plugins.data !== undefined && plugins.data.length === 0 && (
          <p className="rounded-xl border border-dashed border-border px-4 py-10 text-center text-sm text-ink-muted">
            {t('adminPlugins.empty')}
          </p>
        )}
      </div>

      {editing !== undefined && (
        <PluginDefinitionForm
          key={editing === null ? 'new-plugin' : editing.id}
          initial={editing}
          onClose={() => setEditing(undefined)}
          onSaved={() => {
            setEditing(undefined)
            void refresh()
          }}
        />
      )}
    </div>
  )
}

function PluginDefinitionForm({
  initial,
  onClose,
  onSaved,
}: {
  initial: Plugin | null
  onClose: () => void
  onSaved: () => void
}) {
  const { t } = useI18n()
  const [draft, setDraft] = useState<Draft>(() => draftFrom(initial))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const update = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }))

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    let parameters: unknown
    try {
      parameters = JSON.parse(draft.parameters)
    } catch {
      setError(t('adminPlugins.invalidJson'))
      return
    }
    setSaving(true)
    setError(null)
    const body = {
      slug: draft.slug,
      name: draft.name,
      description: draft.description,
      category: draft.category,
      docs_url: draft.docs_url,
      endpoint_url: draft.endpoint_url,
      method: draft.method,
      auth_type: draft.auth_type,
      sensitive: draft.sensitive,
      enabled: draft.enabled,
      timeout_seconds: Number(draft.timeout_seconds) || 10,
      parameters,
    }
    try {
      if (initial === null) {
        await apiRequest('/admin/plugins', { method: 'POST', body })
      } else {
        const updateBody: Record<string, unknown> = { ...body }
        delete updateBody.slug
        await apiRequest(`/admin/plugins/${initial.id}`, {
          method: 'PATCH',
          body: updateBody,
        })
      }
      onSaved()
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/40 p-4"
      onClick={onClose}
    >
      <form
        className="mt-10 w-full max-w-2xl rounded-2xl border border-border bg-surface p-6 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
        onSubmit={(event) => void submit(event)}
      >
        <h2 className="text-base font-semibold text-ink">
          {initial === null ? t('adminPlugins.new') : t('adminPlugins.edit')}
        </h2>
        <div className="mt-4 space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t('adminPlugins.slug')}>
              <Input
                required
                disabled={initial !== null}
                value={draft.slug}
                onChange={(event) => update('slug', event.target.value)}
              />
            </Field>
            <Field label={t('adminPlugins.name')}>
              <Input
                required
                value={draft.name}
                onChange={(event) => update('name', event.target.value)}
              />
            </Field>
          </div>
          <Field label={t('adminPlugins.description')}>
            <Input
              value={draft.description}
              onChange={(event) => update('description', event.target.value)}
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t('adminPlugins.category')}>
              <Input
                value={draft.category}
                onChange={(event) => update('category', event.target.value)}
              />
            </Field>
            <Field label={t('adminPlugins.docsUrl')}>
              <Input
                value={draft.docs_url}
                onChange={(event) => update('docs_url', event.target.value)}
              />
            </Field>
          </div>
          <Field label={t('adminPlugins.endpoint')}>
            <Input
              required
              value={draft.endpoint_url}
              onChange={(event) => update('endpoint_url', event.target.value)}
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label={t('adminPlugins.method')}>
              <select
                className="h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink"
                value={draft.method}
                onChange={(event) => update('method', event.target.value as 'GET' | 'POST')}
              >
                <option value="POST">POST</option>
                <option value="GET">GET</option>
              </select>
            </Field>
            <Field label={t('adminPlugins.auth')}>
              <select
                className="h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink"
                value={draft.auth_type}
                onChange={(event) =>
                  update('auth_type', event.target.value as 'none' | 'bearer')
                }
              >
                <option value="none">none</option>
                <option value="bearer">bearer</option>
              </select>
            </Field>
            <Field label={t('adminPlugins.timeout')}>
              <Input
                type="number"
                min="1"
                max="30"
                value={draft.timeout_seconds}
                onChange={(event) => update('timeout_seconds', event.target.value)}
              />
            </Field>
          </div>
          <Field label={t('adminPlugins.parameters')}>
            <Textarea
              className="min-h-40 font-mono text-xs"
              value={draft.parameters}
              onChange={(event) => update('parameters', event.target.value)}
            />
          </Field>
          <div className="flex flex-wrap gap-4 text-sm text-ink">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={draft.sensitive}
                onChange={(event) => update('sensitive', event.target.checked)}
              />
              {t('adminPlugins.sensitive')}
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={draft.enabled}
                onChange={(event) => update('enabled', event.target.checked)}
              />
              {t('adminPlugins.enabled')}
            </label>
          </div>
        </div>
        {error !== null && <p className="mt-3 text-xs text-danger">{error}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <Button type="button" variant="secondary" size="sm" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" size="sm" disabled={saving}>
            {t('common.save')}
          </Button>
        </div>
      </form>
    </div>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="block">
      <span className="mb-1 block text-xs text-ink-muted">{label}</span>
      {children}
    </div>
  )
}