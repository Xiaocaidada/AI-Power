import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'

import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  Conversation,
  KnowledgeBase,
  ModelEntry,
  PersonalModel,
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
  const [modelId, setModelId] = useState('auto')
  const [kbId, setKbId] = useState('')
  const [agent, setAgent] = useState(false)
  const [templateId, setTemplateId] = useState('')
  const [variables, setVariables] = useState<Record<string, string>>({})
  const [value, setValue] = useState('')
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
  const selected = availableModels.find((model) => model.id === modelId)
  const personalSelected = modelId.startsWith('p:')
    ? personalModels.find((model) => `p:${model.provider_id}:${model.model_id}` === modelId)
    : undefined
  const isAuto = modelId === 'auto'
  const canChat = isAuto || selected !== undefined || personalSelected !== undefined

  const selectTemplate = (nextId: string) => {
    setTemplateId(nextId)
    const template = (templatesQuery.data ?? []).find((item) => item.id === nextId)
    const declared = template?.versions[0]?.variables ?? []
    setVariables(Object.fromEntries(declared.map((variable) => [variable, ''])))
  }

  const send = async (content: string) => {
    setError(null)
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
    try {
      const conversation = await apiRequest<Conversation>('/conversations', {
        method: 'POST',
        body: {
          provider_id: providerId,
          model: modelName,
          kb_id: kbId === '' ? null : kbId,
          agent,
          prompt_version_id: selectedVersion?.id ?? null,
          prompt_variables: selectedVersion !== undefined ? variables : {},
        },
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
            <Field label={t('chat.model')}>
              <select
                className={selectClass}
                value={modelId}
                onChange={(event) => setModelId(event.target.value)}
              >
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
                value={kbId}
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
            checked={agent}
            onChange={(event) => setAgent(event.target.checked)}
          />
          <span>
            <span className="block text-ink">{t('chat.agentMode')}</span>
            <span className="mt-0.5 block text-xs text-ink-muted">{t('chat.agentModeHint')}</span>
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