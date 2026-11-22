import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  Conversation,
  CustomAgent,
  KnowledgeBase,
  ModelEntry,
  PersonalModel,
  Plugin,
  Project,
  PromptTemplate,
} from '../../lib/types'
import { Composer } from './Composer'

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1.5 block text-ink-muted">{label}</span>
      {children}
    </label>
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
  const [kbId, setKbId] = useState('')
  const [agent, setAgent] = useState(
    () =>
      searchParams.get('agent') !== null || searchParams.get('agentMode') !== null,
  )
  const [customAgentId, setCustomAgentId] = useState(
    () => searchParams.get('agent') ?? '',
  )
  const [pluginIds, setPluginIds] = useState<string[]>([])
  const [confirmSensitive, setConfirmSensitive] = useState(false)
  const [templateId, setTemplateId] = useState('')
  const [variables, setVariables] = useState<Record<string, string>>({})
  const [value, setValue] = useState(() => searchParams.get('prompt') ?? '')
  const [error, setError] = useState<string | null>(null)

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

  const availableModels = (modelsQuery.data ?? []).filter((model) => model.available)
  const personalModels = personalModelsQuery.data ?? []
  const selectedTemplate = (templatesQuery.data ?? []).find(
    (template) => template.id === templateId,
  )
  const selectedVersion = selectedTemplate?.versions[0]
  const selectedProject = (projectsQuery.data ?? []).find(
    (project) => project.id === projectId,
  )
  const customAgents = (agentsQuery.data ?? []).filter((item) => !item.builtin)
  const selectedAgent = customAgents.find((item) => item.id === customAgentId)
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
    if (!supportsTools) setAgent(false)
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

  const send = async (content: string) => {
    setError(null)
    const body: Record<string, unknown> = {
      prompt_version_id: selectedVersion?.id ?? null,
      prompt_variables: selectedVersion !== undefined ? variables : {},
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
      body.kb_id = kbId === '' ? null : kbId
      body.agent = agent
    }
    try {
      const conversation = await apiRequest<Conversation>('/conversations', {
        method: 'POST',
        body,
      })
      await queryClient.invalidateQueries({ queryKey: ['conversations'] })
      navigate(`/chat/${conversation.id}`, { state: { pendingMessage: content } })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
      throw caught
    }
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-3xl px-6 py-10">
        <h1 className="font-serif text-3xl text-ink">{t('chat.newTitle')}</h1>
        <p className="mt-2 text-sm text-ink-muted">{t('chat.newLead')}</p>

        {modelsQuery.isLoading || personalModelsQuery.isLoading ? (
          <div className="mt-8 flex items-center gap-2 text-sm text-ink-muted">
            <Spinner />
            {t('common.loading')}
          </div>
        ) : (
          <div className="mt-8 grid gap-3 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <Field label={t('chat.project')}>
                <select
                  className={selectClass}
                  value={projectId}
                  onChange={(event) => {
                    const next = event.target.value
                    setProjectId(next)
                    if (next !== '') setModelId('project')
                    else if (modelId === 'project') setModelId('auto')
                  }}
                >
                  <option value="">{t('chat.noProject')}</option>
                  {(projectsQuery.data ?? []).map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.name}
                    </option>
                  ))}
                </select>
                {selectedProject !== undefined && (
                  <p className="mt-1 text-xs text-ink-muted">
                    {t('chat.projectDefaults', {
                      provider: selectedProject.default_provider_id ?? t('models.auto'),
                      model: selectedProject.default_model ?? t('models.auto'),
                      kb:
                        kbsQuery.data?.find(
                          (kb) => kb.id === selectedProject.default_kb_id,
                        )?.name ?? t('chat.noKnowledgeBase'),
                    })}
                  </p>
                )}
              </Field>
            </div>
            <div className="sm:col-span-2">
              <Field label={t('chat.agent')}>
                <select
                  className={selectClass}
                  value={customAgentId}
                  onChange={(event) => {
                    const next = event.target.value
                    setCustomAgentId(next)
                    if (next !== '') {
                      setModelId('agent')
                      setAgent(true)
                    } else if (modelId === 'agent') {
                      setModelId('auto')
                      setAgent(pluginIds.length > 0)
                    }
                  }}
                >
                  <option value="">{t('chat.noAgent')}</option>
                  {customAgents.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
                {selectedAgent !== undefined && (
                  <p className="mt-1 text-xs text-ink-muted">
                    {selectedAgent.description || selectedAgent.instructions.slice(0, 120)}
                  </p>
                )}
              </Field>
            </div>
            <Field label={t('chat.model')}>
              <select
                className={selectClass}
                value={modelId}
                onChange={(event) => setModelId(event.target.value)}
              >
                {selectedProject !== undefined && (
                  <option value="project">{t('chat.projectDefaultModel')}</option>
                )}
                {selectedAgent !== undefined && (
                  <option value="agent">{t('chat.agentDefaultModel')}</option>
                )}
                <option value="auto">
                  {t('models.auto')} — {t('models.autoHint')}
                </option>
                {availableModels.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.display_name} · {model.provider_id}
                  </option>
                ))}
                {personalModels.length > 0 && (
                  <optgroup label={t('chat.personalModels')}>
                    {personalModels.map((model) => (
                      <option
                        key={`p:${model.provider_id}:${model.model_id}`}
                        value={`p:${model.provider_id}:${model.model_id}`}
                      >
                        {model.display_name} · {model.provider_name}
                      </option>
                    ))}
                  </optgroup>
                )}
              </select>
            </Field>
            <Field label={t('chat.knowledgeBase')}>
              <select
                className={selectClass}
                value={
                  modelId === 'project'
                    ? (selectedProject?.default_kb_id ?? '')
                    : kbId
                }
                disabled={modelId === 'project'}
                onChange={(event) => setKbId(event.target.value)}
              >
                <option value="">{t('chat.noKnowledgeBase')}</option>
                {(kbsQuery.data ?? []).map((kb) => (
                  <option key={kb.id} value={kb.id}>
                    {kb.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        )}

        {configuredPlugins.length > 0 && (
          <div className="mt-3 rounded-lg border border-border bg-surface px-3 py-2.5">
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
                      if (next.length > 0) setAgent(true)
                    }}
                  />
                  {plugin.name}
                  {plugin.sensitive && (
                    <Badge tone="warning">{t('plugins.sensitive')}</Badge>
                  )}
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

        <div className="mt-3 grid gap-3 sm:grid-cols-2">
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
            <div className="space-y-2 sm:col-span-2">
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
        </div>

        <label className="mt-4 flex items-start gap-2 rounded-lg border border-border bg-surface px-3 py-2.5 text-sm">
          <input
            type="checkbox"
            className="mt-0.5 h-4 w-4 accent-accent"
            checked={
              customAgentId !== '' || pluginIds.length > 0
                ? true
                : modelId === 'project'
                  ? (selectedProject?.default_agent ?? false)
                  : agent
            }
            disabled={
              !supportsTools ||
              modelId === 'project' ||
              customAgentId !== '' ||
              pluginIds.length > 0
            }
            onChange={(event) => setAgent(event.target.checked)}
          />
          <span>
            <span className="block text-ink">{t('chat.agentMode')}</span>
            <span className="mt-0.5 block text-xs text-ink-muted">
              {supportsTools ? t('chat.agentModeHint') : t('chat.agentUnsupported')}
            </span>
          </span>
        </label>

        {modelsQuery.data !== undefined &&
          personalModelsQuery.data !== undefined &&
          availableModels.length === 0 &&
          personalModels.length === 0 && (
          <p className="mt-4 rounded-lg bg-warning/10 px-3 py-2 text-sm text-warning">
            {t('chat.noProviders')}
          </p>
        )}

        {error !== null && (
          <p role="alert" className="mt-4 rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </p>
        )}

        <div className="mt-6">
          <Composer
            value={value}
            onValueChange={setValue}
            onSend={send}
            disabled={!canChat}
            placeholder={t('chat.inputPlaceholder')}
          />
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {(['suggestion1', 'suggestion2', 'suggestion3', 'suggestion4'] as const).map((key) => (
            <Button
              key={key}
              variant="secondary"
              size="sm"
              className="rounded-full font-normal text-ink-muted"
              onClick={() => setValue(t(`chat.${key}`))}
            >
              {t(`chat.${key}`)}
            </Button>
          ))}
        </div>
      </div>
    </div>
  )
}