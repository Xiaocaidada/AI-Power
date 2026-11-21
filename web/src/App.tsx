import { useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { AppShell } from './components/AppShell'
import { RequireAuth } from './components/RequireAuth'
import { apiRequest } from './lib/http'
import { clearTokens, hasSession, refreshAccessToken } from './lib/tokens'
import type { User } from './lib/types'
import { ChatPage } from './pages/chat/ChatPage'
import { NewChatPage } from './pages/chat/NewChatPage'
import { LoginPage } from './pages/LoginPage'
import { PlaceholderPage } from './pages/PlaceholderPage'
import { useAuthStore } from './store/auth'

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
          <Route
            path="knowledge"
            element={<PlaceholderPage titleKey="knowledge.title" leadKey="knowledge.lead" />}
          />
          <Route
            path="usage"
            element={<PlaceholderPage titleKey="usage.title" leadKey="usage.lead" />}
          />
          <Route path="settings" element={<Navigate to="/settings/api-keys" replace />} />
          <Route
            path="settings/api-keys"
            element={<PlaceholderPage titleKey="nav.apiKeys" leadKey="settings.lead" />}
          />
          <Route
            path="settings/profile"
            element={<PlaceholderPage titleKey="nav.profile" leadKey="settings.lead" />}
          />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/chat" replace />} />
    </Routes>
  )
}