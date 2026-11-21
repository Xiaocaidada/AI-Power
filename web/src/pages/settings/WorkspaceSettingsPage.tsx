import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'

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
import type { WorkspaceItem, WorkspaceMember } from '../../lib/types'
import { getActiveWorkspaceId, setActiveWorkspaceId } from '../../lib/workspace'

export function WorkspaceSettingsPage() {
  const { t, language } = useI18n()
  const queryClient = useQueryClient()
  const [activeId, setActiveId] = useState<string | null>(getActiveWorkspaceId())
  const [createOpen, setCreateOpen] = useState(false)
  const [name, setName] = useState('')
  const [inviteEmail, setInviteEmail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const workspaces = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => apiRequest<WorkspaceItem[]>('/workspaces'),
  })
  const current = workspaces.data?.find((workspace) => workspace.id === activeId)
  const members = useQuery({
    queryKey: ['members', activeId],
    queryFn: () => apiRequest<WorkspaceMember[]>(`/workspaces/${activeId}/members`),
    enabled: activeId !== null,
  })

  useEffect(() => {
    if (workspaces.data === undefined || workspaces.data.length === 0) return
    if (activeId !== null && workspaces.data.some((item) => item.id === activeId)) return
    const preferred = workspaces.data.find((item) => item.is_personal) ?? workspaces.data[0]
    setActiveId(preferred.id)
    setActiveWorkspaceId(preferred.id)
  }, [workspaces.data, activeId])

  const switchWorkspace = (workspaceId: string) => {
    setActiveId(workspaceId)
    setActiveWorkspaceId(workspaceId)
    queryClient.clear()
    queryClient.invalidateQueries({ queryKey: ['workspaces'] })
  }

  const create = async () => {
    if (name.trim() === '') return
    setBusy(true)
    setError(null)
    try {
      const workspace = await apiRequest<WorkspaceItem>('/workspaces', {
        method: 'POST',
        body: { name: name.trim() },
      })
      await queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      switchWorkspace(workspace.id)
      setCreateOpen(false)
      setName('')
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(false)
    }
  }

  const invite = async () => {
    if (activeId === null || inviteEmail.trim() === '') return
    setBusy(true)
    setError(null)
    try {
      await apiRequest(`/workspaces/${activeId}/members`, {
        method: 'POST',
        body: { email: inviteEmail.trim() },
      })
      setInviteEmail('')
      await queryClient.invalidateQueries({ queryKey: ['members', activeId] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(false)
    }
  }

  const remove = async (userId: string) => {
    if (activeId === null) return
    setError(null)
    try {
      await apiRequest(`/workspaces/${activeId}/members/${userId}`, { method: 'DELETE' })
      await queryClient.invalidateQueries({ queryKey: ['members', activeId] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    }
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="flex items-center justify-between gap-4 border-b border-border bg-surface px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold">{t('workspace.current')}</h1>
          <p className="mt-1 text-sm text-ink-muted">{t('workspace.members')}</p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="h-4 w-4" />
          {t('workspace.create')}
        </Button>
      </header>

      <div className="space-y-5 px-6 py-6">
        {error !== null && (
          <p role="alert" className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </p>
        )}

        <div className="flex flex-wrap gap-2">
          {(workspaces.data ?? []).map((workspace) => (
            <Button
              key={workspace.id}
              size="sm"
              variant={workspace.id === activeId ? 'primary' : 'secondary'}
              onClick={() => switchWorkspace(workspace.id)}
            >
              {workspace.is_personal ? t('workspace.personal') : workspace.name}
            </Button>
          ))}
        </div>

        {current !== undefined && (
          <section className="rounded-card border border-border bg-surface p-4 text-sm">
            <p className="font-medium text-ink">
              {current.is_personal ? t('workspace.personal') : current.name}
            </p>
            <p className="mt-1 text-xs text-ink-muted">
              {t('workspace.plan')}: {current.plan} ·{' '}
              {t('workspace.created', { date: formatDate(current.created_at, language) })}
            </p>
          </section>
        )}

        <section className="rounded-card border border-border bg-surface p-4">
          <div className="mb-3 flex flex-wrap items-end gap-2">
            <label className="flex-1 text-sm">
              <span className="mb-1.5 block text-ink-muted">{t('workspace.inviteEmail')}</span>
              <Input
                type="email"
                value={inviteEmail}
                placeholder="teammate@example.com"
                onChange={(event) => setInviteEmail(event.target.value)}
              />
            </label>
            <Button
              size="sm"
              disabled={busy || inviteEmail.trim() === '' || current?.role !== 'owner'}
              onClick={() => void invite()}
            >
              {t('workspace.inviteAction')}
            </Button>
          </div>

          {members.isLoading && <Spinner />}
          {members.data !== undefined && members.data.length === 0 && (
            <EmptyState title={t('workspace.emptyMembers')} />
          )}
          <ul className="divide-y divide-border">
            {members.data?.map((member) => (
              <li key={member.user_id} className="flex items-center justify-between gap-3 py-2">
                <div className="min-w-0">
                  <p className="truncate text-sm text-ink">{member.email}</p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge tone={member.role === 'owner' ? 'accent' : 'neutral'}>
                    {member.role === 'owner'
                      ? t('workspace.roleOwner')
                      : t('workspace.roleMember')}
                  </Badge>
                  {current?.role === 'owner' && member.role !== 'owner' && (
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={t('workspace.remove')}
                      onClick={() => void remove(member.user_id)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <Dialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title={t('workspace.createTitle')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setCreateOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button size="sm" disabled={busy || name.trim() === ''} onClick={() => void create()}>
              {busy && <Spinner />}
              {t('workspace.createAction')}
            </Button>
          </>
        }
      >
        <label className="block text-sm">
          <span className="mb-1.5 block text-ink-muted">{t('workspace.name')}</span>
          <Input
            autoFocus
            value={name}
            maxLength={120}
            placeholder={t('workspace.namePlaceholder')}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
      </Dialog>
    </div>
  )
}