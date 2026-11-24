import { useQuery } from '@tanstack/react-query'
import { Github, Lock } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Spinner } from '../../components/ui/spinner'
import { errorMessage } from '../../lib/errors'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { GitHubIssue, GitHubRepo, IntegrationConfig } from '../../lib/types'

export function ConnectorsPage() {
  const { t } = useI18n()
  const [integrationId, setIntegrationId] = useState('')
  const [repo, setRepo] = useState<string | null>(null)

  const integrations = useQuery({
    queryKey: ['integrations'],
    queryFn: () => apiRequest<IntegrationConfig[]>('/integrations'),
  })
  const githubConfigs = (integrations.data ?? []).filter(
    (item) => item.kind === 'github' && item.enabled,
  )
  const effectiveId = integrationId || githubConfigs[0]?.id || ''
  const repos = useQuery({
    queryKey: ['github-repos', effectiveId],
    queryFn: () =>
      apiRequest<GitHubRepo[]>(`/connectors/github/repos?integration_id=${effectiveId}`),
    enabled: effectiveId !== '',
  })
  const issues = useQuery({
    queryKey: ['github-issues', effectiveId, repo],
    queryFn: () =>
      apiRequest<GitHubIssue[]>(
        `/connectors/github/repos/${repo}/issues?integration_id=${effectiveId}&state=open`,
      ),
    enabled: effectiveId !== '' && repo !== null,
  })

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-4">
        <h1 className="text-lg font-semibold">{t('connectors.title')}</h1>
        <p className="mt-1 text-sm text-ink-muted">{t('connectors.lead')}</p>
      </header>
      <div className="mx-auto w-full max-w-5xl space-y-5 px-6 py-6">
        <div className="flex flex-wrap items-center gap-2">
          <Github className="h-5 w-5 text-accent" />
          <Badge tone="accent">GitHub</Badge>
          <Badge tone="neutral">{t('connectors.readOnly')}</Badge>
          <select
            className="ml-auto h-9 rounded-lg border border-border bg-surface px-2 text-sm"
            value={effectiveId}
            onChange={(event) => {
              setIntegrationId(event.target.value)
              setRepo(null)
            }}
          >
            {githubConfigs.length === 0 && <option value="">{t('connectors.noConfig')}</option>}
            {githubConfigs.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
          <Link to="/settings/integrations" className="text-xs text-accent underline">
            {t('multimodal.configure')}
          </Link>
        </div>

        {githubConfigs.length === 0 && (
          <div className="rounded-2xl border border-dashed border-border px-6 py-10 text-center text-sm text-ink-muted">
            {t('connectors.configureHint')}
          </div>
        )}

        <div className="grid gap-5 lg:grid-cols-2">
          <section className="rounded-2xl border border-border bg-surface p-4">
            <h2 className="text-sm font-semibold">{t('connectors.repos')}</h2>
            {repos.isLoading && <Spinner className="mt-3" />}
            {repos.error !== null && (
              <p className="mt-2 text-sm text-danger">{errorMessage(repos.error)}</p>
            )}
            <div className="mt-3 space-y-1">
              {(repos.data ?? []).map((item) => (
                <button
                  key={item.full_name}
                  type="button"
                  className={`w-full rounded-xl border px-3 py-2 text-left text-sm ${
                    repo === item.full_name
                      ? 'border-accent bg-accent/5'
                      : 'border-border hover:bg-surface-muted'
                  }`}
                  onClick={() => setRepo(item.full_name)}
                >
                  <span className="flex items-center gap-2 font-medium">
                    {item.private && <Lock className="h-3.5 w-3.5 text-ink-muted" />}
                    {item.full_name}
                  </span>
                  {item.description !== '' && (
                    <span className="mt-0.5 block truncate text-xs text-ink-muted">
                      {item.description}
                    </span>
                  )}
                </button>
              ))}
              {repos.data !== undefined && repos.data.length === 0 && (
                <p className="text-xs text-ink-muted">{t('connectors.noRepos')}</p>
              )}
            </div>
          </section>

          <section className="rounded-2xl border border-border bg-surface p-4">
            <h2 className="text-sm font-semibold">{t('connectors.issues')}</h2>
            {issues.isLoading && <Spinner className="mt-3" />}
            {issues.error !== null && (
              <p className="mt-2 text-sm text-danger">{errorMessage(issues.error)}</p>
            )}
            {repo === null && (
              <p className="mt-2 text-xs text-ink-muted">{t('connectors.selectRepo')}</p>
            )}
            <div className="mt-3 space-y-1">
              {(issues.data ?? []).map((item) => (
                <a
                  key={`${item.number}-${item.html_url}`}
                  href={item.html_url}
                  target="_blank"
                  rel="noreferrer"
                  className="block rounded-xl border border-border px-3 py-2 text-sm hover:bg-surface-muted"
                >
                  <span className="font-medium">
                    #{item.number} {item.title}
                  </span>
                  <span className="ml-2 text-xs text-ink-muted">{item.state}</span>
                </a>
              ))}
              {repo !== null && issues.data !== undefined && issues.data.length === 0 && (
                <p className="text-xs text-ink-muted">{t('connectors.noIssues')}</p>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}