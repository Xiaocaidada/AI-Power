import { Menu } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'

import { useI18n } from '../lib/i18n'
import { ChatSidebar } from './ChatSidebar'

export function ChatLayout() {
  const { t } = useI18n()
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()

  useEffect(() => {
    setMobileOpen(false)
  }, [location.pathname])

  return (
    <div className="flex h-dvh overflow-hidden">
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-ink/30 lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}
      <ChatSidebar open={mobileOpen} onClose={() => setMobileOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-12 shrink-0 items-center gap-3 border-b border-border bg-surface px-4 lg:hidden">
          <button
            type="button"
            aria-label={t('nav.chat')}
            className="rounded-md p-1 text-ink-muted hover:bg-surface-muted"
            onClick={() => setMobileOpen(true)}
          >
            <Menu className="h-5 w-5" />
          </button>
          <span className="font-serif text-lg">{t('common.appName')}</span>
        </div>
        <Outlet />
      </div>
    </div>
  )
}