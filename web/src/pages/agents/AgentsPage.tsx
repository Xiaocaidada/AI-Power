import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, Pencil, Plus, Trash2 } from 'lucide-react'
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
  Plugin,
} from '../../lib/types'

const CATEGORIES = ['general', 'research', 'writing', 'coding', 'analysis', 'orchestration']
const TOOLS = ['kb_search', 'current_time', 'calculator']

interface Draft {
  name: string
  description: string
  instructions: string
  category: string
  modelChoice: string
  kbId: string
  tools: string[]
  pluginIds: string[]
  visibility: 'private' | 'shared'
}

function draftFrom(agent: CustomAgent | null): Draft {
  if (agent === null) {
    return {
      name: '',
      description: '',
      instructions: '',
      category: 'general',
      modelChoice: 'auto',
      kbId: '',
      tools: [],
      pluginIds: [],
      visibility: 'private',
    }
  }
  return {
    name: agent.name,
    description: agent.description,
    instructions: agent.instructions,
    category: agent.category,
    modelChoice:
      agent.default_provider_id === null || agent.default_provider_id === 'auto'
        ? 'auto'
        : `m:${agent.default_provider_id}:${agent.default_model ?? ''}`,
    kbId: agent.default_kb_id ?? '',
    tools: agent.tools,
    pluginIds: agent.plugin_ids,
    visibility: agent.visibility,
  }
}

function parseChoice(choice: string): { provider: string | null; model: string | null } {
  if (choice === 'auto') return { provider: 'auto', model: 'auto' }
  if (choice.startsWith('m:')) {
    const [, provider, ...rest] = choice.split(':')
    return { provider, model: rest.join(':') }
  }
  return { provider: null, model: null }
}

