import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'

import { useAuthStore } from '../store/auth'
import { apiRequest } from './http'
import { clearTokens, getRefreshToken } from './tokens'
import { setActiveWorkspaceId } from './workspace'

export function useLogout(): () => Promise<void> {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const setAnonymous = useAuthStore((state) => state.setAnonymous)

  return async () => {
    const refreshToken = getRefreshToken()
    try {
      if (refreshToken !== null) {
        await apiRequest('/auth/logout', {
          method: 'POST',
          body: { refresh_token: refreshToken },
          auth: false,
        })
      }
    } catch {
      // Local logout is authoritative even when the server call fails.
    }
    clearTokens()
    setActiveWorkspaceId(null)
    queryClient.clear()
    setAnonymous()
    navigate('/login', { replace: true })
  }
}