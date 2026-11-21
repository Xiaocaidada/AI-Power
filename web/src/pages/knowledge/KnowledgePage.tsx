import { useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { EmptyState } from '../../components/ui/empty-state'
import { Input } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { formatDate } from '../../lib/format'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { KnowledgeBase } from '../../lib/types'

export function KnowledgePage() {
  const { t, language } = useI18n()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<KnowledgeBase | null>(null)

  const kbs = useQuery({
    queryKey: ['kbs'],
    queryFn: () => apiRequest<KnowledgeBase[]>('/knowledge-bases'),
  })

  const create = async () => {
    const trimmed = name.trim()
    if (trimmed === '') return
    setBusy(true)
    setError(null)
    try {
      const kb = await apiRequest<KnowledgeBase>('/knowledge-bases', {
        method: 'POST',
        body: { name: trimmed },
      })
      await queryClient.invalidateQueries({ queryKey: ['kbs'] })
      setCreateOpen(false)
      setName('')
      navigate(`/knowledge/${kb.id}`)
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (deleteTarget === null) return
    try {
      await apiRequest(`/knowledge-bases/${deleteTarget.id}`, { method: 'DELETE' })
      await queryClient.invalidateQueries({ queryKey: ['kbs'] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setDeleteTarget(null)
    }
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="flex items-center justify-between gap-4 border-b border-border bg-surface px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold">{t('knowledge.title')}</h1>
          <p className="mt-1 text-sm text-ink-muted">{t('knowledge.lead')}</p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="h-4 w-4" />
          {t('knowledge.new')}
        </Button>
      </header>

      <div className="px-6 py-6">
        {error !== null && (
          <p role="alert" className="mb-4 rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </p>
        )}

        {kbs.isLoading && (
          <div className="flex items-center gap-2 text-sm text-ink-muted">
            <Spinner />
            {t('common.loading')}
          </div>
        )}

        {kbs.isError && (
          <div className="flex items-center gap-3 text-sm text-ink-muted">
            {t('errors.generic')}
            <Button variant="secondary" size="sm" onClick={() => void kbs.refetch()}>
              {t('common.retry')}
            </Button>
          </div>
        )}

        {kbs.data !== undefined && kbs.data.length === 0 && (
          <EmptyState title={t('knowledge.empty')} description={t('knowledge.emptyLead')}>
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" />
              {t('knowledge.new')}
            </Button>
          </EmptyState>
        )}

        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {kbs.data?.map((kb) => (
            <article
              key={kb.id}
              className="group rounded-card border border-border bg-surface p-4 transition-colors hover:border-accent/40"
            >
              <div className="flex items-start justify-between gap-2">
                <button
                  type="button"
                  className="flex min-w-0 items-center gap-2 text-left"
                  onClick={() => navigate(`/knowledge/${kb.id}`)}
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
                    <BookOpen className="h-4 w-4" />
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium text-ink">{kb.name}</span>
                    <span className="block text-xs text-ink-muted">
                      {t('knowledge.created', { date: formatDate(kb.created_at, language) })}
                    </span>
                  </span>
                </button>
                <button
                  type="button"
                  aria-label={t('knowledge.delete')}
                  className="rounded-md p-1 text-ink-muted opacity-0 transition-opacity hover:bg-danger/10 hover:text-danger group-hover:opacity-100"
                  onClick={() => setDeleteTarget(kb)}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
              <div className="mt-3 flex justify-end">
                <Button variant="ghost" size="sm" onClick={() => navigate(`/knowledge/${kb.id}`)}>
                  {t('knowledge.open')}
                </Button>
              </div>
            </article>
          ))}
        </div>
      </div>

      <Dialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title={t('knowledge.new')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setCreateOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button size="sm" disabled={busy || name.trim() === ''} onClick={() => void create()}>
              {busy && <Spinner />}
              {t('knowledge.create')}
            </Button>
          </>
        }
      >
        <label className="block text-sm">
          <span className="mb-1.5 block text-ink-muted">{t('knowledge.name')}</span>
          <Input
            autoFocus
            value={name}
            maxLength={100}
            placeholder={t('knowledge.namePlaceholder')}
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void create()
            }}
          />
        </label>
        {error !== null && <p className="mt-3 text-sm text-danger">{error}</p>}
      </Dialog>

      <Dialog
        open={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        title={t('knowledge.delete')}
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
        <p>{t('knowledge.deleteConfirm', { name: deleteTarget?.name ?? '' })}</p>
        <p className="mt-2 text-xs">{t('knowledge.deleteHint')}</p>
      </Dialog>
    </div>
  )
}