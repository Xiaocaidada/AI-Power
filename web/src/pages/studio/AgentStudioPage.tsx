import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ExternalLink,
  Rocket,
  Settings2,
  Sparkles,
  Workflow as WorkflowIcon,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { Input } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { buildGenerationSettings } from '../../lib/agentSettings'
import {
  clearLocalDraft,
  clearWorkflowDraft,
  localDraftKey,
  readLocalDraft,
  saveWorkflowDraft,
  writeLocalDraft,
} from '../../lib/canvasDraft'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  CustomAgent,
  KnowledgeBase,
  DatabaseConnectionOption,
  McpServerOption,
  ModelEntry,
  PersonalModel,
  Plugin,
  Project,
  Workflow,
  WorkflowCatalog,
  WorkflowDefinition,
  WorkflowVersion,
} from '../../lib/types'
import { StudioBuilderPanel } from './StudioBuilderPanel'
import { StudioCanvas } from './StudioCanvas'
import { StudioConfigPanel } from './StudioConfigPanel'
import { StudioRunPanel } from './StudioRunPanel'
import {
  draftFromAgent,
  normalizeDefinition,
  parseProviderChoice,
  type ModelChoice,
  type StudioAgentDraft,
} from './types'

type StudioTab = 'config' | 'canvas' | 'builder' | 'run'

