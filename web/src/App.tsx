import { lazy, Suspense, useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { AppShell } from './components/AppShell'
import { RequireAuth } from './components/RequireAuth'
import { Spinner } from './components/ui/spinner'
import { apiRequest } from './lib/http'
import { clearTokens, hasSession, refreshAccessToken } from './lib/tokens'
import type { User } from './lib/types'
import { ChatPage } from './pages/chat/ChatPage'
import { NewChatPage } from './pages/chat/NewChatPage'
import { KnowledgeDetailPage } from './pages/knowledge/KnowledgeDetailPage'
import { KnowledgePage } from './pages/knowledge/KnowledgePage'
import { LoginPage } from './pages/LoginPage'
import { ModelsPage } from './pages/models/ModelsPage'
import { ApiKeysPage } from './pages/settings/ApiKeysPage'
import { ProfilePage } from './pages/settings/ProfilePage'
import { PromptTemplatesPage } from './pages/settings/PromptTemplatesPage'
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
      <Route element={<RequireAuth />}>
        <Route element={<AppShell />}>
          <Route index element={<Navigate to="/chat" replace />} />
          <Route path="chat" element={<NewChatPage />} />
          <Route path="chat/:id" element={<ChatPage />} />
          <Route path="models" element={<ModelsPage />} />
          <Route path="knowledge" element={<KnowledgePage />} />
          <Route path="knowledge/:id" element={<KnowledgeDetailPage />} />
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
          <Route path="settings" element={<Navigate to="/settings/api-keys" replace />} />
          <Route path="settings/api-keys" element={<ApiKeysPage />} />
          <Route path="settings/workspace" element={<WorkspaceSettingsPage />} />
          <Route path="settings/prompts" element={<PromptTemplatesPage />} />
          <Route path="settings/profile" element={<ProfilePage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/chat" replace />} />
    </Routes>
  )
}