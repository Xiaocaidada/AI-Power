import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  refreshAccessToken,
  setRefreshToken,
} from './tokens'

function tokenResponse(access: string, refresh: string): Response {
  return new Response(
    JSON.stringify({
      access_token: access,
      token_type: 'bearer',
      expires_in: 1800,
      refresh_token: refresh,
      refresh_expires_in: 604800,
    }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  )
}

describe('refreshAccessToken', () => {
  beforeEach(() => {
    clearTokens()
    localStorage.clear()
    setRefreshToken('old-refresh')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    clearTokens()
    localStorage.clear()
  })

  it('shares one refresh between concurrent callers', async () => {
    const fetchMock = vi.fn(async () => tokenResponse('new-access', 'new-refresh'))
    vi.stubGlobal('fetch', fetchMock)

    const [first, second] = await Promise.all([refreshAccessToken(), refreshAccessToken()])

    expect(first).toBe('new-access')
    expect(second).toBe('new-access')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(getAccessToken()).toBe('new-access')
    expect(getRefreshToken()).toBe('new-refresh')
  })

  it('clears tokens when the refresh token is rejected', async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: { code: 'invalid_refresh_token' } }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(refreshAccessToken()).rejects.toThrow()

    expect(getRefreshToken()).toBeNull()
    expect(getAccessToken()).toBeNull()
  })
})