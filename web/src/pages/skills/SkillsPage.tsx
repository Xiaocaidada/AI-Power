import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Play, Plus, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Input, Textarea } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorMessage } from '../../lib/errors'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { ModelEntry, PersonalModel, Skill, SkillRun } from '../../lib/types'

interface SkillForm {
  name: string
  description: string
  instructions: string
  tools: string
  shared: boolean
  enabled: boolean
}

const EMPTY_FORM: SkillForm = {
  name: '',
  description: '',
  instructions: '',
  tools: '',
  shared: false,
  enabled: true,
}

export function SkillsPage() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<SkillForm>(EMPTY_FORM)
  const [runInput, setRunInput] = useState('')
  const [modelValue, setModelValue] = useState('auto::auto')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const skills = useQuery({
    queryKey: ['skills'],
    queryFn: () => apiRequest<Skill[]>('/skills'),
  })
  const platformModels = useQuery({
    queryKey: ['models'],
    queryFn: () => apiRequest<ModelEntry[]>('/models'),
  })
  const personalModels = useQuery({
    queryKey: ['provider-configs', 'models'],
    queryFn: () => apiRequest<PersonalModel[]>('/provider-configs/models'),
  })
  const runs = useQuery({
    queryKey: ['skill-runs', selectedId],
    queryFn: () => apiRequest<SkillRun[]>(`/skills/${selectedId}/runs`),
    enabled: selectedId !== null,
  })

  const selected = useMemo(
    () => (skills.data ?? []).find((skill) => skill.id === selectedId) ?? null,
    [selectedId, skills.data],
  )
  const modelChoices = useMemo(() => {
    const choices = [{ value: 'auto::auto', label: t('tasks.autoModel') }]
    for (const model of personalModels.data ?? []) {
      choices.push({
        value: `${model.provider_id}::${model.model_id}`,
        label: `${model.display_name} · ${model.provider_name}`,
      })
    }
    for (const model of platformModels.data ?? []) {
      if (model.available) {
        choices.push({
          value: `${model.provider_id}::${model.model_id}`,
          label: `${model.display_name} · ${model.provider_id}`,
        })
      }
    }
    return choices
  }, [personalModels.data, platformModels.data, t])

  const reset = (): void => {
    setEditingId(null)
    setForm(EMPTY_FORM)
  }

  const edit = (skill: Skill): void => {
    setEditingId(skill.id)
    setSelectedId(skill.id)
    setForm({
      name: skill.name,
      description: skill.description,
      instructions: skill.instructions,
      tools: skill.tool_names.join(', '),
      shared: skill.shared,
      enabled: skill.enabled,
    })
  }

  const save = async (): Promise<void> => {
    setBusy(true)
    setError(null)
    const body = {
      name: form.name,
      description: form.description,
      instructions: form.instructions,
      tool_names: form.tools
        .split(',')
        .map((item) => item.trim())
        .filter((item) => item !== ''),
      shared: form.shared,
      enabled: form.enabled,
    }
    try {
      if (editingId === null) {
        const created = await apiRequest<Skill>('/skills', { method: 'POST', body })
        setSelectedId(created.id)
      } else {
        await apiRequest(`/skills/${editingId}`, { method: 'PATCH', body })
      }
      reset()
      await queryClient.invalidateQueries({ queryKey: ['skills'] })
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const remove = async (skill: Skill): Promise<void> => {
    setBusy(true)
    try {
      await apiRequest(`/skills/${skill.id}`, { method: 'DELETE' })
      if (selectedId === skill.id) setSelectedId(null)
      await queryClient.invalidateQueries({ queryKey: ['skills'] })
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const run = async (): Promise<void> => {
    if (selected === null || runInput.trim() === '') return
    setBusy(true)
    setError(null)
    const [providerId, model] = modelValue.split('::')
    try {
      await apiRequest<SkillRun>(`/skills/${selected.id}/run`, {
        method: 'POST',
        body: {
          input: runInput.trim(),
          provider_id: providerId,
          model,
        },
      })
      setRunInput('')
      await queryClient.invalidateQueries({ queryKey: ['skill-runs', selected.id] })
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-4">
        <h1 className="text-lg font-semibold">{t('skills.title')}</h1>
        <p className="mt-1 text-sm text-ink-muted">{t('skills.lead')}</p>
      </header>
      <div className="mx-auto grid w-full max-w-6xl gap-6 px-6 py-6 lg:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="space-y-3">
          <Button
            className="w-full"
            variant="secondary"
            onClick={() => {
              reset()
              setSelectedId(null)
            }}
          >
            <Plus className="h-4 w-4" />
            {t('skills.new')}
          </Button>
          {(skills.data ?? []).map((skill) => (
            <button
              key={skill.id}
              type="button"
              className={`w-full rounded-xl border px-3 py-2 text-left text-sm ${
                skill.id === selectedId
                  ? 'border-accent bg-accent/5'
                  : 'border-border hover:bg-surface-muted'
              }`}
              onClick={() => setSelectedId(skill.id)}
            >
              <span className="block truncate font-medium">{skill.name}</span>
              <span className="mt-1 flex items-center gap-2 text-[11px] text-ink-muted">
                {skill.owned && <Badge tone="neutral">{t('integrations.owned')}</Badge>}
                {skill.shared && <Badge tone="accent">{t('skills.shared')}</Badge>}
                {!skill.enabled && (
                  <Badge tone="warning">{t('integrations.disabled')}</Badge>
                )}
              </span>
            </button>
          ))}
          {skills.data !== undefined && skills.data.length === 0 && (
            <p className="text-xs text-ink-muted">{t('skills.empty')}</p>
          )}
        </aside>

        <main className="min-w-0 space-y-5">
          {error !== null && (
            <p className="rounded-lg border border-danger/40 bg-danger/5 px-3 py-2 text-sm text-danger">
              {error}
            </p>
          )}

          <section className="rounded-2xl border border-border bg-surface p-4">
            <h2 className="text-sm font-semibold">
              {editingId === null ? t('skills.create') : t('skills.edit')}
            </h2>
            <div className="mt-3 space-y-2">
              <Input
                value={form.name}
                placeholder={t('skills.name')}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
              />
              <Input
                value={form.description}
                placeholder={t('skills.description')}
                onChange={(event) => setForm({ ...form, description: event.target.value })}
              />
              <Textarea
                rows={4}
                value={form.instructions}
                placeholder={t('skills.instructions')}
                onChange={(event) => setForm({ ...form, instructions: event.target.value })}
              />
              <Input
                value={form.tools}
                placeholder={t('skills.tools')}
                onChange={(event) => setForm({ ...form, tools: event.target.value })}
              />
              <div className="flex flex-wrap gap-4 text-xs text-ink-muted">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={form.shared}
                    onChange={(event) => setForm({ ...form, shared: event.target.checked })}
                  />
                  {t('skills.share')}
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={form.enabled}
                    onChange={(event) => setForm({ ...form, enabled: event.target.checked })}
                  />
                  {t('integrations.enabled')}
                </label>
              </div>
              <div className="flex gap-2">
                <Button disabled={busy || form.name.trim() === ''} onClick={() => void save()}>
                  {t('common.save')}
                </Button>
                {editingId !== null && (
                  <Button variant="secondary" onClick={reset}>
                    {t('skills.cancelEdit')}
                  </Button>
                )}
                {selected !== null && selected.owned && (
                  <Button variant="ghost" disabled={busy} onClick={() => void remove(selected)}>
                    <Trash2 className="h-4 w-4" />
                    {t('skills.delete')}
                  </Button>
                )}
              </div>
            </div>
          </section>

          {selected !== null && (
            <section className="rounded-2xl border border-border bg-surface p-4">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-sm font-semibold">{selected.name}</h2>
                {selected.owned && (
                  <Button variant="ghost" size="sm" onClick={() => edit(selected)}>
                    {t('common.edit')}
                  </Button>
                )}
                <span className="ml-auto text-xs text-ink-muted">
                  {t('skills.toolsLabel')}: {selected.tool_names.join(', ') || '—'}
                </span>
              </div>
              <div className="mt-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_220px_auto]">
                <Textarea
                  rows={3}
                  value={runInput}
                  placeholder={t('skills.runInput')}
                  onChange={(event) => setRunInput(event.target.value)}
                />
                <select
                  className="h-10 rounded-lg border border-border bg-surface px-2 text-sm"
                  value={modelValue}
                  onChange={(event) => setModelValue(event.target.value)}
                >
                  {modelChoices.map((choice) => (
                    <option key={choice.value} value={choice.value}>
                      {choice.label}
                    </option>
                  ))}
                </select>
                <Button
                  disabled={busy || runInput.trim() === '' || !selected.enabled}
                  onClick={() => void run()}
                >
                  <Play className="h-4 w-4" />
                  {t('skills.run')}
                </Button>
              </div>
              <div className="mt-4 space-y-2">
                <h3 className="text-xs font-semibold text-ink-muted">{t('skills.history')}</h3>
                {(runs.data ?? []).map((item) => (
                  <article key={item.id} className="rounded-xl border border-border p-3">
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <Badge tone={item.status === 'completed' ? 'accent' : 'danger'}>
                        {item.status}
                      </Badge>
                      <span className="text-ink-muted">
                        {new Date(item.created_at).toLocaleString()}
                      </span>
                      {item.error_code !== null && (
                        <span className="text-danger">{item.error_code}</span>
                      )}
                      <span className="ml-auto text-ink-muted">
                        {item.model ?? ''} · {item.prompt_tokens ?? 0}+
                        {item.completion_tokens ?? 0}
                      </span>
                    </div>
                    <p className="mt-2 text-xs text-ink-muted">{item.input}</p>
                    {item.output !== '' && (
                      <div className="markdown mt-2 text-sm text-ink">
                        <ReactMarkdown>{item.output}</ReactMarkdown>
                      </div>
                    )}
                  </article>
                ))}
                {runs.data !== undefined && runs.data.length === 0 && (
                  <p className="text-xs text-ink-muted">{t('skills.noRuns')}</p>
                )}
              </div>
            </section>
          )}

          {busy && (
            <div className="flex items-center gap-2 text-xs text-ink-muted">
              <Spinner />
              {t('common.loading')}
            </div>
          )}
        </main>
      </div>
    </div>
  )
}