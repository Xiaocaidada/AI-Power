import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Megaphone, Pencil, Plus, Trash2 } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { Navigate } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Input, Textarea } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { formatDate } from '../../lib/format'
import { apiRequest } from '../../lib/http'
import { useI18n, type Language } from '../../lib/i18n'
import type {
  Announcement,
  AnnouncementCategory,
  AnnouncementStatus,
  HomePlacement,
  PlacementKind,
} from '../../lib/types'
import { cn } from '../../lib/utils'
import { useAuthStore } from '../../store/auth'

type Tab = 'placements' | 'announcements'

const PLACEMENT_KINDS: PlacementKind[] = ['banner', 'featured', 'activity']
const ANNOUNCEMENT_CATEGORIES: AnnouncementCategory[] = [
  'notice',
  'update',
  'event',
  'maintenance',
]
const ANNOUNCEMENT_STATUSES: AnnouncementStatus[] = ['draft', 'published', 'archived']

export function AdminContentPage() {
  const { t, language } = useI18n()
  const user = useAuthStore((state) => state.user)
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<Tab>('placements')
  const [editingPlacement, setEditingPlacement] = useState<HomePlacement | null | undefined>()
  const [editingAnnouncement, setEditingAnnouncement] = useState<
    Announcement | null | undefined
  >()

  const isAdmin = user?.role === 'admin'
  const placements = useQuery({
    queryKey: ['admin-placements'],
    queryFn: () => apiRequest<HomePlacement[]>('/admin/content/placements'),
    enabled: isAdmin,
  })
  const announcements = useQuery({
    queryKey: ['admin-announcements'],
    queryFn: () => apiRequest<Announcement[]>('/admin/content/announcements'),
    enabled: isAdmin,
  })

  if (!isAdmin) return <Navigate to="/chat" replace />

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ['admin-placements'] })
    await queryClient.invalidateQueries({ queryKey: ['admin-announcements'] })
    await queryClient.invalidateQueries({ queryKey: ['home-feed'] })
    await queryClient.invalidateQueries({ queryKey: ['announcements'] })
  }

  const removePlacement = async (id: string) => {
    if (!window.confirm(t('adminContent.confirmDelete'))) return
    await apiRequest(`/admin/content/placements/${id}`, { method: 'DELETE' })
    await refresh()
  }

  const removeAnnouncement = async (id: string) => {
    if (!window.confirm(t('adminContent.confirmDelete'))) return
    await apiRequest(`/admin/content/announcements/${id}`, { method: 'DELETE' })
    await refresh()
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-4">
        <h1 className="text-lg font-semibold">{t('adminContent.title')}</h1>
        <p className="mt-1 text-sm text-ink-muted">{t('adminContent.lead')}</p>
      </header>

      <div className="space-y-5 px-6 py-6">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant={tab === 'placements' ? 'primary' : 'secondary'}
            onClick={() => setTab('placements')}
          >
            {t('adminContent.tabPlacements')}
          </Button>
          <Button
            size="sm"
            variant={tab === 'announcements' ? 'primary' : 'secondary'}
            onClick={() => setTab('announcements')}
          >
            {t('adminContent.tabAnnouncements')}
          </Button>
          <Button
            size="sm"
            className="ml-auto"
            onClick={() => {
              if (tab === 'placements') setEditingPlacement(null)
              else setEditingAnnouncement(null)
            }}
          >
            <Plus className="h-3.5 w-3.5" />
            {tab === 'placements'
              ? t('adminContent.newPlacement')
              : t('adminContent.newAnnouncement')}
          </Button>
        </div>

        {tab === 'placements' && (
          <>
            {placements.isLoading && <Spinner />}
            <div className="space-y-2">
              {(placements.data ?? []).map((item) => (
                <article
                  key={item.id}
                  className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3"
                >
                  <Badge tone="accent">{t(`adminContent.kind_${item.kind}`)}</Badge>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-ink">{item.title}</p>
                    <p className="truncate text-xs text-ink-muted">
                      {item.subtitle || item.body || item.link_url}
                    </p>
                  </div>
                  <Badge tone={item.enabled ? 'success' : 'neutral'}>
                    {item.enabled ? t('adminContent.enabled') : t('adminContent.disabled')}
                  </Badge>
                  <span className="text-xs text-ink-muted">
                    {windowLabel(item, language, t)}
                  </span>
                  <div className="flex gap-1">
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => setEditingPlacement(item)}
                    >
                      <Pencil className="h-3 w-3" />
                      {t('adminContent.edit')}
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => void removePlacement(item.id)}
                    >
                      <Trash2 className="h-3 w-3" />
                      {t('adminContent.delete')}
                    </Button>
                  </div>
                </article>
              ))}
              {placements.data !== undefined && placements.data.length === 0 && (
                <p className="rounded-xl border border-dashed border-border px-4 py-8 text-center text-sm text-ink-muted">
                  {t('adminContent.emptyPlacements')}
                </p>
              )}
            </div>
          </>
        )}

        {tab === 'announcements' && (
          <>
            {announcements.isLoading && <Spinner />}
            <div className="space-y-2">
              {(announcements.data ?? []).map((item) => (
                <article
                  key={item.id}
                  className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3"
                >
                  <Megaphone className="h-4 w-4 shrink-0 text-accent" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-ink">{item.title}</p>
                    <p className="truncate text-xs text-ink-muted">
                      {t(`announcements.category.${item.category}`)} ·{' '}
                      {formatDate(item.published_at ?? item.created_at, language)}
                    </p>
                  </div>
                  {item.pinned && <Badge tone="accent">{t('adminContent.pinned')}</Badge>}
                  <Badge
                    tone={
                      item.status === 'published'
                        ? 'success'
                        : item.status === 'archived'
                          ? 'neutral'
                          : 'warning'
                    }
                  >
                    {t(`adminContent.status_${item.status}`)}
                  </Badge>
                  <div className="flex gap-1">
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => setEditingAnnouncement(item)}
                    >
                      <Pencil className="h-3 w-3" />
                      {t('adminContent.edit')}
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => void removeAnnouncement(item.id)}
                    >
                      <Trash2 className="h-3 w-3" />
                      {t('adminContent.delete')}
                    </Button>
                  </div>
                </article>
              ))}
              {announcements.data !== undefined && announcements.data.length === 0 && (
                <p className="rounded-xl border border-dashed border-border px-4 py-8 text-center text-sm text-ink-muted">
                  {t('adminContent.emptyAnnouncements')}
                </p>
              )}
            </div>
          </>
        )}
      </div>

      {editingPlacement !== undefined && (
        <PlacementForm
          key={editingPlacement === null ? 'new-placement' : editingPlacement.id}
          initial={editingPlacement}
          onClose={() => setEditingPlacement(undefined)}
          onSaved={() => {
            setEditingPlacement(undefined)
            void refresh()
          }}
        />
      )}

      {editingAnnouncement !== undefined && (
        <AnnouncementForm
          key={editingAnnouncement === null ? 'new-announcement' : editingAnnouncement.id}
          initial={editingAnnouncement}
          onClose={() => setEditingAnnouncement(undefined)}
          onSaved={() => {
            setEditingAnnouncement(undefined)
            void refresh()
          }}
        />
      )}
    </div>
  )
}

