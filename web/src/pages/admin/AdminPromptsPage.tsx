import { useQuery, useQueryClient } from '@tanstack/react-query'
import { FileText, Save, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { Input } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { PromptTemplate } from '../../lib/types'

const textareaClass =
  'mt-1 min-h-28 w-full resize-y rounded-lg border border-border bg-surface px-3 py-2 font-mono text-xs text-ink'

export function AdminPromptsPage() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [category, setCategory] = useState('general')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [userPrompt, setUserPrompt] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDescription, setNewDescription] = useState('')
  const [newCategory, setNewCategory] = useState('general')
  const [newSystemPrompt, setNewSystemPrompt] = useState('')
  const [newUserPrompt, setNewUserPrompt] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<PromptTemplate | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const templates = useQuery({
    queryKey: ['admin-prompt-templates'],
    queryFn: () => apiRequest<PromptTemplate[]>('/admin/prompt-templates'),
  })

  const selected = (templates.data ?? []).find((item) => item.id === selectedId)
  const latest = selected?.versions[0]

  useEffect(() => {
    if (selectedId === '' && (templates.data ?? []).length > 0) {
      setSelectedId(templates.data?.[0]?.id ?? '')
    }
  }, [selectedId, templates.data])

  useEffect(() => {
    if (selected === undefined) return
    setName(selected.name)
    setDescription(selected.description)
    setCategory(selected.category)
    setSystemPrompt(latest?.system_prompt ?? '')
    setUserPrompt(latest?.user_prompt ?? '')
    setError(null)
  }, [selected, latest])

  const createTemplate = async () => {
    if (newName.trim() === '' || newSystemPrompt.trim() === '') return
    setBusy(true)
    setError(null)
    try {
      const created = await apiRequest<PromptTemplate>('/admin/prompt-templates', {
        method: 'POST',
        body: {
          name: newName.trim(),
          description: newDescription.trim(),
          category: newCategory.trim() || 'general',
          system_prompt: newSystemPrompt.trim(),
          user_prompt: newUserPrompt.trim(),
        },
      })
      await queryClient.invalidateQueries({ queryKey: ['admin-prompt-templates'] })
      setCreateOpen(false)
      setNewName('')
      setNewDescription('')
      setNewCategory('general')
      setNewSystemPrompt('')
      setNewUserPrompt('')
      setSelectedId(created.id)
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(false)
    }
  }

  const saveMetadata = async () => {
    if (selected === undefined || name.trim() === '') return
    setBusy(true)
    setError(null)
    try {
      await apiRequest(`/admin/prompt-templates/${selected.id}`, {
        method: 'PATCH',
        body: {
          name: name.trim(),
          description: description.trim(),
          category: category.trim() || 'general',
        },
      })
      await queryClient.invalidateQueries({ queryKey: ['admin-prompt-templates'] })
      await queryClient.invalidateQueries({ queryKey: ['prompt-templates'] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(false)
    }
  }

  const saveVersion = async () => {
    if (selected === undefined || systemPrompt.trim() === '') return
    setBusy(true)
    setError(null)
    try {
      await apiRequest(`/admin/prompt-templates/${selected.id}/versions`, {
        method: 'POST',
        body: {
          system_prompt: systemPrompt,
          user_prompt: userPrompt,
          parameters: latest?.parameters ?? {},
        },
      })
      await queryClient.invalidateQueries({ queryKey: ['admin-prompt-templates'] })
      await queryClient.invalidateQueries({ queryKey: ['prompt-templates'] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(false)
    }
  }

  const deleteTemplate = async () => {
    if (deleteTarget === null) return
    setBusy(true)
    setError(null)
    try {
      await apiRequest(`/admin/prompt-templates/${deleteTarget.id}`, {
        method: 'DELETE',
      })
      await queryClient.invalidateQueries({ queryKey: ['admin-prompt-templates'] })
      await queryClient.invalidateQueries({ queryKey: ['prompt-templates'] })
      setDeleteTarget(null)
      if (selectedId === deleteTarget.id) setSelectedId('')
    } catch (caught) {
      setError(t(errorTextKey(caught)))
      setDeleteTarget(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-4">
        <h1 className="flex items-center gap-2 text-lg font-semibold">
          <FileText className="h-5 w-5 text-accent" />
          {t('adminPrompts.title')}
        </h1>
        <p className="mt-1 text-sm text-ink-muted">{t('adminPrompts.lead')}</p>
      </header>

      <div className="mx-auto grid w-full max-w-6xl gap-4 px-6 py-6 lg:grid-cols-[16rem_1fr]">
        <aside className="rounded-card border border-border bg-surface">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <p className="text-sm font-medium">{t('adminPrompts.templates')}</p>
            <Button size="sm" variant="ghost" onClick={() => setCreateOpen(true)}>
              + {t('common.create')}
            </Button>
          </div>
          {templates.isLoading && <Spinner className="m-3" />}
          <div className="max-h-[60vh] divide-y divide-border overflow-y-auto">
            {(templates.data ?? []).map((template) => (
              <button
                key={template.id}
                type="button"
                onClick={() => setSelectedId(template.id)}
                className={`block w-full px-3 py-2 text-left ${
                  selectedId === template.id
                    ? 'bg-accent-soft text-accent'
                    : 'hover:bg-surface-muted'
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className="truncate text-xs font-medium">{template.name}</span>
                  <Badge tone="neutral">P</Badge>
                </div>
                <p className="truncate text-[10px] text-ink-muted">
                  {template.category} · {template.versions.length} versions
                </p>
              </button>
            ))}
            {templates.data !== undefined && templates.data.length === 0 && (
              <p className="px-3 py-4 text-xs text-ink-muted">
                {t('adminPrompts.empty')}
              </p>
            )}
          </div>
        </aside>

        {selected === undefined ? (
          <p className="text-sm text-ink-muted">{t('adminPrompts.select')}</p>
        ) : (
          <section className="space-y-3">
            <div className="rounded-card border border-border bg-surface p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-medium">{t('adminPrompts.metadata')}</p>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={busy}
                    onClick={() => void saveMetadata()}
                  >
                    <Save className="h-3.5 w-3.5" />
                    {t('common.save')}
                  </Button>
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={() => setDeleteTarget(selected)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    {t('common.delete')}
                  </Button>
                </div>
              </div>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                <label className="text-xs text-ink-muted">
                  {t('adminPrompts.name')}
                  <Input
                    className="mt-1"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                  />
                </label>
                <label className="text-xs text-ink-muted">
                  {t('adminPrompts.category')}
                  <Input
                    className="mt-1"
                    value={category}
                    onChange={(event) => setCategory(event.target.value)}
                  />
                </label>
              </div>
              <label className="mt-2 block text-xs text-ink-muted">
                {t('adminPrompts.description')}
                <Input
                  className="mt-1"
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                />
              </label>
            </div>

            <div className="rounded-card border border-border bg-surface p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-medium">
                  {t('adminPrompts.prompt')} · v{latest?.version ?? 1}
                </p>
                <Button
                  size="sm"
                  disabled={busy || systemPrompt.trim() === ''}
                  onClick={() => void saveVersion()}
                >
                  <Save className="h-3.5 w-3.5" />
                  {t('adminPrompts.saveVersion')}
                </Button>
              </div>
              <label className="mt-3 block text-xs text-ink-muted">
                System Prompt
                <textarea
                  value={systemPrompt}
                  onChange={(event) => setSystemPrompt(event.target.value)}
                  className={textareaClass}
                />
              </label>
              <label className="mt-2 block text-xs text-ink-muted">
                User Prompt
                <textarea
                  value={userPrompt}
                  onChange={(event) => setUserPrompt(event.target.value)}
                  className={textareaClass}
                />
              </label>
              <p className="mt-2 text-[11px] text-ink-muted">
                {selected.versions.map((version) => `v${version.version}`).join(' · ')}
              </p>
              {error !== null && <p className="mt-2 text-xs text-danger">{error}</p>}
            </div>
          </section>
        )}
      </div>

      <Dialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title={t('adminPrompts.create')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setCreateOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              size="sm"
              disabled={busy || newName.trim() === '' || newSystemPrompt.trim() === ''}
              onClick={() => void createTemplate()}
            >
              {t('common.create')}
            </Button>
          </>
        }
      >
        <div className="space-y-2">
          <Input
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
            placeholder={t('adminPrompts.name')}
          />
          <Input
            value={newCategory}
            onChange={(event) => setNewCategory(event.target.value)}
            placeholder={t('adminPrompts.category')}
          />
          <Input
            value={newDescription}
            onChange={(event) => setNewDescription(event.target.value)}
            placeholder={t('adminPrompts.description')}
          />
          <textarea
            value={newSystemPrompt}
            onChange={(event) => setNewSystemPrompt(event.target.value)}
            placeholder="System Prompt"
            className="min-h-24 w-full rounded-lg border border-border bg-surface px-3 py-2 font-mono text-xs"
          />
          <textarea
            value={newUserPrompt}
            onChange={(event) => setNewUserPrompt(event.target.value)}
            placeholder="User Prompt"
            className="min-h-16 w-full rounded-lg border border-border bg-surface px-3 py-2 font-mono text-xs"
          />
          {error !== null && <p className="text-xs text-danger">{error}</p>}
        </div>
      </Dialog>

      <Dialog
        open={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        title={t('adminPrompts.delete')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setDeleteTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              size="sm"
              variant="danger"
              disabled={busy}
              onClick={() => void deleteTemplate()}
            >
              {t('common.delete')}
            </Button>
          </>
        }
      >
        <p className="text-sm text-ink-muted">
          {t('adminPrompts.confirmDelete')} “{deleteTarget?.name}”
        </p>
      </Dialog>
    </div>
  )
}