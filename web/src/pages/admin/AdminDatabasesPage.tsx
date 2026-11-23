import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Database, Pencil, Plus, PlugZap, Trash2 } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { Navigate } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { Input, Textarea } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { DatabaseConnection } from '../../lib/types'
import { useAuthStore } from '../../store/auth'

interface Draft {
  name: string
  description: string
  dsn: string
  enabled: boolean
  maxRows: number
  timeout: number
}

function draftFrom(connection: DatabaseConnection | null): Draft {
  return {
    name: connection?.name ?? '',
    description: connection?.description ?? '',
    dsn: '',
    enabled: connection?.enabled ?? true,
    maxRows: connection?.max_rows ?? 100,
    timeout: connection?.timeout_seconds ?? 15,
  }
}

export function AdminDatabasesPage() {
  const { t } = useI18n()
  const user = useAuthStore((state) => state.user)
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<DatabaseConnection | null | undefined>()
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState<string | null>(null)

  const isAdmin = user?.role === 'admin'
  const connections = useQuery({
    queryKey: ['admin-database-connections'],
    queryFn: () => apiRequest<DatabaseConnection[]>('/admin/database-connections'),
    enabled: isAdmin,
  })

  if (!isAdmin) return <Navigate to="/chat" replace />

  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ['admin-database-connections'] })

  const remove = async (connection: DatabaseConnection) => {
    if (!window.confirm(t('admin.dbDeleteConfirm'))) return
    await apiRequest(`/admin/database-connections/${connection.id}`, {
      method: 'DELETE',
    })
    await refresh()
  }

  const test = async (connection: DatabaseConnection) => {
    setBusy(connection.id)
    setMessage(null)
    try {
      const result = await apiRequest<{ ok: boolean; value: number }>(
        `/admin/database-connections/${connection.id}/test`,
        { method: 'POST' },
      )
      setMessage(`${connection.name}: SELECT ${result.value} ✓`)
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : t('errors.generic'))
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-surface px-6 py-4">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            <Database className="h-4 w-4 text-accent" />
            {t('admin.dbTitle')}
          </h1>
          <p className="mt-1 text-sm text-ink-muted">{t('admin.dbLead')}</p>
        </div>
        <Button size="sm" onClick={() => setEditing(null)}>
          <Plus className="h-3.5 w-3.5" />
          {t('admin.dbNew')}
        </Button>
      </header>

      <div className="space-y-3 px-6 py-6">
        {connections.isLoading && <Spinner />}
        {(connections.data ?? []).map((connection) => (
          <article
            key={connection.id}
            className="rounded-2xl border border-border bg-surface p-5"
          >
            <div className="flex flex-wrap items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-sm font-medium text-ink">{connection.name}</p>
                  <Badge tone={connection.enabled ? 'success' : 'neutral'}>
                    {connection.enabled ? t('admin.dbEnabled') : t('admin.dbDisabled')}
                  </Badge>
                  <Badge tone="neutral">
                    {t('admin.dbMaxRows', { count: connection.max_rows })}
                  </Badge>
                </div>
                <p className="mt-1 text-xs text-ink-muted">{connection.description}</p>
                <p className="mt-1 break-all font-mono text-[10px] text-ink-muted">
                  {connection.dsn_hint}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={busy === connection.id}
                  onClick={() => void test(connection)}
                >
                  <PlugZap className="h-3 w-3" />
                  {t('admin.dbTest')}
                </Button>
                <Button size="sm" variant="secondary" onClick={() => setEditing(connection)}>
                  <Pencil className="h-3 w-3" />
                  {t('common.edit')}
                </Button>
                <Button size="sm" variant="secondary" onClick={() => void remove(connection)}>
                  <Trash2 className="h-3 w-3" />
                  {t('common.delete')}
                </Button>
              </div>
            </div>
          </article>
        ))}
        {connections.data !== undefined && connections.data.length === 0 && (
          <p className="rounded-2xl border border-dashed border-border px-6 py-16 text-center text-sm text-ink-muted">
            {t('admin.dbEmpty')}
          </p>
        )}
        {message !== null && <p className="text-xs text-ink-muted">{message}</p>}
      </div>

      <ConnectionForm
        key={editing === null ? 'new-db' : (editing?.id ?? 'closed')}
        open={editing !== undefined}
        initial={editing ?? null}
        onClose={() => setEditing(undefined)}
        onSaved={() => {
          setEditing(undefined)
          void refresh()
        }}
      />
    </div>
  )
}

function ConnectionForm({
  open,
  initial,
  onClose,
  onSaved,
}: {
  open: boolean
  initial: DatabaseConnection | null
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
    setSaving(true)
    setError(null)
    const body: Record<string, unknown> = {
      name: draft.name,
      description: draft.description,
      enabled: draft.enabled,
      max_rows: draft.maxRows,
      timeout_seconds: draft.timeout,
    }
    if (draft.dsn !== '') body.dsn = draft.dsn
    try {
      if (initial === null) {
        await apiRequest('/admin/database-connections', { method: 'POST', body })
      } else {
        await apiRequest(`/admin/database-connections/${initial.id}`, {
          method: 'PATCH',
          body,
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
    <Dialog
      open={open}
      onClose={onClose}
      title={initial === null ? t('admin.dbNew') : t('admin.dbEdit')}
      footer={
        <>
          <Button size="sm" variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button size="sm" type="submit" form="db-form" disabled={saving}>
            {t('common.save')}
          </Button>
        </>
      }
    >
      <form id="db-form" className="space-y-3" onSubmit={(event) => void submit(event)}>
        <Field label={t('admin.dbName')}>
          <Input
            required
            value={draft.name}
            onChange={(event) => update('name', event.target.value)}
          />
        </Field>
        <Field label={t('admin.dbDescription')}>
          <Textarea
            className="min-h-16"
            value={draft.description}
            onChange={(event) => update('description', event.target.value)}
          />
        </Field>
        <Field label={t('admin.dbDsn')}>
          <Input
            required={initial === null}
            value={draft.dsn}
            onChange={(event) => update('dsn', event.target.value)}
            placeholder={
              initial === null
                ? 'postgresql+asyncpg://user:password@host:5432/db'
                : t('admin.dbDsnKeep')
            }
          />
        </Field>
        <p className="-mt-2 text-[10px] text-ink-muted">{t('admin.dbDsnHint')}</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t('admin.dbMaxRowsLabel')}>
            <Input
              type="number"
              min={1}
              max={500}
              value={draft.maxRows}
              onChange={(event) => update('maxRows', Number(event.target.value))}
            />
          </Field>
          <Field label={t('admin.dbTimeout')}>
            <Input
              type="number"
              min={1}
              max={120}
              value={draft.timeout}
              onChange={(event) => update('timeout', Number(event.target.value))}
            />
          </Field>
        </div>
        <label className="flex items-center gap-2 text-xs text-ink">
          <input
            type="checkbox"
            checked={draft.enabled}
            onChange={(event) => update('enabled', event.target.checked)}
          />
          {t('admin.dbEnabled')}
        </label>
        {error !== null && <p className="text-xs text-danger">{error}</p>}
      </form>
    </Dialog>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block text-xs text-ink-muted">
      <span className="mb-1 block">{label}</span>
      {children}
    </label>
  )
}