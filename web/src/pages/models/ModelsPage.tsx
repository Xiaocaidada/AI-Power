import { useQuery } from '@tanstack/react-query'
import { Check } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { EmptyState } from '../../components/ui/empty-state'
import { Spinner } from '../../components/ui/spinner'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { ModelEntry } from '../../lib/types'
import { cn } from '../../lib/utils'

const MAX_COMPARE = 3

export function ModelsPage() {
  const { t, language } = useI18n()
  const [selected, setSelected] = useState<string[]>([])
  const numberFormat = new Intl.NumberFormat(language === 'zh' ? 'zh-CN' : 'en')

  const models = useQuery({
    queryKey: ['models'],
    queryFn: () => apiRequest<ModelEntry[]>('/models'),
  })
  const compare = useQuery({
    queryKey: ['models-compare', selected.join(',')],
    queryFn: () =>
      apiRequest<ModelEntry[]>(`/models/compare?ids=${encodeURIComponent(selected.join(','))}`),
    enabled: selected.length >= 2,
  })

  const toggle = (id: string) => {
    setSelected((previous) => {
      if (previous.includes(id)) return previous.filter((item) => item !== id)
      if (previous.length >= MAX_COMPARE) return previous
      return [...previous, id]
    })
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-4">
        <h1 className="text-lg font-semibold">{t('models.title')}</h1>
        <p className="mt-1 text-sm text-ink-muted">{t('models.lead')}</p>
      </header>

      <div className="space-y-5 px-6 py-6">
        {models.isLoading && (
          <div className="flex items-center gap-2 text-sm text-ink-muted">
            <Spinner />
            {t('common.loading')}
          </div>
        )}
        {models.isError && (
          <div className="flex items-center gap-3 text-sm text-ink-muted">
            {t('errors.generic')}
            <Button variant="secondary" size="sm" onClick={() => void models.refetch()}>
              {t('common.retry')}
            </Button>
          </div>
        )}
        {models.data !== undefined && models.data.length === 0 && (
          <EmptyState title={t('models.empty')} />
        )}

        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {models.data?.map((model) => {
            const active = selected.includes(model.id)
            return (
              <article
                key={model.id}
                className={cn(
                  'rounded-card border bg-surface p-4 transition-colors',
                  active ? 'border-accent' : 'border-border',
                )}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <h2 className="truncate text-sm font-semibold text-ink">
                      {model.display_name}
                    </h2>
                    <p className="truncate font-mono text-[11px] text-ink-muted">
                      {model.provider_id} · {model.model_id}
                    </p>
                  </div>
                  <Badge tone={model.available ? 'success' : 'danger'}>
                    {model.available ? t('models.available') : t('models.unavailable')}
                  </Badge>
                </div>

                <div className="mt-3 flex flex-wrap gap-1">
                  {model.tags.map((tag) => (
                    <Badge key={tag} tone="accent">
                      {tag}
                    </Badge>
                  ))}
                </div>

                <dl className="mt-3 grid grid-cols-3 gap-2 text-xs text-ink-muted">
                  <div>
                    <dt>{t('models.context')}</dt>
                    <dd className="mt-0.5 font-mono text-ink">
                      {numberFormat.format(model.context_window)}
                    </dd>
                  </div>
                  <div>
                    <dt>{t('models.inputPrice')}</dt>
                    <dd className="mt-0.5 font-mono text-ink">
                      {model.input_price}{' '}
                      <span className="text-[10px]">{t('models.perMillion')}</span>
                    </dd>
                  </div>
                  <div>
                    <dt>{t('models.outputPrice')}</dt>
                    <dd className="mt-0.5 font-mono text-ink">
                      {model.output_price}{' '}
                      <span className="text-[10px]">{t('models.perMillion')}</span>
                    </dd>
                  </div>
                </dl>

                <div className="mt-4 flex justify-end">
                  <Button
                    size="sm"
                    variant={active ? 'primary' : 'secondary'}
                    onClick={() => toggle(model.id)}
                  >
                    {active && <Check className="h-3 w-3" />}
                    {active ? t('models.selected', { count: selected.length }) : t('models.compare')}
                  </Button>
                </div>
              </article>
            )
          })}
        </div>

        {selected.length >= 2 && (
          <section className="rounded-card border border-border bg-surface p-4">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold">{t('models.compareTitle')}</h2>
              <Button variant="ghost" size="sm" onClick={() => setSelected([])}>
                {t('models.clear')}
              </Button>
            </div>
            {compare.isLoading && <Spinner />}
            {compare.data !== undefined && (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] text-left text-sm">
                  <thead className="border-b border-border text-xs uppercase text-ink-muted">
                    <tr>
                      <th className="px-3 py-2 font-medium"> </th>
                      {compare.data.map((model) => (
                        <th key={model.id} className="px-3 py-2 font-medium">
                          {model.display_name}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-b border-border">
                      <td className="px-3 py-2 text-ink-muted">{t('models.context')}</td>
                      {compare.data.map((model) => (
                        <td key={model.id} className="px-3 py-2 font-mono">
                          {numberFormat.format(model.context_window)}
                        </td>
                      ))}
                    </tr>
                    <tr className="border-b border-border">
                      <td className="px-3 py-2 text-ink-muted">{t('models.inputPrice')}</td>
                      {compare.data.map((model) => (
                        <td key={model.id} className="px-3 py-2 font-mono">
                          {model.input_price}
                        </td>
                      ))}
                    </tr>
                    <tr className="border-b border-border">
                      <td className="px-3 py-2 text-ink-muted">{t('models.outputPrice')}</td>
                      {compare.data.map((model) => (
                        <td key={model.id} className="px-3 py-2 font-mono">
                          {model.output_price}
                        </td>
                      ))}
                    </tr>
                    <tr>
                      <td className="px-3 py-2 text-ink-muted">{t('models.available')}</td>
                      {compare.data.map((model) => (
                        <td key={model.id} className="px-3 py-2">
                          <Badge tone={model.available ? 'success' : 'danger'}>
                            {model.available ? t('models.available') : t('models.unavailable')}
                          </Badge>
                        </td>
                      ))}
                    </tr>
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  )
}