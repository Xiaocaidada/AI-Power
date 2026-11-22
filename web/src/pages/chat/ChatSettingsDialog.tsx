import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { Input } from '../../components/ui/input'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  ConversationDetail,
  ModelEntry,
  PersonalModel,
  Plugin,
} from '../../lib/types'

interface ChatSettingsDialogProps {
  conversation: ConversationDetail
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
  const plugins = useQuery({
    queryKey: ['plugins'],
    queryFn: () => apiRequest<Plugin[]>('/plugins'),
    staleTime: 60_000,
  })
  const [pluginIds, setPluginIds] = useState(
    conversation.plugins.map((item) => item.plugin_id),
  )
  const [confirmedIds, setConfirmedIds] = useState(
    conversation.plugins
      .filter((item) => item.confirmed_at !== null)
      .map((item) => item.plugin_id),
  )

  const platform = (models.data ?? []).filter((model) => model.available)
  const personal = personalModels.data ?? []
  const configuredPlugins = (plugins.data ?? []).filter(
    (plugin) => plugin.configured && plugin.config_enabled && plugin.enabled,
  )
  const selectedSensitive = configuredPlugins.filter(
    (plugin) => plugin.sensitive && pluginIds.includes(plugin.id),
  )
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
      if (conversation.agent) {
        await apiRequest(`/conversations/${conversation.id}/plugins`, {
          method: 'PUT',
          body: { plugin_ids: pluginIds },
        })
        const initiallyConfirmed = new Set(
          conversation.plugins
            .filter((item) => item.confirmed_at !== null)
            .map((item) => item.plugin_id),
        )
        const configured = (plugins.data ?? []).filter(
          (plugin) => plugin.configured && plugin.config_enabled && plugin.enabled,
        )
        for (const pluginId of pluginIds) {
          const plugin = configured.find((item) => item.id === pluginId)
          if (plugin === undefined || !plugin.sensitive) continue
          const shouldConfirm = confirmedIds.includes(pluginId)
          const wasConfirmed = initiallyConfirmed.has(pluginId)
          if (shouldConfirm && !wasConfirmed) {
            await apiRequest(
              `/conversations/${conversation.id}/plugins/${pluginId}/confirm`,
              { method: 'POST' },
            )
          } else if (!shouldConfirm && wasConfirmed) {
            await apiRequest(
              `/conversations/${conversation.id}/plugins/${pluginId}/confirm`,
              { method: 'DELETE' },
            )
          }
        }
      }
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
      {conversation.agent && (
        <div className="mt-4 border-t border-border pt-3">
          <p className="text-xs text-ink-muted">{t('chat.plugins')}</p>
          {configuredPlugins.length === 0 ? (
            <p className="mt-1 text-xs text-ink-muted">{t('chat.noPlugins')}</p>
          ) : (
            <div className="mt-1 flex flex-wrap gap-3">
              {configuredPlugins.map((plugin) => (
                <label key={plugin.id} className="flex items-center gap-1.5 text-xs text-ink">
                  <input
                    type="checkbox"
                    checked={pluginIds.includes(plugin.id)}
                    onChange={() =>
                      setPluginIds((current) =>
                        current.includes(plugin.id)
                          ? current.filter((item) => item !== plugin.id)
                          : [...current, plugin.id],
                      )
                    }
                  />
                  {plugin.name}
                </label>
              ))}
            </div>
          )}
          {selectedSensitive.length > 0 && (
            <div className="mt-2 space-y-1">
              {selectedSensitive.map((plugin) => (
                <label
                  key={plugin.id}
                  className="flex items-start gap-2 text-xs text-warning"
                >
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={confirmedIds.includes(plugin.id)}
                    onChange={() =>
                      setConfirmedIds((current) =>
                        current.includes(plugin.id)
                          ? current.filter((item) => item !== plugin.id)
                          : [...current, plugin.id],
                      )
                    }
                  />
                  {t('chat.confirmSensitivePlugin', { name: plugin.name })}
                </label>
              ))}
            </div>
          )}
        </div>
      )}
      {error !== null && <p className="mt-2 text-xs text-danger">{error}</p>}
    </Dialog>
  )
}