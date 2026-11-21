import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Navigate } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { EmptyState } from '../../components/ui/empty-state'
import { Spinner } from '../../components/ui/spinner'
import { formatDate } from '../../lib/format'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  AdminMember,
  AdminModel,
  AdminRunSummary,
  AdminUsage,
  AdminWorkspace,
  AuditLog,
  User,
} from '../../lib/types'
import { cn } from '../../lib/utils'
import { useAuthStore } from '../../store/auth'

type Tab = 'overview' | 'users' | 'workspaces' | 'models' | 'audit'

const TABS: Tab[] = ['overview', 'users', 'workspaces', 'models', 'audit']

export function AdminPage() {
  const { t, language } = useI18n()
  const user = useAuthStore((state) => state.user)
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<Tab>('overview')
  const [workspaceId, setWorkspaceId] = useState<string | null>(null)
  const [busyModel, setBusyModel] = useState<string | null>(null)

  const isAdmin = user?.role === 'admin'
  const users = useQuery({
    queryKey: ['admin-users'],
    queryFn: () => apiRequest<User[]>('/admin/users'),
    enabled: isAdmin,
  })
  const workspaces = useQuery({
    queryKey: ['admin-workspaces'],
    queryFn: () => apiRequest<AdminWorkspace[]>('/admin/workspaces'),
    enabled: isAdmin,
  })
  const members = useQuery({
    queryKey: ['admin-members', workspaceId],
    queryFn: () => apiRequest<AdminMember[]>(`/admin/workspaces/${workspaceId}/members`),
    enabled: isAdmin && workspaceId !== null,
  })
  const models = useQuery({
    queryKey: ['admin-models'],
    queryFn: () => apiRequest<AdminModel[]>('/admin/models'),
    enabled: isAdmin,
  })
  const usage = useQuery({
    queryKey: ['admin-usage'],
    queryFn: () => apiRequest<AdminUsage>('/admin/usage?group_by=model'),
    enabled: isAdmin,
  })
  const runSummary = useQuery({
    queryKey: ['admin-runs'],
    queryFn: () => apiRequest<AdminRunSummary>('/admin/runs/summary'),
    enabled: isAdmin,
  })
  const audit = useQuery({
    queryKey: ['admin-audit'],
    queryFn: () => apiRequest<AuditLog[]>('/admin/audit-logs'),
    enabled: isAdmin && tab === 'audit',
  })

  if (!isAdmin) {
    return <Navigate to="/chat" replace />
  }

  const costFormat = new Intl.NumberFormat(language === 'zh' ? 'zh-CN' : 'en', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 6,
  })
  const numberFormat = new Intl.NumberFormat(language === 'zh' ? 'zh-CN' : 'en')

  const toggleModel = async (model: AdminModel) => {
    setBusyModel(model.id)
    try {
      await apiRequest(`/admin/models/${model.id}`, {
        method: 'PATCH',
        body: { enabled: !model.enabled },
      })
      await queryClient.invalidateQueries({ queryKey: ['admin-models'] })
      await queryClient.invalidateQueries({ queryKey: ['models'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
    } finally {
      setBusyModel(null)
    }
  }

  const changePlan = async (workspace: AdminWorkspace, plan: string) => {
    if (plan === workspace.plan) return
    try {
      await apiRequest(`/admin/workspaces/${workspace.id}/plan`, {
        method: 'PATCH',
        body: { plan },
      })
      await queryClient.invalidateQueries({ queryKey: ['admin-workspaces'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
    } catch {
      // Keep the previous plan in the table; the audit log is the source of truth.
    }
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-4">
        <h1 className="text-lg font-semibold">{t('admin.title')}</h1>
        <p className="mt-1 text-sm text-ink-muted">{t('admin.lead')}</p>
      </header>

      <div className="space-y-5 px-6 py-6">
        <div className="flex flex-wrap gap-2">
          {TABS.map((item) => (
            <Button
              key={item}
              size="sm"
              variant={tab === item ? 'primary' : 'secondary'}
              onClick={() => setTab(item)}
            >
              {t(`admin.tab.${item}`)}
            </Button>
          ))}
        </div>

        {tab === 'overview' && (
          <>
            {usage.isLoading && <Spinner />}
            {usage.data !== undefined && (
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {[
                  { label: t('admin.requests'), value: numberFormat.format(usage.data.requests) },
                  {
                    label: t('admin.tokens'),
                    value: numberFormat.format(usage.data.total_tokens),
                  },
                  { label: t('admin.cost'), value: costFormat.format(usage.data.total_cost) },
                  {
                    label: t('admin.unpriced'),
                    value: numberFormat.format(usage.data.unpriced_requests),
                  },
                ].map((item) => (
                  <div key={item.label} className="rounded-card border border-border bg-surface p-4">
                    <p className="text-xs text-ink-muted">{item.label}</p>
                    <p className="mt-1 font-mono text-xl text-ink">{item.value}</p>
                  </div>
                ))}
              </div>
            )}
            {runSummary.data !== undefined && (
              <div className="grid gap-3 sm:grid-cols-2">
                {[
                  { label: t('admin.workflowRuns'), counts: runSummary.data.workflows },
                  { label: t('admin.collabRuns'), counts: runSummary.data.collaborations },
                ].map((item) => (
                  <div key={item.label} className="rounded-card border border-border bg-surface p-4">
                    <p className="text-xs text-ink-muted">{item.label}</p>
                    <p className="mt-1 font-mono text-xl text-ink">
                      {(item.counts.failure_rate * 100).toFixed(1)}%
                    </p>
                    <p className="mt-1 text-[11px] text-ink-muted">
                      {t('admin.runCounts', {
                        failed: item.counts.failed,
                        total: item.counts.total,
                      })}
                    </p>
                  </div>
                ))}
              </div>
            )}
            {usage.data !== undefined && (
              <section className="overflow-x-auto rounded-card border border-border bg-surface">
                <table className="w-full min-w-[560px] text-left text-sm">
                  <thead className="border-b border-border text-xs uppercase tracking-wide text-ink-muted">
                    <tr>
                      <th className="px-3 py-2 font-medium">{t('admin.model')}</th>
                      <th className="px-3 py-2 text-right font-medium">{t('admin.requests')}</th>
                      <th className="px-3 py-2 text-right font-medium">{t('admin.tokens')}</th>
                      <th className="px-3 py-2 text-right font-medium">{t('admin.cost')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {usage.data.buckets.map((bucket) => (
                      <tr key={bucket.key} className="border-b border-border last:border-0">
                        <td className="px-3 py-2 font-mono text-xs">{bucket.key}</td>
                        <td className="px-3 py-2 text-right">
                          {numberFormat.format(bucket.requests)}
                        </td>
                        <td className="px-3 py-2 text-right">
                          {numberFormat.format(bucket.total_tokens)}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-xs">
                          {costFormat.format(bucket.cost)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            )}
          </>
        )}

        {tab === 'users' && (
          <section className="overflow-x-auto rounded-card border border-border bg-surface">
            <table className="w-full min-w-[520px] text-left text-sm">
              <thead className="border-b border-border text-xs uppercase tracking-wide text-ink-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">{t('admin.email')}</th>
                  <th className="px-3 py-2 font-medium">{t('admin.role')}</th>
                  <th className="px-3 py-2 text-right font-medium">{t('admin.createdAt')}</th>
                </tr>
              </thead>
              <tbody>
                {(users.data ?? []).map((item) => (
                  <tr key={item.id} className="border-b border-border last:border-0">
                    <td className="px-3 py-2 text-ink">{item.email}</td>
                    <td className="px-3 py-2">
                      <Badge tone={item.role === 'admin' ? 'accent' : 'neutral'}>{item.role}</Badge>
                    </td>
                    <td className="px-3 py-2 text-right text-xs text-ink-muted">
                      {formatDate(item.created_at, language)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        {tab === 'workspaces' && (
          <>
            <section className="overflow-x-auto rounded-card border border-border bg-surface">
              <table className="w-full min-w-[560px] text-left text-sm">
                <thead className="border-b border-border text-xs uppercase tracking-wide text-ink-muted">
                  <tr>
                    <th className="px-3 py-2 font-medium">{t('admin.name')}</th>
                    <th className="px-3 py-2 font-medium">{t('admin.plan')}</th>
                    <th className="px-3 py-2 text-right font-medium">{t('admin.members')}</th>
                    <th className="px-3 py-2 text-right font-medium">{t('admin.createdAt')}</th>
                  </tr>
                </thead>
                <tbody>
                  {(workspaces.data ?? []).map((item) => (
                    <tr
                      key={item.id}
                      className={cn(
                        'cursor-pointer border-b border-border last:border-0 hover:bg-surface-muted/60',
                        workspaceId === item.id && 'bg-surface-muted/60',
                      )}
                      onClick={() => setWorkspaceId(item.id)}
                    >
                      <td className="px-3 py-2 text-ink">
                        {item.name}
                        {item.is_personal && (
                          <span className="ml-2 text-[11px] text-ink-muted">
                            {t('admin.personal')}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <select
                          className="h-7 rounded-md border border-border bg-surface px-1 text-xs"
                          value={item.plan}
                          onClick={(event) => event.stopPropagation()}
                          onChange={(event) => void changePlan(item, event.target.value)}
                        >
                          <option value="free">free</option>
                          <option value="pro">pro</option>
                        </select>
                      </td>
                      <td className="px-3 py-2 text-right">{item.member_count}</td>
                      <td className="px-3 py-2 text-right text-xs text-ink-muted">
                        {formatDate(item.created_at, language)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
            {workspaceId !== null && (
              <section className="rounded-card border border-border bg-surface p-4">
                <h2 className="text-sm font-medium">{t('admin.members')}</h2>
                {members.data !== undefined && (
                  <ul className="mt-2 space-y-1 text-sm">
                    {members.data.map((member) => (
                      <li key={member.user_id} className="flex items-center justify-between gap-2">
                        <span className="text-ink">{member.email}</span>
                        <Badge tone={member.role === 'owner' ? 'accent' : 'neutral'}>
                          {member.role}
                        </Badge>
                      </li>
                    ))}
                    {members.data.length === 0 && (
                      <li className="text-sm text-ink-muted">{t('admin.noMembers')}</li>
                    )}
                  </ul>
                )}
              </section>
            )}
          </>
        )}

        {tab === 'models' && (
          <section className="overflow-x-auto rounded-card border border-border bg-surface">
            <table className="w-full min-w-[560px] text-left text-sm">
              <thead className="border-b border-border text-xs uppercase tracking-wide text-ink-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">{t('admin.model')}</th>
                  <th className="px-3 py-2 font-medium">{t('admin.provider')}</th>
                  <th className="px-3 py-2 text-right font-medium">{t('admin.status')}</th>
                </tr>
              </thead>
              <tbody>
                {(models.data ?? []).map((model) => (
                  <tr key={model.id} className="border-b border-border last:border-0">
                    <td className="px-3 py-2 font-mono text-xs">{model.model_id}</td>
                    <td className="px-3 py-2 font-mono text-xs">{model.provider_id}</td>
                    <td className="px-3 py-2 text-right">
                      <Button
                        size="sm"
                        variant={model.enabled ? 'secondary' : 'primary'}
                        disabled={busyModel === model.id}
                        onClick={() => void toggleModel(model)}
                      >
                        {model.enabled ? t('admin.disable') : t('admin.enable')}
                      </Button>
                    </td>
                  </tr>
                ))}
                {(models.data ?? []).length === 0 && (
                  <tr>
                    <td colSpan={3} className="px-3 py-4 text-center text-sm text-ink-muted">
                      {t('admin.noModels')}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </section>
        )}

        {tab === 'audit' && (
          <>
            {audit.isLoading && <Spinner />}
            {audit.data !== undefined && audit.data.length === 0 && (
              <EmptyState title={t('admin.noAudit')} />
            )}
            <section className="space-y-2">
              {(audit.data ?? []).map((entry) => (
                <article
                  key={entry.id}
                  className="rounded-lg border border-border bg-surface px-3 py-2 text-sm"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-mono text-xs text-ink">{entry.action}</span>
                    <span className="text-[11px] text-ink-muted">
                      {entry.actor_email ?? t('admin.system')} ·{' '}
                      {formatDate(entry.created_at, language)}
                    </span>
                  </div>
                  <p className="mt-1 font-mono text-[11px] text-ink-muted">
                    {entry.target_type}
                    {entry.target_id !== null ? `:${entry.target_id}` : ''}
                    {entry.detail !== null ? ` ${JSON.stringify(entry.detail)}` : ''}
                  </p>
                </article>
              ))}
            </section>
          </>
        )}
      </div>
    </div>
  )
}