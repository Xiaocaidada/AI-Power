import { lazy, Suspense, useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { AppShell } from './components/AppShell'
import { ChatLayout } from './components/ChatLayout'
import { PortalLayout } from './components/PortalLayout'
import { RequireAuth } from './components/RequireAuth'
import { Spinner } from './components/ui/spinner'
import { apiRequest } from './lib/http'
import { clearTokens, hasSession, refreshAccessToken } from './lib/tokens'
import type { User } from './lib/types'
import { AdminPluginsPage } from './pages/admin/AdminPluginsPage'
import { AgentDetailPage } from './pages/agents/AgentDetailPage'
import { AgentsPage } from './pages/agents/AgentsPage'
import { ArchivedConversationsPage } from './pages/chat/ArchivedConversationsPage'
import { DashboardPage } from './pages/dashboard/DashboardPage'
import { FilesPage } from './pages/files/FilesPage'
import { SearchPage } from './pages/search/SearchPage'
import { ChatPage } from './pages/chat/ChatPage'
import { NewChatPage } from './pages/chat/NewChatPage'
import { EvaluationPage } from './pages/evaluation/EvaluationPage'
import { KnowledgeDetailPage } from './pages/knowledge/KnowledgeDetailPage'
import { KnowledgePage } from './pages/knowledge/KnowledgePage'
import { LoginPage } from './pages/LoginPage'
import { ModelsPage } from './pages/models/ModelsPage'
import { ModelDetailPage } from './pages/models/ModelDetailPage'
import { ModelPlaygroundPage } from './pages/models/ModelPlaygroundPage'
import { AnnouncementDetailPage } from './pages/portal/AnnouncementDetailPage'
import { AnnouncementsPage } from './pages/portal/AnnouncementsPage'
import { HelpPage } from './pages/help/HelpPage'
import { HomePage } from './pages/portal/HomePage'
import { ProjectDetailPage } from './pages/projects/ProjectDetailPage'
import { PluginsPage } from './pages/plugins/PluginsPage'
import { ProjectsPage } from './pages/projects/ProjectsPage'
import { ApiKeysPage } from './pages/settings/ApiKeysPage'
import { ProvidersPage } from './pages/settings/ProvidersPage'
import { SettingsHubPage } from './pages/settings/SettingsHubPage'
import { AdminPage } from './pages/admin/AdminPage'
import { AdminContentPage } from './pages/admin/AdminContentPage'
import { CollaborationsPage } from './pages/collaborations/CollaborationsPage'
import { WorkflowsPage } from './pages/workflows/WorkflowsPage'
import { ProfilePage } from './pages/settings/ProfilePage'
import { PromptTemplatesPage } from './pages/settings/PromptTemplatesPage'
import { WebhooksPage } from './pages/settings/WebhooksPage'
import { WorkspaceSettingsPage } from './pages/settings/WorkspaceSettingsPage'
import { useAuthStore } from './store/auth'

const UsagePage = lazy(() =>
  import('./pages/usage/UsagePage').then((module) => ({ default: module.UsagePage })),
)

export function App() {
  const setUser = useAuthStore((state) => state.setUser)
  const setAnonymous = useAuthStore((state) => state.setAnonymous)

  useEffect(() => {
    let cancelled = false
    const bootstrap = async () => {
      if (!hasSession()) {
        setAnonymous()
        return
      }
      try {
        await refreshAccessToken()
        const user = await apiRequest<User>('/auth/me')
        if (!cancelled) setUser(user)
      } catch {
        clearTokens()
        if (!cancelled) setAnonymous()
      }
    }
    void bootstrap()
    return () => {
      cancelled = true
    }
  }, [setUser, setAnonymous])

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<PortalLayout />}>
        <Route index element={<HomePage />} />
        <Route path="models" element={<ModelsPage />} />
        <Route path="models/:slug" element={<ModelDetailPage />} />
        <Route path="announcements" element={<AnnouncementsPage />} />
        <Route path="announcements/:id" element={<AnnouncementDetailPage />} />
        <Route path="help" element={<HelpPage />} />
        <Route element={<RequireAuth />}>
          <Route path="models/:slug/playground" element={<ModelPlaygroundPage />} />
        </Route>
      </Route>
      <Route element={<RequireAuth />}>
        <Route element={<ChatLayout />}>
          <Route path="chat" element={<NewChatPage />} />
          <Route path="chat/:id" element={<ChatPage />} />
        </Route>
        <Route element={<AppShell />}>
          <Route path="archive" element={<ArchivedConversationsPage />} />
          <Route path="projects" element={<ProjectsPage />} />
          <Route path="projects/:id" element={<ProjectDetailPage />} />
          <Route path="agents" element={<AgentsPage />} />
          <Route path="agents/:id" element={<AgentDetailPage />} />
          <Route path="plugins" element={<PluginsPage />} />
          <Route path="dashboard" element={<DashboardPage />} />
          <Route path="files" element={<FilesPage />} />
          <Route path="search" element={<SearchPage />} />
          <Route path="workflows" element={<WorkflowsPage />} />
          <Route path="collaborations" element={<CollaborationsPage />} />
          <Route path="admin" element={<AdminPage />} />
          <Route path="admin/content" element={<AdminContentPage />} />
          <Route path="admin/plugins" element={<AdminPluginsPage />} />
          <Route path="knowledge" element={<KnowledgePage />} />
          <Route path="knowledge/:id" element={<KnowledgeDetailPage />} />
          <Route path="evaluation" element={<EvaluationPage />} />
          <Route
            path="usage"
            element={
              <Suspense
                fallback={
                  <div className="flex flex-1 items-center justify-center">
                    <Spinner className="h-6 w-6 text-accent" />
                  </div>
                }
              >
                <UsagePage />
              </Suspense>
            }
          />
          <Route path="settings" element={<SettingsHubPage />} />
          <Route path="settings/providers" element={<ProvidersPage />} />
          <Route path="settings/api-keys" element={<ApiKeysPage />} />
          <Route path="settings/webhooks" element={<WebhooksPage />} />
          <Route path="settings/workspace" element={<WorkspaceSettingsPage />} />
          <Route path="settings/prompts" element={<PromptTemplatesPage />} />
          <Route path="settings/profile" element={<ProfilePage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}