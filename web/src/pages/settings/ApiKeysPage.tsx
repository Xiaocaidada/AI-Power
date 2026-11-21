import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Copy, KeyRound, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { EmptyState } from '../../components/ui/empty-state'
import { Input } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { formatDate } from '../../lib/format'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { ApiKeyCreated, ApiKeyRecord } from '../../lib/types'

const SCOPES = ['chat:write', 'kb:read'] as const

export function ApiKeysPage() {
  const { t, language } = useI18n()
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [name, setName] = useState('')
  const [scopes, setScopes] = useState<string[]>([...SCOPES])
  const [revealed, setRevealed] = useState<ApiKeyCreated | null>(null)
  const [revokeTarget, setRevokeTarget] = useState<ApiKeyRecord | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)

  const keys = useQuery({
    queryKey: ['api-keys'],
    queryFn: () => apiRequest<ApiKeyRecord[]>('/api-keys'),
  })

  const toggleScope = (scope: string) => {
    setScopes((previous) =>
      previous.includes(scope)
        ? previous.filter((item) => item !== scope)
        : [...previous, scope],
    )
  }

  const create = async () => {
    if (name.trim() === '' || scopes.length === 0) return
    setBusy(true)
    setError(null)
    try {
      const created = await apiRequest<ApiKeyCreated>('/api-keys', {
        method: 'POST',
        body: { name: name.trim(), scopes },
      })
      await queryClient.invalidateQueries({ queryKey: ['api-keys'] })
      setCreateOpen(false)
      setName('')
      setScopes([...SCOPES])
      setCopied(false)
      setRevealed(created)
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(false)
    }
  }

  const revoke = async () => {
    if (revokeTarget === null) return
    try {
      await apiRequest(`/api-keys/${revokeTarget.id}`, { method: 'DELETE' })
      await queryClient.invalidateQueries({ queryKey: ['api-keys'] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setRevokeTarget(null)
    }
  }

  const copyKey = async () => {
    if (revealed === null) return
    try {
      await navigator.clipboard.writeText(revealed.key)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }

  const rotationThresholdMs = 90 * 24 * 3600 * 1000
  const staleKeys = (keys.data ?? []).filter(
    (key) =>
      key.revoked_at === null &&
      Date.now() - new Date(key.created_at).getTime() > rotationThresholdMs,
  )

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="flex items-center justify-between gap-4 border-b border-border bg-surface px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold">{t('apiKeys.title')}</h1>
          <p className="mt-1 text-sm text-ink-muted">{t('apiKeys.lead')}</p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="h-4 w-4" />
          {t('apiKeys.create')}
        </Button>
      </header>

      <div className="space-y-4 px-6 py-6">
        {error !== null && (
          <p role="alert" className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </p>
        )}

        {staleKeys.length > 0 && (
          <p role="status" className="rounded-lg bg-warning/10 px-3 py-2 text-sm text-warning">
            {t('apiKeys.rotationHint', { count: staleKeys.length })}
          </p>
        )}

        {keys.isLoading && (
          <div className="flex items-center gap-2 text-sm text-ink-muted">
            <Spinner />
            {t('common.loading')}
          </div>
        )}

        {keys.isError && (
          <div className="flex items-center gap-3 text-sm text-ink-muted">
            {t('errors.generic')}
            <Button variant="secondary" size="sm" onClick={() => void keys.refetch()}>
              {t('common.retry')}
            </Button>
          </div>
        )}

        {keys.data !== undefined && keys.data.length === 0 && (
          <EmptyState title={t('apiKeys.empty')} description={t('apiKeys.emptyLead')}>
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" />
              {t('apiKeys.create')}
            </Button>
          </EmptyState>
        )}

        {keys.data !== undefined && keys.data.length > 0 && (
          <div className="overflow-x-auto rounded-card border border-border bg-surface">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead className="border-b border-border text-xs uppercase tracking-wide text-ink-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">{t('apiKeys.name')}</th>
                  <th className="px-3 py-2 font-medium">{t('apiKeys.prefix')}</th>
                  <th className="px-3 py-2 font-medium">{t('apiKeys.scopes')}</th>
                  <th className="px-3 py-2 font-medium">{t('apiKeys.created')}</th>
                  <th className="px-3 py-2 font-medium">{t('apiKeys.lastUsed')}</th>
                  <th className="px-3 py-2 font-medium">{t('apiKeys.status')}</th>
                  <th className="px-3 py-2 text-right font-medium" />
                </tr>
              </thead>
              <tbody>
                {keys.data.map((key) => {
                  const revoked = key.revoked_at !== null
                  return (
                    <tr
                      key={key.id}
                      className={
                        revoked
                          ? 'border-b border-border text-ink-muted opacity-60 last:border-0'
                          : 'border-b border-border last:border-0'
                      }
                    >
                      <td className="px-3 py-3">
                        <span className="flex items-center gap-2">
                          <KeyRound className="h-4 w-4 text-ink-muted" />
                          <span className="font-medium text-ink">{key.name}</span>
                        </span>
                      </td>
                      <td className="px-3 py-3 font-mono text-xs">{key.prefix}</td>
                      <td className="px-3 py-3">
                        <span className="flex flex-wrap gap-1">
                          {key.scopes.map((scope) => (
                            <Badge key={scope} tone="accent">
                              {scope}
                            </Badge>
                          ))}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-xs text-ink-muted">
                        {formatDate(key.created_at, language)}
                      </td>
                      <td className="px-3 py-3 text-xs text-ink-muted">
                        {key.last_used_at !== null
                          ? formatDate(key.last_used_at, language)
                          : t('apiKeys.never')}
                      </td>
                      <td className="px-3 py-3">
                        <Badge tone={revoked ? 'neutral' : 'success'}>
                          {revoked ? t('apiKeys.revoked') : t('apiKeys.active')}
                        </Badge>
                      </td>
                      <td className="px-3 py-3 text-right">
                        {!revoked && (
                          <Button variant="ghost" size="sm" onClick={() => setRevokeTarget(key)}>
                            <Trash2 className="h-4 w-4" />
                            {t('apiKeys.revoke')}
                          </Button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <Dialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title={t('apiKeys.createTitle')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setCreateOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              size="sm"
              disabled={busy || name.trim() === '' || scopes.length === 0}
              onClick={() => void create()}
            >
              {busy && <Spinner />}
              {t('apiKeys.create')}
            </Button>
          </>
        }
      >
        <label className="block text-sm">
          <span className="mb-1.5 block text-ink-muted">{t('apiKeys.name')}</span>
          <Input
            autoFocus
            value={name}
            maxLength={100}
            placeholder={t('apiKeys.namePlaceholder')}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <fieldset className="mt-4">
          <legend className="mb-1.5 text-sm text-ink-muted">{t('apiKeys.scopes')}</legend>
          <div className="space-y-2">
            {SCOPES.map((scope) => (
              <label key={scope} className="flex items-start gap-2 text-sm text-ink">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={scopes.includes(scope)}
                  onChange={() => toggleScope(scope)}
                />
                {scope === 'chat:write' ? t('apiKeys.scopeChat') : t('apiKeys.scopeKb')}
              </label>
            ))}
          </div>
        </fieldset>
      </Dialog>

      <Dialog
        open={revealed !== null}
        onClose={() => setRevealed(null)}
        dismissible={false}
        title={t('apiKeys.revealTitle')}
        footer={
          <Button size="sm" onClick={() => setRevealed(null)}>
            {t('apiKeys.saved')}
          </Button>
        }
      >
        <p>{t('apiKeys.revealHint')}</p>
        <div className="mt-3 flex items-center gap-2 rounded-lg border border-border bg-surface-muted p-3">
          <code className="min-w-0 flex-1 break-all font-mono text-xs text-ink">
            {revealed?.key ?? ''}
          </code>
          <Button variant="secondary" size="sm" onClick={() => void copyKey()}>
            {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
            {copied ? t('common.copied') : t('common.copy')}
          </Button>
        </div>
        <p className="mt-3 text-sm font-medium text-danger">{t('apiKeys.revealWarning')}</p>
      </Dialog>

      <Dialog
        open={revokeTarget !== null}
        onClose={() => setRevokeTarget(null)}
        title={t('apiKeys.revoke')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setRevokeTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button variant="danger" size="sm" onClick={() => void revoke()}>
              {t('common.confirm')}
            </Button>
          </>
        }
      >
        <p>{t('apiKeys.revokeConfirm', { name: revokeTarget?.name ?? '' })}</p>
        <p className="mt-2 text-xs">{t('apiKeys.revokeHint')}</p>
      </Dialog>
    </div>
  )
}