export function AgentsPage() {
  const { t } = useI18n()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [editing, setEditing] = useState<CustomAgent | null | undefined>()

  const agents = useQuery({
    queryKey: ['agents', search, category],
    queryFn: () =>
      apiRequest<CustomAgent[]>(
        `/agents?${new URLSearchParams({
          ...(search.trim() !== '' ? { q: search.trim() } : {}),
          ...(category !== '' ? { category } : {}),
        }).toString()}`,
      ),
  })

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['agents'] })

  const archive = async (agent: CustomAgent) => {
    if (!window.confirm(t('agents.archiveConfirm'))) return
    await apiRequest(`/agents/${agent.id}`, { method: 'DELETE' })
    await refresh()
  }

  const experience = (agent: CustomAgent) => {
    navigate(agent.builtin ? '/chat?agentMode=1' : `/chat?agent=${agent.id}`)
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-surface px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold">{t('agents.title')}</h1>
          <p className="mt-1 text-sm text-ink-muted">{t('agents.lead')}</p>
        </div>
        <Button size="sm" onClick={() => setEditing(null)}>
          <Plus className="h-3.5 w-3.5" />
          {t('agents.new')}
        </Button>
      </header>

      <div className="space-y-5 px-6 py-6">
        <div className="flex flex-wrap gap-2">
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t('agents.search')}
            className="h-9 w-full max-w-xs rounded-lg border border-border bg-surface px-3 text-sm text-ink focus:border-accent focus:outline-none"
          />
          <select
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            className="h-9 rounded-lg border border-border bg-surface px-2 text-sm text-ink"
          >
            <option value="">{t('agents.allCategories')}</option>
            {CATEGORIES.map((item) => (
              <option key={item} value={item}>
                {t(`agents.category.${item}`)}
              </option>
            ))}
          </select>
        </div>

        {agents.isLoading && <Spinner />}
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {(agents.data ?? []).map((agent) => (
            <article
              key={agent.id}
              className="flex flex-col rounded-2xl border border-border bg-surface p-5"
            >
              <div className="flex items-start justify-between gap-2">
                <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent-soft text-accent">
                  <Bot className="h-4 w-4" />
                </span>
                <div className="flex flex-wrap justify-end gap-1">
                  {agent.builtin && <Badge tone="neutral">{t('agents.builtin')}</Badge>}
                  {agent.visibility === 'shared' && (
                    <Badge tone="accent">{t('agents.shared')}</Badge>
                  )}
                  {agent.archived && <Badge tone="warning">{t('agents.archived')}</Badge>}
                </div>
              </div>
              <Link
                to={`/agents/${agent.id}`}
                className="mt-3 text-base font-semibold text-ink hover:text-accent"
              >
                {agent.name}
              </Link>
              <p className="mt-1 line-clamp-2 min-h-10 text-sm leading-5 text-ink-muted">
                {agent.description || t('agents.noDescription')}
              </p>
              <div className="mt-3 flex flex-wrap gap-1">
                <Badge tone="neutral">{t(`agents.category.${agent.category}`)}</Badge>
                {agent.tools.slice(0, 3).map((tool) => (
                  <Badge key={tool} tone="neutral">
                    {tool}
                  </Badge>
                ))}
                {agent.plugin_ids.length > 0 && (
                  <Badge tone="accent">
                    {t('agents.pluginCount', { count: agent.plugin_ids.length })}
                  </Badge>
                )}
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button size="sm" onClick={() => experience(agent)}>
                  {t('agents.experience')}
                </Button>
                {!agent.builtin && agent.owned && (
                  <>
                    <Button size="sm" variant="secondary" onClick={() => setEditing(agent)}>
                      <Pencil className="h-3 w-3" />
                      {t('common.edit')}
                    </Button>
                    <Button size="sm" variant="secondary" onClick={() => void archive(agent)}>
                      <Trash2 className="h-3 w-3" />
                      {t('agents.archive')}
                    </Button>
                  </>
                )}
              </div>
            </article>
          ))}
        </div>
        {agents.data !== undefined && agents.data.length === 0 && (
          <p className="rounded-2xl border border-dashed border-border px-6 py-16 text-center text-sm text-ink-muted">
            {t('agents.empty')}
          </p>
        )}
      </div>

      {editing !== undefined && (
        <AgentForm
          key={editing === null ? 'new-agent' : editing.id}
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

function AgentForm({
  initial,
  onClose,
  onSaved,
}: {
  initial: CustomAgent | null
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
  const plugins = useQuery({
    queryKey: ['plugins'],
    queryFn: () => apiRequest<Plugin[]>('/plugins'),
    staleTime: 60_000,
  })

  const platform = (models.data ?? []).filter((model) => model.available)
  const personal = personalModels.data ?? []
  const configuredPlugins = (plugins.data ?? []).filter(
    (plugin) => plugin.configured && plugin.config_enabled && plugin.enabled,
  )
  const update = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }))
  const toggle = (key: 'tools' | 'pluginIds', value: string) => {
    const current = draft[key]
    update(
      key,
      current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value],
    )
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const choice = parseChoice(draft.modelChoice)
    setSaving(true)
    setError(null)
    const body = {
      name: draft.name,
      description: draft.description,
      instructions: draft.instructions,
      category: draft.category,
      default_provider_id: choice.provider,
      default_model: choice.model,
      default_kb_id: draft.kbId === '' ? null : draft.kbId,
      tools: draft.tools,
      plugin_ids: draft.pluginIds,
      visibility: draft.visibility,
    }
    try {
      if (initial === null) {
        await apiRequest('/agents', { method: 'POST', body })
      } else {
        await apiRequest(`/agents/${initial.id}`, { method: 'PATCH', body })
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
          {initial === null ? t('agents.new') : t('agents.edit')}
        </h2>
        <div className="mt-4 space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t('agents.name')}>
              <Input
                required
                aria-label={t('agents.name')}
                value={draft.name}
                onChange={(event) => update('name', event.target.value)}
              />
            </Field>
            <Field label={t('agents.categoryLabel')}>
              <select
                className="h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink"
                value={draft.category}
                onChange={(event) => update('category', event.target.value)}
              >
                {CATEGORIES.map((item) => (
                  <option key={item} value={item}>
                    {t(`agents.category.${item}`)}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field label={t('agents.description')}>
            <Input
              aria-label={t('agents.description')}
              value={draft.description}
              onChange={(event) => update('description', event.target.value)}
            />
          </Field>
          <Field label={t('agents.instructions')}>
            <Textarea
              required
              aria-label={t('agents.instructions')}
              className="min-h-28"
              value={draft.instructions}
              onChange={(event) => update('instructions', event.target.value)}
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t('agents.defaultModel')}>
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
                    value={`m:${model.provider_id}:${model.model_id}`}
                  >
                    {model.display_name} · {model.provider_name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t('agents.defaultKb')}>
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
          <Field label={t('agents.tools')}>
            <div className="flex flex-wrap gap-2">
              {TOOLS.map((tool) => (
                <label key={tool} className="flex items-center gap-1.5 text-xs text-ink">
                  <input
                    type="checkbox"
                    checked={draft.tools.includes(tool)}
                    onChange={() => toggle('tools', tool)}
                  />
                  {t(`agents.tool.${tool}`)}
                </label>
              ))}
            </div>
          </Field>
          {configuredPlugins.length > 0 && (
            <Field label={t('agents.plugins')}>
              <div className="flex flex-wrap gap-2">
                {configuredPlugins.map((plugin) => (
                  <label key={plugin.id} className="flex items-center gap-1.5 text-xs text-ink">
                    <input
                      type="checkbox"
                      checked={draft.pluginIds.includes(plugin.id)}
                      onChange={() => toggle('pluginIds', plugin.id)}
                    />
                    {plugin.name}
                    {plugin.sensitive && (
                      <Badge tone="warning">{t('plugins.sensitive')}</Badge>
                    )}
                  </label>
                ))}
              </div>
            </Field>
          )}
          <Field label={t('agents.visibility')}>
            <select
              className="h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink"
              value={draft.visibility}
              onChange={(event) =>
                update('visibility', event.target.value as 'private' | 'shared')
              }
            >
              <option value="private">{t('agents.private')}</option>
              <option value="shared">{t('agents.shared')}</option>
            </select>
          </Field>
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
    <div className="block">
      <span className="mb-1 block text-xs text-ink-muted">{label}</span>
      {children}
    </div>
  )
}