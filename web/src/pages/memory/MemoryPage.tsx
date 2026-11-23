import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Brain, Pencil, Plus, Trash2 } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { Input, Textarea } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { AgentMemory, CustomAgent } from '../../lib/types'

type Scope = 'user' | 'workspace'
type Kind = 'fact' | 'preference' | 'summary'

interface Draft {
  title: string
  content: string
  scope: Scope
  kind: Kind
  agentId: string
  importance: number
}

function draftFrom(memory: AgentMemory | null): Draft {
  return {
    title: memory?.title ?? '',
    content: memory?.content ?? '',
    scope: memory?.scope ?? 'user',
    kind: memory?.kind ?? 'fact',
    agentId: memory?.agent_id ?? '',
    importance: memory?.importance ?? 3,
  }
}

export function MemoryPage() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [scope, setScope] = useState<'' | Scope>('')
  const [agentFilter, setAgentFilter] = useState('')
  const [editing, setEditing] = useState<AgentMemory | null | undefined>()

  const memories = useQuery({
    queryKey: ['memories', search, scope, agentFilter],
    queryFn: () =>
      apiRequest<AgentMemory[]>(
        `/memories?${new URLSearchParams({
          ...(search.trim() !== '' ? { q: search.trim() } : {}),
          ...(scope !== '' ? { scope } : {}),
          ...(agentFilter !== '' ? { agent_id: agentFilter } : {}),
        }).toString()}`,
      ),
  })
  const agents = useQuery({
    queryKey: ['agents', 'memory-options'],
    queryFn: () => apiRequest<CustomAgent[]>('/agents?scope=mine'),
    staleTime: 60_000,
  })

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['memories'] })

  const remove = async (memory: AgentMemory) => {
    if (!window.confirm(t('memory.deleteConfirm'))) return
    await apiRequest(`/memories/${memory.id}`, { method: 'DELETE' })
    await refresh()
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-surface px-6 py-4">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            <Brain className="h-4 w-4 text-accent" />
            {t('memory.title')}
          </h1>
          <p className="mt-1 text-sm text-ink-muted">{t('memory.lead')}</p>
        </div>
        <Button size="sm" onClick={() => setEditing(null)}>
          <Plus className="h-3.5 w-3.5" />
          {t('memory.new')}
        </Button>
      </header>

      <div className="space-y-4 px-6 py-6">
        <div className="flex flex-wrap gap-2">
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t('memory.search')}
            className="h-9 w-full max-w-sm rounded-lg border border-border bg-surface px-3 text-sm text-ink focus:border-accent focus:outline-none"
          />
          <select
            value={scope}
            onChange={(event) => setScope(event.target.value as '' | Scope)}
            className="h-9 rounded-lg border border-border bg-surface px-2 text-sm text-ink"
          >
            <option value="">{t('memory.allScopes')}</option>
            <option value="user">{t('memory.scope.user')}</option>
            <option value="workspace">{t('memory.scope.workspace')}</option>
          </select>
          <select
            value={agentFilter}
            onChange={(event) => setAgentFilter(event.target.value)}
            className="h-9 rounded-lg border border-border bg-surface px-2 text-sm text-ink"
          >
            <option value="">{t('memory.allAgents')}</option>
            {(agents.data ?? [])
              .filter((agent) => !agent.builtin)
              .map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.icon} {agent.name}
                </option>
              ))}
          </select>
        </div>

        {memories.isLoading && <Spinner />}
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {(memories.data ?? []).map((memory) => (
            <article
              key={memory.id}
              className="flex flex-col rounded-2xl border border-border bg-surface p-4"
            >
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="accent">{t(`memory.kind.${memory.kind}`)}</Badge>
                <Badge tone="neutral">{t(`memory.scope.${memory.scope}`)}</Badge>
                <span className="ml-auto text-[10px] text-ink-muted">
                  {'★'.repeat(memory.importance)}
                </span>
              </div>
              <p className="mt-2 text-sm font-medium text-ink">
                {memory.title || memory.content.slice(0, 40)}
              </p>
              <p className="mt-1 line-clamp-4 whitespace-pre-wrap text-xs text-ink-muted">
                {memory.content}
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-[10px] text-ink-muted">
                <span>{memory.source}</span>
                <span>{new Date(memory.updated_at).toLocaleString()}</span>
                <div className="ml-auto flex gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={t('common.edit')}
                    onClick={() => setEditing(memory)}
                  >
                    <Pencil className="h-3 w-3" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={t('common.delete')}
                    onClick={() => void remove(memory)}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
              </div>
            </article>
          ))}
        </div>
        {memories.data !== undefined && memories.data.length === 0 && (
          <p className="rounded-2xl border border-dashed border-border px-6 py-16 text-center text-sm text-ink-muted">
            {t('memory.empty')}
          </p>
        )}
      </div>

      <MemoryForm
        key={editing === null ? 'new-memory' : (editing?.id ?? 'closed')}
        open={editing !== undefined}
        initial={editing ?? null}
        agents={(agents.data ?? []).filter((agent) => !agent.builtin)}
        onClose={() => setEditing(undefined)}
        onSaved={() => {
          setEditing(undefined)
          void refresh()
        }}
      />
    </div>
  )
}

function MemoryForm({
  open,
  initial,
  agents,
  onClose,
  onSaved,
}: {
  open: boolean
  initial: AgentMemory | null
  agents: CustomAgent[]
  onClose: () => void
  onSaved: () => void
}) {
  const { t } = useI18n()
  const [draft, setDraft] = useState<Draft>(() => draftFrom(initial))
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
      scope: draft.scope,
      kind: draft.kind,
      agent_id: draft.agentId === '' ? null : draft.agentId,
      importance: draft.importance,
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
    >
      <form id="memory-form" className="space-y-3" onSubmit={(event) => void submit(event)}>
        <Field label={t('memory.memoryTitle')}>
          <Input
            value={draft.title}
            onChange={(event) => update('title', event.target.value)}
          />
        </Field>
        <Field label={t('memory.content')}>
          <Textarea
            required
            className="min-h-28"
            value={draft.content}
            onChange={(event) => update('content', event.target.value)}
          />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t('memory.kindLabel')}>
            <select
              className="h-9 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink"
              value={draft.kind}
              onChange={(event) => update('kind', event.target.value as Kind)}
            >
              {(['fact', 'preference', 'summary'] as const).map((item) => (
                <option key={item} value={item}>
                  {t(`memory.kind.${item}`)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('memory.scopeLabel')}>
            <select
              className="h-9 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink"
              value={draft.scope}
              onChange={(event) => update('scope', event.target.value as Scope)}
            >
              {(['user', 'workspace'] as const).map((item) => (
                <option key={item} value={item}>
                  {t(`memory.scope.${item}`)}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t('memory.agent')}>
            <select
              className="h-9 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink"
              value={draft.agentId}
              onChange={(event) => update('agentId', event.target.value)}
            >
              <option value="">{t('memory.allAgents')}</option>
              {agents.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.icon} {agent.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('memory.importance')}>
            <Input
              type="number"
              min={1}
              max={5}
              value={draft.importance}
              onChange={(event) => update('importance', Number(event.target.value))}
            />
          </Field>
        </div>
        {error !== null && <p className="text-xs text-danger">{error}</p>}
      </form>
    </Dialog>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block text-xs text-ink-muted">
      <span className="mb-1 block">{label}</span>
      {children}
    </label>
  )
}