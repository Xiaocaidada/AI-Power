import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, RefreshCw, Server, Trash2, Zap } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { EmptyState } from '../../components/ui/empty-state'
import { Input, Textarea } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  ProviderConfig,
  ProviderModel,
  ProviderSyncResult,
  ProviderTestResult,
  ThinkingLevelSpec,
} from '../../lib/types'

const CAPABILITIES = [
  'chat',
  'stream',
  'tools',
  'vision',
  'file',
  'structured',
  'reasoning',
  'long_context',
  'embedding',
  'rerank',
] as const

const MAX_THINKING_LEVELS = 10

interface FormState {
  name: string
  provider_type: string
  base_url: string
  api_key: string
  note: string
  shared: boolean
}

const EMPTY_FORM: FormState = {
  name: '',
  provider_type: 'openai_compatible',
  base_url: '',
  api_key: '',
  note: '',
  shared: false,
}

function statusTone(status: string): 'success' | 'danger' | 'neutral' {
  if (status === 'ok') return 'success'
  if (status === 'error') return 'danger'
  return 'neutral'
}

function ProviderModelsPanel({ config }: { config: ProviderConfig }) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [modelId, setModelId] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [settingsTarget, setSettingsTarget] = useState<ProviderModel | null>(null)
  const [contextWindow, setContextWindow] = useState('')
  const [maxOutput, setMaxOutput] = useState('')
  const [capabilities, setCapabilities] = useState<string[]>([])
  const [thinkingConfig, setThinkingConfig] = useState<ThinkingLevelSpec[]>([])
  const [saving, setSaving] = useState(false)
  const models = useQuery({
    queryKey: ['provider-models', config.id],
    queryFn: () => apiRequest<ProviderModel[]>(`/provider-configs/${config.id}/models`),
  })

  const add = async () => {
    if (!config.owned || modelId.trim() === '') return
    setError(null)
    try {
      await apiRequest(`/provider-configs/${config.id}/models`, {
        method: 'POST',
        body: {
          model_id: modelId.trim(),
          display_name: displayName.trim(),
          capabilities: ['chat', 'stream'],
        },
      })
      setModelId('')
      setDisplayName('')
      await queryClient.invalidateQueries({ queryKey: ['provider-models', config.id] })
      await queryClient.invalidateQueries({ queryKey: ['provider-configs'] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    }
  }

  const toggle = async (model: ProviderModel) => {
    await apiRequest(`/provider-configs/${config.id}/models/${model.id}`, {
      method: 'PATCH',
      body: { enabled: !model.enabled },
    })
    await queryClient.invalidateQueries({ queryKey: ['provider-models', config.id] })
    await queryClient.invalidateQueries({ queryKey: ['provider-configs'] })
  }

  const remove = async (model: ProviderModel) => {
    await apiRequest(`/provider-configs/${config.id}/models/${model.id}`, { method: 'DELETE' })
    await queryClient.invalidateQueries({ queryKey: ['provider-models', config.id] })
    await queryClient.invalidateQueries({ queryKey: ['provider-configs'] })
  }

  const openSettings = (model: ProviderModel) => {
    setSettingsTarget(model)
    setContextWindow(model.context_window > 0 ? String(model.context_window) : '')
    setMaxOutput(
      model.max_output !== null && model.max_output > 0 ? String(model.max_output) : '',
    )
    setCapabilities(model.capabilities)
    const configured = model.thinking_config ?? []
    setThinkingConfig(
      configured.length > 0
        ? configured
        : (model.reasoning_levels ?? []).map((id) => ({ id, label: '' })),
    )
    setError(null)
  }

  const toggleCapability = (capability: string, checked: boolean) => {
    setCapabilities((current) =>
      checked
        ? [...current.filter((item) => item !== capability), capability]
        : current.filter((item) => item !== capability),
    )
  }

  const addThinkingLevel = () => {
    setThinkingConfig((current) =>
      current.length >= MAX_THINKING_LEVELS
        ? current
        : [...current, { id: '', label: '' }],
    )
  }

  const updateThinkingLevel = (
    index: number,
    patch: Partial<ThinkingLevelSpec>,
  ) => {
    setThinkingConfig((current) =>
      current.map((item, itemIndex) =>
        itemIndex === index ? { ...item, ...patch } : item,
      ),
    )
  }

  const removeThinkingLevel = (index: number) => {
    setThinkingConfig((current) =>
      current.filter((_, itemIndex) => itemIndex !== index),
    )
  }

  const saveSettings = async () => {
    if (settingsTarget === null) return
    setSaving(true)
    setError(null)
    try {
      await apiRequest(`/provider-configs/${config.id}/models/${settingsTarget.id}`, {
        method: 'PATCH',
        body: {
          capabilities,
          thinking_config: thinkingConfig.filter((item) => item.id.trim() !== ''),
          context_window: Number(contextWindow) || 0,
          max_output: Number(maxOutput) || 0,
        },
      })
      setSettingsTarget(null)
      await queryClient.invalidateQueries({ queryKey: ['provider-models', config.id] })
      await queryClient.invalidateQueries({ queryKey: ['provider-configs'] })
      await queryClient.invalidateQueries({ queryKey: ['provider-configs', 'models'] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mt-3 border-t border-border pt-3">
      {models.isLoading && (
        <div className="flex items-center gap-2 text-xs text-ink-muted">
          <Spinner />
          {t('common.loading')}
        </div>
      )}
      {models.data !== undefined && models.data.length === 0 && (
        <p className="text-xs text-ink-muted">{t('providerHub.noModels')}</p>
      )}
      {models.data !== undefined && models.data.length > 0 && (
        <ul className="space-y-2">
          {models.data.map((model) => (
            <li
              key={model.id}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-border px-3 py-2 text-xs"
            >
              <span className="font-mono text-ink">{model.model_id}</span>
              {model.source === 'manual' && <Badge tone="neutral">{t('providerHub.manual')}</Badge>}
              <span className="flex flex-wrap gap-1">
                {model.capabilities.map((capability) => (
                  <Badge key={capability} tone="accent">
                    {capability}
                  </Badge>
                ))}
              </span>
              <span className="ml-auto flex items-center gap-1">
                {config.owned && (
                  <>
                    <Button variant="ghost" size="sm" onClick={() => void toggle(model)}>
                      {model.enabled ? t('providerHub.disable') : t('providerHub.enable')}
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => openSettings(model)}>
                      {t('providerHub.modelSettings')}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={t('providerHub.removeModel')}
                      onClick={() => void remove(model)}
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      {config.owned && (
        <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
          <Input
            value={modelId}
            onChange={(event) => setModelId(event.target.value)}
            placeholder={t('providerHub.modelId')}
          />
          <Input
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            placeholder={t('providerHub.modelName')}
          />
          <Button size="sm" disabled={modelId.trim() === ''} onClick={() => void add()}>
            <Plus className="h-3.5 w-3.5" />
            {t('providerHub.addModel')}
          </Button>
        </div>
      )}
      {error !== null && <p className="mt-2 text-xs text-danger">{error}</p>}
      <Dialog
        open={settingsTarget !== null}
        onClose={() => setSettingsTarget(null)}
        title={t('providerHub.modelSettings')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setSettingsTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button size="sm" disabled={saving} onClick={() => void saveSettings()}>
              {t('common.save')}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <label className="block text-xs text-ink-muted">
            {t('providerHub.contextWindow')}
            <Input
              className="mt-1"
              type="number"
              min="0"
              value={contextWindow}
              onChange={(event) => setContextWindow(event.target.value)}
            />
            <span className="mt-1 block text-[11px] text-ink-muted">
              {t('providerHub.contextWindowHint')}
            </span>
          </label>
          <label className="block text-xs text-ink-muted">
            {t('providerHub.maxOutput')}
            <Input
              className="mt-1"
              type="number"
              min="0"
              value={maxOutput}
              onChange={(event) => setMaxOutput(event.target.value)}
            />
          </label>
          <div>
            <p className="text-xs text-ink-muted">{t('providerHub.capabilityTags')}</p>
            <div className="mt-1 grid grid-cols-2 gap-1.5 sm:grid-cols-3">
              {CAPABILITIES.map((capability) => (
                <label
                  key={capability}
                  className="flex items-center gap-1.5 text-xs text-ink"
                >
                  <input
                    type="checkbox"
                    className="h-3.5 w-3.5 accent-accent"
                    checked={capabilities.includes(capability)}
                    onChange={(event) =>
                      toggleCapability(capability, event.target.checked)
                    }
                  />
                  {capability}
                </label>
              ))}
            </div>
          </div>
          <div>
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs text-ink-muted">
                {t('providerHub.thinkingConfig')}
              </p>
              <Button
                variant="ghost"
                size="sm"
                disabled={thinkingConfig.length >= MAX_THINKING_LEVELS}
                onClick={addThinkingLevel}
              >
                <Plus className="h-3.5 w-3.5" />
                {t('providerHub.addThinkingLevel')}
              </Button>
            </div>
            <p className="mt-1 text-[11px] text-ink-muted">
              {t('providerHub.thinkingConfigHint')}
            </p>
            {thinkingConfig.length === 0 ? (
              <p className="mt-2 text-xs text-ink-muted">
                {t('providerHub.thinkingEmpty')}
              </p>
            ) : (
              <div className="mt-2 space-y-2">
                {thinkingConfig.map((item, index) => (
                  <div
                    key={index}
                    className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]"
                  >
                    <Input
                      value={item.id}
                      placeholder={t('providerHub.thinkingValuePlaceholder')}
                      onChange={(event) =>
                        updateThinkingLevel(index, { id: event.target.value })
                      }
                    />
                    <Input
                      value={item.label}
                      placeholder={t('providerHub.thinkingLabelPlaceholder')}
                      onChange={(event) =>
                        updateThinkingLevel(index, { label: event.target.value })
                      }
                    />
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={t('providerHub.removeThinkingLevel')}
                      onClick={() => removeThinkingLevel(index)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </div>
          {error !== null && <p className="text-xs text-danger">{error}</p>}
        </div>
      </Dialog>
    </div>
  )
}

export function ProvidersPage() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<ProviderConfig | null>(null)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<ProviderConfig | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [testingId, setTestingId] = useState<string | null>(null)
  const [syncingId, setSyncingId] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const configs = useQuery({
    queryKey: ['provider-configs'],
    queryFn: () => apiRequest<ProviderConfig[]>('/provider-configs'),
  })

  const openCreate = () => {
    setEditTarget(null)
    setForm(EMPTY_FORM)
    setError(null)
    setDialogOpen(true)
  }

  const openEdit = (config: ProviderConfig) => {
    setEditTarget(config)
    setForm({
      name: config.name,
      provider_type: config.provider_type,
      base_url: config.base_url,
      api_key: '',
      note: config.note,
      shared: config.shared,
    })
    setError(null)
    setDialogOpen(true)
  }

  const save = async () => {
    if (form.name.trim() === '' || form.base_url.trim() === '') return
    if (editTarget === null && form.api_key.trim() === '') return
    setBusy(true)
    setError(null)
    try {
      if (editTarget === null) {
        await apiRequest('/provider-configs', {
          method: 'POST',
          body: {
            name: form.name.trim(),
            provider_type: form.provider_type,
            base_url: form.base_url.trim(),
            api_key: form.api_key,
            note: form.note.trim(),
            shared: form.shared,
          },
        })
      } else {
        await apiRequest(`/provider-configs/${editTarget.id}`, {
          method: 'PATCH',
          body: {
            name: form.name.trim(),
            base_url: form.base_url.trim(),
            api_key: form.api_key.trim() === '' ? undefined : form.api_key,
            note: form.note.trim(),
            shared: form.shared,
          },
        })
      }
      await queryClient.invalidateQueries({ queryKey: ['provider-configs'] })
      setDialogOpen(false)
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(false)
    }
  }

  const test = async (config: ProviderConfig) => {
    setTestingId(config.id)
    setNotice(null)
    try {
      const result = await apiRequest<ProviderTestResult>(
        `/provider-configs/${config.id}/test`,
        { method: 'POST' },
      )
      setNotice(
        result.status === 'ok'
          ? t('providerHub.testOk', { count: result.model_count })
          : t('providerHub.testFailed', { code: result.error_code ?? 'error' }),
      )
      await queryClient.invalidateQueries({ queryKey: ['provider-configs'] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setTestingId(null)
    }
  }

  const sync = async (config: ProviderConfig) => {
    setSyncingId(config.id)
    setNotice(null)
    try {
      const result = await apiRequest<ProviderSyncResult>(
        `/provider-configs/${config.id}/sync`,
        { method: 'POST' },
      )
      setNotice(
        t('providerHub.syncDone', {
          added: result.added,
          updated: result.updated,
          total: result.total,
        }),
      )
      await queryClient.invalidateQueries({ queryKey: ['provider-configs'] })
      await queryClient.invalidateQueries({ queryKey: ['provider-models', config.id] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setSyncingId(null)
    }
  }

  const remove = async () => {
    if (deleteTarget === null) return
    try {
      await apiRequest(`/provider-configs/${deleteTarget.id}`, { method: 'DELETE' })
      await queryClient.invalidateQueries({ queryKey: ['provider-configs'] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setDeleteTarget(null)
    }
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-surface px-6 py-4">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            <Server className="h-5 w-5 text-accent" />
            {t('providerHub.title')}
          </h1>
          <p className="mt-1 text-sm text-ink-muted">{t('providerHub.lead')}</p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="h-4 w-4" />
          {t('providerHub.create')}
        </Button>
      </header>

      <div className="space-y-4 px-6 py-6">
        {error !== null && (
          <p role="alert" className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </p>
        )}
        {notice !== null && (
          <p role="status" className="rounded-lg bg-success/10 px-3 py-2 text-sm text-success">
            {notice}
          </p>
        )}
        {configs.isLoading && (
          <div className="flex items-center gap-2 text-sm text-ink-muted">
            <Spinner />
            {t('common.loading')}
          </div>
        )}
        {configs.data !== undefined && configs.data.length === 0 && (
          <EmptyState title={t('providerHub.empty')} description={t('providerHub.emptyLead')}>
            <Button onClick={openCreate}>
              <Plus className="h-4 w-4" />
              {t('providerHub.create')}
            </Button>
          </EmptyState>
        )}
        {configs.data?.map((config) => (
          <article key={config.id} className="rounded-card border border-border bg-surface p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-ink">{config.name}</span>
                  <Badge tone={statusTone(config.status)}>{config.status}</Badge>
                  {config.shared && <Badge tone="accent">{t('providerHub.shared')}</Badge>}
                  {!config.owned && <Badge tone="neutral">{t('providerHub.sharedReadOnly')}</Badge>}
                </div>
                <p className="mt-1 break-all font-mono text-xs text-ink-muted">{config.base_url}</p>
                <p className="mt-1 text-xs text-ink-muted">
                  {t('providerHub.keyHint')}: {config.api_key_hint} ·{' '}
                  {t('providerHub.modelCount', { count: config.model_count })}
                  {config.last_error !== null ? ` · ${config.last_error}` : ''}
                </p>
                {config.note !== '' && (
                  <p className="mt-1 text-xs text-ink-muted">{config.note}</p>
                )}
              </div>
              <div className="flex flex-wrap gap-1">
                {config.owned && (
                  <>
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={testingId === config.id}
                      onClick={() => void test(config)}
                    >
                      {testingId === config.id ? <Spinner /> : <Zap className="h-3 w-3" />}
                      {t('providerHub.test')}
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={syncingId === config.id}
                      onClick={() => void sync(config)}
                    >
                      {syncingId === config.id ? <Spinner /> : <RefreshCw className="h-3 w-3" />}
                      {t('providerHub.sync')}
                    </Button>
                    <Button variant="secondary" size="sm" onClick={() => openEdit(config)}>
                      {t('common.edit')}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={t('common.delete')}
                      onClick={() => setDeleteTarget(config)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setExpandedId(expandedId === config.id ? null : config.id)}
                >
                  {t('providerHub.models')}
                </Button>
              </div>
            </div>
            {expandedId === config.id && <ProviderModelsPanel config={config} />}
          </article>
        ))}
      </div>

      <Dialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        title={editTarget === null ? t('providerHub.create') : t('providerHub.edit')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setDialogOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button size="sm" disabled={busy} onClick={() => void save()}>
              {busy && <Spinner />}
              {t('common.save')}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <label className="block text-xs text-ink-muted">
            <span className="mb-1 block">{t('providerHub.name')}</span>
            <Input
              value={form.name}
              onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
              placeholder={t('providerHub.namePlaceholder')}
            />
          </label>
          <label className="block text-xs text-ink-muted">
            <span className="mb-1 block">{t('providerHub.type')}</span>
            <select
              className="h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm"
              value={form.provider_type}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, provider_type: event.target.value }))
              }
            >
              <option value="openai_compatible">{t('providerHub.typeOpenAI')}</option>
              <option value="custom">{t('providerHub.typeCustom')}</option>
            </select>
          </label>
          <label className="block text-xs text-ink-muted">
            <span className="mb-1 block">{t('providerHub.endpoint')}</span>
            <Input
              value={form.base_url}
              onChange={(event) => setForm((prev) => ({ ...prev, base_url: event.target.value }))}
              placeholder="https://api.example.com/v1"
            />
          </label>
          <label className="block text-xs text-ink-muted">
            <span className="mb-1 block">{t('providerHub.apiKey')}</span>
            <Input
              type="password"
              value={form.api_key}
              onChange={(event) => setForm((prev) => ({ ...prev, api_key: event.target.value }))}
              placeholder={editTarget === null ? 'sk-...' : t('providerHub.apiKeyEditHint')}
            />
          </label>
          <label className="block text-xs text-ink-muted">
            <span className="mb-1 block">{t('providerHub.note')}</span>
            <Textarea
              className="min-h-16 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
              value={form.note}
              onChange={(event) => setForm((prev) => ({ ...prev, note: event.target.value }))}
            />
          </label>
          <label className="flex items-start gap-2 text-sm text-ink">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={form.shared}
              onChange={(event) => setForm((prev) => ({ ...prev, shared: event.target.checked }))}
            />
            <span>
              <span className="block">{t('providerHub.share')}</span>
              <span className="block text-xs text-ink-muted">{t('providerHub.shareHint')}</span>
            </span>
          </label>
          {error !== null && <p className="text-sm text-danger">{error}</p>}
          <p className="text-xs text-ink-muted">
            {t('providerHub.capabilitiesHint')}: {CAPABILITIES.join(' / ')}
          </p>
        </div>
      </Dialog>

      <Dialog
        open={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        title={t('providerHub.deleteTitle')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setDeleteTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button variant="danger" size="sm" onClick={() => void remove()}>
              {t('common.delete')}
            </Button>
          </>
        }
      >
        {t('providerHub.deleteConfirm', { name: deleteTarget?.name ?? '' })}
      </Dialog>
    </div>
  )
}