function windowLabel(
  item: HomePlacement,
  language: Language,
  t: (key: string) => string,
): string {
  if (item.starts_at !== null && item.ends_at !== null) {
    return `${formatDate(item.starts_at, language)} – ${formatDate(item.ends_at, language)}`
  }
  if (item.starts_at !== null) {
    return `${t('adminContent.startsAt')} ${formatDate(item.starts_at, language)}`
  }
  if (item.ends_at !== null) {
    return `${t('adminContent.endsAt')} ${formatDate(item.ends_at, language)}`
  }
  return ''
}

interface PlacementDraft {
  kind: PlacementKind
  title: string
  subtitle: string
  body: string
  image_url: string
  link_url: string
  link_label: string
  sort_order: string
  enabled: boolean
  starts_at: string
  ends_at: string
}

function placementDraft(initial: HomePlacement | null): PlacementDraft {
  return {
    kind: initial?.kind ?? 'banner',
    title: initial?.title ?? '',
    subtitle: initial?.subtitle ?? '',
    body: initial?.body ?? '',
    image_url: initial?.image_url ?? '',
    link_url: initial?.link_url ?? '',
    link_label: initial?.link_label ?? '',
    sort_order: String(initial?.sort_order ?? 100),
    enabled: initial?.enabled ?? true,
    starts_at: toLocalInput(initial?.starts_at ?? null),
    ends_at: toLocalInput(initial?.ends_at ?? null),
  }
}

