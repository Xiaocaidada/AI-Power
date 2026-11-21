import { API_BASE } from './config'
import { toApiError } from './errors'
import { getAccessToken, hasSession, refreshAccessToken } from './tokens'
import { getActiveWorkspaceId } from './workspace'

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  body?: unknown
  signal?: AbortSignal
  auth?: boolean
  retryOn401?: boolean
  headers?: Record<string, string>
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, signal, auth = true, retryOn401 = true, headers } = options

  const send = async (): Promise<Response> => {
    const finalHeaders: Record<string, string> = { ...(headers ?? {}) }
    if (body !== undefined) finalHeaders['Content-Type'] = 'application/json'
    const token = getAccessToken()
    if (auth && token !== null) finalHeaders.Authorization = `Bearer ${token}`
    const workspaceId = getActiveWorkspaceId()
    if (auth && workspaceId !== null) finalHeaders['X-Workspace-Id'] = workspaceId
    return fetch(`${API_BASE}${path}`, {
      method,
      headers: finalHeaders,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    })
  }

  let response = await send()
  if (response.status === 401 && auth && retryOn401 && hasSession()) {
    try {
      await refreshAccessToken()
    } catch {
      throw await toApiError(response)
    }
    response = await send()
  }
  if (!response.ok) throw await toApiError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export function publicRequest<T>(
  path: string,
  options: Omit<RequestOptions, 'auth' | 'retryOn401'> = {},
): Promise<T> {
  return apiRequest<T>(path, { ...options, auth: false, retryOn401: false })
}