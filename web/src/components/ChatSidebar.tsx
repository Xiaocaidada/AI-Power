import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Archive,
  ArrowLeft,
  Blocks,
  BookOpen,
  Brain,
  Check,
  ChevronDown,
  FolderInput,
  FolderOpen,
  Github,
  ListChecks,
  MoreHorizontal,
  Moon,
  Pencil,
  Pin,
  Plug,
  Plus,
  Search,
  Sun,
  Trash2,
  X,
} from 'lucide-react'
import {
  useDeferredValue,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'

import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { groupConversationsByTime, type TimeGroupKey } from '../lib/conversationGroups'
import { apiRequest } from '../lib/http'
import { useI18n } from '../lib/i18n'
import { PAGE_SIZE, mergePages, pageFromItems } from '../lib/pagination'
import { applyTheme, storedTheme, type Theme } from '../lib/theme'
import { useLogout } from '../lib/useLogout'
import type { Conversation, Project, WorkspaceItem } from '../lib/types'
import { cn } from '../lib/utils'
import { getActiveWorkspaceId, setActiveWorkspaceId } from '../lib/workspace'
import { useAuthStore } from '../store/auth'

interface ChatSidebarProps {
  open: boolean
  onClose: () => void
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

export function ChatSidebar({ open, onClose }: ChatSidebarProps) {
  const { t, language, setLanguage } = useI18n()
  const location = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const logout = useLogout()
  const user = useAuthStore((state) => state.user)
  const [theme, setTheme] = useState<Theme>(() => storedTheme())
  const [activeWorkspaceId, setActiveId] = useState<string | null>(getActiveWorkspaceId())
  const [search, setSearch] = useState('')
  const deferredSearch = useDeferredValue(search)
  const [projectFilter, setProjectFilter] = useState('')
  const [menuId, setMenuId] = useState<string | null>(null)
  const [selectMode, setSelectMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [deleteIds, setDeleteIds] = useState<string[] | null>(null)
  const searchRef = useRef<HTMLInputElement | null>(null)

  const toggleTheme = () => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark'
    applyTheme(next)
    setTheme(next)
  }

  const goBack = () => {
    const state = window.history.state as { idx?: number } | null
    if ((state?.idx ?? 0) > 0) navigate(-1)
    else navigate('/dashboard')
  }

  const workspaces = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => apiRequest<WorkspaceItem[]>('/workspaces'),
  })
  const activeWorkspace = (workspaces.data ?? []).find(
    (workspace) => workspace.id === activeWorkspaceId,
  )
  const projects = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiRequest<Project[]>('/projects'),
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

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        searchRef.current?.focus()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const switchWorkspace = (workspaceId: string) => {
    setActiveWorkspaceId(workspaceId)
    setActiveId(workspaceId)
    queryClient.clear()
    navigate('/chat')
  }

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
    staleTime: 30_000,
  })
  const conversationRows = mergePages(conversations.data?.pages)
  const pinnedRows = conversationRows.filter((item) => item.pinned === true)
  const groupedRows = groupConversationsByTime(
    conversationRows.filter((item) => item.pinned !== true),
  )

  const groupLabel: Record<TimeGroupKey, string> = {
    today: t('chat.groupToday'),
    yesterday: t('chat.groupYesterday'),
    week: t('chat.groupWeek'),
    earlier: t('chat.groupEarlier'),
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

  const activeConversationId = location.pathname.startsWith('/chat/')
    ? location.pathname.slice('/chat/'.length)
    : null

  const clearSelection = () => {
    setSelectMode(false)
    setSelectedIds([])
  }

  const toggleSelected = (conversationId: string) => {
    setSelectedIds((prev) =>
      prev.includes(conversationId)
        ? prev.filter((item) => item !== conversationId)
        : [...prev, conversationId],
    )
  }

  const removeConversations = async (ids: string[]) => {
    try {
      if (ids.length === 1) {
        await apiRequest(`/conversations/${ids[0]}/permanent`, { method: 'DELETE' })
      } else {
        await apiRequest('/conversations/batch', {
          method: 'POST',
          body: { action: 'delete', conversation_ids: ids },
        })
      }
      await queryClient.invalidateQueries({ queryKey: ['conversations'] })
      if (activeConversationId !== null && ids.includes(activeConversationId)) {
        navigate('/chat')
      }
    } finally {
      setDeleteIds(null)
      clearSelection()
    }
  }

  const archiveSelected = async () => {
    if (selectedIds.length === 0) return
    await apiRequest('/conversations/batch', {
      method: 'POST',
      body: { action: 'archive', conversation_ids: selectedIds },
    })
    if (activeConversationId !== null && selectedIds.includes(activeConversationId)) {
      navigate('/chat')
    }
    clearSelection()
    await queryClient.invalidateQueries({ queryKey: ['conversations'] })
  }

  const renderConversation = (conversation: Conversation) => {
    if (selectMode) {
      const checked = selectedIds.includes(conversation.id)
      return (
        <button
          key={conversation.id}
          type="button"
          onClick={() => toggleSelected(conversation.id)}
          className={cn(
            'flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-[13px]',
            checked
              ? 'bg-accent-soft text-accent'
              : 'text-ink-muted hover:bg-surface-muted hover:text-ink',
          )}
        >
          <span
            className={cn(
              'flex h-4 w-4 shrink-0 items-center justify-center rounded border',
              checked
                ? 'border-accent bg-accent text-[rgb(var(--accent-ink))]'
                : 'border-border',
            )}
          >
            {checked && <Check className="h-3 w-3" />}
          </span>
          <span className="truncate">
            {conversation.title || t('chat.newConversation')}
          </span>
        </button>
      )
    }
    const active = location.pathname === `/chat/${conversation.id}`
    return (
      <div key={conversation.id} className="group relative">
        <NavLink
          to={`/chat/${conversation.id}`}
          onClick={() => setMenuId(null)}
          className={cn(
            'block truncate rounded-lg px-3 py-2 pr-8 text-[13px] transition-colors',
            active
              ? 'bg-accent-soft font-medium text-accent'
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
          className="absolute right-1 top-1.5 rounded p-1 text-ink-muted opacity-0 hover:bg-surface hover:text-ink group-hover:opacity-100 focus:opacity-100"
          onClick={() => setMenuId(menuId === conversation.id ? null : conversation.id)}
        >
          <MoreHorizontal className="h-3.5 w-3.5" />
        </button>
        {menuId === conversation.id && (
          <>
            <button
              type="button"
              aria-hidden
              tabIndex={-1}
              className="fixed inset-0 z-10 cursor-default"
              onClick={() => setMenuId(null)}
            />
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
              <MenuAction
                icon={<Trash2 className="h-3 w-3" />}
                label={t('chat.deletePermanently')}
                onClick={() => {
                  setMenuId(null)
                  setDeleteIds([conversation.id])
                }}
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
          </>
        )}
      </div>
    )
  }

  return (
    <aside
      className={cn(
        'fixed inset-y-0 left-0 z-40 flex w-[272px] shrink-0 flex-col border-r border-border bg-surface transition-transform',
        'lg:static lg:translate-x-0',
        open ? 'translate-x-0' : '-translate-x-full',
      )}
    >
      <div className="flex h-14 items-center justify-between px-3">
        <div className="flex min-w-0 items-center gap-1">
          <button
            type="button"
            aria-label={t('nav.back')}
            title={t('nav.back')}
            className="rounded-md p-1.5 text-ink-muted hover:bg-surface-muted hover:text-ink"
            onClick={goBack}
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
          <Link to="/" className="truncate font-serif text-lg text-ink">
            {t('common.appName')}
          </Link>
        </div>
        <button
          type="button"
          aria-label={t('common.close')}
          className="rounded-md p-1 text-ink-muted hover:bg-surface-muted lg:hidden"
          onClick={onClose}
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="mx-2 mb-2 rounded-lg border border-border bg-surface-muted/40 p-2">
        <div className="relative flex items-center gap-2">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent-soft text-[11px] font-semibold text-accent">
            {(activeWorkspace?.name ?? 'AI').slice(0, 2).toUpperCase()}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-medium text-ink">
              {activeWorkspace === undefined
                ? t('workspace.current')
                : activeWorkspace.is_personal
                  ? t('workspace.personal')
                  : activeWorkspace.name}
            </p>
            <p className="text-[10px] text-ink-muted">
              {(activeWorkspace?.plan ?? 'free').toUpperCase()} ·{' '}
              {activeWorkspace?.role ?? 'owner'}
            </p>
          </div>
          <ChevronDown className="h-3.5 w-3.5 text-ink-muted" />
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
      </div>

      <div className="space-y-2 px-3 pb-2">
        <Link
          to="/chat"
          onClick={onClose}
          className="flex h-9 items-center justify-center gap-2 rounded-lg bg-accent text-sm font-medium text-[rgb(var(--accent-ink))] transition-colors hover:bg-accent/90"
        >
          <Plus className="h-4 w-4" />
          {t('chat.newConversation')}
        </Link>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-muted" />
          <input
            ref={searchRef}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t('chat.searchConversations')}
            aria-label={t('chat.searchConversations')}
            className="h-8 w-full rounded-lg border border-border bg-surface pl-8 pr-8 text-xs text-ink placeholder:text-ink-muted/70 focus:border-accent focus:outline-none"
          />
          <kbd className="pointer-events-none absolute right-2 top-1/2 hidden -translate-y-1/2 rounded border border-border px-1 text-[10px] text-ink-muted lg:block">
            ⌘K
          </kbd>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        <div className="px-1 pb-1 pt-1">
          <div className="flex items-center justify-between">
            <p className="text-[10px] font-medium uppercase tracking-wider text-ink-muted/70">
              {t('projects.title')}
            </p>
            <div className="flex items-center gap-2">
              <Link
                to="/archive"
                title={t('chat.archived')}
                aria-label={t('chat.archived')}
                className="inline-flex items-center text-[10px] text-ink-muted hover:text-ink"
              >
                <Archive className="h-3 w-3" />
              </Link>
              <button
                type="button"
                className="inline-flex items-center gap-1 text-[10px] text-ink-muted hover:text-ink"
                onClick={() => {
                  if (selectMode) clearSelection()
                  else setSelectMode(true)
                }}
              >
                <ListChecks className="h-3 w-3" />
                {selectMode ? t('chat.cancelSelection') : t('chat.batchSelect')}
              </button>
            </div>
          </div>
          <div className="mt-1 space-y-0.5">
            <button
              type="button"
              onClick={() => setProjectFilter('')}
              className={cn(
                'flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-xs',
                projectFilter === ''
                  ? 'bg-surface-muted font-medium text-ink'
                  : 'text-ink-muted hover:bg-surface-muted hover:text-ink',
              )}
            >
              <FolderOpen className="h-3.5 w-3.5" />
              {t('chat.allConversations')}
            </button>
            {(projects.data ?? []).map((project) => (
              <button
                key={project.id}
                type="button"
                onClick={() => setProjectFilter(project.id)}
                className={cn(
                  'flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-xs',
                  projectFilter === project.id
                    ? 'bg-surface-muted font-medium text-ink'
                    : 'text-ink-muted hover:bg-surface-muted hover:text-ink',
                )}
              >
                <FolderOpen className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">{project.name}</span>
                <span className="ml-auto text-[10px] text-ink-muted">
                  {project.conversation_count}
                </span>
              </button>
            ))}
          </div>
        </div>

        <div className="mt-2 border-t border-border pt-2">
          {conversationRows.length === 0 && (
            <p className="px-3 py-2 text-xs text-ink-muted">{t('nav.noConversations')}</p>
          )}
          {pinnedRows.length > 0 && (
            <div className="mb-1">
              <p className="px-3 pb-1 text-[10px] uppercase tracking-wide text-ink-muted/70">
                {t('chat.pinned')}
              </p>
              {pinnedRows.map(renderConversation)}
            </div>
          )}
          {groupedRows.map((group) => (
            <div key={group.key} className="mb-1">
              <p className="px-3 pb-1 pt-1 text-[10px] uppercase tracking-wide text-ink-muted/70">
                {groupLabel[group.key]}
              </p>
              {group.items.map(renderConversation)}
            </div>
          ))}
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

      {selectMode && (
        <div className="space-y-1.5 border-t border-border px-3 py-2">
          <p className="text-[11px] text-ink-muted">
            {t('chat.batchSelected', { count: selectedIds.length })}
          </p>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="secondary"
              disabled={selectedIds.length === 0}
              onClick={() => void archiveSelected()}
            >
              <Archive className="h-3 w-3" />
              {t('chat.archive')}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              className="text-danger"
              disabled={selectedIds.length === 0}
              onClick={() => setDeleteIds(selectedIds)}
            >
              <Trash2 className="h-3 w-3" />
              {t('chat.delete')}
            </Button>
          </div>
        </div>
      )}

      <div className="border-t border-border px-3 py-2">
        <p className="text-[10px] font-medium uppercase tracking-wider text-ink-muted/70">
          {t('chat.tools')}
        </p>
        <div className="mt-1 grid grid-cols-2 gap-1">
          {[
            { to: '/knowledge', label: t('nav.knowledge'), icon: BookOpen },
            { to: '/memory', label: t('nav.memory'), icon: Brain },
            { to: '/skills', label: t('nav.skills'), icon: Blocks },
            { to: '/connectors', label: t('nav.connectors'), icon: Github },
            { to: '/plugins', label: t('nav.plugins'), icon: Plug },
          ].map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className="flex items-center gap-1.5 rounded-md px-1.5 py-1 text-[11px] text-ink-muted hover:bg-surface-muted hover:text-ink"
            >
              <Icon className="h-3.5 w-3.5" />
              <span className="truncate">{label}</span>
            </NavLink>
          ))}
        </div>
      </div>

      <div className="space-y-2 border-t border-border p-3">
        <div className="flex items-center justify-between gap-2">
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
            <button
              type="button"
              aria-label={t('common.language')}
              className="shrink-0 rounded-md px-1 text-[11px] text-ink-muted hover:bg-surface-muted hover:text-ink"
              onClick={() => setLanguage(language === 'zh' ? 'en' : 'zh')}
            >
              {language === 'zh' ? 'EN' : '中'}
            </button>
            <span className="truncate text-[11px] text-ink-muted">{user?.email ?? ''}</span>
          </div>
          <button
            type="button"
            className="shrink-0 text-[11px] text-ink-muted underline-offset-2 hover:text-ink hover:underline"
            onClick={() => void logout()}
          >
            {t('nav.logout')}
          </button>
        </div>
      </div>

      <Dialog
        open={deleteIds !== null}
        onClose={() => setDeleteIds(null)}
        title={t('chat.deletePermanently')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setDeleteIds(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="danger"
              size="sm"
              onClick={() => {
                if (deleteIds !== null) void removeConversations(deleteIds)
              }}
            >
              {t('chat.delete')}
            </Button>
          </>
        }
      >
        {t('chat.deleteConfirm', { count: deleteIds?.length ?? 0 })}
      </Dialog>
    </aside>
  )
}