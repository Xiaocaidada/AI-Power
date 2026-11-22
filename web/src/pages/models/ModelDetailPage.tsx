import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Check, Copy, ExternalLink, Play, Server } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Spinner } from '../../components/ui/spinner'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { MarketModel } from '../../lib/types'
import { useAuthStore } from '../../store/auth'

type CodeTab = 'platform' | 'sdk' | 'compatible'

function examples(model: MarketModel): Record<CodeTab, string> {
  return {
    platform: `# 1. 创建会话
curl -X POST "$BASE/conversations" \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"provider_id":"${model.provider_id}","model":"${model.model_id}"}'

# 2. 流式发送消息
curl -N -X POST "$BASE/conversations/$CONVERSATION_ID/messages" \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"content":"你好，介绍一下你自己"}'`,
    sdk: `from ai_power_sdk import AIPowerClient

with AIPowerClient("http://your-host:8080/api", api_key="ap_...") as client:
    conversation = client.create_conversation(
        provider_id="${model.provider_id}",
        model="${model.model_id}",
    )
    for event in client.chat_stream(conversation["id"], "你好，介绍一下你自己"):
        if event.event == "delta":
            print(event.json().get("text", ""), end="")`,
    compatible: `curl -N -X POST "$PROVIDER_BASE_URL/chat/completions" \\
  -H "Authorization: Bearer $PROVIDER_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "${model.model_id}",
    "stream": true,
    "messages": [{"role": "user", "content": "你好"}]
  }'`,
  }
}

