import { KeyRound, LayoutDashboard, LogOut, Settings, UserRound } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { useI18n } from '../lib/i18n'
import { useLogout } from '../lib/useLogout'
import { cn } from '../lib/utils'
import { useAuthStore } from '../store/auth'

function initials(email: string | undefined): string {
  if (email === undefined || email.trim() === '') return 'AI'
  return email.trim().slice(0, 2).toUpperCase()
}

export function UserAvatarMenu({ className }: { className?: string }) {
  const { t } = useI18n()
  const user = useAuthStore((state) => state.user)
  const logout = useLogout()
  const [open, setOpen] = useState(false)

  return (
    <div className="relative">
      <button
        type="button"
        aria-label={t('portal.account')}
        aria-expanded={open}
        className={cn(
          'flex h-9 w-9 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent transition-transform hover:scale-105',
          className,
        )}
        onClick={() => setOpen((value) => !value)}
      >
        {initials(user?.email)}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full z-50 mt-2 w-64 animate-pop overflow-hidden rounded-2xl border border-border bg-surface shadow-xl">
            <div className="border-b border-border px-4 py-3">
              <p className="text-[11px] uppercase tracking-wide text-ink-muted">
                {t('portal.account')}
              </p>
              <p className="mt-0.5 truncate text-sm text-ink">{user?.email ?? ''}</p>
            </div>
            <div className="py-1">
              <MenuLink
                to="/dashboard"
                icon={<LayoutDashboard className="h-4 w-4" />}
                onClick={() => setOpen(false)}
              >
                {t('nav.console')}
              </MenuLink>
              <MenuLink
                to="/settings/profile"
                icon={<UserRound className="h-4 w-4" />}
                onClick={() => setOpen(false)}
              >
                {t('nav.profile')}
              </MenuLink>
              <MenuLink
                to="/settings/api-keys"
                icon={<KeyRound className="h-4 w-4" />}
                onClick={() => setOpen(false)}
              >
                {t('nav.apiKeys')}
              </MenuLink>
              <MenuLink
                to="/settings"
                icon={<Settings className="h-4 w-4" />}
                onClick={() => setOpen(false)}
              >
                {t('nav.settings')}
              </MenuLink>
            </div>
            <button
              type="button"
              className="flex w-full items-center gap-2 border-t border-border px-4 py-2.5 text-left text-sm text-ink-muted hover:bg-surface-muted hover:text-ink"
              onClick={() => {
                setOpen(false)
                void logout()
              }}
            >
              <LogOut className="h-4 w-4" />
              {t('nav.logout')}
            </button>
          </div>
        </>
      )}
    </div>
  )
}

function MenuLink({
  to,
  icon,
  children,
  onClick,
}: {
  to: string
  icon: ReactNode
  children: ReactNode
  onClick: () => void
}) {
  return (
    <Link
      to={to}
      onClick={onClick}
      className="flex items-center gap-2 px-4 py-2 text-sm text-ink-muted hover:bg-surface-muted hover:text-ink"
    >
      {icon}
      {children}
    </Link>
  )
}