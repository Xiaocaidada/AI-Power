import { useQuery, useQueryClient } from '@tanstack/react-query'
import { FolderPlus, MessageSquare, Pencil, Trash2 } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Input, Textarea } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  CustomAgent,
  KnowledgeBase,
  ModelEntry,
  PersonalModel,
  Project,
} from '../../lib/types'

interface Draft {
  name: string
  description: string
  instructions: string
  modelChoice: string
  defaultAgent: boolean
  customAgentId: string
  kbId: string
}

function draftFrom(project: Project | null): Draft {
  if (project === null) {
    return {
      name: '',
      description: '',
      instructions: '',
      modelChoice: 'auto',
      defaultAgent: false,
      customAgentId: '',
      kbId: '',
    }
  }
  let modelChoice = 'auto'
  if (project.default_provider_id !== null && project.default_model !== null) {
    modelChoice = `m:${project.default_provider_id}:${project.default_model}`
  }
  return {
    name: project.name,
    description: project.description,
    instructions: project.instructions,
    modelChoice,
    defaultAgent: project.default_agent,
    customAgentId: project.default_custom_agent_id ?? '',
    kbId: project.default_kb_id ?? '',
  }
}

function parseChoice(choice: string): { provider: string | null; model: string | null } {
  if (choice === 'auto') return { provider: 'auto', model: 'auto' }
  if (choice.startsWith('m:') || choice.startsWith('p:')) {
    const [, provider, ...rest] = choice.split(':')
    return { provider, model: rest.join(':') }
  }
  return { provider: null, model: null }
}

export function ProjectsPage() {
  const { t } = useI18n()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<Project | null | undefined>()

  const projects = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiRequest<Project[]>('/projects'),
  })

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['projects'] })

  const archive = async (project: Project) => {
    if (!window.confirm(t('projects.archiveConfirm'))) return
    await apiRequest(`/projects/${project.id}`, { method: 'DELETE' })
    await refresh()
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-surface px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold">{t('projects.title')}</h1>
          <p className="mt-1 text-sm text-ink-muted">{t('projects.lead')}</p>
        </div>
        <Button size="sm" onClick={() => setEditing(null)}>
          <FolderPlus className="h-3.5 w-3.5" />
          {t('projects.new')}
        </Button>
      </header>

      <div className="px-6 py-6">
        {projects.isLoading && <Spinner />}
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {(projects.data ?? []).map((project) => (
            <article
              key={project.id}
              className="flex flex-col rounded-2xl border border-border bg-surface p-5"
            >
              <div className="flex items-start justify-between gap-2">
                <Link
                  to={`/projects/${project.id}`}
                  className="text-base font-semibold text-ink hover:text-accent"
                >
                  {project.name}
                </Link>
                <Badge tone="neutral">
                  {t('projects.conversations', { count: project.conversation_count })}
                </Badge>
              </div>
              <p className="mt-2 line-clamp-2 min-h-10 text-sm leading-5 text-ink-muted">
                {project.description || t('projects.noDescription')}
              </p>
              {project.instructions !== '' && (
                <p className="mt-2 line-clamp-2 rounded-lg bg-surface-muted px-2 py-1.5 text-xs text-ink-muted">
                  {project.instructions}
                </p>
              )}
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-ink-muted">
                <span className="font-mono">
                  {project.default_provider_id ?? t('models.auto')}
                  {project.default_model !== null ? ` · ${project.default_model}` : ''}
                </span>
                {project.default_agent && <Badge tone="accent">{t('chat.agentMode')}</Badge>}
                {project.default_custom_agent_id && (
                  <Badge tone="accent">{t('projects.customAgentBadge')}</Badge>
                )}
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => navigate(`/chat?project=${project.id}`)}
                >
                  <MessageSquare className="h-3 w-3" />
                  {t('projects.newChat')}
                </Button>
                {project.owned && (
                  <>
                    <Button size="sm" variant="secondary" onClick={() => setEditing(project)}>
                      <Pencil className="h-3 w-3" />
                      {t('common.edit')}
                    </Button>
                    <Button size="sm" variant="secondary" onClick={() => void archive(project)}>
                      <Trash2 className="h-3 w-3" />
                      {t('projects.archive')}
                    </Button>
                  </>
                )}
              </div>
            </article>
          ))}
        </div>
        {projects.data !== undefined && projects.data.length === 0 && (
          <p className="rounded-2xl border border-dashed border-border px-6 py-16 text-center text-sm text-ink-muted">
            {t('projects.empty')}
          </p>
        )}
      </div>

      {editing !== undefined && (
        <ProjectForm
          key={editing === null ? 'new-project' : editing.id}
          initial={editing}
          onClose={() => setEditing(undefined)}
          onSaved={() => {
            setEditing(undefined)
            void refresh()
          }}
        />
      )}
    </div>
  )
}

