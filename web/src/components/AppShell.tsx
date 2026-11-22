import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Archive,
  BarChart3,
  BookOpen,
  Bot,
  FlaskConical,
  FolderInput,
  Megaphone,
  Menu,
  MessageSquare,
  Moon,
  MoreHorizontal,
  Pencil,
  Pin,
  Plug,
  Puzzle,
  Settings,
  Shield,
  Sun,
  Users,
  Workflow,
  X,
} from 'lucide-react'
import { useDeferredValue, useEffect, useState, type ReactNode } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { apiRequest } from '../lib/http'
import { useI18n } from '../lib/i18n'
import { PAGE_SIZE, mergePages, pageFromItems } from '../lib/pagination'
import { applyTheme, storedTheme, type Theme } from '../lib/theme'
import { useLogout } from '../lib/useLogout'
import type { Conversation, Project, WorkspaceItem } from '../lib/types'
import { cn } from '../lib/utils'
import { getActiveWorkspaceId, setActiveWorkspaceId } from '../lib/workspace'
import { useAuthStore } from '../store/auth'

const workNav = [
  { to: '/chat', labelKey: 'nav.chat', icon: MessageSquare },
  { to: '/agents', labelKey: 'nav.agents', icon: Bot },
  { to: '/knowledge', labelKey: 'nav.knowledge', icon: BookOpen },
]

const buildNav = [
  { to: '/workflows', labelKey: 'nav.workflows', icon: Workflow },
  { to: '/collaborations', labelKey: 'nav.collaborations', icon: Users },
  { to: '/evaluation', labelKey: 'nav.evaluation', icon: FlaskConical },
]

const bottomNav = [
  { to: '/usage', labelKey: 'nav.usage', icon: BarChart3 },
  { to: '/plugins', labelKey: 'nav.plugins', icon: Plug },
  { to: '/settings', labelKey: 'nav.settings', icon: Settings },
]

