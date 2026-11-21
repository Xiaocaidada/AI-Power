import { useQuery } from '@tanstack/react-query'
import {
  BarChart3,
  BookOpen,
  Menu,
  MessageSquare,
  Settings,
  X,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'

import { apiRequest } from '../lib/http'
import { useI18n } from '../lib/i18n'
import { useLogout } from '../lib/useLogout'
import type { Conversation } from '../lib/types'
import { cn } from '../lib/utils'
import { useAuthStore } from '../store/auth'

const navItems = [
  { to: '/chat', labelKey: 'nav.chat', icon: MessageSquare },
  { to: '/knowledge', labelKey: 'nav.knowledge', icon: BookOpen },
  { to: '/usage', labelKey: 'nav.usage', icon: BarChart3 },
  { to: '/settings/api-keys', labelKey: 'nav.settings', icon: Settings },
]

function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t, language, setLanguage } = useI18n()
  const location = useLocation()
  const logout = useLogout()
  const user = useAuthStore((state) => state.user)
  const isChat = location.pathname.startsWith('/chat')

  const conversations = useQuery({
    queryKey: ['conversations'],
    queryFn: () => apiRequest<Conversation[]>('/conversations'),
    enabled: isChat,
    staleTime: 30_000,
  })

  return (
    <aside
      className={cn(
        'fixed inset-y-0 left-0 z-40 flex w-[264px] shrink-0 flex-col border-r border-border bg-surface transition-transform',
        'lg:static lg:translate-x-0',
        open ? 'translate-x-0' : '-translate-x-full',
      )}
    >
      <div className="flex h-14 items-center justify-between px-4">
        <span className="font-serif text-lg text-ink">{t('common.appName')}</span>
        <button
          type="button"
          aria-label={t('common.close')}
          className="rounded-md p-1 text-ink-muted hover:bg-surface-muted lg:hidden"
          onClick={onClose}
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <nav className="space-y-1 px-2">
        {navItems.map(({ to, labelKey, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm',
                isActive
                  ? 'bg-accent-soft font-medium text-accent'
                  : 'text-ink-muted hover:bg-surface-muted hover:text-ink',
              )
            }
          >
            <Icon className="h-4 w-4" />
            {t(labelKey)}
          </NavLink>
        ))}
      </nav>

      {isChat && (
        <div className="mt-4 flex min-h-0 flex-1 flex-col">
          <p className="px-4 pb-2 text-xs font-medium uppercase tracking-wide text-ink-muted">
            {t('nav.conversations')}
          </p>
          <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
            {conversations.data !== undefined && conversations.data.length === 0 && (
              <p className="px-3 py-2 text-xs text-ink-muted">{t('nav.noConversations')}</p>
            )}
            {conversations.data?.map((conversation) => {
              const active = location.pathname === `/chat/${conversation.id}`
              return (
                <NavLink
                  key={conversation.id}
                  to={`/chat/${conversation.id}`}
                  className={cn(
                    'block truncate rounded-lg px-3 py-2 text-[13px]',
                    active
                      ? 'bg-surface-muted font-medium text-ink'
                      : 'text-ink-muted hover:bg-surface-muted hover:text-ink',
                  )}
                >
                  {conversation.title || t('chat.newConversation')}
                </NavLink>
              )
            })}
          </div>
        </div>
      )}

      <div className="mt-auto space-y-2 border-t border-border p-3">
        <div className="flex items-center gap-1 rounded-lg bg-surface-muted p-1 text-xs">
          <button
            type="button"
            onClick={() => setLanguage('zh')}
            className={cn(
              'flex-1 rounded-md py-1',
              language === 'zh' ? 'bg-surface font-medium text-ink' : 'text-ink-muted',
            )}
          >
            {t('common.chinese')}
          </button>
          <button
            type="button"
            onClick={() => setLanguage('en')}
            className={cn(
              'flex-1 rounded-md py-1',
              language === 'en' ? 'bg-surface font-medium text-ink' : 'text-ink-muted',
            )}
          >
            {t('common.english')}
          </button>
        </div>
        <div className="flex items-center justify-between gap-2 px-1">
          <span className="truncate text-xs text-ink-muted">{user?.email ?? ''}</span>
          <button
            type="button"
            className="shrink-0 text-xs text-ink-muted underline-offset-2 hover:text-ink hover:underline"
            onClick={() => void logout()}
          >
            {t('nav.logout')}
          </button>
        </div>
      </div>
    </aside>
  )
}

export function AppShell() {
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
      <Sidebar open={mobileOpen} onClose={() => setMobileOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-14 items-center gap-3 border-b border-border bg-surface px-4 lg:hidden">
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