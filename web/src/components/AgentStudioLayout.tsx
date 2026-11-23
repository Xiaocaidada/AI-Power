import { ArrowLeft, Moon, Sun } from 'lucide-react'
import { useState } from 'react'
import { Link, Outlet } from 'react-router-dom'

import { useI18n } from '../lib/i18n'
import { applyTheme, storedTheme, type Theme } from '../lib/theme'

export function AgentStudioLayout() {
  const { t } = useI18n()
  const [theme, setTheme] = useState<Theme>(() => storedTheme())

  const toggleTheme = () => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark'
    applyTheme(next)
    setTheme(next)
  }

  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-canvas">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-surface px-4">
        <Link
          to="/agents"
          className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-ink-muted hover:bg-surface-muted hover:text-ink"
        >
          <ArrowLeft className="h-4 w-4" />
          {t('studio.back')}
        </Link>
        <span className="font-serif text-lg text-ink">Agent Studio</span>
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            aria-label={t('common.toggleTheme')}
            title={t('common.toggleTheme')}
            className="rounded-md p-2 text-ink-muted hover:bg-surface-muted hover:text-ink"
            onClick={toggleTheme}
          >
            {theme === 'dark' ? (
              <Sun className="h-4 w-4" />
            ) : (
              <Moon className="h-4 w-4" />
            )}
          </button>
        </div>
      </header>
      <div className="min-h-0 flex-1">
        <Outlet />
      </div>
    </div>
  )
}