import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Plus, RefreshCw, Trash2, Webhook as WebhookIcon } from 'lucide-react'
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
import type { Webhook, WebhookCreated, WebhookDelivery } from '../../lib/types'

const EVENTS = [
  { id: 'message.completed', labelKey: 'webhooks.eventMessage' },
  { id: 'document.ready', labelKey: 'webhooks.eventDocumentReady' },
  { id: 'document.failed', labelKey: 'webhooks.eventDocumentFailed' },
  { id: 'workflow.completed', labelKey: 'webhooks.eventWorkflow' },
  { id: 'collaboration.completed', labelKey: 'webhooks.eventCollaboration' },
  { id: 'budget.exceeded', labelKey: 'webhooks.eventBudget' },
] as const

function deliveryTone(status: string): 'success' | 'danger' | 'accent' | 'neutral' {
  if (status === 'delivered') return 'success'
  if (status === 'dead') return 'danger'
  if (status === 'pending' || status === 'failed') return 'accent'
  return 'neutral'
}

export function WebhooksPage() {
  const { t, language } = useI18n()
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [url, setUrl] = useState('')
  const [events, setEvents] = useState<string[]>([
    'message.completed',
    'document.ready',
    'document.failed',
  ])
  const [createdSecret, setCreatedSecret] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<Webhook | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const hooks = useQuery({
    queryKey: ['webhooks'],
    queryFn: () => apiRequest<Webhook[]>('/webhooks'),
  })
  const deliveries = useQuery({
    queryKey: ['webhook-deliveries', selectedId],
    queryFn: () =>
      apiRequest<WebhookDelivery[]>(`/webhooks/${selectedId}/deliveries?limit=50`),
    enabled: selectedId !== '',
    refetchInterval: 5000,
  })

  const create = async () => {
    if (url.trim() === '' || events.length === 0) {
      setError(t('webhooks.required'))
      return
    }
    setBusy(true)
    setError(null)
    try {
      const created = await apiRequest<WebhookCreated>('/webhooks', {
        method: 'POST',
        body: { url: url.trim(), events },
      })
      await queryClient.invalidateQueries({ queryKey: ['webhooks'] })
      setCreateOpen(false)
      setUrl('')
      setCreatedSecret(created.secret)
      setSelectedId(created.id)
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(false)
    }
  }

  const toggle = async (hook: Webhook) => {
    try {
      await apiRequest(`/webhooks/${hook.id}`, {
        method: 'PATCH',
        body: { active: !hook.active },
      })
      await queryClient.invalidateQueries({ queryKey: ['webhooks'] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    }
  }

  const remove = async () => {
    if (deleteTarget === null) return
    try {
      await apiRequest(`/webhooks/${deleteTarget.id}`, { method: 'DELETE' })
      await queryClient.invalidateQueries({ queryKey: ['webhooks'] })
      if (selectedId === deleteTarget.id) setSelectedId('')
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setDeleteTarget(null)
    }
  }

  const replay = async (delivery: WebhookDelivery) => {
    try {
      await apiRequest(`/webhooks/${selectedId}/deliveries/${delivery.id}/replay`, {
        method: 'POST',
      })
      await queryClient.invalidateQueries({ queryKey: ['webhook-deliveries', selectedId] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    }
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-border bg-surface px-6 py-4">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            <WebhookIcon className="h-5 w-5 text-accent" />
            {t('webhooks.title')}
          </h1>
          <p className="mt-1 text-sm text-ink-muted">{t('webhooks.lead')}</p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="h-4 w-4" />
          {t('webhooks.create')}
        </Button>
      </header>

      <div className="space-y-5 px-6 py-6">
        {error !== null && (
          <p role="alert" className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </p>
        )}

        {hooks.isLoading && (
          <div className="flex items-center gap-2 text-sm text-ink-muted">
            <Spinner />
            {t('common.loading')}
          </div>
        )}

        {hooks.isError && (
          <p role="alert" className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
            {t(errorTextKey(hooks.error))}
          </p>
        )}

        {hooks.isSuccess && (hooks.data?.length ?? 0) === 0 && (
          <EmptyState title={t('webhooks.empty')} description={t('webhooks.emptyLead')}>
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" />
              {t('webhooks.create')}
            </Button>
          </EmptyState>
        )}

        <div className="space-y-3">
          {hooks.data?.map((hook) => (
            <article key={hook.id} className="rounded-card border border-border bg-surface p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate font-mono text-sm text-ink">{hook.url}</span>
                    <Badge tone={hook.active ? 'success' : 'neutral'}>
                      {hook.active ? t('webhooks.active') : t('webhooks.paused')}
                    </Badge>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {hook.events.map((event) => (
                      <span
                        key={event}
                        className="rounded-full bg-surface-muted px-2 py-0.5 text-[11px] text-ink-muted"
                      >
                        {event}
                      </span>
                    ))}
                  </div>
                  <p className="mt-2 text-xs text-ink-muted">
                    {t('webhooks.created', {
                      date: formatDate(hook.created_at, language),
                    })}
                  </p>
                </div>
                <div className="flex flex-wrap gap-1">
                  <Button variant="secondary" size="sm" onClick={() => void toggle(hook)}>
                    {hook.active ? t('webhooks.pause') : t('webhooks.activate')}
                  </Button>
                  <Button
                    variant={selectedId === hook.id ? 'primary' : 'secondary'}
                    size="sm"
                    onClick={() => setSelectedId(selectedId === hook.id ? '' : hook.id)}
                  >
                    {t('webhooks.deliveries')}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={t('common.delete')}
                    onClick={() => setDeleteTarget(hook)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>

              {selectedId === hook.id && (
                <div className="mt-4 border-t border-border pt-3">
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-xs font-medium text-ink-muted">
                      {t('webhooks.deliveryLog')}
                    </p>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() =>
                        void queryClient.invalidateQueries({
                          queryKey: ['webhook-deliveries', selectedId],
                        })
                      }
                    >
                      <RefreshCw className="h-3 w-3" />
                      {t('common.retry')}
                    </Button>
                  </div>
                  {deliveries.isLoading && (
                    <div className="flex items-center gap-2 text-xs text-ink-muted">
                      <Spinner />
                      {t('common.loading')}
                    </div>
                  )}
                  {deliveries.isSuccess && (deliveries.data?.length ?? 0) === 0 && (
                    <p className="text-xs text-ink-muted">{t('webhooks.noDeliveries')}</p>
                  )}
                  {deliveries.data !== undefined && deliveries.data.length > 0 && (
                    <div className="overflow-x-auto">
                      <table className="w-full min-w-[720px] text-left text-xs">
                        <thead className="text-ink-muted">
                          <tr>
                            <th className="px-2 py-1 font-medium">{t('webhooks.event')}</th>
                            <th className="px-2 py-1 font-medium">{t('webhooks.status')}</th>
                            <th className="px-2 py-1 font-medium">{t('webhooks.attempts')}</th>
                            <th className="px-2 py-1 font-medium">{t('webhooks.response')}</th>
                            <th className="px-2 py-1 font-medium">{t('webhooks.error')}</th>
                            <th className="px-2 py-1 text-right font-medium">
                              {t('webhooks.actions')}
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {deliveries.data.map((delivery) => (
                            <tr key={delivery.id} className="border-t border-border">
                              <td className="px-2 py-2 font-mono">{delivery.event}</td>
                              <td className="px-2 py-2">
                                <Badge tone={deliveryTone(delivery.status)}>
                                  {delivery.status}
                                </Badge>
                              </td>
                              <td className="px-2 py-2 text-ink-muted">{delivery.attempts}</td>
                              <td className="px-2 py-2 text-ink-muted">
                                {delivery.response_status ?? '—'}
                              </td>
                              <td className="max-w-[220px] truncate px-2 py-2 text-danger">
                                {delivery.error ?? '—'}
                              </td>
                              <td className="px-2 py-2 text-right">
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => void replay(delivery)}
                                >
                                  {t('webhooks.replay')}
                                </Button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </article>
          ))}
        </div>
      </div>

      <Dialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title={t('webhooks.create')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setCreateOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button size="sm" disabled={busy} onClick={() => void create()}>
              {busy && <Spinner />}
              {t('webhooks.createAction')}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <label className="block text-xs text-ink-muted">
            <span className="mb-1 block">{t('webhooks.url')}</span>
            <Input
              value={url}
              placeholder="https://example.com/webhook"
              onChange={(event) => setUrl(event.target.value)}
            />
          </label>
          <div>
            <p className="mb-1 text-xs text-ink-muted">{t('webhooks.events')}</p>
            <div className="space-y-1.5">
              {EVENTS.map((event) => (
                <label key={event.id} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={events.includes(event.id)}
                    onChange={(checkbox) =>
                      setEvents((previous) =>
                        checkbox.target.checked
                          ? [...previous, event.id]
                          : previous.filter((item) => item !== event.id),
                      )
                    }
                  />
                  <span className="font-mono text-xs">{event.id}</span>
                  <span className="text-xs text-ink-muted">{t(event.labelKey)}</span>
                </label>
              ))}
            </div>
          </div>
          <p className="text-xs text-ink-muted">{t('webhooks.urlHint')}</p>
        </div>
      </Dialog>

      <Dialog
        open={createdSecret !== null}
        onClose={() => setCreatedSecret(null)}
        title={t('webhooks.secretTitle')}
        footer={
          <Button size="sm" onClick={() => setCreatedSecret(null)}>
            {t('common.close')}
          </Button>
        }
      >
        <p className="text-sm text-ink">{t('webhooks.secretLead')}</p>
        <div className="mt-3 flex items-center gap-2 rounded-lg bg-surface-muted px-3 py-2">
          <code className="min-w-0 flex-1 break-all font-mono text-xs">
            {createdSecret ?? ''}
          </code>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              if (createdSecret !== null) void navigator.clipboard.writeText(createdSecret)
            }}
          >
            <Copy className="h-3 w-3" />
            {t('common.copy')}
          </Button>
        </div>
        <p className="mt-3 text-xs text-danger">{t('webhooks.secretWarning')}</p>
      </Dialog>

      <Dialog
        open={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        title={t('webhooks.deleteTitle')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setDeleteTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button variant="danger" size="sm" onClick={() => void remove()}>
              {t('common.confirm')}
            </Button>
          </>
        }
      >
        <p>{t('webhooks.deleteConfirm', { url: deleteTarget?.url ?? '' })}</p>
      </Dialog>
    </div>
  )
}