function NavGroup({
  label,
  items,
}: {
  label: string
  items: { to: string; labelKey: string; icon: typeof MessageSquare }[]
}) {
  const { t } = useI18n()
  return (
    <div>
      <p className="px-3 pb-1 text-[10px] font-medium uppercase tracking-wider text-ink-muted/70">
        {label}
      </p>
      <div className="space-y-1">
        {items.map(({ to, labelKey, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/settings' || to === '/admin'}
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
    </div>
  )
}

function MenuAction({
  icon,
  label,
  onClick,
}: {
  icon: ReactNode
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-ink-muted hover:bg-surface-muted hover:text-ink"
      onClick={onClick}
    >
      {icon}
      <span className="truncate">{label}</span>
    </button>
  )
}

function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t, language, setLanguage } = useI18n()
  const location = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const logout = useLogout()
  const user = useAuthStore((state) => state.user)
  const isChat = location.pathname.startsWith('/chat')
  const [activeWorkspaceId, setActiveId] = useState<string | null>(getActiveWorkspaceId())
  const [theme, setTheme] = useState<Theme>(() => storedTheme())
  const [search, setSearch] = useState('')
  const deferredSearch = useDeferredValue(search)
  const [projectFilter, setProjectFilter] = useState('')
  const [menuId, setMenuId] = useState<string | null>(null)

  const toggleTheme = () => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark'
    applyTheme(next)
    setTheme(next)
  }

  const workspaces = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => apiRequest<WorkspaceItem[]>('/workspaces'),
  })
  const projects = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiRequest<Project[]>('/projects'),
    enabled: isChat,
  })

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
        ]
      : []

  const conversations = useInfiniteQuery({
    queryKey: ['conversations', deferredSearch, projectFilter],
    queryFn: async ({ pageParam }) => {
      const params = new URLSearchParams({ limit: String(PAGE_SIZE) })
      if (pageParam) params.set('before', pageParam)
      if (deferredSearch.trim() !== '') params.set('q', deferredSearch.trim())
      if (projectFilter !== '') params.set('project_id', projectFilter)
      return pageFromItems(
        await apiRequest<Conversation[]>(`/conversations?${params.toString()}`),
        PAGE_SIZE,
      )
    },
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next,
    enabled: isChat,
    staleTime: 30_000,
  })
  const conversationRows = mergePages(conversations.data?.pages)
  const pinnedRows = conversationRows.filter((item) => item.pinned === true)
  const recentRows = conversationRows.filter((item) => item.pinned !== true)

  const renderConversation = (conversation: Conversation) => {
    const active = location.pathname === `/chat/${conversation.id}`
    return (
      <div key={conversation.id} className="group relative">
        <NavLink
          to={`/chat/${conversation.id}`}
          onClick={() => setMenuId(null)}
          className={cn(
            'block truncate rounded-lg px-3 py-2 pr-8 text-[13px]',
            active
              ? 'bg-surface-muted font-medium text-ink'
              : 'text-ink-muted hover:bg-surface-muted hover:text-ink',
          )}
        >
          <span className="flex items-center gap-1">
            {conversation.pinned === true && (
              <Pin className="h-3 w-3 shrink-0 text-accent" />
            )}
            <span className="truncate">
              {conversation.title || t('chat.newConversation')}
            </span>
          </span>
        </NavLink>
        <button
          type="button"
          aria-label={t('chat.conversationMenu')}
          className="absolute right-1 top-1.5 rounded p-1 text-ink-muted opacity-0 hover:bg-surface hover:text-ink group-hover:opacity-100"
          onClick={() => setMenuId(menuId === conversation.id ? null : conversation.id)}
        >
          <MoreHorizontal className="h-3.5 w-3.5" />
        </button>
        {menuId === conversation.id && (
          <div className="absolute right-1 top-8 z-20 w-48 rounded-lg border border-border bg-surface py-1 text-xs shadow-xl">
            <MenuAction
              icon={<Pencil className="h-3 w-3" />}
              label={t('chat.rename')}
              onClick={() => void renameConversation(conversation)}
            />
            <MenuAction
              icon={<Pin className="h-3 w-3" />}
              label={conversation.pinned === true ? t('chat.unpin') : t('chat.pin')}
              onClick={() =>
                void mutateConversation(conversation, {
                  pinned: conversation.pinned !== true,
                })
              }
            />
            <MenuAction
              icon={<Archive className="h-3 w-3" />}
              label={t('chat.archive')}
              onClick={() => void archiveConversation(conversation)}
            />
            <div className="mt-1 border-t border-border pt-1">
              <p className="px-3 py-1 text-[10px] uppercase tracking-wide text-ink-muted">
                {t('chat.moveToProject')}
              </p>
              {(projects.data ?? []).map((project) => (
                <MenuAction
                  key={project.id}
                  icon={<FolderInput className="h-3 w-3" />}
                  label={project.name}
                  onClick={() =>
                    void mutateConversation(conversation, { project_id: project.id })
                  }
                />
              ))}
              <MenuAction
                icon={<FolderInput className="h-3 w-3" />}
                label={t('chat.noProject')}
                onClick={() =>
                  void mutateConversation(conversation, { project_id: null })
                }
              />
            </div>
          </div>
        )}
      </div>
    )
  }

  const mutateConversation = async (
    conversation: Conversation,
    body: Record<string, unknown>,
  ) => {
    await apiRequest(`/conversations/${conversation.id}`, { method: 'PATCH', body })
    setMenuId(null)
    await queryClient.invalidateQueries({ queryKey: ['conversations'] })
  }

  const renameConversation = async (conversation: Conversation) => {
    const title = window.prompt(t('chat.renamePrompt'), conversation.title)
    if (title === null) return
    await mutateConversation(conversation, { title })
  }

  const archiveConversation = async (conversation: Conversation) => {
    await mutateConversation(conversation, { archived: true })
    if (location.pathname === `/chat/${conversation.id}`) navigate('/chat')
  }

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

      <div className="mx-2 mb-2 rounded-lg border border-border p-2">
        <p className="mb-1 text-[11px] uppercase tracking-wide text-ink-muted">
          {t('workspace.current')}
        </p>
        <select
          className="h-8 w-full rounded-md border border-border bg-surface px-2 text-xs text-ink focus:border-accent focus:outline-none"
          value={activeWorkspaceId ?? ''}
          onChange={(event) => switchWorkspace(event.target.value)}
        >
          {(workspaces.data ?? []).map((workspace) => (
            <option key={workspace.id} value={workspace.id}>
              {workspace.is_personal ? t('workspace.personal') : workspace.name}
            </option>
          ))}
        </select>
        <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-ink-muted">
          <NavLink to="/settings/workspace" className="hover:text-ink">
            {t('workspace.members')}
          </NavLink>
          <NavLink to="/projects" className="hover:text-ink">
            {t('projects.title')}
          </NavLink>
          <NavLink to="/archive" className="hover:text-ink">
            {t('chat.archived')}
          </NavLink>
        </div>
      </div>

      <nav className="space-y-4 px-2">
        <NavGroup label={t('nav.groupWork')} items={workNav} />
        <NavGroup label={t('nav.groupBuild')} items={buildNav} />
        <NavGroup label={t('nav.groupAccount')} items={[...bottomNav, ...adminNav]} />
      </nav>

      {isChat && (
        <div className="mt-4 flex min-h-0 flex-1 flex-col">
          <div className="space-y-1.5 px-3 pb-2">
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={t('chat.searchConversations')}
              className="h-8 w-full rounded-lg border border-border bg-surface px-2 text-xs text-ink placeholder:text-ink-muted/70 focus:border-accent focus:outline-none"
            />
            <select
              value={projectFilter}
              onChange={(event) => setProjectFilter(event.target.value)}
              className="h-8 w-full rounded-lg border border-border bg-surface px-2 text-xs text-ink focus:border-accent focus:outline-none"
            >
              <option value="">{t('chat.allProjects')}</option>
              {(projects.data ?? []).map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
            <div className="flex items-center justify-between px-1">
              <p className="text-[10px] font-medium uppercase tracking-wider text-ink-muted/70">
                {t('nav.conversations')}
              </p>
              <NavLink
                to="/projects"
                className="text-[10px] text-ink-muted hover:text-ink"
              >
                {t('projects.title')}
              </NavLink>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
            {conversationRows.length === 0 && (
              <p className="px-3 py-2 text-xs text-ink-muted">{t('nav.noConversations')}</p>
            )}
            {pinnedRows.length > 0 && (
              <>
                <p className="px-3 pb-1 pt-1 text-[10px] uppercase tracking-wide text-ink-muted/70">
                  {t('chat.pinned')}
                </p>
                {pinnedRows.map(renderConversation)}
                <div className="my-1 border-t border-border" />
              </>
            )}
            {recentRows.map(renderConversation)}
            {conversations.hasNextPage && (
              <button
                type="button"
                className="mt-1 w-full rounded-lg px-3 py-2 text-left text-xs text-accent hover:bg-surface-muted disabled:opacity-60"
                disabled={conversations.isFetchingNextPage}
                onClick={() => void conversations.fetchNextPage()}
              >
                {conversations.isFetchingNextPage
                  ? t('common.loading')
                  : t('common.loadMore')}
              </button>
            )}
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