export function ModelDetailPage() {
  const { t, language } = useI18n()
  const { slug = '' } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const status = useAuthStore((state) => state.status)
  const [codeTab, setCodeTab] = useState<CodeTab>('platform')
  const [copied, setCopied] = useState(false)
  const numberFormat = new Intl.NumberFormat(language === 'zh' ? 'zh-CN' : 'en')

  const model = useQuery({
    queryKey: ['market-model', slug],
    queryFn: () => apiRequest<MarketModel>(`/market/models/${slug}`, { auth: false }),
    enabled: slug !== '',
  })

  if (model.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner className="h-6 w-6 text-accent" />
      </div>
    )
  }

  if (model.isError || model.data === undefined) {
    return (
      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col items-center justify-center gap-3 px-6">
        <p className="text-sm text-ink-muted">{t('models.detailMissing')}</p>
        <Button variant="secondary" onClick={() => navigate('/models')}>
          {t('models.backToMarket')}
        </Button>
      </div>
    )
  }

  const detail = model.data
  const snippets = examples(detail)
  const snippet = snippets[codeTab]

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(snippet)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }

  const experience = () => {
    const target = `/models/${detail.slug}/playground`
    if (status === 'anonymous') {
      navigate('/login', { state: { from: target } })
    } else {
      navigate(target)
    }
  }

  return (
    <div className="flex-1">
      <div className="border-b border-border bg-surface">
        <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6">
          <Link
            to="/models"
            className="inline-flex items-center gap-1 text-xs text-ink-muted hover:text-ink"
          >
            <ArrowLeft className="h-3 w-3" />
            {t('models.backToMarket')}
          </Link>
          <div className="mt-5 flex flex-wrap items-start justify-between gap-4">
            <div className="flex items-start gap-4">
              <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent-soft text-lg font-semibold text-accent">
                {detail.name.slice(0, 2).toUpperCase()}
              </span>
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="text-2xl font-semibold text-ink">{detail.name}</h1>
                  {detail.featured && <Badge tone="accent">{t('models.featured')}</Badge>}
                  {detail.is_new && <Badge tone="success">{t('models.new')}</Badge>}
                  <Badge tone={detail.available ? 'success' : 'neutral'}>
                    {detail.available ? t('models.available') : t('models.configRequiredShort')}
                  </Badge>
                </div>
                <p className="mt-1 text-sm text-ink-muted">
                  {detail.provider_name} · {detail.model_id} · {detail.category}
                </p>
                <div className="mt-3 flex flex-wrap gap-1">
                  {detail.capabilities.map((capability) => (
                    <Badge key={capability} tone="neutral">
                      {capability}
                    </Badge>
                  ))}
                </div>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {detail.available ? (
                <Button onClick={experience}>
                  <Play className="h-4 w-4" />
                  {t('models.experience')}
                </Button>
              ) : (
                <Button variant="secondary" onClick={() => navigate('/settings/providers')}>
                  <Server className="h-4 w-4" />
                  {t('models.configure')}
                </Button>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="mx-auto grid w-full max-w-7xl gap-6 px-4 py-8 sm:px-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-6">
          <section className="rounded-2xl border border-border bg-surface p-6">
            <h2 className="text-sm font-semibold text-ink">{t('models.detailOverview')}</h2>
            <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-ink-muted">
              {detail.description || t('models.noDescription')}
            </p>
            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              <Spec label={t('models.context')} value={numberFormat.format(detail.context_window)} />
              <Spec
                label={t('models.maxOutput')}
                value={detail.max_output === null ? '—' : numberFormat.format(detail.max_output)}
              />
              <Spec label={t('models.inputTypes')} value={detail.input_types.join(', ')} />
              <Spec label={t('models.outputTypes')} value={detail.output_types.join(', ')} />
            </div>
            {detail.docs_url !== '' && (
              <a
                href={detail.docs_url}
                target="_blank"
                rel="noreferrer"
                className="mt-4 inline-flex items-center gap-1 text-sm text-accent"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                {t('models.docs')}
              </a>
            )}
          </section>

          <section className="rounded-2xl border border-border bg-surface p-6">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 className="text-sm font-semibold text-ink">{t('models.invocation')}</h2>
                <p className="mt-1 text-xs text-ink-muted">{t('models.invocationLead')}</p>
              </div>
              <div className="flex gap-1">
                {(['platform', 'sdk', 'compatible'] as const).map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    onClick={() => setCodeTab(tab)}
                    className={
                      codeTab === tab
                        ? 'rounded-lg bg-accent-soft px-2.5 py-1.5 text-xs font-medium text-accent'
                        : 'rounded-lg px-2.5 py-1.5 text-xs text-ink-muted hover:bg-surface-muted'
                    }
                  >
                    {tab === 'platform'
                      ? t('models.codePlatform')
                      : tab === 'sdk'
                        ? 'Python SDK'
                        : 'OpenAI-compatible'}
                  </button>
                ))}
              </div>
            </div>
            <div className="relative mt-4">
              <pre className="overflow-x-auto rounded-xl bg-[#0f172a] p-4 text-xs leading-6 text-slate-200">
                <code>{snippet}</code>
              </pre>
              <Button
                variant="secondary"
                size="sm"
                className="absolute right-3 top-3"
                onClick={() => void copy()}
              >
                {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                {copied ? t('common.copied') : t('common.copy')}
              </Button>
            </div>
            {!detail.available && (
              <p className="mt-3 rounded-lg bg-warning/10 px-3 py-2 text-xs text-warning">
                {t('models.configRequired')}
              </p>
            )}
          </section>
        </div>

        <aside className="space-y-4">
          <section className="rounded-2xl border border-border bg-surface p-5">
            <h2 className="text-sm font-semibold text-ink">{t('models.detailQuick')}</h2>
            <p className="mt-2 text-xs leading-5 text-ink-muted">{t('models.detailQuickLead')}</p>
            <Button className="mt-4 w-full" onClick={experience} disabled={!detail.available}>
              <Play className="h-4 w-4" />
              {t('models.experience')}
            </Button>
            <Button
              variant="secondary"
              className="mt-2 w-full"
              onClick={() => navigate('/settings/providers')}
            >
              <Server className="h-4 w-4" />
              {t('models.configure')}
            </Button>
          </section>
          <section className="rounded-2xl border border-border bg-surface p-5">
            <h2 className="text-sm font-semibold text-ink">{t('models.detailSpecs')}</h2>
            <dl className="mt-3 space-y-3 text-xs">
              <Spec label={t('models.provider')} value={detail.provider_name} />
              <Spec label={t('models.category')} value={detail.category} />
              <Spec label={t('models.modelId')} value={detail.model_id} mono />
            </dl>
          </section>
        </aside>
      </div>
    </div>
  )
}

function Spec({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-xs text-ink-muted">{label}</dt>
      <dd className={`mt-1 text-sm text-ink ${mono ? 'break-all font-mono text-xs' : ''}`}>
        {value}
      </dd>
    </div>
  )
}