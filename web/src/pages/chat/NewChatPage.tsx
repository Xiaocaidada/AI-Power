import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BookOpen,
  Bot,
  FolderOpen,
  SlidersHorizontal,
} from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import {
  THINKING_LEVELS,
  modelReasoningLevels,
  modeLabelKey,
  normalizeThinkingLevel,
  thinkingLabelKey,
} from '../../lib/chatModes'
import { useChatModes, isModeImplemented } from '../../lib/useChatModes'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { Input } from '../../components/ui/input'
import { MultiPopoverSelect } from '../../components/ui/multi-popover-select'
import {
  PopoverSelect,
  type PopoverSelectOption,
} from '../../components/ui/popover-select'
import { Spinner } from '../../components/ui/spinner'
import { uploadChatAttachment } from '../../lib/attachments'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  ChatAttachment,
  ChatMode,
  ChatModeMeta,
  Conversation,
  CustomAgent,
  KnowledgeBase,
  ModelEntry,
  PersonalModel,
  Plugin,
  Project,
  ProjectAgent,
  PromptTemplate,
  SearchProvider,
  ThinkingLevel,
} from '../../lib/types'
import { Composer } from './Composer'
import { ModeSelector } from './ModeSelector'

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="text-xs text-ink-muted">
      <p className="mb-1.5">{label}</p>
      {children}
    </div>
  )
}

const selectClass =
  'h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink focus:border-accent focus:outline-none'

