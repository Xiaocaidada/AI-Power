import { ArrowLeft, LayoutDashboard, Sparkles } from 'lucide-react'
import { Link, Outlet } from 'react-router-dom'

import { UserAvatarMenu } from './UserAvatarMenu'
import { useI18n } from '../lib/i18n'

export function ToolLayout() {
  const { t } = useI18n()
  return (
    <div className="flex min-h-dvh flex-col bg-canvas">
      <header className="sticky top-0 z-30 border-b border-border bg-surface/90 backdrop-blur">
        <div className="mx-auto flex h-14 w-full max-w-7xl items-center gap-3 px-4 sm:px-6">
          <Link to="/" className="flex items-center gap-2 text-ink">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-accent-soft text-accent">
              <Sparkles className="h-4 w-4" />
            </span>
            <span className="font-serif text-lg">{t('common.appName')}</span>
          </Link>
          <span className="mx-2 hidden h-5 w-px bg-border sm:block" />
          <Link
            to="/"
            className="inline-flex items-center gap-1 text-sm text-ink-muted hover:text-ink"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            {t('toolLayout.home')}
          </Link>
          <Link
            to="/models"
            className="hidden text-sm text-ink-muted hover:text-ink sm:block"
          >
            {t('portal.models')}
          </Link>
          <div className="ml-auto flex items-center gap-2">
            <Link
              to="/dashboard"
              className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-sm text-ink-muted hover:bg-surface-muted hover:text-ink"
            >
              <LayoutDashboard className="h-3.5 w-3.5" />
              {t('nav.console')}
            </Link>
            <UserAvatarMenu />
          </div>
        </div>
      </header>
      <main className="flex flex-1 flex-col animate-page">
        <Outlet />
      </main>
    </div>
  )
}