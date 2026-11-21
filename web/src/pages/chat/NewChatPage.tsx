import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'

import { Button } from '../../components/ui/button'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { Conversation, KnowledgeBase, Provider } from '../../lib/types'
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
  const [providerId, setProviderId] = useState('')
  const [model, setModel] = useState('')
  const [kbId, setKbId] = useState('')
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)

  const providersQuery = useQuery({
    queryKey: ['providers'],
    queryFn: () => apiRequest<Provider[]>('/providers'),
    staleTime: 60_000,
  })
  const kbsQuery = useQuery({
    queryKey: ['kbs'],
    queryFn: () => apiRequest<KnowledgeBase[]>('/knowledge-bases'),
    staleTime: 60_000,
  })

  const availableProviders = (providersQuery.data ?? []).filter((provider) => provider.available)
  const selectedProvider =
    availableProviders.find((provider) => provider.id === providerId) ?? availableProviders[0]
  const models = selectedProvider?.models ?? []
  const currentModel = models.includes(model) ? model : (models[0] ?? '')
  const canChat = selectedProvider !== undefined && currentModel !== ''

  const send = async (content: string) => {
    if (selectedProvider === undefined || currentModel === '') {
      setError(t('chat.noProviders'))
      throw new Error('no provider')
    }
    setError(null)
    try {
      const conversation = await apiRequest<Conversation>('/conversations', {
        method: 'POST',
        body: {
          provider_id: selectedProvider.id,
          model: currentModel,
          kb_id: kbId === '' ? null : kbId,
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

        {providersQuery.isLoading ? (
          <div className="mt-8 flex items-center gap-2 text-sm text-ink-muted">
            <Spinner />
            {t('common.loading')}
          </div>
        ) : availableProviders.length === 0 ? (
          <p className="mt-8 rounded-lg bg-warning/10 px-3 py-2 text-sm text-warning">
            {t('chat.noProviders')}
          </p>
        ) : (
          <div className="mt-8 grid gap-3 sm:grid-cols-3">
            <Field label={t('chat.provider')}>
              <select
                className={selectClass}
                value={selectedProvider?.id ?? ''}
                onChange={(event) => {
                  setProviderId(event.target.value)
                  setModel('')
                }}
              >
                {availableProviders.map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.id}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t('chat.model')}>
              <select
                className={selectClass}
                value={currentModel}
                onChange={(event) => setModel(event.target.value)}
              >
                {models.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
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