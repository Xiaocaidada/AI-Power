import { useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, Bot, FolderOpen, Globe2, Plug } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import {
  modelReasoningLevels,
  modelThinkingSpecs,
  modeLabelKey,
  normalizeThinkingLevel,
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
  StudyLevel,
  StudyMode,
  StudySession,
  ThinkingLevel,
} from '../../lib/types'
import { Composer } from './Composer'
import { ModeSelector } from './ModeSelector'
import { ThinkingSelect } from './ThinkingSelect'

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
  const [customAgentId, setCustomAgentId] = useState(
    () => searchParams.get('agent') ?? '',
  )
  const [pluginIds, setPluginIds] = useState<string[]>([])
  const [mode, setMode] = useState<ChatMode>(() =>
    searchParams.get('agent') !== null || searchParams.get('agentMode') !== null
      ? 'agent'
      : 'chat',
  )
  const [thinkingLevel, setThinkingLevel] = useState<ThinkingLevel>('standard')
  const [thinkingAdjusted, setThinkingAdjusted] = useState(false)
  const [searchProviderId, setSearchProviderId] = useState('')
  const [studyLevel, setStudyLevel] = useState<StudyLevel>('intermediate')
  const [studyMode, setStudyMode] = useState<StudyMode>('guided')
  const [studyGoals, setStudyGoals] = useState('')
  const [confirmSensitive, setConfirmSensitive] = useState(false)
  const [templateId, setTemplateId] = useState('')
  const [variables, setVariables] = useState<Record<string, string>>({})
  const [value, setValue] = useState(() => searchParams.get('prompt') ?? '')
  const [pluginOpen, setPluginOpen] = useState(false)
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
  const pluginLockedByAgent = customAgentId !== '' || pluginIds.length > 0
  const effectiveMode: ChatMode = pluginLockedByAgent ? 'agent' : mode
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
  const supportedThinkingSpecs = modelThinkingSpecs(personalSelected ?? selected)

  useEffect(() => {
    const next = normalizeThinkingLevel(thinkingLevel, supportedThinking)
    if (next !== thinkingLevel) {
      setThinkingLevel(next)
      setThinkingAdjusted(true)
    }
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
    if (supportsTools) return
    setCustomAgentId('')
    setPluginIds([])
    setMode((current) => (current === 'agent' ? 'chat' : current))
    setModelId((current) => (current === 'agent' ? 'auto' : current))
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
    body.agent = effectiveMode === 'agent'
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
      body.agent = effectiveMode === 'agent'
    }
    try {
      const conversation = await apiRequest<Conversation>('/conversations', {
        method: 'POST',
        body,
      })
      let pendingMeta = modeMeta
      if (effectiveMode === 'study') {
        const study = await apiRequest<StudySession>('/study/sessions', {
          method: 'POST',
          body: {
            topic: content.trim().slice(0, 200) || t('study.defaultTopic'),
            conversation_id: conversation.id,
            level: studyLevel,
            mode: studyMode,
            goals: studyGoals,
          },
        })
        pendingMeta = { ...modeMeta, study_session_id: study.id }
      }
      await queryClient.invalidateQueries({ queryKey: ['conversations'] })
      navigate(`/chat/${conversation.id}`, {
        state: modeImplemented
          ? { pendingMessage: content, pendingModeMeta: pendingMeta }
          : { pendingModeNotice: effectiveMode },
      })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
      throw caught
    }
  }

  const changeMode = (next: ChatMode) => {
    if (next === 'agent' && !supportsTools) {
      setError(t('chat.agentUnsupported'))
      return
    }
    setError(null)
    setMode(next)
  }

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
    { value: '', label: t('chat.autoAgent') },
    ...customAgents.map((item) => ({
      value: item.id,
      label: item.name,
      description: item.description || item.instructions.slice(0, 60),
    })),
  ]

  const templateOptions: PopoverSelectOption[] = [
    { value: '', label: t('prompts.none') },
    ...(templatesQuery.data ?? []).map((template) => ({
      value: template.id,
      label: template.name,
      trailing: `v${template.versions[0]?.version ?? 1}`,
    })),
  ]

  const studyLevelOptions: PopoverSelectOption[] = [
    { value: 'beginner', label: t('study.levelBeginner') },
    { value: 'intermediate', label: t('study.levelIntermediate') },
    { value: 'advanced', label: t('study.levelAdvanced') },
  ]

  const studyModeOptions: PopoverSelectOption[] = [
    { value: 'explain', label: t('study.modeExplain') },
    { value: 'guided', label: t('study.modeGuided') },
    { value: 'practice', label: t('study.modePractice') },
    { value: 'quiz', label: t('study.modeQuiz') },
    { value: 'review', label: t('study.modeReview') },
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
    { value: 'auto', label: t('chat.autoModelShort'), description: t('models.autoHint') },
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
      placement="bottom"
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

        {effectiveMode === 'study' && (
          <div className="mt-6 flex flex-wrap items-center justify-start gap-2">
            <PopoverSelect
              label={t('study.level')}
              value={studyLevel}
              options={studyLevelOptions}
              onChange={(next) => setStudyLevel(next as StudyLevel)}
            />
            <PopoverSelect
              label={t('study.mode')}
              value={studyMode}
              options={studyModeOptions}
              onChange={(next) => setStudyMode(next as StudyMode)}
            />
            <Input
              className="h-8 max-w-64"
              value={studyGoals}
              onChange={(event) => setStudyGoals(event.target.value)}
              placeholder={t('study.goalsPlaceholder')}
            />
          </div>
        )}

        <div className={effectiveMode === 'study' ? 'mt-4' : 'mt-8'}>
          <Composer
            value={value}
            onValueChange={setValue}
            onSend={send}
            disabled={!canChat || searchProviderMissing}
            size="hero"
            autoFocus
            footerStart={
              <>
                <ModeSelector
                  value={effectiveMode === 'web_search' ? 'chat' : effectiveMode}
                  catalog={chatModesQuery.data}
                  hiddenModes={['web_search']}
                  disabled={pluginLockedByAgent}
                  onChange={changeMode}
                />
                {effectiveMode === 'agent' && (
                  <PopoverSelect
                    icon={<Bot className="h-3.5 w-3.5" />}
                    label={t('chat.agent')}
                    value={customAgentId}
                    options={agentOptions}
                    triggerClassName="max-w-40"
                    onChange={(next) => {
                      setCustomAgentId(next)
                      if (next !== '') {
                        setModelId('agent')
                      } else if (modelId === 'agent') {
                        setModelId('auto')
                      }
                    }}
                  />
                )}
                {canChat &&
                  (effectiveMode === 'chat' || effectiveMode === 'web_search') && (
                    <button
                      type="button"
                      aria-pressed={effectiveMode === 'web_search'}
                      title={t('chat.webSearchQuickHint')}
                      onClick={() =>
                        changeMode(
                          effectiveMode === 'web_search' ? 'chat' : 'web_search',
                        )
                      }
                      className={`inline-flex h-7 items-center gap-1 rounded-full border px-2 text-[11px] transition-colors ${
                        effectiveMode === 'web_search'
                          ? 'border-accent bg-accent-soft text-accent'
                          : 'border-border text-ink-muted hover:text-ink'
                      }`}
                    >
                      <Globe2 className="h-3.5 w-3.5" />
                      {t('chat.webSearchQuick')}
                    </button>
                  )}
                {effectiveMode === 'web_search' &&
                  enabledSearchProviders.length > 0 && (
                    <PopoverSelect
                      label={t('chat.searchProvider')}
                      value={searchProviderId}
                      options={enabledSearchProviders.map((provider) => ({
                        value: provider.id,
                        label: provider.name,
                      }))}
                      onChange={setSearchProviderId}
                      variant="ghost"
                      triggerClassName="max-w-40"
                    />
                  )}
              </>
            }
            footerEnd={
              <>
                {modelSelect}
                <ThinkingSelect
                  value={thinkingLevel}
                  supported={supportedThinking}
                  specs={supportedThinkingSpecs}
                  disabled={!modeImplemented}
                  onChange={(next) => {
                    setThinkingLevel(next)
                    setThinkingAdjusted(false)
                  }}
                />
              </>
            }
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
            emptyLabel={t('knowledge.empty')}
            emptyAction={
              <Link to="/knowledge" className="text-accent hover:underline">
                {t('knowledge.new')}
              </Link>
            }
          />
          <PopoverSelect
            icon={<BookOpen className="h-3.5 w-3.5" />}
            label={t('prompts.select')}
            value={templateId}
            options={templateOptions}
            onChange={selectTemplate}
          />
          {effectiveMode === 'agent' && configuredPlugins.length > 0 && (
            <button
              type="button"
              onClick={() => setPluginOpen(true)}
              className="inline-flex h-7 items-center gap-1 rounded-full border border-border px-2 text-[11px] text-ink-muted transition-colors hover:text-ink"
            >
              <Plug className="h-3.5 w-3.5" />
              {t('chat.plugins')}
              {pluginIds.length > 0 ? ` · ${pluginIds.length}` : ''}
            </button>
          )}
        </div>

        {!modeImplemented && (
          <p className="mt-3 rounded-lg bg-warning/10 px-3 py-2 text-xs text-warning">
            {t('chat.modePlannedNotice', {
              mode: t(modeLabelKey(effectiveMode)),
            })}
          </p>
        )}
        {thinkingAdjusted && (
          <p className="mt-3 rounded-lg bg-warning/10 px-3 py-2 text-xs text-warning">
            {t('chat.thinkingAdjusted', {
              level:
                supportedThinkingSpecs.find(
                  (item) => item.id === thinkingLevel,
                )?.label || thinkingLevel,
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
        open={pluginOpen}
        onClose={() => setPluginOpen(false)}
        title={t('chat.plugins')}
        footer={
          <Button size="sm" onClick={() => setPluginOpen(false)}>
            {t('common.close')}
          </Button>
        }
      >
        <div className="rounded-lg border border-border bg-surface px-3 py-2.5">
          <p className="text-xs text-ink-muted">{t('chat.pluginsHint')}</p>
          {configuredPlugins.length === 0 ? (
            <p className="mt-2 text-xs text-ink-muted">{t('chat.noPlugins')}</p>
          ) : (
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
                    }}
                  />
                  {plugin.name}
                  {plugin.sensitive && <Badge tone="warning">{t('plugins.sensitive')}</Badge>}
                </label>
              ))}
            </div>
          )}
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
      </Dialog>
    </div>
  )
}