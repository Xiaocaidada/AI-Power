import { useState, type FormEvent } from 'react'

import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { Input, Textarea } from '../../components/ui/input'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  AgentMemory,
  CustomAgent,
  MemoryCategory,
  MemoryScopeType,
  Project,
} from '../../lib/types'

const CATEGORIES: MemoryCategory[] = [
  'preference',
  'profile',
  'project',
  'technical',
  'experience',
  'decision',
  'relation',
  'fact',
]

interface Draft {
  title: string
  content: string
  category: MemoryCategory
  scopeType: MemoryScopeType
  projectId: string
  agentId: string
  importance: number
  tags: string
  pinned: boolean
  favorite: boolean
  enabled: boolean
  sensitivity: 'normal' | 'sensitive'
  validUntil: string
  retentionDays: string
}

function draftFrom(
  memory: AgentMemory | null,
  defaultScopeType: MemoryScopeType = 'global',
  defaultProjectId = '',
): Draft {
  return {
    title: memory?.title ?? '',
    content: memory?.content ?? '',
    category: memory?.category ?? 'preference',
    scopeType: memory?.scope_type ?? defaultScopeType,
    projectId: memory?.project_id ?? defaultProjectId,
    agentId: memory?.agent_id ?? '',
    importance: memory?.importance ?? 3,
    tags: (memory?.tags ?? []).join(', '),
    pinned: memory?.pinned ?? false,
    favorite: memory?.favorite ?? false,
    enabled: memory?.enabled ?? true,
    sensitivity: memory?.sensitivity ?? 'normal',
    validUntil: memory?.valid_until ? memory.valid_until.slice(0, 10) : '',
    retentionDays:
      memory?.retention_days === null || memory?.retention_days === undefined
        ? ''
        : String(memory.retention_days),
  }
}

interface MemoryFormDialogProps {
  open: boolean
  initial: AgentMemory | null
  projects: Project[]
  agents: CustomAgent[]
  defaultScopeType?: MemoryScopeType
  defaultProjectId?: string
  onClose: () => void
  onSaved: () => void
}

export function MemoryFormDialog({
  open,
  initial,
  projects,
  agents,
  defaultScopeType = 'global',
  defaultProjectId = '',
  onClose,
  onSaved,
}: MemoryFormDialogProps) {
  const { t } = useI18n()
  const [draft, setDraft] = useState<Draft>(() =>
    draftFrom(initial, defaultScopeType, defaultProjectId),
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const update = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }))

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setSaving(true)
    setError(null)
    const body = {
      title: draft.title,
      content: draft.content,
      category: draft.category,
      scope_type: draft.scopeType,
      project_id:
        draft.scopeType === 'project' && draft.projectId !== ''
          ? draft.projectId
          : null,
      agent_id:
        draft.scopeType === 'agent' && draft.agentId !== '' ? draft.agentId : null,
      importance: draft.importance,
      tags: draft.tags
        .split(',')
        .map((item) => item.trim())
        .filter((item) => item !== ''),
      pinned: draft.pinned,
      favorite: draft.favorite,
      enabled: draft.enabled,
      sensitivity: draft.sensitivity,
      valid_until:
        draft.validUntil === '' ? null : `${draft.validUntil}T00:00:00Z`,
      retention_days:
        draft.retentionDays.trim() === ''
          ? 0
          : Number(draft.retentionDays),
    }
    try {
      if (initial === null) {
        await apiRequest('/memories', { method: 'POST', body })
      } else {
        await apiRequest(`/memories/${initial.id}`, { method: 'PATCH', body })
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
      title={initial === null ? t('memory.new') : t('memory.edit')}
      footer={
        <>
          <Button size="sm" variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button size="sm" disabled={saving} form="memory-form" type="submit">
            {t('common.save')}
          </Button>
        </>
      }
      className="max-w-2xl"
    >
      <form
        id="memory-form"
        className="space-y-3"
        onSubmit={(event) => void submit(event)}
      >
        <Field label={t('memory.memoryTitle')}>
          <Input
            value={draft.title}
            onChange={(event) => update('title', event.target.value)}
          />
        </Field>
        <Field label={t('memory.content')}>
          <Textarea
            required
            className="min-h-32"
            value={draft.content}
            onChange={(event) => update('content', event.target.value)}
          />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t('memory.categoryLabel')}>
            <select
              value={draft.category}
              onChange={(event) =>
                update('category', event.target.value as MemoryCategory)
              }
              className="h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink"
            >
              {CATEGORIES.map((category) => (
                <option key={category} value={category}>
                  {t(`memory.category.${category}`)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('memory.scopeLabel')}>
            <select
              value={draft.scopeType}
              onChange={(event) =>
                update('scopeType', event.target.value as MemoryScopeType)
              }
              className="h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink"
            >
              <option value="global">{t('memory.scopeType.global')}</option>
              <option value="project">{t('memory.scopeType.project')}</option>
              <option value="agent">{t('memory.scopeType.agent')}</option>
            </select>
          </Field>
          {draft.scopeType === 'project' && (
            <Field label={t('memory.project')}>
              <select
                value={draft.projectId}
                onChange={(event) => update('projectId', event.target.value)}
                className="h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink"
              >
                <option value="">{t('memory.selectProject')}</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
            </Field>
          )}
          {draft.scopeType === 'agent' && (
            <Field label={t('memory.agent')}>
              <select
                value={draft.agentId}
                onChange={(event) => update('agentId', event.target.value)}
                className="h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink"
              >
                <option value="">{t('memory.selectAgent')}</option>
                {agents.map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.icon} {agent.name}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <Field label={t('memory.importance')}>
            <select
              value={draft.importance}
              onChange={(event) => update('importance', Number(event.target.value))}
              className="h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink"
            >
              {[1, 2, 3, 4, 5].map((value) => (
                <option key={value} value={value}>
                  {'★'.repeat(value)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('memory.sensitivity')}>
            <select
              value={draft.sensitivity}
              onChange={(event) =>
                update('sensitivity', event.target.value as 'normal' | 'sensitive')
              }
              className="h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink"
            >
              <option value="normal">{t('memory.sensitivityType.normal')}</option>
              <option value="sensitive">
                {t('memory.sensitivityType.sensitive')}
              </option>
            </select>
          </Field>
          <Field label={t('memory.tags')}>
            <Input
              value={draft.tags}
              onChange={(event) => update('tags', event.target.value)}
              placeholder={t('memory.tagsPlaceholder')}
            />
          </Field>
          <Field label={t('memory.validUntil')}>
            <Input
              type="date"
              value={draft.validUntil}
              onChange={(event) => update('validUntil', event.target.value)}
            />
          </Field>
          <Field label={t('memory.retentionDays')}>
            <Input
              type="number"
              min={0}
              value={draft.retentionDays}
              placeholder={t('memory.retentionDaysPlaceholder')}
              onChange={(event) => update('retentionDays', event.target.value)}
            />
          </Field>
        </div>
        <div className="flex flex-wrap gap-4 text-sm text-ink">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={draft.pinned}
              onChange={(event) => update('pinned', event.target.checked)}
            />
            {t('memory.pinned')}
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={draft.favorite}
              onChange={(event) => update('favorite', event.target.checked)}
            />
            {t('memory.favorite')}
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={draft.enabled}
              onChange={(event) => update('enabled', event.target.checked)}
            />
            {t('memory.enabled')}
          </label>
        </div>
        {error !== null && <p className="text-xs text-danger">{error}</p>}
      </form>
    </Dialog>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-xs text-ink-muted">
      <span className="mb-1 block">{label}</span>
      {children}
    </label>
  )
}