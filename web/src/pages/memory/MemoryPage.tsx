import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Brain,
  ListChecks,
  Pencil,
  Pin,
  Plus,
  Star,
  Trash2,
} from 'lucide-react'
import { useState } from 'react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { EmptyState } from '../../components/ui/empty-state'
import { Spinner } from '../../components/ui/spinner'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  AgentMemory,
  CustomAgent,
  MemoryCandidate,
  MemoryCategory,
  MemoryLifecycle,
  MemorySettings,
  MemoryStats,
  MemoryStatus,
  MemoryUsage,
  Project,
} from '../../lib/types'
import { cn } from '../../lib/utils'
import { MemoryDetailDialog } from './MemoryDetailDialog'
import { MemoryFormDialog } from './MemoryFormDialog'
import { MemoryGraphPanel } from './MemoryGraphPanel'
import { MemoryQualityPanel } from './MemoryQualityPanel'
import { MemorySettingsPanel } from './MemorySettingsPanel'

type Tab =
  | 'overview'
  | 'all'
  | 'graph'
  | 'quality'
  | 'pending'
  | 'usage'
  | 'settings'

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

const STATUSES: MemoryStatus[] = [
  'active',
  'candidate',
  'conflict',
  'expired',
  'archived',
  'rejected',
]

export function MemoryPage() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<Tab>('overview')
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [status, setStatus] = useState('')
  const [scopeType, setScopeType] = useState('')
  const [projectFilter, setProjectFilter] = useState('')
  const [agentFilter, setAgentFilter] = useState('')
  const [favoriteOnly, setFavoriteOnly] = useState(false)
  const [editing, setEditing] = useState<AgentMemory | null | undefined>()
  const [detail, setDetail] = useState<AgentMemory | null>(null)

  const stats = useQuery({
    queryKey: ['memory-stats'],
    queryFn: () => apiRequest<MemoryStats>('/memories/stats'),
  })
  const settings = useQuery({
    queryKey: ['memory-settings'],
    queryFn: () => apiRequest<MemorySettings>('/memories/settings'),
  })
  const projects = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiRequest<Project[]>('/projects'),
  })
  const agents = useQuery({
    queryKey: ['agents', 'memory-options'],
    queryFn: () => apiRequest<CustomAgent[]>('/agents?scope=mine'),
    staleTime: 60_000,
  })
  const usage = useQuery({
    queryKey: ['memory-usage'],
    queryFn: () => apiRequest<MemoryUsage[]>('/memories/usage?limit=100'),
    enabled: tab === 'usage',
  })
  const candidates = useQuery({
    queryKey: ['memory-candidates'],
    queryFn: () =>
      apiRequest<MemoryCandidate[]>('/memories/candidates?status=pending'),
    enabled: tab === 'pending',
  })
  const effectiveStatus = tab === 'pending' ? 'candidate' : status
  const memories = useQuery({
    queryKey: [
      'memories',
      search,
      category,
      effectiveStatus,
      scopeType,
      projectFilter,
      agentFilter,
      favoriteOnly,
    ],
    queryFn: () =>
      apiRequest<AgentMemory[]>(
        `/memories?${new URLSearchParams({
          ...(search.trim() !== '' ? { q: search.trim() } : {}),
          ...(category !== '' ? { category } : {}),
          ...(effectiveStatus !== '' ? { status: effectiveStatus } : {}),
          ...(scopeType !== '' ? { scope_type: scopeType } : {}),
          ...(projectFilter !== '' ? { project_id: projectFilter } : {}),
          ...(agentFilter !== '' ? { agent_id: agentFilter } : {}),
          ...(favoriteOnly ? { favorite: 'true' } : {}),
        }).toString()}`,
      ),
    enabled: tab === 'all',
  })

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['memories'] }),
      queryClient.invalidateQueries({ queryKey: ['memory-stats'] }),
      queryClient.invalidateQueries({ queryKey: ['memory-usage'] }),
      queryClient.invalidateQueries({ queryKey: ['memory-lifecycle'] }),
    ])
  }

  const toggleFlag = async (memory: AgentMemory, key: 'pinned' | 'favorite') => {
    await apiRequest(`/memories/${memory.id}`, {
      method: 'PATCH',
      body: { [key]: !memory[key] },
    })
    await refresh()
  }

  const reviewCandidate = async (
    candidate: MemoryCandidate,
    action: 'accept' | 'reject',
  ) => {
    await apiRequest(`/memories/candidates/${candidate.id}/${action}`, {
      method: 'POST',
      ...(action === 'accept' ? { body: {} } : {}),
    })
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['memory-candidates'] }),
      refresh(),
    ])
  }

  const remove = async (memory: AgentMemory) => {
    if (!window.confirm(t('memory.deleteConfirm'))) return
    await apiRequest(`/memories/${memory.id}`, { method: 'DELETE' })
    if (detail?.id === memory.id) setDetail(null)
    await refresh()
  }

  const openMemoryById = async (memoryId: string) => {
    const memory = await apiRequest<AgentMemory>(`/memories/${memoryId}`)
    setDetail(memory)
  }

  const rows = memories.data ?? []
  const agentOptions = (agents.data ?? []).filter((agent) => !agent.builtin)

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-surface px-6 py-4">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            <Brain className="h-4 w-4 text-accent" />
            {t('memory.title')}
          </h1>
          <p className="mt-1 text-sm text-ink-muted">{t('memory.lead')}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {settings.data !== undefined && !settings.data.enabled && (
            <Badge tone="warning">{t('memory.settings.off')}</Badge>
          )}
          <Button size="sm" onClick={() => setEditing(null)}>
            <Plus className="h-3.5 w-3.5" />
            {t('memory.new')}
          </Button>
        </div>
      </header>

      <nav className="flex flex-wrap gap-1 border-b border-border bg-surface px-6">
        {(['overview', 'all', 'graph', 'quality', 'pending', 'usage', 'settings'] as const).map((item) => (
          <button
            key={item}
            type="button"
            onClick={() => setTab(item)}
            className={cn(
              'rounded-t-md px-3 py-2 text-xs',
              tab === item
                ? 'border-b-2 border-accent text-accent'
                : 'text-ink-muted hover:text-ink',
            )}
          >
            {t(`memory.tab.${item}`)}
          </button>
        ))}
      </nav>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
        {tab === 'overview' && (
          <Overview
            stats={stats.data}
            loading={stats.isLoading}
            agents={agentOptions}
            projects={projects.data ?? []}
            onOpen={setDetail}
          />
        )}

        {tab === 'all' && (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-2">
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder={t('memory.search')}
                className="h-9 w-full max-w-sm rounded-lg border border-border bg-surface px-3 text-sm text-ink focus:border-accent focus:outline-none"
              />
              <select
                value={category}
                onChange={(event) => setCategory(event.target.value)}
                className="h-9 rounded-lg border border-border bg-surface px-2 text-sm text-ink"
              >
                <option value="">{t('memory.allCategories')}</option>
                {CATEGORIES.map((item) => (
                  <option key={item} value={item}>
                    {t(`memory.category.${item}`)}
                  </option>
                ))}
              </select>
              <>
                <select
                  value={status}
                    onChange={(event) => setStatus(event.target.value)}
                    className="h-9 rounded-lg border border-border bg-surface px-2 text-sm text-ink"
                  >
                    <option value="">{t('memory.allStatuses')}</option>
                    {STATUSES.map((item) => (
                      <option key={item} value={item}>
                        {t(`memory.status.${item}`)}
                      </option>
                    ))}
                  </select>
                  <select
                    value={projectFilter}
                    onChange={(event) => setProjectFilter(event.target.value)}
                    className="h-9 rounded-lg border border-border bg-surface px-2 text-sm text-ink"
                  >
                    <option value="">{t('memory.allProjects')}</option>
                    {(projects.data ?? []).map((project) => (
                      <option key={project.id} value={project.id}>
                        {project.name}
                      </option>
                    ))}
                  </select>
                </>
              <select
                value={scopeType}
                onChange={(event) => setScopeType(event.target.value)}
                className="h-9 rounded-lg border border-border bg-surface px-2 text-sm text-ink"
              >
                <option value="">{t('memory.allScopes')}</option>
                <option value="global">{t('memory.scopeType.global')}</option>
                <option value="project">{t('memory.scopeType.project')}</option>
                <option value="agent">{t('memory.scopeType.agent')}</option>
              </select>
              <select
                value={agentFilter}
                onChange={(event) => setAgentFilter(event.target.value)}
                className="h-9 rounded-lg border border-border bg-surface px-2 text-sm text-ink"
              >
                <option value="">{t('memory.allAgents')}</option>
                {agentOptions.map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.icon} {agent.name}
                  </option>
                ))}
              </select>
              <label className="flex items-center gap-2 text-xs text-ink-muted">
                <input
                  type="checkbox"
                  checked={favoriteOnly}
                  onChange={(event) => setFavoriteOnly(event.target.checked)}
                />
                {t('memory.favoriteOnly')}
              </label>
            </div>

            {memories.isLoading && <Spinner />}
            {!memories.isLoading && rows.length === 0 && (
              <EmptyState
                title={t('memory.empty')}
                description={t('memory.emptyLead')}
              />
            )}
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {rows.map((memory) => (
                <MemoryCard
                  key={memory.id}
                  memory={memory}
                  onOpen={() => setDetail(memory)}
                  onEdit={() => setEditing(memory)}
                  onDelete={() => void remove(memory)}
                  onToggle={(key) => void toggleFlag(memory, key)}
                />
              ))}
            </div>
          </div>
        )}

        {tab === 'graph' && (
          <MemoryGraphPanel
            onOpenMemory={(memoryId) => void openMemoryById(memoryId)}
          />
        )}

        {tab === 'quality' && <MemoryQualityPanel />}

        {tab === 'pending' && (
          <div className="space-y-3">
            {candidates.isLoading && <Spinner />}
            {!candidates.isLoading && (candidates.data ?? []).length === 0 && (
              <EmptyState
                title={t('memory.pendingEmpty')}
                description={t('memory.pendingEmptyLead')}
              />
            )}
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {(candidates.data ?? []).map((candidate) => (
                <CandidateCard
                  key={candidate.id}
                  candidate={candidate}
                  onAccept={() => void reviewCandidate(candidate, 'accept')}
                  onReject={() => void reviewCandidate(candidate, 'reject')}
                />
              ))}
            </div>
          </div>
        )}

        {tab === 'usage' && (
          <div className="rounded-card border border-border bg-surface">
            {usage.isLoading ? (
              <div className="flex justify-center py-10">
                <Spinner />
              </div>
            ) : (usage.data ?? []).length === 0 ? (
              <EmptyState
                title={t('memory.usageEmpty')}
                description={t('memory.usageEmptyLead')}
              />
            ) : (
              <table className="w-full text-left text-xs">
                <thead className="text-ink-muted">
                  <tr>
                    <th className="px-4 py-2 font-medium">{t('memory.memoryTitle')}</th>
                    <th className="px-4 py-2 font-medium">{t('memory.usageContext')}</th>
                    <th className="px-4 py-2 font-medium">{t('memory.usageModel')}</th>
                    <th className="px-4 py-2 font-medium">{t('memory.usageChars')}</th>
                    <th className="px-4 py-2 font-medium">{t('memory.usageTime')}</th>
                  </tr>
                </thead>
                <tbody>
                  {(usage.data ?? []).map((item) => (
                    <tr key={item.id} className="border-t border-border">
                      <td className="px-4 py-2 text-ink">
                        {item.memory_title || item.memory_id.slice(0, 8)}
                      </td>
                      <td className="px-4 py-2 text-ink-muted">
                        {item.context_type}
                        {item.context_id ? ` · ${item.context_id.slice(0, 8)}` : ''}
                      </td>
                      <td className="px-4 py-2 text-ink-muted">
                        {item.provider_id ?? '—'} / {item.model ?? '—'}
                      </td>
                      <td className="px-4 py-2 text-ink-muted">
                        {item.injected_chars}
                      </td>
                      <td className="px-4 py-2 text-ink-muted">
                        {new Date(item.created_at).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {tab === 'settings' && <MemorySettingsPanel />}
      </div>

      <MemoryFormDialog
        key={editing === null ? 'new' : (editing?.id ?? 'closed')}
        open={editing !== undefined}
        initial={editing ?? null}
        projects={projects.data ?? []}
        agents={agentOptions}
        onClose={() => setEditing(undefined)}
        onSaved={() => {
          setEditing(undefined)
          void refresh()
        }}
      />

      <MemoryDetailDialog
        memory={detail}
        onClose={() => setDetail(null)}
        onEdit={(memory) => {
          setDetail(null)
          setEditing(memory)
        }}
        onChanged={() => void refresh()}
      />
    </div>
  )
}

function Overview({
  stats,
  loading,
  agents,
  projects,
  onOpen,
}: {
  stats: MemoryStats | undefined
  loading: boolean
  agents: CustomAgent[]
  projects: Project[]
  onOpen: (memory: AgentMemory) => void
}) {
  const { t } = useI18n()
  const lifecycle = useQuery({
    queryKey: ['memory-lifecycle'],
    queryFn: () => apiRequest<MemoryLifecycle>('/memories/lifecycle'),
  })
  if (loading || stats === undefined) {
    return (
      <div className="flex justify-center py-10">
        <Spinner />
      </div>
    )
  }
  const completeness = stats.completeness
  const agentNames = new Map(agents.map((agent) => [agent.id, agent.name]))
  const projectNames = new Map(projects.map((project) => [project.id, project.name]))
  const cards = [
    { label: t('memory.stats.total'), value: stats.total, tone: 'accent' },
    { label: t('memory.stats.active'), value: stats.active, tone: 'success' },
    {
      label: t('memory.stats.pending'),
      value: stats.pending + (stats.candidates_pending ?? 0),
      tone: 'warning',
    },
    { label: t('memory.stats.conflict'), value: stats.conflict, tone: 'danger' },
    {
      label: t('memory.stats.completeness'),
      value: `${Math.round(completeness?.average_score ?? 0)}%`,
      tone: 'accent',
    },
    {
      label: t('memory.stats.expiringSoon'),
      value: stats.expiring_soon ?? 0,
      tone: 'warning',
    },
    { label: t('memory.stats.stale'), value: stats.stale ?? 0, tone: 'neutral' },
    {
      label: t('memory.stats.usageTotal'),
      value: stats.usage_total ?? 0,
      tone: 'success',
    },
  ] as const
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map((card) => (
          <div
            key={card.label}
            className="rounded-card border border-border bg-surface p-4"
          >
            <p className="text-[11px] uppercase tracking-wide text-ink-muted">
              {card.label}
            </p>
            <p className="mt-1 text-2xl font-semibold text-ink">{card.value}</p>
            <Badge tone={card.tone} className="mt-2">
              {t('memory.stats.card')}
            </Badge>
          </div>
        ))}
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <section className="rounded-card border border-border bg-surface p-4">
          <h2 className="flex items-center gap-2 text-sm font-medium text-ink">
            <ListChecks className="h-4 w-4" />
            {t('memory.stats.byCategory')}
          </h2>
          <div className="mt-2 space-y-1">
            {Object.entries(stats.by_category).length === 0 && (
              <p className="text-xs text-ink-muted">—</p>
            )}
            {Object.entries(stats.by_category).map(([key, value]) => (
              <div key={key} className="flex items-center gap-2 text-xs">
                <span className="w-24 text-ink-muted">
                  {t(`memory.category.${key}` as 'memory.category.fact')}
                </span>
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-muted">
                  <div
                    className="h-full bg-accent"
                    style={{
                      width: `${Math.min(
                        (value / Math.max(stats.total, 1)) * 100,
                        100,
                      )}%`,
                    }}
                  />
                </div>
                <span className="text-ink-muted">{value}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-card border border-border bg-surface p-4">
          <h2 className="flex items-center gap-2 text-sm font-medium text-ink">
            <Star className="h-4 w-4" />
            {t('memory.stats.topUsed')}
          </h2>
          <div className="mt-2 space-y-1">
            {stats.top_used.length === 0 && (
              <p className="text-xs text-ink-muted">—</p>
            )}
            {stats.top_used.map((memory) => (
              <button
                key={memory.id}
                type="button"
                onClick={() => onOpen(memory)}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-xs hover:bg-surface-muted"
              >
                <span className="min-w-0 flex-1 truncate text-ink">
                  {memory.title || memory.content.slice(0, 40)}
                </span>
                <span className="text-ink-muted">{memory.use_count}</span>
              </button>
            ))}
          </div>
        </section>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <section className="rounded-card border border-border bg-surface p-4">
          <h2 className="text-sm font-medium text-ink">
            {t('memory.stats.completenessTitle')}
          </h2>
          <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
            {(
              [
                ['complete', completeness?.complete ?? 0],
                ['partial', completeness?.partial ?? 0],
                ['sparse', completeness?.sparse ?? 0],
              ] as const
            ).map(([key, value]) => (
              <div key={key} className="rounded-lg bg-surface-muted px-2 py-1.5">
                <p className="text-[10px] text-ink-muted">
                  {t(`memory.stats.completenessLevel.${key}`)}
                </p>
                <p className="mt-0.5 font-semibold text-ink">{value}</p>
              </div>
            ))}
          </div>
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-surface-muted">
            <div
              className="h-full bg-accent"
              style={{ width: `${Math.min(completeness?.average_score ?? 0, 100)}%` }}
            />
          </div>
          <p className="mt-1 text-[11px] text-ink-muted">
            {t('memory.stats.averageCompleteness', {
              score: Math.round(completeness?.average_score ?? 0),
            })}
          </p>
          {Object.keys(stats.by_source ?? {}).length > 0 && (
            <p className="mt-2 text-[10px] text-ink-muted">
              {Object.entries(stats.by_source ?? {})
                .map(([key, value]) => `${key}: ${value}`)
                .join(' · ')}
            </p>
          )}
        </section>

        <section className="rounded-card border border-border bg-surface p-4">
          <h2 className="text-sm font-medium text-ink">
            {t('memory.stats.usageTitle')}
          </h2>
          <p className="mt-1 text-[11px] text-ink-muted">
            {t('memory.stats.usageSummary', {
              total: stats.usage_total ?? 0,
              chars: stats.usage_chars ?? 0,
            })}
          </p>
          <div className="mt-2 space-y-1">
            {(stats.usage_by_model ?? []).length === 0 && (
              <p className="text-xs text-ink-muted">—</p>
            )}
            {(stats.usage_by_model ?? []).map((item) => (
              <div
                key={`${item.provider_id}/${item.model}`}
                className="flex items-center justify-between text-xs"
              >
                <span className="truncate text-ink-muted">
                  {item.provider_id}/{item.model}
                </span>
                <span className="text-ink">{item.count}</span>
              </div>
            ))}
          </div>
          {Object.keys(stats.usage_by_context ?? {}).length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {Object.entries(stats.usage_by_context ?? {}).map(([key, value]) => (
                <Badge key={key} tone="neutral">
                  {key}: {value}
                </Badge>
              ))}
            </div>
          )}
          {(stats.usage_by_agent ?? []).length > 0 && (
            <div className="mt-2">
              <p className="text-[10px] font-medium text-ink">
                {t('memory.stats.byAgent')}
              </p>
              {(stats.usage_by_agent ?? []).slice(0, 3).map((item) => (
                <p key={item.agent_id ?? 'none'} className="text-[10px] text-ink-muted">
                  {item.agent_id
                    ? agentNames.get(item.agent_id) ??
                      item.agent_id.slice(0, 8)
                    : t('memory.stats.noAgent')}
                  : {item.count}
                </p>
              ))}
            </div>
          )}
          {(stats.usage_by_project ?? []).length > 0 && (
            <div className="mt-2">
              <p className="text-[10px] font-medium text-ink">
                {t('memory.stats.byProject')}
              </p>
              {(stats.usage_by_project ?? []).slice(0, 3).map((item) => (
                <p
                  key={item.project_id ?? 'none'}
                  className="text-[10px] text-ink-muted"
                >
                  {item.project_id
                    ? projectNames.get(item.project_id) ??
                      item.project_id.slice(0, 8)
                    : t('memory.stats.noProject')}
                  : {item.count}
                </p>
              ))}
            </div>
          )}
          {(stats.usage_by_conversation ?? []).length > 0 && (
            <div className="mt-2">
              <p className="text-[10px] font-medium text-ink">
                {t('memory.stats.byConversation')}
              </p>
              {(stats.usage_by_conversation ?? []).slice(0, 3).map((item) => (
                <p
                  key={item.context_id ?? 'none'}
                  className="text-[10px] text-ink-muted"
                >
                  {item.context_id ? item.context_id.slice(0, 8) : '—'}: {item.count}
                </p>
              ))}
            </div>
          )}
        </section>
      </div>

      {lifecycle.data !== undefined && lifecycle.data.retention_days !== null && (
        <section className="rounded-card border border-border bg-surface p-4">
          <h2 className="text-sm font-medium text-ink">
            {t('memory.stats.lifecycleTitle')}
          </h2>
          <p className="mt-1 text-[11px] text-ink-muted">
            {t('memory.stats.lifecycleLead', {
              days: lifecycle.data.retention_days,
              count: lifecycle.data.expiring_count,
            })}
          </p>
          {lifecycle.data.items.length > 0 && (
            <ul className="mt-2 space-y-1">
              {lifecycle.data.items.slice(0, 5).map((item) => (
                <li
                  key={item.id}
                  className="flex items-center justify-between rounded-md bg-surface-muted px-2 py-1 text-[11px]"
                >
                  <span className="truncate text-ink">{item.title}</span>
                  <span className="ml-2 text-ink-muted">
                    {t('memory.stats.lifecycleItem', {
                      days: item.retention_days,
                    })}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <section className="rounded-card border border-border bg-surface p-4">
        <h2 className="text-sm font-medium text-ink">{t('memory.stats.recent')}</h2>
        <div className="mt-2 grid gap-2 md:grid-cols-2">
          {stats.recent.map((memory) => (
            <button
              key={memory.id}
              type="button"
              onClick={() => onOpen(memory)}
              className="rounded-lg bg-surface-muted px-3 py-2 text-left hover:bg-surface"
            >
              <p className="truncate text-xs font-medium text-ink">
                {memory.title || memory.content.slice(0, 40)}
              </p>
              <p className="mt-0.5 truncate text-[11px] text-ink-muted">
                {memory.content}
              </p>
            </button>
          ))}
        </div>
      </section>
    </div>
  )
}

function CandidateCard({
  candidate,
  onAccept,
  onReject,
}: {
  candidate: MemoryCandidate
  onAccept: () => void
  onReject: () => void
}) {
  const { t } = useI18n()
  return (
    <article className="flex flex-col rounded-2xl border border-dashed border-accent/40 bg-surface p-4">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge tone="accent">{t(`memory.category.${candidate.category}`)}</Badge>
        <Badge tone="neutral">{t(`memory.scopeType.${candidate.scope_type}`)}</Badge>
        <Badge tone={candidate.suggested_action === 'update' ? 'warning' : 'neutral'}>
          {candidate.suggested_action}
        </Badge>
        <span className="ml-auto text-[10px] text-ink-muted">
          {(candidate.confidence * 100).toFixed(0)}%
        </span>
      </div>
      <p className="mt-2 text-sm font-medium text-ink">
        {candidate.title || candidate.content.slice(0, 40)}
      </p>
      <p className="mt-1 line-clamp-4 whitespace-pre-wrap text-xs text-ink-muted">
        {candidate.content}
      </p>
      {candidate.reason !== '' && (
        <p className="mt-1 text-[10px] text-ink-muted">{candidate.reason}</p>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {candidate.tags.map((tag) => (
          <Badge key={tag} tone="neutral">
            {tag}
          </Badge>
        ))}
        <div className="ml-auto flex gap-1">
          <Button size="sm" onClick={onAccept}>
            {t('memory.candidate.accept')}
          </Button>
          <Button size="sm" variant="secondary" onClick={onReject}>
            {t('memory.candidate.reject')}
          </Button>
        </div>
      </div>
    </article>
  )
}

function MemoryCard({
  memory,
  onOpen,
  onEdit,
  onDelete,
  onToggle,
}: {
  memory: AgentMemory
  onOpen: () => void
  onEdit: () => void
  onDelete: () => void
  onToggle: (key: 'pinned' | 'favorite') => void
}) {
  const { t } = useI18n()
  return (
    <article className="flex flex-col rounded-2xl border border-border bg-surface p-4">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge tone="accent">{t(`memory.category.${memory.category}`)}</Badge>
        <Badge tone="neutral">{t(`memory.scopeType.${memory.scope_type}`)}</Badge>
        {memory.status !== 'active' && (
          <Badge tone={memory.status === 'conflict' ? 'danger' : 'neutral'}>
            {t(`memory.status.${memory.status}`)}
          </Badge>
        )}
        <div className="ml-auto flex gap-0.5">
          <Button
            size="sm"
            variant="ghost"
            aria-label={t('memory.pinned')}
            onClick={() => onToggle('pinned')}
          >
            <Pin
              className={cn(
                'h-3 w-3',
                memory.pinned ? 'text-accent' : 'text-ink-muted',
              )}
            />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label={t('memory.favorite')}
            onClick={() => onToggle('favorite')}
          >
            <Star
              className={cn(
                'h-3 w-3',
                memory.favorite ? 'text-warning' : 'text-ink-muted',
              )}
            />
          </Button>
        </div>
      </div>
      <button type="button" onClick={onOpen} className="mt-2 text-left">
        <p className="text-sm font-medium text-ink">
          {memory.title || memory.content.slice(0, 40)}
        </p>
        <p className="mt-1 line-clamp-4 whitespace-pre-wrap text-xs text-ink-muted">
          {memory.content}
        </p>
      </button>
      <div className="mt-3 flex flex-wrap items-center gap-1">
        {memory.tags.slice(0, 4).map((tag) => (
          <Badge key={tag} tone="neutral">
            {tag}
          </Badge>
        ))}
        {!memory.enabled && <Badge tone="danger">{t('memory.disabled')}</Badge>}
      </div>
      <div className="mt-3 flex items-center gap-2 text-[10px] text-ink-muted">
        <span>{'★'.repeat(memory.importance)}</span>
        <span>v{memory.version}</span>
        <span>{new Date(memory.updated_at).toLocaleDateString()}</span>
        <div className="ml-auto flex gap-1">
          <Button size="sm" variant="ghost" onClick={onEdit}>
            <Pencil className="h-3 w-3" />
          </Button>
          <Button size="sm" variant="ghost" onClick={onDelete}>
            <Trash2 className="h-3 w-3" />
          </Button>
        </div>
      </div>
    </article>
  )
}