export function NewChatPage() {
  const { t } = useI18n()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const initialProvider = searchParams.get('provider')
  const initialModel = searchParams.get('model')
  const initialPromptVersion = searchParams.get('promptVersion')
  const appliedQueryRef = useRef(false)
  const [projectId, setProjectId] = useState(() => searchParams.get('project') ?? '')
  const [modelId, setModelId] = useState(() => {
    if (searchParams.get('agent') !== null) return 'agent'
    if (searchParams.get('project') !== null) return 'project'
    return 'auto'
  })
  const [kbIds, setKbIds] = useState<string[]>([])
  const [attachments, setAttachments] = useState<ChatAttachment[]>([])
  const [attaching, setAttaching] = useState(false)
  const [attachError, setAttachError] = useState<string | null>(null)
  const [agent, setAgent] = useState(
    () =>
      searchParams.get('agent') !== null || searchParams.get('agentMode') !== null,
  )
  const [customAgentId, setCustomAgentId] = useState(
    () => searchParams.get('agent') ?? '',
  )
  const [pluginIds, setPluginIds] = useState<string[]>([])
  const [mode, setMode] = useState<ChatMode>('chat')
  const [thinkingLevel, setThinkingLevel] = useState<ThinkingLevel>('standard')
  const [searchProviderId, setSearchProviderId] = useState('')
  const [confirmSensitive, setConfirmSensitive] = useState(false)
  const [templateId, setTemplateId] = useState('')
  const [variables, setVariables] = useState<Record<string, string>>({})
  const [value, setValue] = useState(() => searchParams.get('prompt') ?? '')
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const chatModesQuery = useChatModes()
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
  const kbsQuery = useQuery({
    queryKey: ['kbs'],
    queryFn: () => apiRequest<KnowledgeBase[]>('/knowledge-bases'),
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
    staleTime: 60_000,
  })
  const projectAgentsQuery = useQuery({
    queryKey: ['project-agents', projectId],
    queryFn: () => apiRequest<ProjectAgent[]>(`/projects/${projectId}/agents`),
    enabled: projectId !== '',
  })
  const pluginsQuery = useQuery({
    queryKey: ['plugins'],
    queryFn: () => apiRequest<Plugin[]>('/plugins'),
    staleTime: 60_000,
  })
  const templatesQuery = useQuery({
    queryKey: ['prompt-templates'],
    queryFn: () => apiRequest<PromptTemplate[]>('/prompt-templates'),
    staleTime: 60_000,
  })
  const searchProvidersQuery = useQuery({
    queryKey: ['search-providers'],
    queryFn: () => apiRequest<SearchProvider[]>('/search-providers'),
    staleTime: 60_000,
  })

  const availableModels = (modelsQuery.data ?? []).filter((model) => model.available)
  const personalModels = personalModelsQuery.data ?? []
  const selectedTemplate = (templatesQuery.data ?? []).find(
    (template) => template.id === templateId,
  )
  const selectedVersion = selectedTemplate?.versions[0]
  const selectedProject = (projectsQuery.data ?? []).find(
    (project) => project.id === projectId,
  )
  const allCustomAgents = (agentsQuery.data ?? []).filter((item) => !item.builtin)
  const projectAgentIds = new Set(
    (projectAgentsQuery.data ?? []).map((agent) => agent.agent_id),
  )
  const customAgents =
    projectId !== '' && projectAgentIds.size > 0
      ? allCustomAgents.filter((item) => projectAgentIds.has(item.id))
      : allCustomAgents
  const selectedAgent = customAgents.find((item) => item.id === customAgentId)

  useEffect(() => {
    if (projectId === '' || projectAgentIds.size === 0) return
    if (customAgentId !== '' && !projectAgentIds.has(customAgentId)) {
      setCustomAgentId('')
    }
  }, [customAgentId, projectAgentIds, projectId])
  const configuredPlugins = (pluginsQuery.data ?? []).filter(
    (plugin) => plugin.configured && plugin.config_enabled && plugin.enabled,
  )
  const selectedSensitive = configuredPlugins.filter(
    (plugin) => plugin.sensitive && pluginIds.includes(plugin.id),
  )
  const selected = availableModels.find((model) => model.id === modelId)
  const personalSelected = modelId.startsWith('p:')
    ? personalModels.find((model) => `p:${model.provider_id}:${model.model_id}` === modelId)
    : undefined
  const isAuto = modelId === 'auto'
  const supportsTools =
    personalSelected === undefined || personalSelected.capabilities.includes('tools')
  const personalSupportsChat =
    personalSelected === undefined || personalSelected.capabilities.includes('chat')
  const canChat =
    modelId === 'project' ||
    modelId === 'agent' ||
    isAuto ||
    selected !== undefined ||
    (personalSelected !== undefined && personalSupportsChat)
  const modeLockedByAgent = customAgentId !== '' || pluginIds.length > 0
  const effectiveMode: ChatMode = modeLockedByAgent ? 'agent' : mode
  const modeImplemented = isModeImplemented(effectiveMode, chatModesQuery.data)
  const enabledSearchProviders = (searchProvidersQuery.data ?? []).filter(
    (item) => item.enabled,
  )
  const searchProviderMissing =
    effectiveMode === 'web_search' && enabledSearchProviders.length === 0
  const supportedThinking =
    modelId === 'auto' || modelId === 'project' || modelId === 'agent'
      ? (['standard'] as ThinkingLevel[])
      : modelReasoningLevels(personalSelected ?? selected)

  useEffect(() => {
    const next = normalizeThinkingLevel(thinkingLevel, supportedThinking)
    if (next !== thinkingLevel) setThinkingLevel(next)
  }, [supportedThinking, thinkingLevel])

  useEffect(() => {
    const enabled = (searchProvidersQuery.data ?? []).filter((item) => item.enabled)
    const preferred =
      enabled.find((item) => item.is_default)?.id ?? enabled[0]?.id ?? ''
    if (preferred !== '') setSearchProviderId(preferred)
  }, [searchProvidersQuery.data])

  useEffect(() => {
    if (appliedQueryRef.current || initialProvider === null || initialModel === null) return
    if (availableModels.length === 0 && personalModels.length === 0) return
    const personalMatch = personalModels.find(
      (model) => model.provider_id === initialProvider && model.model_id === initialModel,
    )
    if (personalMatch !== undefined) {
      setModelId(`p:${personalMatch.provider_id}:${personalMatch.model_id}`)
      appliedQueryRef.current = true
      return
    }
    const platformMatch = availableModels.find(
      (model) => model.provider_id === initialProvider && model.model_id === initialModel,
    )
    if (platformMatch !== undefined) {
      setModelId(platformMatch.id)
      appliedQueryRef.current = true
    }
  }, [availableModels, initialModel, initialProvider, personalModels])

  useEffect(() => {
    if (!supportsTools) {
      setAgent(false)
      setMode('chat')
    }
  }, [supportsTools])

  useEffect(() => {
    if (initialPromptVersion === null) return
    const template = (templatesQuery.data ?? []).find((item) =>
      item.versions.some((version) => version.id === initialPromptVersion),
    )
    if (template === undefined) return
    setTemplateId(template.id)
    const declared = template.versions[0]?.variables ?? []
    setVariables(Object.fromEntries(declared.map((variable) => [variable, ''])))
  }, [initialPromptVersion, templatesQuery.data])

  const selectTemplate = (nextId: string) => {
    setTemplateId(nextId)
    const template = (templatesQuery.data ?? []).find((item) => item.id === nextId)
    const declared = template?.versions[0]?.variables ?? []
    setVariables(Object.fromEntries(declared.map((variable) => [variable, ''])))
  }

  const attachFiles = async (files: File[]) => {
    setAttachError(null)
    setAttaching(true)
    try {
      for (const file of files) {
        const uploaded = await uploadChatAttachment(file)
        setAttachments((prev) => [...prev, uploaded])
      }
    } catch (caught) {
      setAttachError(t(errorTextKey(caught)))
    } finally {
      setAttaching(false)
    }
  }

  const send = async (content: string) => {
    setError(null)
    const modeMeta: ChatModeMeta = {
      thinking_level: thinkingLevel,
      ...(effectiveMode === 'web_search' && searchProviderId !== ''
        ? { search_provider_id: searchProviderId }
        : {}),
    }
    const body: Record<string, unknown> = {
      prompt_version_id: selectedVersion?.id ?? null,
      prompt_variables: selectedVersion !== undefined ? variables : {},
      mode: effectiveMode,
    }
    if (effectiveMode !== 'agent') body.agent = false
    if (attachments.length > 0) {
      body.attachment_ids = attachments.map((attachment) => attachment.id)
    }
    if (projectId !== '') body.project_id = projectId
    if (customAgentId !== '') body.custom_agent_id = customAgentId
    if (pluginIds.length > 0) {
      body.plugin_ids = pluginIds
      body.agent = true
      if (confirmSensitive && selectedSensitive.length > 0) {
        body.confirmed_plugin_ids = selectedSensitive.map((plugin) => plugin.id)
      }
    }
    if (modelId !== 'project' && modelId !== 'agent') {
      const providerId = isAuto
        ? 'auto'
        : (personalSelected?.provider_id ?? selected?.provider_id)
      const modelName = isAuto
        ? 'auto'
        : (personalSelected?.model_id ?? selected?.model_id)
      if (providerId === undefined || modelName === undefined) {
        setError(t('chat.noProviders'))
        throw new Error('no model')
      }
      body.provider_id = providerId
      body.model = modelName
      body.kb_ids = kbIds
      body.kb_id = kbIds[0] ?? null
      body.agent = agent
    }
    try {
      const conversation = await apiRequest<Conversation>('/conversations', {
        method: 'POST',
        body,
      })
      await queryClient.invalidateQueries({ queryKey: ['conversations'] })
      navigate(`/chat/${conversation.id}`, {
        state: modeImplemented
          ? { pendingMessage: content, pendingModeMeta: modeMeta }
          : { pendingModeNotice: effectiveMode },
      })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
      throw caught
    }
  }

  const agentModeChecked =
    customAgentId !== '' || pluginIds.length > 0
      ? true
      : modelId === 'project'
        ? (selectedProject?.default_agent ?? false)
        : agent

  const projectKbName = kbsQuery.data?.find(
    (kb) => kb.id === selectedProject?.default_kb_id,
  )?.name
  const effectiveKbIds =
    modelId === 'project'
      ? selectedProject?.default_kb_id !== null &&
        selectedProject?.default_kb_id !== undefined
        ? [selectedProject.default_kb_id]
        : []
      : kbIds

  const projectOptions: PopoverSelectOption[] = [
    { value: '', label: t('chat.noProject') },
    ...(projectsQuery.data ?? []).map((project) => ({
      value: project.id,
      label: project.name,
      trailing: String(project.conversation_count),
    })),
  ]

  const agentOptions: PopoverSelectOption[] = [
    { value: '', label: t('chat.noAgent') },
    ...customAgents.map((item) => ({
      value: item.id,
      label: item.name,
      description: item.description || item.instructions.slice(0, 60),
    })),
  ]

  const kbOptions = (kbsQuery.data ?? []).map((kb) => ({
    value: kb.id,
    label: kb.name,
    description: kb.description || undefined,
  }))

  const modelOptions: PopoverSelectOption[] = [
    ...(selectedProject !== undefined
      ? [
          {
            value: 'project',
            label: t('chat.projectDefaultModel'),
            description: selectedProject.name,
          },
        ]
      : []),
    ...(selectedAgent !== undefined
      ? [
          {
            value: 'agent',
            label: t('chat.agentDefaultModel'),
            description: selectedAgent.name,
          },
        ]
      : []),
    { value: 'auto', label: t('models.auto'), description: t('models.autoHint') },
    ...availableModels.map((model) => ({
      value: model.id,
      label: model.display_name,
      description: model.provider_id,
      group: t('chat.platformModels'),
    })),
    ...personalModels.map((model) => ({
      value: `p:${model.provider_id}:${model.model_id}`,
      label: model.display_name,
      description: model.provider_name,
      group: t('chat.personalModels'),
    })),
  ]

  const modelSelect = modelsQuery.isLoading ? (
    <span className="px-2 text-[11px] text-ink-muted">{t('common.loading')}</span>
  ) : (
    <PopoverSelect
      label={t('chat.model')}
      variant="ghost"
      placement="top"
      value={modelId}
      options={modelOptions}
      onChange={setModelId}
    />
  )

  return (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div
        aria-hidden
        className="chat-hero-glow pointer-events-none absolute inset-0"
      />
      <div className="relative mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center px-5 py-10">
        <div className="text-center">
          <h1
            aria-label={`${t('chat.headingLead')}${t('chat.headingAccent')}${t('chat.headingTail')}`}
            className="font-serif text-3xl leading-tight text-ink sm:text-4xl"
          >
            {t('chat.headingLead')}<span className="relative inline-block text-accent">{t('chat.headingAccent')}<svg
                viewBox="0 0 100 8"
                preserveAspectRatio="none"
                aria-hidden
                className="absolute -bottom-1 left-0 h-2 w-full text-accent/50"
              >
                <path
                  d="M2 5.5C22 1.5 62 1.5 98 4.5"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
              </svg></span>{t('chat.headingTail')}
          </h1>
          <p className="mt-3 text-sm text-ink-muted">{t('chat.newLead')}</p>
        </div>

        <div className="mt-8">
          <Composer
            value={value}
            onValueChange={setValue}
            onSend={send}
            disabled={!canChat || searchProviderMissing}
            size="hero"
            autoFocus
            footerStart={modelSelect}
            placeholder={t('chat.inputPlaceholder')}
            attachments={attachments}
            attaching={attaching}
            onAttachFiles={(files) => void attachFiles(files)}
            onRemoveAttachment={(id) => {
              void apiRequest(`/attachments/${id}`, { method: 'DELETE' }).catch(() => {})
              setAttachments((prev) => prev.filter((item) => item.id !== id))
            }}
          />
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <PopoverSelect
            icon={<FolderOpen className="h-3.5 w-3.5" />}
            label={t('chat.project')}
            value={projectId}
            options={projectOptions}
            onChange={(next) => {
              setProjectId(next)
              if (next !== '') setModelId('project')
              else if (modelId === 'project') setModelId('auto')
            }}
          />

          <ModeSelector
            value={effectiveMode}
            catalog={chatModesQuery.data}
            disabled={modeLockedByAgent}
            onChange={(next) => {
              setMode(next)
              if (next === 'agent') {
                setAgent(true)
              } else if (!modeLockedByAgent) {
                setAgent(false)
              }
            }}
          />

          <PopoverSelect
            icon={<Bot className="h-3.5 w-3.5" />}
            label={t('chat.agent')}
            value={customAgentId}
            options={agentOptions}
            onChange={(next) => {
              setCustomAgentId(next)
              if (next !== '') {
                setModelId('agent')
                setAgent(true)
                setMode('agent')
              } else if (modelId === 'agent') {
                setModelId('auto')
                setAgent(pluginIds.length > 0)
                setMode(pluginIds.length > 0 ? 'agent' : 'chat')
              }
            }}
          />

          <MultiPopoverSelect
            icon={<BookOpen className="h-3.5 w-3.5" />}
            label={t('chat.knowledgeBase')}
            values={effectiveKbIds}
            options={kbOptions}
            placeholder={
              modelId === 'project'
                ? (projectKbName ?? t('chat.noKnowledgeBase'))
                : t('chat.noKnowledgeBase')
            }
            disabled={modelId === 'project'}
            onChange={setKbIds}
          />

          <Button
            variant="secondary"
            size="sm"
            className="rounded-full font-normal"
            onClick={() => setAdvancedOpen(true)}
          >
            <SlidersHorizontal className="h-3.5 w-3.5" />
            {t('chat.advanced')}
          </Button>
        </div>

        {!modeImplemented && (
          <p className="mt-3 rounded-lg bg-warning/10 px-3 py-2 text-xs text-warning">
            {t('chat.modePlannedNotice', {
              mode: t(modeLabelKey(effectiveMode)),
            })}
          </p>
        )}
        {searchProviderMissing && (
          <p className="mt-3 rounded-lg bg-warning/10 px-3 py-2 text-xs text-warning">
            {t('chat.searchProviderMissing')}{' '}
            <Link to="/settings/search" className="underline">
              {t('chat.searchProviderSettings')}
            </Link>
          </p>
        )}

        {selectedProject !== undefined && (
          <p className="mt-2 text-xs text-ink-muted">
            {t('chat.projectDefaults', {
              provider: selectedProject.default_provider_id ?? t('models.auto'),
              model: selectedProject.default_model ?? t('models.auto'),
              kb:
                kbsQuery.data?.find((kb) => kb.id === selectedProject.default_kb_id)?.name ??
                t('chat.noKnowledgeBase'),
            })}
          </p>
        )}
        {selectedAgent !== undefined && (
          <p className="mt-2 truncate text-xs text-ink-muted">
            {selectedAgent.description || selectedAgent.instructions.slice(0, 120)}
          </p>
        )}

        {modelsQuery.data !== undefined &&
          personalModelsQuery.data !== undefined &&
          availableModels.length === 0 &&
          personalModels.length === 0 && (
            <p className="mt-3 rounded-lg bg-warning/10 px-3 py-2 text-sm text-warning">
              {t('chat.noProviders')}
            </p>
          )}

        {error !== null && (
          <p role="alert" className="mt-3 rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </p>
        )}
        {attachError !== null && (
          <p role="alert" className="mt-3 rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
            {attachError}
          </p>
        )}

        <div className="mt-8 grid gap-2 sm:grid-cols-2">
          {(['suggestion1', 'suggestion2', 'suggestion3', 'suggestion4'] as const).map(
            (key) => (
              <button
                key={key}
                type="button"
                className="rounded-xl border border-border bg-surface px-4 py-3 text-left text-sm text-ink-muted transition-colors hover:border-accent/40 hover:text-ink"
                onClick={() => setValue(t(`chat.${key}`))}
              >
                {t(`chat.${key}`)}
              </button>
            ),
          )}
        </div>

        {modelsQuery.isLoading && (
          <div className="mt-4 flex items-center gap-2 text-xs text-ink-muted">
            <Spinner className="h-3.5 w-3.5" />
            {t('common.loading')}
          </div>
        )}
      </div>

      <Dialog
        open={advancedOpen}
        onClose={() => setAdvancedOpen(false)}
        title={t('chat.advanced')}
        footer={
          <Button size="sm" onClick={() => setAdvancedOpen(false)}>
            {t('common.close')}
          </Button>
        }
      >
        <div className="space-y-4">
          <Field label={t('prompts.select')}>
            <select
              className={selectClass}
              value={templateId}
              onChange={(event) => selectTemplate(event.target.value)}
            >
              <option value="">{t('prompts.none')}</option>
              {(templatesQuery.data ?? []).map((template) => (
                <option key={template.id} value={template.id}>
                  {template.name} · v{template.versions[0]?.version ?? 1}
                </option>
              ))}
            </select>
          </Field>
          {(selectedVersion?.variables ?? []).length > 0 && (
            <div className="space-y-2">
              {selectedVersion?.variables.map((variable) => (
                <Input
                  key={variable}
                  value={variables[variable] ?? ''}
                  onChange={(event) =>
                    setVariables((prev) => ({ ...prev, [variable]: event.target.value }))
                  }
                  placeholder={`{{${variable}}}`}
                />
              ))}
            </div>
          )}

          {effectiveMode === 'web_search' && (
            <Field label={t('chat.searchProvider')}>
              {enabledSearchProviders.length === 0 ? (
                <p className="text-xs text-warning">
                  {t('chat.searchProviderMissing')}{' '}
                  <Link to="/settings/search" className="underline">
                    {t('chat.searchProviderSettings')}
                  </Link>
                </p>
              ) : (
                <select
                  className={selectClass}
                  value={searchProviderId}
                  onChange={(event) => setSearchProviderId(event.target.value)}
                >
                  {enabledSearchProviders.map((provider) => (
                    <option key={provider.id} value={provider.id}>
                      {provider.name}
                    </option>
                  ))}
                </select>
              )}
            </Field>
          )}
          <Field label={t('chat.thinkingLevel')}>
            <select
              className={selectClass}
              value={thinkingLevel}
              onChange={(event) =>
                setThinkingLevel(event.target.value as ThinkingLevel)
              }
            >
              {THINKING_LEVELS.map((level) => (
                <option
                  key={level}
                  value={level}
                  disabled={!supportedThinking.includes(level)}
                >
                  {t(thinkingLabelKey(level))}
                  {supportedThinking.includes(level)
                    ? ''
                    : ` · ${t('chat.thinkingUnsupported')}`}
                </option>
              ))}
            </select>
            <p className="mt-1 text-[11px] text-ink-muted">
              {t('chat.thinkingHint')}
            </p>
          </Field>

          <label className="flex items-start gap-2 rounded-lg border border-border bg-surface px-3 py-2.5 text-sm">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 accent-accent"
              checked={agentModeChecked}
              disabled={
                !supportsTools ||
                modelId === 'project' ||
                customAgentId !== '' ||
                pluginIds.length > 0
              }
              onChange={(event) => {
                setAgent(event.target.checked)
                setMode(event.target.checked ? 'agent' : 'chat')
              }}
            />
            <span>
              <span className="block text-ink">{t('chat.agentMode')}</span>
              <span className="mt-0.5 block text-xs text-ink-muted">
                {supportsTools ? t('chat.agentModeHint') : t('chat.agentUnsupported')}
              </span>
            </span>
          </label>

          {configuredPlugins.length > 0 && (
            <div className="rounded-lg border border-border bg-surface px-3 py-2.5">
              <p className="text-sm text-ink">{t('chat.plugins')}</p>
              <p className="mt-0.5 text-xs text-ink-muted">{t('chat.pluginsHint')}</p>
              <div className="mt-2 flex flex-wrap gap-3">
                {configuredPlugins.map((plugin) => (
                  <label key={plugin.id} className="flex items-center gap-1.5 text-xs text-ink">
                    <input
                      type="checkbox"
                      checked={pluginIds.includes(plugin.id)}
                      onChange={() => {
                        const next = pluginIds.includes(plugin.id)
                          ? pluginIds.filter((item) => item !== plugin.id)
                          : [...pluginIds, plugin.id]
                        setPluginIds(next)
                        if (next.length > 0) {
                          setAgent(true)
                          setMode('agent')
                        }
                      }}
                    />
                    {plugin.name}
                    {plugin.sensitive && <Badge tone="warning">{t('plugins.sensitive')}</Badge>}
                  </label>
                ))}
              </div>
              {selectedSensitive.length > 0 && (
                <label className="mt-2 flex items-start gap-2 text-xs text-warning">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={confirmSensitive}
                    onChange={(event) => setConfirmSensitive(event.target.checked)}
                  />
                  {t('chat.confirmSensitive')}
                </label>
              )}
            </div>
          )}
        </div>
      </Dialog>
    </div>
  )
}