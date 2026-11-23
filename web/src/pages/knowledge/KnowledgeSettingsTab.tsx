import { useQuery } from '@tanstack/react-query'
import { Save } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { KnowledgeBaseSettings, PersonalModel } from '../../lib/types'

interface KnowledgeSettingsTabProps {
  kbId: string
  settings: KnowledgeBaseSettings
  onSaved: (settings: KnowledgeBaseSettings) => void
}

export function KnowledgeSettingsTab({ kbId, settings, onSaved }: KnowledgeSettingsTabProps) {
  const { t } = useI18n()
  const [form, setForm] = useState(settings)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [metadataText, setMetadataText] = useState(
    JSON.stringify(settings.retrieval.metadata_filter ?? {}, null, 2),
  )
  const providerModels = useQuery({
    queryKey: ['provider-configs', 'models'],
    queryFn: () => apiRequest<PersonalModel[]>('/provider-configs/models'),
    staleTime: 60_000,
  })

  useEffect(() => {
    setForm(settings)
    setMetadataText(JSON.stringify(settings.retrieval.metadata_filter ?? {}, null, 2))
  }, [settings])

  const embeddingModels = (providerModels.data ?? []).filter((model) =>
    model.capabilities.includes('embedding'),
  )
  const rerankModels = (providerModels.data ?? []).filter((model) =>
    model.capabilities.includes('rerank'),
  )
  const invalidChunking = form.chunking.chunk_overlap >= form.chunking.chunk_size
  const invalidCandidates = form.retrieval.candidate_k < form.retrieval.top_k

  const save = async () => {
    if (invalidChunking || invalidCandidates || saving) return
    setError(null)
    setMessage(null)
    let metadataFilter: Record<string, string>
    try {
      const parsed = JSON.parse(metadataText || '{}') as unknown
      if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('metadata filter must be an object')
      }
      metadataFilter = Object.fromEntries(
        Object.entries(parsed as Record<string, unknown>)
          .filter(([, value]) => typeof value === 'string')
          .map(([key, value]) => [key, String(value)]),
      )
    } catch {
      setError(t('knowledge.settings.invalidMetadata'))
      return
    }
    setSaving(true)
    try {
      const saved = await apiRequest<KnowledgeBaseSettings>(
        `/knowledge-bases/${kbId}/settings`,
        {
          method: 'PATCH',
          body: {
            ...form,
            retrieval: { ...form.retrieval, metadata_filter: metadataFilter },
          },
        },
      )
      setForm(saved)
      setMetadataText(JSON.stringify(saved.retrieval.metadata_filter ?? {}, null, 2))
      onSaved(saved)
      setMessage(t('knowledge.settings.saved'))
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setSaving(false)
    }
  }

  const updateChunking = (key: 'chunk_size' | 'chunk_overlap', value: number) => {
    setForm((previous) => ({
      ...previous,
      chunking: { ...previous.chunking, [key]: value },
    }))
  }

  const updateRetrievalNumber = (key: 'top_k' | 'candidate_k', value: number) => {
    setForm((previous) => ({
      ...previous,
      retrieval: { ...previous.retrieval, [key]: value },
    }))
  }

  const updateRetrievalFlag = (key: 'hybrid_enabled' | 'rerank_enabled', value: boolean) => {
    setForm((previous) => ({
      ...previous,
      retrieval: { ...previous.retrieval, [key]: value },
    }))
  }

  return (
    <div className="max-w-3xl space-y-4">
      <section className="rounded-card border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold">{t('knowledge.settings.chunkingTitle')}</h2>
        <p className="mt-1 text-xs text-ink-muted">{t('knowledge.settings.chunkingLead')}</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <label className="text-xs text-ink-muted">
            <span className="mb-1 block">{t('knowledge.settings.chunkSize')}</span>
            <Input
              type="number"
              min={50}
              max={4000}
              value={form.chunking.chunk_size}
              onChange={(event) => updateChunking('chunk_size', Number(event.target.value) || 50)}
            />
          </label>
          <label className="text-xs text-ink-muted">
            <span className="mb-1 block">{t('knowledge.settings.chunkOverlap')}</span>
            <Input
              type="number"
              min={0}
              max={1000}
              value={form.chunking.chunk_overlap}
              onChange={(event) => updateChunking('chunk_overlap', Number(event.target.value) || 0)}
            />
          </label>
        </div>
        {invalidChunking && (
          <p className="mt-2 text-xs text-danger">{t('knowledge.settings.invalidOverlap')}</p>
        )}
      </section>

      <section className="rounded-card border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold">{t('knowledge.settings.retrievalTitle')}</h2>
        <p className="mt-1 text-xs text-ink-muted">{t('knowledge.settings.retrievalLead')}</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <label className="text-xs text-ink-muted">
            <span className="mb-1 block">{t('knowledge.settings.topK')}</span>
            <Input
              type="number"
              min={1}
              max={20}
              value={form.retrieval.top_k}
              onChange={(event) => updateRetrievalNumber('top_k', Number(event.target.value) || 1)}
            />
          </label>
          <label className="text-xs text-ink-muted">
            <span className="mb-1 block">{t('knowledge.settings.candidateK')}</span>
            <Input
              type="number"
              min={1}
              max={100}
              value={form.retrieval.candidate_k}
              onChange={(event) => updateRetrievalNumber('candidate_k', Number(event.target.value) || 1)}
            />
          </label>
        </div>
        {invalidCandidates && (
          <p className="mt-2 text-xs text-danger">{t('knowledge.settings.invalidCandidates')}</p>
        )}
        <div className="mt-3 space-y-2">
          <label className="flex items-start gap-2 text-sm text-ink">
            <input
              type="checkbox"
              className="mt-1"
              checked={form.retrieval.hybrid_enabled}
              onChange={(event) => updateRetrievalFlag('hybrid_enabled', event.target.checked)}
            />
            <span>
              <span className="font-medium">{t('knowledge.settings.hybrid')}</span>
              <span className="block text-xs text-ink-muted">
                {t('knowledge.settings.hybridLead')}
              </span>
            </span>
          </label>
          <label className="flex items-start gap-2 text-sm text-ink">
            <input
              type="checkbox"
              className="mt-1"
              checked={form.retrieval.rerank_enabled}
              onChange={(event) => updateRetrievalFlag('rerank_enabled', event.target.checked)}
            />
            <span>
              <span className="font-medium">{t('knowledge.settings.rerank')}</span>
              <span className="block text-xs text-ink-muted">
                {t('knowledge.settings.rerankLead')}
              </span>
            </span>
          </label>
        </div>
        <label className="mt-3 block text-xs text-ink-muted">
          <span className="mb-1 block font-medium text-ink">
            {t('knowledge.settings.metadataFilter')}
          </span>
          <span className="mb-2 block">{t('knowledge.settings.metadataFilterLead')}</span>
          <textarea
            value={metadataText}
            onChange={(event) => setMetadataText(event.target.value)}
            placeholder='{"department": "finance"}'
            className="min-h-24 w-full rounded-lg border border-border bg-surface px-3 py-2 font-mono text-xs text-ink focus:border-accent focus:outline-none"
          />
        </label>
        <p className="mt-3 text-xs text-ink-muted">{t('knowledge.settings.note')}</p>
      </section>


      <section className="rounded-card border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold">{t('knowledge.settings.modelsTitle')}</h2>
        <p className="mt-1 text-xs text-ink-muted">{t('knowledge.settings.modelsLead')}</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <label className="text-xs text-ink-muted">
            <span className="mb-1 block">{t('knowledge.settings.embeddingModel')}</span>
            <select
              className="h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm"
              value={
                form.embedding.provider_config_id !== null && form.embedding.model !== null
                  ? `${form.embedding.provider_config_id}|${form.embedding.model}`
                  : ''
              }
              onChange={(event) => {
                const [providerId, modelId] = event.target.value.split('|')
                setForm((previous) => ({
                  ...previous,
                  embedding: {
                    ...previous.embedding,
                    provider_config_id: event.target.value === '' ? null : providerId,
                    model: event.target.value === '' ? null : modelId,
                  },
                }))
              }}
            >
              <option value="">{t('knowledge.settings.defaultModel')}</option>
              {embeddingModels.map((model) => (
                <option
                  key={`${model.provider_id}|${model.model_id}`}
                  value={`${model.provider_id}|${model.model_id}`}
                >
                  {model.display_name} · {model.provider_name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-ink-muted">
            <span className="mb-1 block">{t('knowledge.settings.rerankModel')}</span>
            <select
              className="h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm"
              value={
                form.rerank.provider_config_id !== null && form.rerank.model !== null
                  ? `${form.rerank.provider_config_id}|${form.rerank.model}`
                  : ''
              }
              onChange={(event) => {
                const [providerId, modelId] = event.target.value.split('|')
                setForm((previous) => ({
                  ...previous,
                  rerank: {
                    ...previous.rerank,
                    provider_config_id: event.target.value === '' ? null : providerId,
                    model: event.target.value === '' ? null : modelId,
                  },
                }))
              }}
            >
              <option value="">{t('knowledge.settings.defaultModel')}</option>
              {rerankModels.map((model) => (
                <option
                  key={`${model.provider_id}|${model.model_id}`}
                  value={`${model.provider_id}|${model.model_id}`}
                >
                  {model.display_name} · {model.provider_name}
                </option>
              ))}
            </select>
          </label>
        </div>
        {embeddingModels.length === 0 && rerankModels.length === 0 && (
          <p className="mt-2 text-xs text-ink-muted">
            {t('knowledge.settings.noProviderModels')}
          </p>
        )}
        <p className="mt-2 text-xs text-ink-muted">{t('knowledge.settings.modelsHint')}</p>
      </section>

      <div className="flex items-center gap-3">
        <Button
          disabled={saving || invalidChunking || invalidCandidates}
          onClick={() => void save()}
        >
          {saving ? <Spinner /> : <Save className="h-4 w-4" />}
          {t('common.save')}
        </Button>
        {message !== null && <span className="text-xs text-success">{message}</span>}
        {error !== null && <span className="text-xs text-danger">{error}</span>}
      </div>
    </div>
  )
}