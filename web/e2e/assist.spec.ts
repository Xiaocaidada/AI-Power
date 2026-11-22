import { expect, test } from '@playwright/test'

const workspace = {
  id: '00000000-0000-0000-0000-000000000001',
  name: 'Personal',
  plan: 'free',
  is_personal: true,
  role: 'owner',
  created_at: '2026-11-21T00:00:00Z',
}

const dashboard = {
  counts: {
    providers: 1,
    models: 2,
    conversations: 3,
    projects: 1,
    knowledge_bases: 2,
    agents: 1,
    plugins: 0,
    unread_notifications: 0,
    requests_30d: 4,
    tokens_30d: 100,
    cost_30d: 0.01,
  },
  recent_conversations: [
    {
      id: 'conv-1',
      title: 'Recent chat',
      provider_id: 'fake',
      model: 'fake-model',
      kb_id: null,
      agent: false,
      created_at: '2026-11-23T00:00:00Z',
      updated_at: '2026-11-23T00:00:00Z',
    },
  ],
  recent_projects: [
    { id: 'project-1', name: 'Recent project', updated_at: '2026-11-23T00:00:00Z' },
  ],
}

test('dashboard and global search render', async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem('ai_power_refresh_token', 'e2e-refresh-token-0123456789'),
  )
  await page.route('**/api/auth/refresh', (route) =>
    route.fulfill({
      json: {
        access_token: 'e2e-access',
        token_type: 'bearer',
        expires_in: 1800,
        refresh_token: 'e2e-refresh-token-0123456789',
        refresh_expires_in: 604800,
      },
    }),
  )
  await page.route('**/api/auth/me', (route) =>
    route.fulfill({
      json: {
        id: '00000000-0000-0000-0000-000000000002',
        email: 'e2e@example.com',
        role: 'user',
        created_at: '2026-11-21T00:00:00Z',
      },
    }),
  )
  await page.route('**/api/workspaces', (route) => route.fulfill({ json: [workspace] }))
  await page.route('**/api/dashboard', (route) => route.fulfill({ json: dashboard }))
  await page.route(/\/api\/search\?.*$/, (route) =>
    route.fulfill({
      json: {
        query: 'needle',
        results: [
          {
            type: 'project',
            id: 'project-1',
            title: 'Needle project',
            subtitle: 'A project',
            href: '/projects/project-1',
          },
        ],
      },
    }),
  )
  await page.route('**/api/conversations**', (route) => route.fulfill({ json: [] }))

  await page.goto('/dashboard')
  await expect(page.getByRole('heading', { name: '个人控制台' })).toBeVisible()
  await expect(page.getByText('Recent chat')).toBeVisible()
  await expect(page.getByText('Recent project')).toBeVisible()
  await expect(page.getByText('近 30 天请求')).toBeVisible()

  await page.goto('/search?q=needle')
  await expect(page.getByRole('heading', { name: '全局搜索' })).toBeVisible()
  await expect(page.getByText('Needle project')).toBeVisible()
})