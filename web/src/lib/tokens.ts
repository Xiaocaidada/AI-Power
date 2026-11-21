import { API_BASE } from './config'
import { ApiError, toApiError } from './errors'
import type { TokenResponse } from './types'

const REFRESH_KEY = 'ai_power_refresh_token'

let accessToken: string | null = null
let refreshPromise: Promise<string> | null = null

export function getAccessToken(): string | null {
  return accessToken
}

export function setAccessToken(token: string | null): void {
  accessToken = token
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY)
}

export function setRefreshToken(token: string | null): void {
  if (token === null) localStorage.removeItem(REFRESH_KEY)
  else localStorage.setItem(REFRESH_KEY, token)
}

export function hasSession(): boolean {
  return getRefreshToken() !== null
}

export function clearTokens(): void {
  accessToken = null
  setRefreshToken(null)
}

async function requestRefresh(): Promise<string> {
  const refreshToken = getRefreshToken()
  if (refreshToken === null) {
    throw new ApiError(401, 'No refresh token', 'invalid_refresh_token')
  }
  const response = await fetch(`${API_BASE}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  })
  if (!response.ok) {
    clearTokens()
    throw await toApiError(response)
  }
  const data = (await response.json()) as TokenResponse
  accessToken = data.access_token
  setRefreshToken(data.refresh_token)
  return accessToken
}

export function refreshAccessToken(): Promise<string> {
  if (refreshPromise === null) {
    refreshPromise = requestRefresh().finally(() => {
      refreshPromise = null
    })
  }
  return refreshPromise
}