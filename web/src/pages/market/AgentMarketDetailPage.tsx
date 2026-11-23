import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Copy } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Spinner } from '../../components/ui/spinner'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import { hasSession } from '../../lib/tokens'
import type { AgentMarketDetail, CustomAgent } from '../../lib/types'

export function AgentMarketDetailPage() {
  const { slug = '' } = useParams<{ slug: string }>()
  const { t } = useI18n()
  const navigate = useNavigate()
  const [copying, setCopying] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const agent = useQuery({
    queryKey: ['market-agent', slug],
    queryFn: () =>
      apiRequest<AgentMarketDetail>(`/market/agents/${slug}`, { auth: false }),
    enabled: slug !== '',
  })

  if (agent.isLoading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Spinner className="h-6 w-6 text-accent" />
      </div>
    )
  }
  if (agent.isError || agent.data === undefined) {
    return (
      <div className="mx-auto flex min-h-[50vh] w-full max-w-3xl flex-col items-center justify-center gap-3 px-6">
        <p className="text-sm text-ink-muted">{t('market.missing')}</p>
        <Link to="/market/agents" className="text-sm text-accent">
          {t('market.back')}
        </Link>
      </div>
    )
  }

  const detail = agent.data
  const copy = async () => {
    if (!hasSession()) {
      navigate(`/login?next=${encodeURIComponent(`/market/agents/${slug}`)}`)
      return
    }
    setCopying(true)
    setError(null)
    try {
      const created = await apiRequest<CustomAgent>(`/agents/${detail.id}/copy`, {
        method: 'POST',
      })
      navigate(`/studio/${created.id}`)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('errors.generic'))
    } finally {
      setCopying(false)
    }
  }

  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-10">
      <Link
        to="/market/agents"
        className="inline-flex items-center gap-1 text-xs text-ink-muted hover:text-ink"
      >
        <ArrowLeft className="h-3 w-3" />
        {t('market.back')}
      </Link>
      <header className="mt-4 flex flex-wrap items-start gap-4">
        <span className="flex h-16 w-16 items-center justify-center rounded-2xl bg-accent-soft text-3xl">
          {detail.icon}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold text-ink">{detail.name}</h1>
            <Badge tone="neutral">{detail.mode}</Badge>
            {detail.featured && <Badge tone="accent">{t('market.featured')}</Badge>}
            {detail.allow_copy && <Badge tone="success">{t('market.copyable')}</Badge>}
          </div>
          <p className="mt-1 text-sm text-ink-muted">{detail.description}</p>
          <div className="mt-2 flex flex-wrap gap-4 text-[11px] text-ink-muted">
            <span>{detail.usage_count} uses</span>
            <span>{detail.favorite_count} favorites</span>
            <span>{detail.copy_count} copies</span>
            {detail.model_hint && <span>{detail.model_hint}</span>}
          </div>
        </div>
        <Button size="sm" disabled={copying || !detail.allow_copy} onClick={() => void copy()}>
          <Copy className="h-3.5 w-3.5" />
          {t('market.copyToWorkspace')}
        </Button>
      </header>
      {error !== null && <p className="mt-2 text-xs text-danger">{error}</p>}

      <div className="mt-8 grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <section className="rounded-card border border-border bg-surface p-5">
          <h2 className="text-sm font-medium text-ink">{t('market.about')}</h2>
          <p className="mt-2 whitespace-pre-wrap text-sm text-ink-muted">
            {detail.usage_instructions || detail.description}
          </p>
          {detail.welcome_message && (
            <p className="mt-3 rounded-lg bg-surface-muted p-3 text-xs text-ink">
              {detail.welcome_message}
            </p>
          )}
          {detail.examples.length > 0 && (
            <>
              <h3 className="mt-4 text-xs font-medium text-ink">{t('market.examples')}</h3>
              <ul className="mt-1 list-inside list-disc text-xs text-ink-muted">
                {detail.examples.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          )}
        </section>

        <section className="space-y-4">
          <div className="rounded-card border border-border bg-surface p-5">
            <h2 className="text-sm font-medium text-ink">{t('market.requirements')}</h2>
            {detail.kb_requirements.length === 0 &&
            detail.plugin_requirements.length === 0 ? (
              <p className="mt-2 text-xs text-ink-muted">{t('market.noRequirements')}</p>
            ) : (
              <div className="mt-2 space-y-2 text-xs text-ink-muted">
                {detail.kb_requirements.length > 0 && (
                  <p>
                    <span className="font-medium text-ink">KB</span>:{' '}
                    {detail.kb_requirements.join(', ')}
                  </p>
                )}
                {detail.plugin_requirements.length > 0 && (
                  <p>
                    <span className="font-medium text-ink">Plugins</span>:{' '}
                    {detail.plugin_requirements.join(', ')}
                  </p>
                )}
              </div>
            )}
          </div>

          {detail.workflow ? (
            <div className="rounded-card border border-border bg-surface p-5">
              <h2 className="text-sm font-medium text-ink">{t('market.structure')}</h2>
              <div className="mt-2 space-y-2">
                {detail.workflow.nodes.map((node) => (
                  <div
                    key={node.id}
                    className="flex items-center justify-between rounded-lg bg-surface-muted px-3 py-1.5 text-xs"
                  >
                    <span className="text-ink">{node.id}</span>
                    <span className="text-ink-muted">{node.type}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="rounded-card border border-border bg-surface p-5">
              <h2 className="text-sm font-medium text-ink">{t('market.structure')}</h2>
              <p className="mt-2 text-xs text-ink-muted">
                {t('market.structureHidden')}
              </p>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}