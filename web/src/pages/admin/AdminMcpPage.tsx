import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, Server, Trash2, Wrench } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { Navigate } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { Input, Textarea } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { McpPrompt, McpResource, McpServer, McpTool } from '../../lib/types'
import { useAuthStore } from '../../store/auth'

interface Draft {
  name: string
  description: string
  endpointUrl: string
  token: string
  enabled: boolean
  timeout: number
}

function draftFrom(server: McpServer | null): Draft {
  return {
    name: server?.name ?? '',
    description: server?.description ?? '',
    endpointUrl: server?.endpoint_url ?? '',
    token: '',
    enabled: server?.enabled ?? true,
    timeout: server?.timeout_seconds ?? 20,
  }
}

export function AdminMcpPage() {
  const { t } = useI18n()
  const user = useAuthStore((state) => state.user)
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<McpServer | null | undefined>()
  const [toolsFor, setToolsFor] = useState<McpServer | null>(null)
  const [error, setError] = useState<string | null>(null)

  const isAdmin = user?.role === 'admin'
  const servers = useQuery({
    queryKey: ['admin-mcp-servers'],
    queryFn: () => apiRequest<McpServer[]>('/admin/mcp-servers'),
    enabled: isAdmin,
  })
  const tools = useQuery({
    queryKey: ['admin-mcp-tools', toolsFor?.id ?? ''],
    queryFn: () => apiRequest<McpTool[]>(`/admin/mcp-servers/${toolsFor?.id}/tools`),
    enabled: isAdmin && toolsFor !== null,
    retry: false,
  })
  const resources = useQuery({
    queryKey: ['admin-mcp-resources', toolsFor?.id ?? ''],
    queryFn: () =>
      apiRequest<McpResource[]>(`/admin/mcp-servers/${toolsFor?.id}/resources`),
    enabled: isAdmin && toolsFor !== null,
    retry: false,
  })
  const prompts = useQuery({
    queryKey: ['admin-mcp-prompts', toolsFor?.id ?? ''],
    queryFn: () => apiRequest<McpPrompt[]>(`/admin/mcp-servers/${toolsFor?.id}/prompts`),
    enabled: isAdmin && toolsFor !== null,
    retry: false,
  })

  if (!isAdmin) return <Navigate to="/chat" replace />

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['admin-mcp-servers'] })

  const remove = async (server: McpServer) => {
    if (!window.confirm(t('admin.mcpDeleteConfirm'))) return
    await apiRequest(`/admin/mcp-servers/${server.id}`, { method: 'DELETE' })
    await refresh()
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-surface px-6 py-4">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            <Server className="h-4 w-4 text-accent" />
            {t('admin.mcpTitle')}
          </h1>
          <p className="mt-1 text-sm text-ink-muted">{t('admin.mcpLead')}</p>
        </div>
        <Button size="sm" onClick={() => setEditing(null)}>
          <Plus className="h-3.5 w-3.5" />
          {t('admin.mcpNew')}
        </Button>
      </header>

      <div className="space-y-3 px-6 py-6">
        {servers.isLoading && <Spinner />}
        {(servers.data ?? []).map((server) => (
          <article
            key={server.id}
            className="rounded-2xl border border-border bg-surface p-5"
          >
            <div className="flex flex-wrap items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-sm font-medium text-ink">{server.name}</p>
                  <Badge tone={server.enabled ? 'success' : 'neutral'}>
                    {server.enabled ? t('admin.mcpEnabled') : t('admin.mcpDisabled')}
                  </Badge>
                  {server.auth_hint && (
                    <Badge tone="accent">{server.auth_hint}</Badge>
                  )}
                </div>
                <p className="mt-1 text-xs text-ink-muted">{server.description}</p>
                <p className="mt-1 break-all font-mono text-[10px] text-ink-muted">
                  {server.endpoint_url}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => setToolsFor(server)}
                >
                  <Wrench className="h-3 w-3" />
                  {t('admin.mcpTools')}
                </Button>
                <Button size="sm" variant="secondary" onClick={() => setEditing(server)}>
                  <Pencil className="h-3 w-3" />
                  {t('common.edit')}
                </Button>
                <Button size="sm" variant="secondary" onClick={() => void remove(server)}>
                  <Trash2 className="h-3 w-3" />
                  {t('common.delete')}
                </Button>
              </div>
            </div>
          </article>
        ))}
        {servers.data !== undefined && servers.data.length === 0 && (
          <p className="rounded-2xl border border-dashed border-border px-6 py-16 text-center text-sm text-ink-muted">
            {t('admin.mcpEmpty')}
          </p>
        )}
        {error !== null && <p className="text-xs text-danger">{error}</p>}
      </div>

      <Dialog
        open={toolsFor !== null}
        onClose={() => setToolsFor(null)}
        title={`${t('admin.mcpTools')} · ${toolsFor?.name ?? ''}`}
        className="max-w-lg"
      >
        {tools.isLoading && <Spinner />}
        {tools.isError && <p className="text-xs text-danger">{t('admin.mcpToolsError')}</p>}
        <ul className="mt-2 space-y-2">
          {(tools.data ?? []).map((tool) => (
            <li key={tool.name} className="rounded-lg bg-surface-muted px-3 py-2">
              <p className="text-xs font-medium text-ink">{tool.name}</p>
              <p className="mt-0.5 text-[11px] text-ink-muted">{tool.description}</p>
            </li>
          ))}
          {tools.data !== undefined && tools.data.length === 0 && (
            <p className="text-xs text-ink-muted">{t('admin.mcpNoTools')}</p>
          )}
        </ul>
        <p className="mt-4 text-xs font-medium text-ink">{t('admin.mcpResources')}</p>
        <ul className="mt-2 space-y-1">
          {(resources.data ?? []).map((resource) => (
            <li key={resource.uri} className="rounded-lg bg-surface-muted px-3 py-1.5">
              <p className="text-[11px] text-ink">{resource.name || resource.uri}</p>
              <p className="truncate font-mono text-[10px] text-ink-muted">{resource.uri}</p>
            </li>
          ))}
          {resources.data !== undefined && resources.data.length === 0 && (
            <p className="text-[11px] text-ink-muted">{t('admin.mcpNoResources')}</p>
          )}
        </ul>
        <p className="mt-4 text-xs font-medium text-ink">{t('admin.mcpPrompts')}</p>
        <ul className="mt-2 space-y-1">
          {(prompts.data ?? []).map((prompt) => (
            <li key={prompt.name} className="rounded-lg bg-surface-muted px-3 py-1.5">
              <p className="text-[11px] text-ink">{prompt.name}</p>
              <p className="text-[10px] text-ink-muted">{prompt.description}</p>
            </li>
          ))}
          {prompts.data !== undefined && prompts.data.length === 0 && (
            <p className="text-[11px] text-ink-muted">{t('admin.mcpNoPrompts')}</p>
          )}
        </ul>
      </Dialog>

      <McpForm
        key={editing === null ? 'new-mcp' : (editing?.id ?? 'closed')}
        open={editing !== undefined}
        initial={editing ?? null}
        onClose={() => setEditing(undefined)}
        onError={setError}
        onSaved={() => {
          setEditing(undefined)
          void refresh()
        }}
      />
    </div>
  )
}

