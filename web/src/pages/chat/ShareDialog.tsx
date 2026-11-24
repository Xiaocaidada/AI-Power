import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Link2, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { errorTextKey } from '../../lib/errorText'
import { formatTime } from '../../lib/format'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { ConversationShare, ConversationShareCreated } from '../../lib/types'

interface ShareDialogProps {
  open: boolean
  conversationId: string
  onClose: () => void
}

export function ShareDialog({ open, conversationId, onClose }: ShareDialogProps) {
  const { t, language } = useI18n()
  const queryClient = useQueryClient()
  const [createdLink, setCreatedLink] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const shares = useQuery({
    queryKey: ['conversation-shares', conversationId],
    queryFn: () =>
      apiRequest<ConversationShare[]>(`/conversations/${conversationId}/shares`),
    enabled: open,
  })

  const create = async () => {
    setBusy(true)
    setError(null)
    try {
      const result = await apiRequest<ConversationShareCreated>(
        `/conversations/${conversationId}/shares`,
        { method: 'POST', body: { expires_in_days: 7 } },
      )
      const link = `${window.location.origin}/share/${result.token}`
      setCreatedLink(link)
      await navigator.clipboard?.writeText(link).catch(() => undefined)
      await queryClient.invalidateQueries({
        queryKey: ['conversation-shares', conversationId],
      })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(false)
    }
  }

  const revoke = async (share: ConversationShare) => {
    setBusy(true)
    setError(null)
    try {
      await apiRequest(
        `/conversations/${conversationId}/shares/${share.id}`,
        { method: 'DELETE' },
      )
      await queryClient.invalidateQueries({
        queryKey: ['conversation-shares', conversationId],
      })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t('share.title')}
      footer={
        <Button variant="secondary" size="sm" onClick={onClose}>
          {t('common.close')}
        </Button>
      }
    >
      <p className="text-sm text-ink-muted">{t('share.hint')}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" disabled={busy} onClick={() => void create()}>
          <Link2 className="h-3.5 w-3.5" />
          {t('share.create')}
        </Button>
        {createdLink !== '' && (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              void navigator.clipboard?.writeText(createdLink).catch(() => undefined)
            }}
          >
            <Copy className="h-3.5 w-3.5" />
            {t('share.copy')}
          </Button>
        )}
      </div>
      {createdLink !== '' && (
        <p className="mt-2 break-all rounded-lg bg-surface-muted px-2 py-1.5 font-mono text-[11px] text-ink-muted">
          {createdLink}
        </p>
      )}
      <div className="mt-4 space-y-2">
        {(shares.data ?? []).map((share) => (
          <div
            key={share.id}
            className="flex flex-wrap items-center gap-2 rounded-lg border border-border px-3 py-2 text-xs"
          >
            <Badge tone={share.active ? 'success' : 'neutral'}>
              {share.active ? t('share.active') : t('share.revoked')}
            </Badge>
            <span className="text-ink-muted">
              {t('share.createdAt', {
                time: formatTime(share.created_at, language),
              })}
            </span>
            {share.expires_at !== null && (
              <span className="text-ink-muted">
                {t('share.expiresAt', {
                  time: formatTime(share.expires_at, language),
                })}
              </span>
            )}
            {share.active && (
              <Button
                variant="ghost"
                size="sm"
                className="ml-auto"
                disabled={busy}
                onClick={() => void revoke(share)}
              >
                <Trash2 className="h-3.5 w-3.5" />
                {t('share.revoke')}
              </Button>
            )}
          </div>
        ))}
        {shares.data !== undefined && shares.data.length === 0 && (
          <p className="text-xs text-ink-muted">{t('share.empty')}</p>
        )}
      </div>
      {error !== null && <p className="mt-2 text-xs text-danger">{error}</p>}
    </Dialog>
  )
}