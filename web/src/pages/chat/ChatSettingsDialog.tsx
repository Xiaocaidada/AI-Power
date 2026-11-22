import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { Input } from '../../components/ui/input'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { Conversation, ModelEntry, PersonalModel } from '../../lib/types'

interface ChatSettingsDialogProps {
  conversation: Conversation
  onClose: () => void
}

function encodeChoice(providerId: string, modelId: string): string {
  if (providerId === 'auto') return 'auto'
  return `m:${providerId}:${modelId}`
}

function numberOrNull(value: string): number | null {
  if (value.trim() === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

export function ChatSettingsDialog({ conversation, onClose }: ChatSettingsDialogProps) {
  const { t } = useI18n()
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

  const platform = (models.data ?? []).filter((model) => model.available)
  const personal = personalModels.data ?? []
  const initialChoice =
    conversation.provider_id === 'auto'
      ? 'auto'
      : platform.some(
            (model) =>
              model.provider_id === conversation.provider_id &&
              model.model_id === conversation.model,
          )
        ? encodeChoice(conversation.provider_id, conversation.model)
        : `p:${conversation.provider_id}:${conversation.model}`
  const [choice, setChoice] = useState(initialChoice)
  const [temperature, setTemperature] = useState(
    conversation.generation_settings?.temperature?.toString() ?? '',
  )
  const [maxTokens, setMaxTokens] = useState(
    conversation.generation_settings?.max_tokens?.toString() ?? '',
  )
  const [topP, setTopP] = useState(
    conversation.generation_settings?.top_p?.toString() ?? '',
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = async () => {
    let providerId = 'auto'
    let modelId = 'auto'
    if (choice.startsWith('m:') || choice.startsWith('p:')) {
      const [, provider, ...rest] = choice.split(':')
      providerId = provider
      modelId = rest.join(':')
    }
    setSaving(true)
    setError(null)
    try {
      await apiRequest(`/conversations/${conversation.id}`, {
        method: 'PATCH',
        body: {
          provider_id: providerId,
          model: modelId,
          generation_settings: {
            temperature: numberOrNull(temperature),
            max_tokens: numberOrNull(maxTokens),
            top_p: numberOrNull(topP),
          },
        },
      })
      onClose()
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title={t('chat.settingsTitle')}
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button size="sm" disabled={saving} onClick={() => void save()}>
            {t('common.save')}
          </Button>
        </>
      }
    >
      <label className="block text-xs text-ink-muted">
        {t('chat.model')}
        <select
          className="mt-1 h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink"
          value={choice}
          onChange={(event) => setChoice(event.target.value)}
        >
          <option value="auto">{t('models.auto')}</option>
          {platform.map((model) => (
            <option
              key={`m:${model.provider_id}:${model.model_id}`}
              value={encodeChoice(model.provider_id, model.model_id)}
            >
              {model.display_name} · {model.provider_id}
            </option>
          ))}
          {personal.map((model) => (
            <option
              key={`p:${model.provider_id}:${model.model_id}`}
              value={`p:${model.provider_id}:${model.model_id}`}
            >
              {model.display_name} · {model.provider_name}
            </option>
          ))}
          {!initialChoice.startsWith('m:') &&
            !initialChoice.startsWith('p:') &&
            initialChoice !== 'auto' && (
              <option value={initialChoice}>
                {conversation.provider_id} · {conversation.model}
              </option>
            )}
        </select>
      </label>
      <div className="mt-3 grid grid-cols-3 gap-2">
        <label className="block text-xs text-ink-muted">
          {t('chat.temperature')}
          <Input
            className="mt-1"
            type="number"
            step="0.1"
            min="0"
            max="2"
            value={temperature}
            onChange={(event) => setTemperature(event.target.value)}
          />
        </label>
        <label className="block text-xs text-ink-muted">
          {t('chat.maxTokens')}
          <Input
            className="mt-1"
            type="number"
            min="1"
            max="32768"
            value={maxTokens}
            onChange={(event) => setMaxTokens(event.target.value)}
          />
        </label>
        <label className="block text-xs text-ink-muted">
          {t('chat.topP')}
          <Input
            className="mt-1"
            type="number"
            step="0.05"
            min="0"
            max="1"
            value={topP}
            onChange={(event) => setTopP(event.target.value)}
          />
        </label>
      </div>
      {error !== null && <p className="mt-2 text-xs text-danger">{error}</p>}
    </Dialog>
  )
}