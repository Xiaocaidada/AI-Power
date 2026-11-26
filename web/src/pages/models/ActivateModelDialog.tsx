import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { Input } from '../../components/ui/input'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { MarketModel, MarketModelActivateResult } from '../../lib/types'

interface ActivateModelDialogProps {
  model: MarketModel
  onClose: () => void
  onActivated: (providerId: string, modelId: string) => void
}

export function ActivateModelDialog({
  model,
  onClose,
  onActivated,
}: ActivateModelDialogProps) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [baseUrl, setBaseUrl] = useState(model.provider_base_url)
  const [apiKey, setApiKey] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const canSubmit = baseUrl.trim() !== '' && apiKey.trim() !== '' && !saving

  const submit = async () => {
    if (!canSubmit) return
    setSaving(true)
    setError(null)
    try {
      const result = await apiRequest<MarketModelActivateResult>(
        `/market/models/${model.slug}/activate`,
        {
          method: 'POST',
          body: { base_url: baseUrl.trim(), api_key: apiKey.trim() },
        },
      )
      await queryClient.invalidateQueries({ queryKey: ['provider-configs', 'models'] })
      await queryClient.invalidateQueries({ queryKey: ['provider-configs'] })
      setApiKey('')
      onActivated(result.provider_id, result.model_id)
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
      title={t('models.activateTitle', { name: model.name })}
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button size="sm" disabled={!canSubmit} onClick={() => void submit()}>
            {t('models.activateSubmit')}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <p className="text-xs leading-5 text-ink-muted">{t('models.activateLead')}</p>
        <label className="block text-xs text-ink-muted">
          {t('models.baseUrl')}
          <Input
            className="mt-1"
            value={baseUrl}
            placeholder="https://api.example.com/v1"
            onChange={(event) => setBaseUrl(event.target.value)}
          />
        </label>
        <label className="block text-xs text-ink-muted">
          {t('models.apiKey')}
          <Input
            className="mt-1"
            type="password"
            autoComplete="off"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
          />
          <span className="mt-1 block text-[11px] text-ink-muted">
            {t('models.apiKeyHint')}
          </span>
        </label>
        <div className="rounded-lg bg-surface-muted px-3 py-2 text-[11px] text-ink-muted">
          {model.provider_name} · {model.model_id}
          {model.context_window > 0 && (
            <> · {new Intl.NumberFormat().format(model.context_window)} ctx</>
          )}
        </div>
        {error !== null && <p className="text-xs text-danger">{error}</p>}
      </div>
    </Dialog>
  )
}