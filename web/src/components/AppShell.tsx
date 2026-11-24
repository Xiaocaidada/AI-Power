import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BarChart3,
  BookOpen,
  Bot,
  Brain,
  ChevronDown,
  Database,
  Github,
  FlaskConical,
  FolderOpen,
  Image as ImageIcon,
  LayoutDashboard,
  Megaphone,
  Menu,
  MessageSquare,
  Moon,
  Plug,
  Puzzle,
  Search,
  Server,
  Settings,
  Shield,
  Sun,
  Blocks,
  Users,
  Workflow,
  X,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { apiRequest } from '../lib/http'
import { useI18n } from '../lib/i18n'
import { applyTheme, storedTheme, type Theme } from '../lib/theme'
import { useLogout } from '../lib/useLogout'
import type { WorkspaceItem } from '../lib/types'
import { cn } from '../lib/utils'
import { getActiveWorkspaceId, setActiveWorkspaceId } from '../lib/workspace'
import { useAuthStore } from '../store/auth'

const overviewNav = [
  { to: '/dashboard', labelKey: 'nav.dashboard', icon: LayoutDashboard },
]

const workNav = [
  { to: '/chat', labelKey: 'nav.chat', icon: MessageSquare },
  { to: '/media', labelKey: 'nav.multimodal', icon: ImageIcon },
]

const knowledgeNav = [
  { to: '/knowledge', labelKey: 'nav.knowledge', icon: BookOpen },
  { to: '/files', labelKey: 'nav.files', icon: FolderOpen },
  { to: '/memory', labelKey: 'nav.memory', icon: Brain },
]

const buildNav = [
  { to: '/agents', labelKey: 'nav.agents', icon: Bot },
  { to: '/studio', labelKey: 'nav.studio', icon: Workflow },
  { to: '/workflows', labelKey: 'nav.workflows', icon: Workflow },
  { to: '/collaborations', labelKey: 'nav.collaborations', icon: Users },
  { to: '/evaluation', labelKey: 'nav.evaluation', icon: FlaskConical },
]

const extensionNav = [
  { to: '/skills', labelKey: 'nav.skills', icon: Blocks },
  { to: '/connectors', labelKey: 'nav.connectors', icon: Github },
  { to: '/plugins', labelKey: 'nav.plugins', icon: Plug },
]

const accountNav = [
  { to: '/usage', labelKey: 'nav.usage', icon: BarChart3 },
  { to: '/settings', labelKey: 'nav.settings', icon: Settings },
]

