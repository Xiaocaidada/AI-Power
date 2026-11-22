import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell, CheckCheck, Code2, LayoutDashboard, LogIn, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'

import { Button } from './ui/button'
import { apiRequest } from '../lib/http'
import { useI18n } from '../lib/i18n'
import type { NotificationFeed } from '../lib/types'
import { cn } from '../lib/utils'
import { useAuthStore } from '../store/auth'

export function PortalLayout() {
  const { t } = useI18n()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const status = useAuthStore((state) => state.status)
  const user = useAuthStore((state) => state.user)
  const [showNotifications, setShowNotifications] = useState(false)

  const notifications = useQuery({
    queryKey: ['notifications'],
    queryFn: () => apiRequest<NotificationFeed>('/notifications'),
    enabled: status === 'authenticated',
    staleTime: 30_000,
  })
  const unread = notifications.data?.unread_count ?? 0

  const markAllRead = async () => {
    await apiRequest('/notifications/read-all', { method: 'POST' })
    await queryClient.invalidateQueries({ queryKey: ['notifications'] })
  }

  return (
    <div className="flex min-h-dvh flex-col bg-canvas">
      <header className="sticky top-0 z-30 border-b border-border bg-surface/90 backdrop-blur">
        <div className="mx-auto flex h-16 w-full max-w-7xl items-center gap-6 px-4 sm:px-6">
          <Link to="/" className="flex items-center gap-2 text-ink">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-accent-soft text-accent">
              <Sparkles className="h-4 w-4" />
            </span>
            <span className="font-serif text-lg">{t('common.appName')}</span>
          </Link>
          <nav className="hidden items-center gap-1 md:flex">
            <PortalLink to="/" label={t('portal.home')} end />
            <PortalLink to="/models" label={t('portal.models')} />
            <PortalLink to="/announcements" label={t('announcements.title')} />
            <PortalLink to="/chat" label={t('portal.workspace')} />
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <a
              href="https://github.com"
              target="_blank"
              rel="noreferrer"
              aria-label="GitHub"
              className="hidden rounded-lg p-2 text-ink-muted hover:bg-surface-muted hover:text-ink sm:block"
            >
              <Code2 className="h-4 w-4" />
            </a>
            {status === 'authenticated' ? (
              <>
                <div className="relative">
                  <button
                    type="button"
                    aria-label={t('notifications.title')}
                    className="relative rounded-lg p-2 text-ink-muted hover:bg-surface-muted hover:text-ink"
                    onClick={() => setShowNotifications((open) => !open)}
                  >
                    <Bell className="h-4 w-4" />
                    {unread > 0 && (
                      <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold text-white">
                        {unread > 9 ? '9+' : unread}
                      </span>
                    )}
                  </button>
                  {showNotifications && (
                    <>
                      <div
                        className="fixed inset-0 z-40"
                        onClick={() => setShowNotifications(false)}
                      />
                      <div className="absolute right-0 top-full z-50 mt-2 w-80 rounded-2xl border border-border bg-surface shadow-xl">
                        <div className="flex items-center justify-between border-b border-border px-4 py-3">
                          <div>
                            <p className="text-sm font-semibold text-ink">
                              {t('notifications.title')}
                            </p>
                            <p className="text-[11px] text-ink-muted">
                              {unread > 0
                                ? t('notifications.unread', { count: unread })
                                : t('notifications.none')}
                            </p>
                          </div>
                          <button
                            type="button"
                            disabled={unread === 0}
                            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-accent disabled:opacity-40"
                            onClick={() => void markAllRead()}
                          >
                            <CheckCheck className="h-3.5 w-3.5" />
                            {t('notifications.markAll')}
                          </button>
                        </div>
                        <div className="max-h-96 overflow-y-auto">
                          {(notifications.data?.items ?? []).map((item) => (
                            <Link
                              key={item.id}
                              to={`/announcements/${item.id}`}
                              onClick={() => setShowNotifications(false)}
                              className="block border-b border-border px-4 py-3 last:border-0 hover:bg-surface-muted"
                            >
                              <div className="flex items-start gap-2">
                                <span
                                  className={cn(
                                    'mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full',
                                    item.read_at === null ? 'bg-accent' : 'bg-transparent',
                                  )}
                                />
                                <div className="min-w-0">
                                  <p className="truncate text-sm text-ink">{item.title}</p>
                                  <p className="mt-0.5 truncate text-xs text-ink-muted">
                                    {t(`announcements.category.${item.category}`)} ·{' '}
                                    {item.summary}
                                  </p>
                                </div>
                              </div>
                            </Link>
                          ))}
                          {notifications.data !== undefined &&
                            notifications.data.items.length === 0 && (
                              <p className="px-4 py-6 text-center text-xs text-ink-muted">
                                {t('notifications.empty')}
                              </p>
                            )}
                        </div>
                        <Link
                          to="/announcements"
                          onClick={() => setShowNotifications(false)}
                          className="block border-t border-border px-4 py-2.5 text-center text-xs text-accent hover:bg-surface-muted"
                        >
                          {t('notifications.viewAll')}
                        </Link>
                      </div>
                    </>
                  )}
                </div>
                <span className="hidden max-w-[180px] truncate text-xs text-ink-muted sm:block">
                  {user?.email ?? ''}
                </span>
                <Button size="sm" onClick={() => navigate('/chat')}>
                  <LayoutDashboard className="h-3.5 w-3.5" />
                  {t('portal.console')}
                </Button>
              </>
            ) : (
              <Button size="sm" variant="secondary" onClick={() => navigate('/login')}>
                <LogIn className="h-3.5 w-3.5" />
                {t('portal.login')}
              </Button>
            )}
          </div>
        </div>
      </header>
      <main className="flex flex-1 flex-col">
        <Outlet />
      </main>
      <footer className="border-t border-border bg-surface px-6 py-6">
        <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center justify-between gap-3 text-xs text-ink-muted">
          <span>
            {t('common.appName')} · {t('portal.footer')}
          </span>
          <div className="flex gap-4">
            <Link to="/models" className="hover:text-ink">
              {t('portal.models')}
            </Link>
            <Link to="/chat" className="hover:text-ink">
              {t('portal.console')}
            </Link>
          </div>
        </div>
      </footer>
    </div>
  )
}

function PortalLink({ to, label, end }: { to: string; label: string; end?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cn(
          'rounded-lg px-3 py-2 text-sm transition-colors',
          isActive ? 'bg-accent-soft font-medium text-accent' : 'text-ink-muted hover:text-ink',
        )
      }
    >
      {label}
    </NavLink>
  )
}