function PlacementForm({
  initial,
  onClose,
  onSaved,
}: {
  initial: HomePlacement | null
  onClose: () => void
  onSaved: () => void
}) {
  const { t } = useI18n()
  const [draft, setDraft] = useState<PlacementDraft>(() => placementDraft(initial))
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const update = <K extends keyof PlacementDraft>(key: K, value: PlacementDraft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }))

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setSaving(true)
    setError(null)
    const body = {
      ...draft,
      sort_order: Number(draft.sort_order) || 0,
      starts_at: fromLocalInput(draft.starts_at),
      ends_at: fromLocalInput(draft.ends_at),
    }
    try {
      if (initial === null) {
        await apiRequest('/admin/content/placements', { method: 'POST', body })
      } else {
        await apiRequest(`/admin/content/placements/${initial.id}`, {
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
    <Modal title={t('adminContent.newPlacement')} onClose={onClose}>
      <form className="space-y-3" onSubmit={(event) => void submit(event)}>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t('adminContent.kind')}>
            <select
              className="h-10 w-full rounded-lg border border-border bg-surface px-3 text-sm text-ink"
              value={draft.kind}
              onChange={(event) => update('kind', event.target.value as PlacementKind)}
            >
              {PLACEMENT_KINDS.map((kind) => (
                <option key={kind} value={kind}>
                  {t(`adminContent.kind_${kind}`)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('adminContent.sortOrder')}>
            <Input
              type="number"
              value={draft.sort_order}
              onChange={(event) => update('sort_order', event.target.value)}
            />
          </Field>
        </div>
        <Field label={t('adminContent.titleField')}>
          <Input
            required
            value={draft.title}
            onChange={(event) => update('title', event.target.value)}
          />
        </Field>
        <Field label={t('adminContent.subtitle')}>
          <Input
            value={draft.subtitle}
            onChange={(event) => update('subtitle', event.target.value)}
          />
        </Field>
        <Field label={t('adminContent.body')}>
          <Textarea
            className="min-h-20"
            value={draft.body}
            onChange={(event) => update('body', event.target.value)}
          />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t('adminContent.imageUrl')}>
            <Input
              value={draft.image_url}
              onChange={(event) => update('image_url', event.target.value)}
            />
          </Field>
          <Field label={t('adminContent.linkUrl')}>
            <Input
              value={draft.link_url}
              onChange={(event) => update('link_url', event.target.value)}
            />
          </Field>
          <Field label={t('adminContent.linkLabel')}>
            <Input
              value={draft.link_label}
              onChange={(event) => update('link_label', event.target.value)}
            />
          </Field>
          <Field label={t('adminContent.enabled')}>
            <label className="flex h-10 items-center gap-2 text-sm text-ink">
              <input
                type="checkbox"
                checked={draft.enabled}
                onChange={(event) => update('enabled', event.target.checked)}
              />
              {t('adminContent.enabled')}
            </label>
          </Field>
          <Field label={t('adminContent.startsAt')}>
            <Input
              type="datetime-local"
              value={draft.starts_at}
              onChange={(event) => update('starts_at', event.target.value)}
            />
          </Field>
          <Field label={t('adminContent.endsAt')}>
            <Input
              type="datetime-local"
              value={draft.ends_at}
              onChange={(event) => update('ends_at', event.target.value)}
            />
          </Field>
        </div>
        {error !== null && <p className="text-xs text-danger">{error}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="secondary" onClick={onClose}>
            {t('adminContent.cancel')}
          </Button>
          <Button type="submit" disabled={saving}>
            {t('adminContent.save')}
          </Button>
        </div>
      </form>
    </Modal>
  )
}

interface AnnouncementDraft {
  title: string
  summary: string
  body: string
  cover_url: string
  category: AnnouncementCategory
  pinned: boolean
  status: AnnouncementStatus
  published_at: string
  expires_at: string
}

function announcementDraft(initial: Announcement | null): AnnouncementDraft {
  return {
    title: initial?.title ?? '',
    summary: initial?.summary ?? '',
    body: initial?.body ?? '',
    cover_url: initial?.cover_url ?? '',
    category: initial?.category ?? 'notice',
    pinned: initial?.pinned ?? false,
    status: initial?.status ?? 'draft',
    published_at: toLocalInput(initial?.published_at ?? null),
    expires_at: toLocalInput(initial?.expires_at ?? null),
  }
}

function AnnouncementForm({
  initial,
  onClose,
  onSaved,
}: {
  initial: Announcement | null
  onClose: () => void
  onSaved: () => void
}) {
  const { t } = useI18n()
  const [draft, setDraft] = useState<AnnouncementDraft>(() => announcementDraft(initial))
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const update = <K extends keyof AnnouncementDraft>(
    key: K,
    value: AnnouncementDraft[K],
  ) => setDraft((current) => ({ ...current, [key]: value }))

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setSaving(true)
    setError(null)
    const body = {
      ...draft,
      published_at: fromLocalInput(draft.published_at),
      expires_at: fromLocalInput(draft.expires_at),
    }
    try {
      if (initial === null) {
        await apiRequest('/admin/content/announcements', { method: 'POST', body })
      } else {
        await apiRequest(`/admin/content/announcements/${initial.id}`, {
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
    <Modal title={t('adminContent.newAnnouncement')} onClose={onClose}>
      <form className="space-y-3" onSubmit={(event) => void submit(event)}>
        <Field label={t('adminContent.titleField')}>
          <Input
            required
            value={draft.title}
            onChange={(event) => update('title', event.target.value)}
          />
        </Field>
        <Field label={t('adminContent.summary')}>
          <Input
            value={draft.summary}
            onChange={(event) => update('summary', event.target.value)}
          />
        </Field>
        <Field label={t('adminContent.body')}>
          <Textarea
            required
            className="min-h-32"
            value={draft.body}
            onChange={(event) => update('body', event.target.value)}
          />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t('adminContent.category')}>
            <select
              className="h-10 w-full rounded-lg border border-border bg-surface px-3 text-sm text-ink"
              value={draft.category}
              onChange={(event) =>
                update('category', event.target.value as AnnouncementCategory)
              }
            >
              {ANNOUNCEMENT_CATEGORIES.map((category) => (
                <option key={category} value={category}>
                  {t(`announcements.category.${category}`)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('adminContent.status')}>
            <select
              className="h-10 w-full rounded-lg border border-border bg-surface px-3 text-sm text-ink"
              value={draft.status}
              onChange={(event) =>
                update('status', event.target.value as AnnouncementStatus)
              }
            >
              {ANNOUNCEMENT_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {t(`adminContent.status_${status}`)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('adminContent.publishedAt')}>
            <Input
              type="datetime-local"
              value={draft.published_at}
              onChange={(event) => update('published_at', event.target.value)}
            />
          </Field>
          <Field label={t('adminContent.expiresAt')}>
            <Input
              type="datetime-local"
              value={draft.expires_at}
              onChange={(event) => update('expires_at', event.target.value)}
            />
          </Field>
          <Field label={t('adminContent.coverUrl')}>
            <Input
              value={draft.cover_url}
              onChange={(event) => update('cover_url', event.target.value)}
            />
          </Field>
          <Field label={t('adminContent.pinned')}>
            <label className="flex h-10 items-center gap-2 text-sm text-ink">
              <input
                type="checkbox"
                checked={draft.pinned}
                onChange={(event) => update('pinned', event.target.checked)}
              />
              {t('adminContent.pinned')}
            </label>
          </Field>
        </div>
        {error !== null && <p className="text-xs text-danger">{error}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="secondary" onClick={onClose}>
            {t('adminContent.cancel')}
          </Button>
          <Button type="submit" disabled={saving}>
            {t('adminContent.save')}
          </Button>
        </div>
      </form>
    </Modal>
  )
}

function Modal({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: ReactNode
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/40 p-4"
      onClick={onClose}
    >
      <div
        className={cn(
          'mt-10 w-full max-w-2xl rounded-2xl border border-border bg-surface p-6 shadow-2xl',
        )}
        onClick={(event) => event.stopPropagation()}
      >
        <h2 className="text-base font-semibold text-ink">{title}</h2>
        <div className="mt-4">{children}</div>
      </div>
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

function toLocalInput(value: string | null): string {
  if (value === null) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (input: number) => String(input).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function fromLocalInput(value: string): string | null {
  if (value === '') return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}