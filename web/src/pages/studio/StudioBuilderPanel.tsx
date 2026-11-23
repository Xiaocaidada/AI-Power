import { Sparkles } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { PopoverSelect } from '../../components/ui/popover-select'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { AgentBuilderResult, WorkflowDefinition } from '../../lib/types'
import type { ModelChoice } from './types'

interface StudioBuilderPanelProps {
  agentId: string
  definition: WorkflowDefinition
  models: ModelChoice[]
  onApply: (definition: WorkflowDefinition) => void
}

export function StudioBuilderPanel({
  agentId,
  definition,
  models,
  onApply,
}: StudioBuilderPanelProps) {
  const { t } = useI18n()
  const [prompt, setPrompt] = useState('')
  const [choice, setChoice] = useState(
    models[0] === undefined ? '' : `${models[0].provider_id}/${models[0].model}`,
  )
  const [result, setResult] = useState<AgentBuilderResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (models.length === 0) return
    const options = new Set(models.map((item) => `${item.provider_id}/${item.model}`))
    if (choice === '' || !options.has(choice)) {
      setChoice(`${models[0].provider_id}/${models[0].model}`)
    }
  }, [choice, models])

  const generate = async () => {
    if (prompt.trim() === '' || choice === '') return
    const [providerId, ...rest] = choice.split('/')
    setLoading(true)
    setError(null)
    try {
      const response = await apiRequest<AgentBuilderResult>('/agent-builder/generate', {
        method: 'POST',
        body: {
          prompt: prompt.trim(),
          provider_id: providerId,
          model: rest.join('/'),
          current_definition: definition,
          agent_id: agentId,
        },
      })
      setResult(response)
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto grid w-full max-w-6xl gap-4 px-6 py-6 lg:grid-cols-[1.1fr_1fr]">
        <section className="rounded-card border border-border bg-surface p-4">
          <h2 className="flex items-center gap-2 text-sm font-medium text-ink">
            <Sparkles className="h-4 w-4 text-accent" />
            {t('studio.builderTitle')}
          </h2>
          <p className="mt-1 text-xs text-ink-muted">{t('studio.builderLead')}</p>
          <label className="mt-3 block text-xs text-ink-muted">
            {t('studio.builderModel')}
            <PopoverSelect
              label={t('studio.builderModel')}
              value={choice}
              options={models.map((item) => ({
                value: `${item.provider_id}/${item.model}`,
                label: item.label,
              }))}
              onChange={setChoice}
            />
          </label>
          <label className="mt-3 block text-xs text-ink-muted">
            {t('studio.builderPrompt')}
            <textarea
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder={t('studio.builderPlaceholder')}
              className="mt-1 min-h-48 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink"
            />
          </label>
          <div className="mt-3 flex items-center gap-3">
            <Button
              size="sm"
              disabled={loading || prompt.trim() === '' || choice === ''}
              onClick={() => void generate()}
            >
              <Sparkles className="h-3.5 w-3.5" />
              {loading ? t('studio.builderGenerating') : t('studio.builderGenerate')}
            </Button>
            {error !== null && <p className="text-xs text-danger">{error}</p>}
          </div>
        </section>

        <section className="rounded-card border border-border bg-surface p-4">
          <p className="text-sm font-medium text-ink">{t('studio.builderResult')}</p>
          {result === null ? (
            <p className="mt-2 text-xs text-ink-muted">{t('studio.builderEmpty')}</p>
          ) : (
            <div className="mt-3 space-y-3">
              <p className="text-xs text-ink">{result.summary || '—'}</p>
              <div className="flex flex-wrap gap-2 text-[11px] text-ink-muted">
                <Badge tone="neutral">
                  {result.definition.nodes.length} {t('studio.nodes')}
                </Badge>
                <Badge tone="neutral">
                  {result.definition.edges.length} {t('studio.edges')}
                </Badge>
              </div>
              {result.missing_resources.length > 0 && (
                <div className="rounded-lg border border-warning/40 bg-warning/10 p-2">
                  <p className="text-xs font-medium text-warning">
                    {t('studio.missingResources')}
                  </p>
                  <ul className="mt-1 list-inside list-disc text-[11px] text-ink">
                    {result.missing_resources.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}
              <div className="max-h-72 overflow-auto rounded-lg border border-border bg-surface-muted p-2 font-mono text-[10px] text-ink">
                {result.definition.nodes.map((node) => (
                  <div key={node.id}>
                    {node.id} · {node.type}
                  </div>
                ))}
              </div>
              <Button
                size="sm"
                onClick={() => {
                  onApply(result.definition)
                }}
              >
                {t('studio.applyToCanvas')}
              </Button>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}