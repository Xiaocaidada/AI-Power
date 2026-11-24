import { useQuery } from '@tanstack/react-query'
import { Plus, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { Input } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { CustomAgent, WorkflowCatalog, WorkflowTemplate } from '../../lib/types'

export function StudioListPage() {
  const { t } = useI18n()
  const navigate = useNavigate()
  const [template, setTemplate] = useState<WorkflowTemplate | null>(null)
  const [templateName, setTemplateName] = useState('')
  const [creating, setCreating] = useState(false)
  const [templateError, setTemplateError] = useState<string | null>(null)
  const agents = useQuery({
    queryKey: ['agents'],
    queryFn: () => apiRequest<CustomAgent[]>('/agents'),
  })
  const catalog = useQuery({
    queryKey: ['workflow-catalog', 'agent'],
    queryFn: () => apiRequest<WorkflowCatalog>('/workflows/catalog?kind=agent'),
    staleTime: 300_000,
  })
  const templates = (catalog.data?.templates ?? []).filter(
    (item) => item.id !== undefined,
  )

  const startTemplate = async () => {
    if (template?.id === undefined || templateName.trim() === '') return
    setCreating(true)
    setTemplateError(null)
    try {
      const created = await apiRequest<CustomAgent>('/agents/from-template', {
        method: 'POST',
        body: {
          template: template.id,
          name: templateName.trim(),
          description: template.description,
        },
      })
      navigate(`/studio/${created.id}`)
    } catch (caught) {
      setTemplateError(
        caught instanceof Error ? caught.message : t('errors.generic'),
      )
    } finally {
      setCreating(false)
    }
  }
  const custom = (agents.data ?? []).filter(
    (agent) => !agent.builtin && agent.owned,
  )

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-6xl px-6 py-8">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 font-serif text-2xl text-ink">
              <Sparkles className="h-5 w-5 text-accent" />
              {t('studio.listTitle')}
            </h1>
            <p className="mt-1 text-sm text-ink-muted">{t('studio.listLead')}</p>
          </div>
          <div className="flex gap-2">
            <Link to="/market/agents">
              <Button variant="secondary" size="sm">
                {t('studio.openPlaza')}
              </Button>
            </Link>
            <Link to="/agents">
              <Button size="sm">
                <Plus className="h-3.5 w-3.5" />
                {t('studio.newAgent')}
              </Button>
            </Link>
          </div>
        </header>

        {templates.length > 0 && (
          <section className="mt-6">
            <div>
              <h2 className="text-sm font-medium text-ink">{t('studio.templates')}</h2>
              <p className="mt-1 text-xs text-ink-muted">{t('studio.templatesHint')}</p>
            </div>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {templates.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => {
                    setTemplate(item)
                    setTemplateName(item.name)
                    setTemplateError(null)
                  }}
                  className="rounded-card border border-dashed border-border bg-surface p-4 text-left transition-colors hover:border-accent/60"
                >
                  <div className="flex items-start gap-3">
                    <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-soft text-lg">
                      {item.icon ?? '✨'}
                    </span>
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-ink">{item.name}</p>
                      <p className="mt-0.5 line-clamp-2 text-xs text-ink-muted">
                        {item.description}
                      </p>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </section>
        )}

        {agents.isLoading && <Spinner className="mt-8" />}
        {agents.data !== undefined && custom.length === 0 && (
          <div className="mt-10 rounded-card border border-dashed border-border p-10 text-center">
            <p className="text-sm text-ink-muted">{t('studio.noAgents')}</p>
            <Link to="/agents" className="mt-2 inline-block text-sm text-accent">
              {t('studio.newAgent')}
            </Link>
          </div>
        )}
        <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {custom.map((agent) => (
            <Link
              key={agent.id}
              to={`/studio/${agent.id}`}
              className="rounded-card border border-border bg-surface p-4 transition-colors hover:border-accent/50"
            >
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-soft text-lg">
                  {agent.icon}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="truncate text-sm font-medium text-ink">{agent.name}</p>
                    {agent.published && <Badge tone="success">public</Badge>}
                  </div>
                  <p className="mt-0.5 line-clamp-2 text-xs text-ink-muted">
                    {agent.description || t('studio.noDescription')}
                  </p>
                  <div className="mt-2 flex items-center gap-2 text-[10px] text-ink-muted">
                    <Badge tone="neutral">{agent.mode}</Badge>
                    <span>{agent.conversation_count} chats</span>
                    <span>v{agent.copy_count} copies</span>
                  </div>
                </div>
              </div>
            </Link>
          ))}
        </div>
      </div>

      <Dialog
        open={template !== null}
        onClose={() => setTemplate(null)}
        title={t('studio.useTemplate')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setTemplate(null)}>
              {t('common.close')}
            </Button>
            <Button
              size="sm"
              disabled={creating || templateName.trim() === ''}
              onClick={() => void startTemplate()}
            >
              {creating ? t('studio.creating') : t('studio.createFromTemplate')}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <p className="text-xs text-ink-muted">{template?.description}</p>
          <label className="block text-xs text-ink-muted">
            {t('studio.name')}
            <Input
              className="mt-1"
              value={templateName}
              onChange={(event) => setTemplateName(event.target.value)}
            />
          </label>
          {templateError !== null && (
            <p className="text-xs text-danger">{templateError}</p>
          )}
        </div>
      </Dialog>
    </div>
  )
}