export function AgentStudioPage() {
  const { id = '' } = useParams<{ id: string }>()
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<StudioTab>('config')
  const [draft, setDraft] = useState<StudioAgentDraft | null>(null)
  const [definition, setDefinition] = useState<WorkflowDefinition>({
    nodes: [],
    edges: [],
  })
  const [canvasSeed, setCanvasSeed] = useState(0)
  const [savingConfig, setSavingConfig] = useState(false)
  const [configError, setConfigError] = useState<string | null>(null)
  const [savingCanvas, setSavingCanvas] = useState(false)
  const [canvasError, setCanvasError] = useState<string | null>(null)
  const [publishOpen, setPublishOpen] = useState(false)
  const [publishSlug, setPublishSlug] = useState('')
  const [allowCopy, setAllowCopy] = useState(true)
  const [showStructure, setShowStructure] = useState(true)
  const [publishError, setPublishError] = useState<string | null>(null)
  const [publishing, setPublishing] = useState(false)
  const [builderSessionId, setBuilderSessionId] = useState('')
  const [lastRunId, setLastRunId] = useState<string | null>(null)
  const [draftRestored, setDraftRestored] = useState(false)
  const draftInitialized = useRef(false)
  const definitionInitialized = useRef(false)

  const agentQuery = useQuery({
    queryKey: ['studio-agent', id],
    queryFn: () => apiRequest<CustomAgent>(`/agents/${id}`),
    enabled: id !== '',
  })
  const catalogQuery = useQuery({
    queryKey: ['workflow-catalog'],
    queryFn: () => apiRequest<WorkflowCatalog>('/workflows/catalog'),
    staleTime: 300_000,
  })
  const modelsQuery = useQuery({
    queryKey: ['models'],
    queryFn: () => apiRequest<ModelEntry[]>('/models'),
    staleTime: 60_000,
  })
  const personalModelsQuery = useQuery({
    queryKey: ['provider-configs', 'models'],
    queryFn: () => apiRequest<PersonalModel[]>('/provider-configs/models'),
    staleTime: 60_000,
  })
  const knowledgeQuery = useQuery({
    queryKey: ['knowledge-bases'],
    queryFn: () => apiRequest<KnowledgeBase[]>('/knowledge-bases'),
  })
  const pluginsQuery = useQuery({
    queryKey: ['plugins'],
    queryFn: () => apiRequest<Plugin[]>('/plugins'),
    staleTime: 60_000,
  })
  const projectsQuery = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiRequest<Project[]>('/projects'),
    staleTime: 60_000,
  })
  const agentsQuery = useQuery({
    queryKey: ['agents'],
    queryFn: () => apiRequest<CustomAgent[]>('/agents'),
    staleTime: 30_000,
  })
  const mcpServersQuery = useQuery({
    queryKey: ['mcp-servers'],
    queryFn: () => apiRequest<McpServerOption[]>('/mcp-servers'),
    staleTime: 60_000,
  })
  const databaseConnectionsQuery = useQuery({
    queryKey: ['database-connections'],
    queryFn: () => apiRequest<DatabaseConnectionOption[]>('/database-connections'),
    staleTime: 60_000,
  })
  const workflowQuery = useQuery({
    queryKey: ['studio-workflow', agentQuery.data?.workflow_id ?? ''],
    queryFn: () =>
      apiRequest<Workflow>(`/workflows/${agentQuery.data?.workflow_id ?? ''}`),
    enabled: agentQuery.data?.workflow_id !== null && agentQuery.data?.workflow_id !== undefined,
  })

  const agent = agentQuery.data

  useEffect(() => {
    if (agent === undefined || draftInitialized.current) return
    setDraft(draftFromAgent(agent))
    setPublishSlug(agent.public_slug ?? '')
    setAllowCopy(agent.allow_copy)
    setShowStructure(agent.show_structure)
    draftInitialized.current = true
  }, [agent])

  useEffect(() => {
    if (definitionInitialized.current || agent === undefined) return
    if (agent.workflow_id !== null && workflowQuery.data === undefined) return
    const latest = workflowQuery.data?.versions[0]
    const remoteDraft = workflowQuery.data?.draft_definition ?? null
    const localDraft =
      agent.workflow_id === null
        ? readLocalDraft(localDraftKey(`agent:${agent.id}`))
        : null
    const chosen = remoteDraft ?? localDraft ?? latest?.definition
    if (chosen !== undefined && chosen !== null) {
      setDefinition(normalizeDefinition(chosen))
      setCanvasSeed((value) => value + 1)
    }
    setDraftRestored(remoteDraft !== null || localDraft !== null)
    definitionInitialized.current = true
  }, [agent, workflowQuery.data])

  const models = useMemo<ModelChoice[]>(
    () => [
      ...(modelsQuery.data ?? [])
        .filter((item) => item.available)
        .map((item) => ({
          provider_id: item.provider_id,
          model: item.model_id,
          label: `${item.display_name} · ${item.provider_id}`,
        })),
      ...(personalModelsQuery.data ?? []).map((item) => ({
        provider_id: item.provider_id,
        model: item.model_id,
        label: `${item.display_name} · ${item.provider_name}`,
      })),
    ],
    [modelsQuery.data, personalModelsQuery.data],
  )

  const canvasLocalKey = localDraftKey(`agent:${id}`)
  const autosaveCanvas = useCallback(
    async (next: WorkflowDefinition) => {
      const workflowId = agentQuery.data?.workflow_id
      if (workflowId !== null && workflowId !== undefined) {
        await saveWorkflowDraft(workflowId, next)
      } else {
        writeLocalDraft(canvasLocalKey, next)
      }
    },
    [agentQuery.data?.workflow_id, canvasLocalKey],
  )

  const restoreCanvasVersion = async (version: number) => {
    const workflowId = agentQuery.data?.workflow_id
    if (workflowId === null || workflowId === undefined) return
    const restored = await apiRequest<WorkflowVersion>(
      `/workflows/${workflowId}/versions/${version}/restore`,
      { method: 'POST' },
    )
    setDefinition(normalizeDefinition(restored.definition))
    setCanvasSeed((value) => value + 1)
    setDraftRestored(false)
    await queryClient.invalidateQueries({
      queryKey: ['studio-workflow', workflowId],
    })
  }

  const discardCanvasDraft = async () => {
    const workflowId = agentQuery.data?.workflow_id
    if (workflowId !== null && workflowId !== undefined) {
      await clearWorkflowDraft(workflowId)
      await queryClient.invalidateQueries({
        queryKey: ['studio-workflow', workflowId],
      })
    } else {
      clearLocalDraft(canvasLocalKey)
    }
    const latest = workflowQuery.data?.versions[0]
    setDefinition(normalizeDefinition(latest?.definition))
    setCanvasSeed((value) => value + 1)
    setDraftRestored(false)
  }

  if (agentQuery.isLoading || draft === null) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner className="h-6 w-6 text-accent" />
      </div>
    )
  }
  if (agentQuery.isError || agent === undefined) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3">
        <p className="text-sm text-ink-muted">{t('studio.loadError')}</p>
        <Link to="/agents" className="text-sm text-accent">
          {t('studio.back')}
        </Link>
      </div>
    )
  }

  const patchDraft = (patch: Partial<StudioAgentDraft>) =>
    setDraft((prev) => (prev === null ? prev : { ...prev, ...patch }))

  const saveConfig = async () => {
    if (draft.name.trim() === '' || draft.instructions.trim() === '') {
      setConfigError(t('studio.nameAndInstructionsRequired'))
      return
    }
    if (draft.mode !== 'autonomous' && agent.workflow_id === null) {
      setConfigError(t('studio.modeNeedsWorkflow'))
      return
    }
    const pair = parseProviderChoice(draft.providerChoice)
    setSavingConfig(true)
    setConfigError(null)
    try {
      await apiRequest(`/agents/${agent.id}`, {
        method: 'PATCH',
        body: {
          name: draft.name.trim(),
          description: draft.description.trim(),
          instructions: draft.instructions,
          category: draft.category.trim() || 'general',
          mode: draft.mode,
          icon: draft.icon || '🤖',
          cover_url: draft.coverUrl,
          generation_settings: buildGenerationSettings(draft),
          welcome_message: draft.welcomeMessage,
          examples: draft.examples
            .split('\n')
            .map((item) => item.trim())
            .filter((item) => item !== ''),
          usage_instructions: draft.usageInstructions,
          default_provider_id: pair.provider_id,
          default_model: pair.model,
          default_kb_id: draft.kbIds[0] ?? null,
          kb_ids: draft.kbIds,
          tools: draft.tools,
          plugin_ids: draft.pluginIds,
          visibility: draft.visibility,
          allow_copy: draft.allowCopy,
          show_structure: draft.showStructure,
          memory_enabled: draft.memoryEnabled,
          attachments_enabled: draft.attachmentsEnabled,
          memory_read_global: draft.memoryReadGlobal,
          memory_read_project: draft.memoryReadProject,
          memory_read_agent: draft.memoryReadAgent,
          memory_write: draft.memoryWrite,
          memory_write_scope: draft.memoryWriteScope,
          memory_write_mode: draft.memoryWriteMode,
        },
      })
      await queryClient.invalidateQueries({ queryKey: ['studio-agent', id] })
      await queryClient.invalidateQueries({ queryKey: ['agents'] })
    } catch (caught) {
      setConfigError(caught instanceof Error ? caught.message : t('errors.generic'))
    } finally {
      setSavingConfig(false)
    }
  }

  const saveCanvas = async (next: WorkflowDefinition) => {
    setSavingCanvas(true)
    setCanvasError(null)
    try {
      if (agent.workflow_id === null) {
        const workflow = await apiRequest<Workflow>('/workflows', {
          method: 'POST',
          body: { name: agent.name, description: agent.description, definition: next },
        })
        await apiRequest(`/agents/${agent.id}`, {
          method: 'PATCH',
          body: {
            workflow_id: workflow.id,
            mode: draft.mode === 'autonomous' ? 'hybrid' : draft.mode,
          },
        })
      } else {
        await apiRequest(`/workflows/${agent.workflow_id}/versions`, {
          method: 'POST',
          body: { definition: next },
        })
      }
      setDefinition(next)
      clearLocalDraft(canvasLocalKey)
      setDraftRestored(false)
      draftInitialized.current = false
      definitionInitialized.current = false
      await queryClient.invalidateQueries({ queryKey: ['studio-agent', id] })
      await queryClient.invalidateQueries({ queryKey: ['studio-workflow'] })
      await queryClient.invalidateQueries({ queryKey: ['agents'] })
    } catch (caught) {
      setCanvasError(caught instanceof Error ? caught.message : t('errors.generic'))
    } finally {
      setSavingCanvas(false)
    }
  }

  const applyBuilder = (next: WorkflowDefinition) => {
    setDefinition(next)
    setCanvasSeed((value) => value + 1)
    setTab('canvas')
  }

  const publish = async () => {
    setPublishing(true)
    setPublishError(null)
    try {
      await apiRequest(`/agents/${agent.id}/publish`, {
        method: 'POST',
        body: {
          slug: publishSlug.trim(),
          allow_copy: allowCopy,
          show_structure: showStructure,
        },
      })
      setPublishOpen(false)
      draftInitialized.current = false
      await queryClient.invalidateQueries({ queryKey: ['studio-agent', id] })
    } catch (caught) {
      setPublishError(caught instanceof Error ? caught.message : t('errors.generic'))
    } finally {
      setPublishing(false)
    }
  }

  const unpublish = async () => {
    setPublishing(true)
    setPublishError(null)
    try {
      await apiRequest(`/agents/${agent.id}/publish`, { method: 'DELETE' })
      setPublishOpen(false)
      draftInitialized.current = false
      await queryClient.invalidateQueries({ queryKey: ['studio-agent', id] })
    } catch (caught) {
      setPublishError(caught instanceof Error ? caught.message : t('errors.generic'))
    } finally {
      setPublishing(false)
    }
  }

  const tabs: { key: StudioTab; label: string; icon: typeof Settings2 }[] = [
    { key: 'config', label: t('studio.tabConfig'), icon: Settings2 },
    { key: 'canvas', label: t('studio.tabCanvas'), icon: WorkflowIcon },
    { key: 'builder', label: t('studio.tabBuilder'), icon: Sparkles },
    { key: 'run', label: t('studio.tabRun'), icon: Rocket },
  ]

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-3 border-b border-border bg-surface px-5 py-2.5">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent-soft text-lg">
          {agent.icon}
        </span>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="truncate text-sm font-medium text-ink">{agent.name}</h1>
            <Badge tone="neutral">{agent.mode}</Badge>
            {agent.published && <Badge tone="success">public</Badge>}
          </div>
          <p className="truncate text-[11px] text-ink-muted">{agent.description}</p>
        </div>
        <div className="ml-auto flex items-center gap-1.5">
          {tabs.map((item) => {
            const Icon = item.icon
            return (
              <Button
                key={item.key}
                size="sm"
                variant={tab === item.key ? 'primary' : 'ghost'}
                onClick={() => setTab(item.key)}
              >
                <Icon className="h-3.5 w-3.5" />
                {item.label}
              </Button>
            )
          })}
          <Button size="sm" variant="secondary" onClick={() => setPublishOpen(true)}>
            <Rocket className="h-3.5 w-3.5" />
            {agent.published ? t('studio.managePublish') : t('studio.publish')}
          </Button>
        </div>
      </div>

      <div className="min-h-0 flex-1">
        {tab === 'config' && (
          <StudioConfigPanel
            agentId={agent.id}
            draft={draft}
            models={models}
            knowledgeBases={knowledgeQuery.data ?? []}
            plugins={pluginsQuery.data ?? []}
            hasWorkflow={agent.workflow_id !== null}
            saving={savingConfig}
            error={configError}
            onChange={patchDraft}
            onSave={() => void saveConfig()}
          />
        )}
        {tab === 'canvas' && (
          <div className="flex h-full min-h-0 flex-col">
            {draftRestored && (
              <div className="flex flex-wrap items-center gap-2 border-b border-border bg-warning/10 px-4 py-2 text-xs text-warning">
                <span>{t('studio.draftRestored')}</span>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => void discardCanvasDraft()}
                >
                  {t('studio.discardDraft')}
                </Button>
              </div>
            )}
            <div className="min-h-0 flex-1">
              <StudioCanvas
                initialDefinition={definition}
                seed={canvasSeed}
                catalog={catalogQuery.data}
                resources={{
                  models,
                  knowledgeBases: knowledgeQuery.data ?? [],
                  agents: (agentsQuery.data ?? []).filter((item) => !item.builtin),
                  plugins: pluginsQuery.data ?? [],
                  projects: projectsQuery.data ?? [],
                  mcpServers: mcpServersQuery.data ?? [],
                  databaseConnections: databaseConnectionsQuery.data ?? [],
                }}
                versions={workflowQuery.data?.versions ?? []}
                workflowId={agent.workflow_id}
                version={workflowQuery.data?.versions[0]?.version}
                debuggable
                saving={savingCanvas}
                error={canvasError}
                onSave={(next) => void saveCanvas(next)}
                onRestoreVersion={(version) => void restoreCanvasVersion(version)}
                onAutosave={autosaveCanvas}
              />
            </div>
          </div>
        )}
        {tab === 'builder' && (
          <StudioBuilderPanel
            agentId={agent.id}
            workflowId={agent.workflow_id}
            definition={definition}
            models={models}
            sessionId={builderSessionId}
            onSessionId={setBuilderSessionId}
            onApply={applyBuilder}
            lastRunId={lastRunId}
          />
        )}
        {tab === 'run' && (
          <StudioRunPanel
            agent={agent}
            workflowId={agent.workflow_id}
            definition={definition}
            onRunId={setLastRunId}
          />
        )}
      </div>

      <Dialog
        open={publishOpen}
        onClose={() => setPublishOpen(false)}
        title={agent.published ? t('studio.managePublish') : t('studio.publish')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setPublishOpen(false)}>
              {t('common.close')}
            </Button>
            {agent.published ? (
              <Button
                size="sm"
                variant="danger"
                disabled={publishing}
                onClick={() => void unpublish()}
              >
                {t('studio.unpublish')}
              </Button>
            ) : (
              <Button size="sm" disabled={publishing} onClick={() => void publish()}>
                {t('studio.publish')}
              </Button>
            )}
          </>
        }
      >
        <div className="space-y-3">
          <label className="block text-xs text-ink-muted">
            {t('studio.publicSlug')}
            <Input
              className="mt-1"
              value={publishSlug}
              onChange={(event) => setPublishSlug(event.target.value)}
              placeholder="research-studio"
            />
          </label>
          <label className="flex items-center gap-2 text-xs text-ink">
            <input
              type="checkbox"
              checked={allowCopy}
              onChange={(event) => setAllowCopy(event.target.checked)}
            />
            {t('studio.allowCopy')}
          </label>
          <label className="flex items-center gap-2 text-xs text-ink">
            <input
              type="checkbox"
              checked={showStructure}
              onChange={(event) => setShowStructure(event.target.checked)}
            />
            {t('studio.showStructure')}
          </label>
          {agent.published && agent.public_slug && (
            <Link
              to={`/market/agents/${agent.public_slug}`}
              className="inline-flex items-center gap-1 text-xs text-accent"
            >
              <ExternalLink className="h-3 w-3" />
              /market/agents/{agent.public_slug}
            </Link>
          )}
          {publishError !== null && <p className="text-xs text-danger">{publishError}</p>}
        </div>
      </Dialog>
    </div>
  )
}