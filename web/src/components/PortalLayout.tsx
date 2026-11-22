import { Code2, LayoutDashboard, LogIn, Sparkles } from 'lucide-react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'

import { Button } from './ui/button'
import { useI18n } from '../lib/i18n'
import { cn } from '../lib/utils'
import { useAuthStore } from '../store/auth'

export function PortalLayout() {
  const { t } = useI18n()
  const navigate = useNavigate()
  const status = useAuthStore((state) => state.status)
  const user = useAuthStore((state) => state.user)

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