function NavGroup({
  label,
  items,
  collapsible = false,
}: {
  label: string
  items: { to: string; labelKey: string; icon: typeof MessageSquare }[]
  collapsible?: boolean
}) {
  const { t } = useI18n()
  const links = (
    <div className="space-y-1">
      {items.map(({ to, labelKey, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={to === '/settings' || to === '/admin' || to === '/settings/prompts'}
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
    </div>
  )
  if (collapsible) {
    return (
      <details className="group">
        <summary className="flex cursor-pointer list-none items-center justify-between px-3 pb-1 text-[10px] font-medium uppercase tracking-wider text-ink-muted/70 [&::-webkit-details-marker]:hidden">
          {label}
          <span className="text-[9px] transition-transform group-open:rotate-180">▾</span>
        </summary>
        <div className="mt-1">{links}</div>
      </details>
    )
  }
  return (
    <div>
      <p className="px-3 pb-1 text-[10px] font-medium uppercase tracking-wider text-ink-muted/70">
        {label}
      </p>
      {links}
    </div>
  )
}


function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t, language, setLanguage } = useI18n()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const logout = useLogout()
  const user = useAuthStore((state) => state.user)
  const [activeWorkspaceId, setActiveId] = useState<string | null>(getActiveWorkspaceId())
  const [theme, setTheme] = useState<Theme>(() => storedTheme())

  const toggleTheme = () => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark'
    applyTheme(next)
    setTheme(next)
  }

  const workspaces = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => apiRequest<WorkspaceItem[]>('/workspaces'),
  })
  const activeWorkspace = (workspaces.data ?? []).find(
    (workspace) => workspace.id === activeWorkspaceId,
  )

  useEffect(() => {
    if (workspaces.data === undefined || workspaces.data.length === 0) return
    const current = getActiveWorkspaceId()
    if (current !== null && workspaces.data.some((item) => item.id === current)) return
    const preferred =
      workspaces.data.find((item) => item.is_personal) ?? workspaces.data[0]
    setActiveWorkspaceId(preferred.id)
    setActiveId(preferred.id)
    queryClient.invalidateQueries()
  }, [workspaces.data, queryClient])

  const switchWorkspace = (workspaceId: string) => {
    setActiveWorkspaceId(workspaceId)
    setActiveId(workspaceId)
    queryClient.clear()
    navigate('/chat')
  }

  const adminNav =
    user?.role === 'admin'
      ? [
          { to: '/admin', labelKey: 'nav.admin', icon: Shield },
          { to: '/admin/content', labelKey: 'nav.contentAdmin', icon: Megaphone },
          { to: '/admin/plugins', labelKey: 'nav.pluginAdmin', icon: Puzzle },
          { to: '/admin/mcp', labelKey: 'nav.mcpAdmin', icon: Server },
          { to: '/admin/databases', labelKey: 'nav.dbAdmin', icon: Database },
          { to: '/admin/prompts', labelKey: 'nav.promptAdmin', icon: BookOpen },
        ]
      : []

  return (
    <aside
      className={cn(
        'fixed inset-y-0 left-0 z-40 flex w-[264px] shrink-0 flex-col border-r border-border bg-surface transition-transform',
        'lg:static lg:translate-x-0',
        open ? 'translate-x-0' : '-translate-x-full',
      )}
    >
      <div className="flex h-14 items-center justify-between px-4">
        <Link to="/" className="font-serif text-lg text-ink">
          {t('common.appName')}
        </Link>
        <button
          type="button"
          aria-label={t('common.close')}
          className="rounded-md p-1 text-ink-muted hover:bg-surface-muted lg:hidden"
          onClick={onClose}
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="mx-3 mb-3 rounded-xl border border-border bg-surface-muted/40 p-2.5">
        <div className="relative flex items-center gap-2.5">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-xs font-semibold text-accent">
            {(activeWorkspace?.name ?? 'AI').slice(0, 2).toUpperCase()}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-ink">
              {activeWorkspace === undefined
                ? t('workspace.current')
                : activeWorkspace.is_personal
                  ? t('workspace.personal')
                  : activeWorkspace.name}
            </p>
            <p className="mt-0.5 flex items-center gap-1.5 text-[10px] text-ink-muted">
              <span className="rounded bg-surface px-1 py-0.5 uppercase">
                {activeWorkspace?.plan ?? 'free'}
              </span>
              <span>{activeWorkspace?.role ?? 'owner'}</span>
            </p>
          </div>
          <ChevronDown className="h-4 w-4 shrink-0 text-ink-muted" />
          <select
            aria-label={t('workspace.current')}
            className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
            value={activeWorkspaceId ?? ''}
            onChange={(event) => switchWorkspace(event.target.value)}
          >
            {(workspaces.data ?? []).map((workspace) => (
              <option key={workspace.id} value={workspace.id}>
                {workspace.is_personal ? t('workspace.personal') : workspace.name}
              </option>
            ))}
          </select>
        </div>
        <div className="mt-2 grid grid-cols-2 gap-x-2 gap-y-1 text-[11px] text-ink-muted">
          <NavLink to="/settings/workspace" className="hover:text-ink">
            {t('workspace.members')}
          </NavLink>
          <NavLink to="/projects" className="hover:text-ink">
            {t('projects.title')}
          </NavLink>
          <NavLink to="/archive" className="hover:text-ink">
            {t('chat.archived')}
          </NavLink>
          <NavLink to="/search" className="inline-flex items-center gap-1 hover:text-ink">
            <Search className="h-3 w-3" />
            {t('search.short')}
          </NavLink>
        </div>
      </div>

      <nav className="min-h-0 flex-1 space-y-4 overflow-y-auto px-2 pb-3">
        <NavGroup label={t('nav.groupOverview')} items={overviewNav} />
        <NavGroup label={t('nav.groupWork')} items={workNav} />
        <NavGroup label={t('nav.groupKnowledge')} items={knowledgeNav} />
        <NavGroup label={t('nav.groupBuild')} items={buildNav} />
        <NavGroup label={t('nav.groupExtensions')} items={extensionNav} />
        <NavGroup label={t('nav.groupAccount')} items={accountNav} />
        {adminNav.length > 0 && (
          <NavGroup label={t('nav.admin')} items={adminNav} collapsible />
        )}
      </nav>

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
          <div className="flex min-w-0 items-center gap-1.5">
            <button
              type="button"
              aria-label={t('common.toggleTheme')}
              title={t('common.toggleTheme')}
              className="shrink-0 rounded-md p-1 text-ink-muted hover:bg-surface-muted hover:text-ink"
              onClick={toggleTheme}
            >
              {theme === 'dark' ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
            </button>
            <span className="truncate text-xs text-ink-muted">{user?.email ?? ''}</span>
          </div>
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