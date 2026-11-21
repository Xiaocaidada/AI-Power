import { useQuery, useQueryClient } from '@tanstack/react-query'
import { FilePlus2, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { EmptyState } from '../../components/ui/empty-state'
import { Input, Textarea } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { formatDate } from '../../lib/format'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { PromptTemplate } from '../../lib/types'

const textareaClass =
  'min-h-32 w-full rounded-lg border border-border bg-surface px-3 py-2 font-mono text-xs text-ink focus:border-accent focus:outline-none'

export function PromptTemplatesPage() {
  const { t, language } = useI18n()
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [prompt, setPrompt] = useState('')
  const [versionTarget, setVersionTarget] = useState<PromptTemplate | null>(null)
  const [versionPrompt, setVersionPrompt] = useState('')
  const [previewTarget, setPreviewTarget] = useState<PromptTemplate | null>(null)
  const [variables, setVariables] = useState<Record<string, string>>({})
  const [rendered, setRendered] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<PromptTemplate | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const templates = useQuery({
    queryKey: ['prompt-templates'],
    queryFn: () => apiRequest<PromptTemplate[]>('/prompt-templates'),
  })

  const resetError = () => setError(null)

  const create = async () => {
    if (name.trim() === '' || prompt.trim() === '') return
    setBusy(true)
    resetError()
    try {
      await apiRequest('/prompt-templates', {
        method: 'POST',
        body: {
          name: name.trim(),
          description: description.trim(),
          system_prompt: prompt.trim(),
        },
      })
      await queryClient.invalidateQueries({ queryKey: ['prompt-templates'] })
      setCreateOpen(false)
      setName('')
      setDescription('')
      setPrompt('')
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(false)
    }
  }

  const addVersion = async () => {
    if (versionTarget === null || versionPrompt.trim() === '') return
    setBusy(true)
    resetError()
    try {
      await apiRequest(`/prompt-templates/${versionTarget.id}/versions`, {
        method: 'POST',
        body: { system_prompt: versionPrompt.trim() },
      })
      await queryClient.invalidateQueries({ queryKey: ['prompt-templates'] })
      setVersionTarget(null)
      setVersionPrompt('')
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(false)
    }
  }

  const openPreview = (template: PromptTemplate) => {
    setPreviewTarget(template)
    setVariables({})
    setRendered(null)
    resetError()
  }

  const render = async () => {
    if (previewTarget === null) return
    setBusy(true)
    resetError()
    try {
      const result = await apiRequest<{ rendered: string }>(
        `/prompt-templates/${previewTarget.id}/render`,
        { method: 'POST', body: { variables } },
      )
      setRendered(result.rendered)
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (deleteTarget === null) return
    setBusy(true)
    resetError()
    try {
      await apiRequest(`/prompt-templates/${deleteTarget.id}`, { method: 'DELETE' })
      await queryClient.invalidateQueries({ queryKey: ['prompt-templates'] })
      setDeleteTarget(null)
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(false)
    }
  }

  const latest = previewTarget?.versions[0]

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-3xl px-6 py-8">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="font-serif text-2xl text-ink">{t('prompts.title')}</h1>
            <p className="mt-1 text-sm text-ink-muted">{t('prompts.lead')}</p>
          </div>
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" />
            {t('prompts.create')}
          </Button>
        </div>

        {error !== null && (
          <p role="alert" className="mt-4 rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </p>
        )}

        {templates.isLoading && (
          <div className="mt-8 flex items-center gap-2 text-sm text-ink-muted">
            <Spinner />
            {t('common.loading')}
          </div>
        )}

        {templates.data !== undefined && templates.data.length === 0 && (
          <div className="mt-8">
            <EmptyState title={t('prompts.empty')} description={t('prompts.emptyHint')} />
          </div>
        )}

        <div className="mt-6 space-y-3">
          {templates.data?.map((template) => {
            const current = template.versions[0]
            return (
              <article key={template.id} className="rounded-xl border border-border bg-surface p-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-ink">{template.name}</p>
                    <p className="truncate text-xs text-ink-muted">
                      {template.description || t('prompts.noDescription')}
                    </p>
                  </div>
                  <Badge tone="accent">v{current?.version ?? 1}</Badge>
                </div>
                {current !== undefined && current.variables.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {current.variables.map((variable) => (
                      <code
                        key={variable}
                        className="rounded bg-surface-muted px-1.5 py-0.5 text-[11px] text-ink-muted"
                      >
                        {`{{${variable}}}`}
                      </code>
                    ))}
                  </div>
                )}
                <p className="mt-2 line-clamp-2 font-mono text-[11px] text-ink-muted">
                  {current?.system_prompt}
                </p>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <Button variant="secondary" size="sm" onClick={() => openPreview(template)}>
                    {t('prompts.preview')}
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => {
                      setVersionTarget(template)
                      setVersionPrompt(current?.system_prompt ?? '')
                      resetError()
                    }}
                  >
                    <FilePlus2 className="h-3.5 w-3.5" />
                    {t('prompts.newVersion')}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={t('prompts.delete')}
                    onClick={() => setDeleteTarget(template)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                  <span className="ml-auto text-[11px] text-ink-muted">
                    {formatDate(template.created_at, language)}
                  </span>
                </div>
              </article>
            )
          })}
        </div>
      </div>

      <Dialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title={t('prompts.create')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setCreateOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button size="sm" disabled={busy} onClick={() => void create()}>
              {t('common.create')}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={t('prompts.name')}
            maxLength={120}
          />
          <Input
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder={t('prompts.description')}
            maxLength={500}
          />
          <Textarea
            className={textareaClass}
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder={t('prompts.systemPrompt')}
          />
          <p className="text-xs text-ink-muted">{t('prompts.variableHint')}</p>
        </div>
      </Dialog>

      <Dialog
        open={versionTarget !== null}
        onClose={() => setVersionTarget(null)}
        title={t('prompts.newVersion')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setVersionTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button size="sm" disabled={busy} onClick={() => void addVersion()}>
              {t('common.save')}
            </Button>
          </>
        }
      >
        <Textarea
          className={textareaClass}
          value={versionPrompt}
          onChange={(event) => setVersionPrompt(event.target.value)}
        />
      </Dialog>

      <Dialog
        open={previewTarget !== null}
        onClose={() => setPreviewTarget(null)}
        title={t('prompts.preview')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setPreviewTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button size="sm" disabled={busy} onClick={() => void render()}>
              {t('prompts.render')}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {(latest?.variables ?? []).map((variable) => (
            <Input
              key={variable}
              value={variables[variable] ?? ''}
              onChange={(event) =>
                setVariables((prev) => ({ ...prev, [variable]: event.target.value }))
              }
              placeholder={`{{${variable}}}`}
            />
          ))}
          {(latest?.variables ?? []).length === 0 && (
            <p className="text-xs text-ink-muted">{t('prompts.noVariables')}</p>
          )}
          {rendered !== null && (
            <pre className="whitespace-pre-wrap rounded-lg bg-surface-muted p-3 font-mono text-xs text-ink">
              {rendered}
            </pre>
          )}
        </div>
      </Dialog>

      <Dialog
        open={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        title={t('prompts.delete')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setDeleteTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button variant="danger" size="sm" disabled={busy} onClick={() => void remove()}>
              {t('common.confirm')}
            </Button>
          </>
        }
      >
        {t('prompts.deleteConfirm')}
      </Dialog>
    </div>
  )
}