function McpForm({
  open,
  initial,
  onClose,
  onSaved,
  onError,
}: {
  open: boolean
  initial: McpServer | null
  onClose: () => void
  onSaved: () => void
  onError: (message: string | null) => void
}) {
  const { t } = useI18n()
  const [draft, setDraft] = useState<Draft>(() => draftFrom(initial))
  const [clearToken, setClearToken] = useState(false)
  const [saving, setSaving] = useState(false)

  const update = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }))

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setSaving(true)
    onError(null)
    const body: Record<string, unknown> = {
      name: draft.name,
      description: draft.description,
      endpoint_url: draft.endpointUrl,
      enabled: draft.enabled,
      timeout_seconds: draft.timeout,
    }
    if (clearToken) body.auth_token = ''
    else if (draft.token !== '') body.auth_token = draft.token
    try {
      if (initial === null) {
        await apiRequest('/admin/mcp-servers', { method: 'POST', body })
      } else {
        await apiRequest(`/admin/mcp-servers/${initial.id}`, { method: 'PATCH', body })
      }
      onSaved()
    } catch (caught) {
      onError(t(errorTextKey(caught)))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={initial === null ? t('admin.mcpNew') : t('admin.mcpEdit')}
      footer={
        <>
          <Button size="sm" variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button size="sm" type="submit" form="mcp-form" disabled={saving}>
            {t('common.save')}
          </Button>
        </>
      }
    >
      <form id="mcp-form" className="space-y-3" onSubmit={(event) => void submit(event)}>
        <Field label={t('admin.mcpName')}>
          <Input
            required
            value={draft.name}
            onChange={(event) => update('name', event.target.value)}
          />
        </Field>
        <Field label={t('admin.mcpDescription')}>
          <Textarea
            className="min-h-16"
            value={draft.description}
            onChange={(event) => update('description', event.target.value)}
          />
        </Field>
        <Field label={t('admin.mcpEndpoint')}>
          <Input
            required
            value={draft.endpointUrl}
            onChange={(event) => update('endpointUrl', event.target.value)}
            placeholder="https://mcp.example.com/mcp"
          />
        </Field>
        <Field
          label={
            initial === null || initial.auth_hint === ''
              ? t('admin.mcpToken')
              : `${t('admin.mcpToken')} (${initial.auth_hint})`
          }
        >
          <Input
            value={draft.token}
            onChange={(event) => update('token', event.target.value)}
            placeholder={initial === null ? '' : t('admin.mcpTokenKeep')}
          />
        </Field>
        {initial !== null && initial.auth_hint !== '' && (
          <label className="flex items-center gap-2 text-xs text-ink">
            <input
              type="checkbox"
              checked={clearToken}
              onChange={(event) => setClearToken(event.target.checked)}
            />
            {t('admin.mcpTokenClear')}
          </label>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t('admin.mcpTimeout')}>
            <Input
              type="number"
              min={1}
              max={120}
              value={draft.timeout}
              onChange={(event) => update('timeout', Number(event.target.value))}
            />
          </Field>
          <label className="flex items-end gap-2 pb-2 text-xs text-ink">
            <input
              type="checkbox"
              checked={draft.enabled}
              onChange={(event) => update('enabled', event.target.checked)}
            />
            {t('admin.mcpEnabled')}
          </label>
        </div>
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