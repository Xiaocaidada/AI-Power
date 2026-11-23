import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Brain, MessageSquare, Pencil, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Spinner } from '../../components/ui/spinner'
import { formatDate } from '../../lib/format'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  AgentMemory,
  Conversation,
  CustomAgent,
  KnowledgeBase,
  Project,
} from '../../lib/types'
import { MemoryFormDialog } from '../memory/MemoryFormDialog'

export function ProjectDetailPage() {
  const { id = '' } = useParams<{ id: string }>()
  const { t, language } = useI18n()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<AgentMemory | null | undefined>()

  const project = useQuery({
    queryKey: ['project', id],
    queryFn: () => apiRequest<Project>(`/projects/${id}`),
    enabled: id !== '',
  })
  const conversations = useQuery({
    queryKey: ['conversations', 'project', id],
    queryFn: () =>
      apiRequest<Conversation[]>(`/conversations?project_id=${id}&limit=50`),
    enabled: id !== '',
  })
  const kbs = useQuery({
    queryKey: ['kbs'],
    queryFn: () => apiRequest<KnowledgeBase[]>('/knowledge-bases'),
    staleTime: 60_000,
  })
  const memories = useQuery({
    queryKey: ['memories', 'project', id],
    queryFn: () =>
      apiRequest<AgentMemory[]>(
        `/memories?${new URLSearchParams({
          scope_type: 'project',
          project_id: id,
          limit: '50',
        }).toString()}`,
      ),
    enabled: id !== '',
  })
  const agents = useQuery({
    queryKey: ['agents', 'project-memory-options'],
    queryFn: () => apiRequest<CustomAgent[]>('/agents?scope=mine'),
    staleTime: 60_000,
  })

  if (project.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner className="h-6 w-6 text-accent" />
      </div>
    )
  }

  if (project.isError || project.data === undefined) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3">
        <p className="text-sm text-ink-muted">{t('projects.missing')}</p>
        <Button variant="secondary" onClick={() => navigate('/projects')}>
          {t('projects.back')}
        </Button>
      </div>
    )
  }

  const detail = project.data
  const kbName =
    kbs.data?.find((kb) => kb.id === detail.default_kb_id)?.name ??
    t('chat.noKnowledgeBase')
  const agentOptions = (agents.data ?? []).filter((agent) => !agent.builtin)
  const refreshMemories = async () => {
    await queryClient.invalidateQueries({ queryKey: ['memories'] })
    await queryClient.invalidateQueries({ queryKey: ['memory-stats'] })
  }
  const updateMemoryPermissions = async (
    patch: Partial<
      Pick<Project, 'memory_enabled' | 'allow_global_memory' | 'allow_agent_writes'>
    >,
  ) => {
    await apiRequest(`/projects/${detail.id}`, { method: 'PATCH', body: patch })
    await queryClient.invalidateQueries({ queryKey: ['project', detail.id] })
  }
  const removeMemory = async (memory: AgentMemory) => {
    if (!window.confirm(t('memory.deleteConfirm'))) return
    await apiRequest(`/memories/${memory.id}`, { method: 'DELETE' })
    await refreshMemories()
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-5">
        <Link
          to="/projects"
          className="inline-flex items-center gap-1 text-xs text-ink-muted hover:text-ink"
        >
          <ArrowLeft className="h-3 w-3" />
          {t('projects.back')}
        </Link>
        <div className="mt-3 flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold text-ink">{detail.name}</h1>
              {detail.archived && <Badge tone="neutral">{t('projects.archived')}</Badge>}
            </div>
            <p className="mt-1 text-sm text-ink-muted">
              {detail.description || t('projects.noDescription')}
            </p>
          </div>
          <Button onClick={() => navigate(`/chat?project=${detail.id}`)}>
            <MessageSquare className="h-4 w-4" />
            {t('projects.newChat')}
          </Button>
        </div>
      </header>

      <div className="grid gap-5 px-6 py-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <section className="space-y-4">
          <div className="rounded-2xl border border-border bg-surface p-5">
            <h2 className="text-sm font-semibold text-ink">{t('projects.instructions')}</h2>
            <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-ink-muted">
              {detail.instructions || t('projects.noInstructions')}
            </p>
          </div>

          <div className="rounded-2xl border border-border bg-surface">
            <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-3">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-ink">
                <Brain className="h-4 w-4 text-accent" />
                {t('projects.memoryTitle')}
              </h2>
              <Button size="sm" variant="secondary" onClick={() => setEditing(null)}>
                <Plus className="h-3.5 w-3.5" />
                {t('projects.addMemory')}
              </Button>
            </div>
            <div className="divide-y divide-border">
              {(memories.data ?? []).map((memory) => (
                <div key={memory.id} className="flex items-start gap-3 px-5 py-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge tone="accent">
                        {t(`memory.category.${memory.category}`)}
                      </Badge>
                      <Badge tone="neutral">
                        {t(`memory.status.${memory.status}`)}
                      </Badge>
                      {!memory.enabled && (
                        <Badge tone="danger">{t('memory.disabled')}</Badge>
                      )}
                    </div>
                    <p className="mt-1 truncate text-sm text-ink">
                      {memory.title || memory.content.slice(0, 60)}
                    </p>
                    <p className="mt-0.5 line-clamp-2 text-xs text-ink-muted">
                      {memory.content}
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={t('memory.edit')}
                      onClick={() => setEditing(memory)}
                    >
                      <Pencil className="h-3 w-3" />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={t('common.delete')}
                      onClick={() => void removeMemory(memory)}
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                </div>
              ))}
              {memories.data !== undefined && memories.data.length === 0 && (
                <p className="px-5 py-8 text-center text-sm text-ink-muted">
                  {t('projects.noMemories')}
                </p>
              )}
            </div>
          </div>

          <div className="rounded-2xl border border-border bg-surface">
            <h2 className="border-b border-border px-5 py-3 text-sm font-semibold text-ink">
              {t('projects.conversationsTitle')}
            </h2>
            <div className="divide-y divide-border">
              {(conversations.data ?? []).map((conversation) => (
                <Link
                  key={conversation.id}
                  to={`/chat/${conversation.id}`}
                  className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-surface-muted"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm text-ink">
                      {conversation.title || t('chat.newConversation')}
                    </p>
                    <p className="truncate text-xs text-ink-muted">
                      {conversation.provider_id} · {conversation.model}
                    </p>
                  </div>
                  <span className="shrink-0 text-xs text-ink-muted">
                    {formatDate(conversation.updated_at ?? conversation.created_at, language)}
                  </span>
                </Link>
              ))}
              {conversations.data !== undefined && conversations.data.length === 0 && (
                <p className="px-5 py-8 text-center text-sm text-ink-muted">
                  {t('projects.noConversations')}
                </p>
              )}
            </div>
          </div>
        </section>

        <aside className="space-y-4">
          <div className="rounded-2xl border border-border bg-surface p-5">
            <h2 className="text-sm font-semibold text-ink">{t('projects.defaults')}</h2>
            <dl className="mt-3 space-y-3 text-xs">
              <div>
                <dt className="text-ink-muted">{t('chat.model')}</dt>
                <dd className="mt-1 font-mono text-ink">
                  {detail.default_provider_id ?? t('models.auto')}
                  {detail.default_model !== null ? ` · ${detail.default_model}` : ''}
                </dd>
              </div>
              <div>
                <dt className="text-ink-muted">{t('projects.defaultKb')}</dt>
                <dd className="mt-1 text-ink">{kbName}</dd>
              </div>
              <div>
                <dt className="text-ink-muted">{t('chat.agentMode')}</dt>
                <dd className="mt-1 text-ink">
                  {detail.default_agent ? t('common.yes') : t('common.no')}
                </dd>
              </div>
              <div>
                <dt className="text-ink-muted">{t('projects.createdAt')}</dt>
                <dd className="mt-1 text-ink">{formatDate(detail.created_at, language)}</dd>
              </div>
            </dl>
          </div>

          <div className="rounded-2xl border border-border bg-surface p-5">
            <h2 className="text-sm font-semibold text-ink">
              {t('projects.memoryPermissions')}
            </h2>
            <p className="mt-1 text-[11px] text-ink-muted">
              {t('projects.memoryPermissionsHint')}
            </p>
            <div className="mt-3 space-y-3 text-xs">
              <label className="block text-ink-muted">
                {t('projects.memoryEnabled')}
                <select
                  className="mt-1 h-9 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink"
                  value={
                    detail.memory_enabled === null
                      ? 'inherit'
                      : detail.memory_enabled
                        ? 'on'
                        : 'off'
                  }
                  disabled={!detail.owned}
                  onChange={(event) =>
                    void updateMemoryPermissions({
                      memory_enabled:
                        event.target.value === 'inherit'
                          ? null
                          : event.target.value === 'on',
                    })
                  }
                >
                  <option value="inherit">{t('projects.memoryInherit')}</option>
                  <option value="on">{t('common.yes')}</option>
                  <option value="off">{t('common.no')}</option>
                </select>
              </label>
              <label className="flex items-start gap-2 text-ink">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={detail.allow_global_memory}
                  disabled={!detail.owned}
                  onChange={(event) =>
                    void updateMemoryPermissions({
                      allow_global_memory: event.target.checked,
                    })
                  }
                />
                <span>
                  {t('projects.allowGlobalMemory')}
                  <span className="mt-0.5 block text-[10px] text-ink-muted">
                    {t('projects.allowGlobalMemoryHint')}
                  </span>
                </span>
              </label>
              <label className="flex items-start gap-2 text-ink">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={detail.allow_agent_writes}
                  disabled={!detail.owned}
                  onChange={(event) =>
                    void updateMemoryPermissions({
                      allow_agent_writes: event.target.checked,
                    })
                  }
                />
                <span>
                  {t('projects.allowAgentWrites')}
                  <span className="mt-0.5 block text-[10px] text-ink-muted">
                    {t('projects.allowAgentWritesHint')}
                  </span>
                </span>
              </label>
            </div>
          </div>
        </aside>
      </div>

      <MemoryFormDialog
        key={editing === null ? `new-${detail.id}` : (editing?.id ?? 'closed')}
        open={editing !== undefined}
        initial={editing ?? null}
        projects={[detail]}
        agents={agentOptions}
        defaultScopeType="project"
        defaultProjectId={detail.id}
        onClose={() => setEditing(undefined)}
        onSaved={() => {
          setEditing(undefined)
          void refreshMemories()
        }}
      />
    </div>
  )
}