function ProjectForm({
  initial,
  onClose,
  onSaved,
}: {
  initial: Project | null
  onClose: () => void
  onSaved: () => void
}) {
  const { t } = useI18n()
  const [draft, setDraft] = useState<Draft>(() => draftFrom(initial))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const models = useQuery({
    queryKey: ['models'],
    queryFn: () => apiRequest<ModelEntry[]>('/models'),
    staleTime: 60_000,
  })
  const personalModels = useQuery({
    queryKey: ['provider-configs', 'models'],
    queryFn: () => apiRequest<PersonalModel[]>('/provider-configs/models'),
    staleTime: 60_000,
  })
  const kbs = useQuery({
    queryKey: ['kbs'],
    queryFn: () => apiRequest<KnowledgeBase[]>('/knowledge-bases'),
    staleTime: 60_000,
  })
  const agents = useQuery({
    queryKey: ['agents', 'project-options'],
    queryFn: () => apiRequest<CustomAgent[]>('/agents?scope=mine'),
    staleTime: 60_000,
  })

  const platform = (models.data ?? []).filter((model) => model.available)
  const personal = personalModels.data ?? []
  const update = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }))

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const choice = parseChoice(draft.modelChoice)
    setSaving(true)
    setError(null)
    const body = {
      name: draft.name,
      description: draft.description,
      instructions: draft.instructions,
      default_provider_id: choice.provider,
      default_model: choice.model,
      default_agent: draft.defaultAgent,
      default_custom_agent_id:
        draft.customAgentId === '' ? null : draft.customAgentId,
      default_kb_id: draft.kbId === '' ? null : draft.kbId,
    }
    try {
      if (initial === null) {
        await apiRequest('/projects', { method: 'POST', body })
      } else {
        await apiRequest(`/projects/${initial.id}`, { method: 'PATCH', body })
      }
      onSaved()
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/40 p-4"
      onClick={onClose}
    >
      <form
        className="mt-10 w-full max-w-2xl rounded-2xl border border-border bg-surface p-6 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
        onSubmit={(event) => void submit(event)}
      >
        <h2 className="text-base font-semibold text-ink">
          {initial === null ? t('projects.new') : t('projects.edit')}
        </h2>
        <div className="mt-4 space-y-3">
          <Field label={t('projects.name')}>
            <Input
              required
              value={draft.name}
              onChange={(event) => update('name', event.target.value)}
            />
          </Field>
          <Field label={t('projects.description')}>
            <Input
              value={draft.description}
              onChange={(event) => update('description', event.target.value)}
            />
          </Field>
          <Field label={t('projects.instructions')}>
            <Textarea
              className="min-h-24"
              value={draft.instructions}
              onChange={(event) => update('instructions', event.target.value)}
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t('projects.defaultModel')}>
              <select
                className="h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink"
                value={draft.modelChoice}
                onChange={(event) => update('modelChoice', event.target.value)}
              >
                <option value="auto">{t('models.auto')}</option>
                {platform.map((model) => (
                  <option
                    key={`m:${model.provider_id}:${model.model_id}`}
                    value={`m:${model.provider_id}:${model.model_id}`}
                  >
                    {model.display_name} · {model.provider_id}
                  </option>
                ))}
                {personal.map((model) => (
                  <option
                    key={`p:${model.provider_id}:${model.model_id}`}
                    value={`p:${model.provider_id}:${model.model_id}`}
                  >
                    {model.display_name} · {model.provider_name}
                  </option>
                ))}
                {draft.modelChoice !== 'auto' &&
                  !platform.some(
                    (model) =>
                      `m:${model.provider_id}:${model.model_id}` === draft.modelChoice,
                  ) &&
                  !personal.some(
                    (model) =>
                      `p:${model.provider_id}:${model.model_id}` === draft.modelChoice,
                  ) && (
                    <option value={draft.modelChoice}>
                      {draft.modelChoice.replace(/^[mp]:/, '').replace(':', ' · ')}
                    </option>
                  )}
              </select>
            </Field>
            <Field label={t('projects.defaultKb')}>
              <select
                className="h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink"
                value={draft.kbId}
                onChange={(event) => update('kbId', event.target.value)}
              >
                <option value="">{t('chat.noKnowledgeBase')}</option>
                {(kbs.data ?? []).map((kb) => (
                  <option key={kb.id} value={kb.id}>
                    {kb.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field label={t('projects.defaultCustomAgent')}>
            <select
              className="h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink"
              value={draft.customAgentId}
              onChange={(event) => update('customAgentId', event.target.value)}
            >
              <option value="">{t('projects.noDefaultCustomAgent')}</option>
              {(agents.data ?? [])
                .filter((agent) => !agent.builtin)
                .map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.icon} {agent.name}
                  </option>
                ))}
            </select>
          </Field>
          <label className="flex items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={draft.defaultAgent}
              onChange={(event) => update('defaultAgent', event.target.checked)}
            />
            {t('projects.defaultAgent')}
          </label>
        </div>
        {error !== null && <p className="mt-3 text-xs text-danger">{error}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <Button type="button" variant="secondary" size="sm" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" size="sm" disabled={saving}>
            {t('common.save')}
          </Button>
        </div>
      </form>
    </div>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-ink-muted">{label}</span>
      {children}
    </label>
  )
}