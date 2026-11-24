import { expect, test, type Page } from '@playwright/test'

const workspace = {
  id: '00000000-0000-0000-0000-000000000001',
  name: 'Personal',
  plan: 'free',
  is_personal: true,
  role: 'owner',
  created_at: '2026-11-23T00:00:00Z',
}

const memory = {
  id: 'mem-1',
  agent_id: null,
  project_id: null,
  scope: 'user',
  scope_type: 'global',
  kind: 'fact',
  category: 'preference',
  status: 'active',
  title: 'Answer style',
  content: 'User prefers concise answers.',
  importance: 4,
  source: 'manual',
  source_type: 'manual',
  source_id: null,
  source_ref: {},
  confidence: 1,
  sensitivity: 'normal',
  enabled: true,
  pinned: false,
  favorite: false,
  tags: ['style'],
  valid_until: null,
  retention_days: 30,
  use_count: 3,
  version: 2,
  metadata: {},
  last_used_at: '2026-11-23T00:00:00Z',
  created_at: '2026-11-23T00:00:00Z',
  updated_at: '2026-11-23T00:00:00Z',
}

const stats = {
  total: 2,
  active: 2,
  pending: 0,
  candidates_pending: 0,
  conflict: 0,
  expired: 0,
  archived: 0,
  by_category: { preference: 2 },
  by_scope: { global: 2 },
  by_status: { active: 2 },
  by_source: { manual: 2 },
  completeness: { average_score: 75, complete: 1, partial: 1, sparse: 0 },
  retention_days: 30,
  expiring_soon: 1,
  stale: 0,
  active_chars: 120,
  usage_total: 4,
  usage_chars: 480,
  usage_by_model: [
    { provider_id: 'fake', model: 'fake-model', count: 4, injected_chars: 480 },
  ],
  usage_by_context: { chat: 4 },
  usage_by_agent: [],
  usage_by_project: [],
  usage_by_conversation: [],
  recent: [memory],
  top_used: [memory],
}

const settings = {
  enabled: true,
  auto_extract: true,
  auto_save: false,
  require_confirmation: true,
  allowed_categories: ['preference'],
  allow_project_extract: true,
  allow_agent_extract: false,
  allow_cross_model: true,
  max_inject_items: 8,
  max_inject_chars: 4000,
  blocked_topics: [],
  retention_days: 30,
  updated_at: '2026-11-23T00:00:00Z',
}

async function mockMemory(page: Page) {
  await page.route('**/api/auth/login', (route) =>
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
        created_at: '2026-11-23T00:00:00Z',
      },
    }),
  )
  await page.route('**/api/workspaces', (route) => route.fulfill({ json: [workspace] }))
  await page.route('**/api/memories/stats', (route) => route.fulfill({ json: stats }))
  await page.route('**/api/memories/settings', (route) =>
    route.fulfill({ json: settings }),
  )
  await page.route('**/api/memories/lifecycle', (route) =>
    route.fulfill({
      json: {
        retention_days: 30,
        expiring_count: 1,
        items: [
          {
            id: 'mem-1',
            title: 'Answer style',
            updated_at: '2026-11-23T00:00:00Z',
            retention_days: 30,
          },
        ],
      },
    }),
  )
  await page.route('**/api/projects', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/agents?scope=mine', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/memories/mem-1/versions', (route) =>
    route.fulfill({
      json: [
        {
          id: 'v2',
          version: 2,
          snapshot: {},
          changed_by: null,
          change_reason: 'manual update',
          created_at: '2026-11-23T00:00:00Z',
        },
        {
          id: 'v1',
          version: 1,
          snapshot: {},
          changed_by: null,
          change_reason: 'created',
          created_at: '2026-11-22T00:00:00Z',
        },
      ],
    }),
  )
  await page.route('**/api/memories/mem-1/versions/diff**', (route) =>
    route.fulfill({
      json: {
        from_version: 1,
        to_version: 2,
        from_created_at: '2026-11-22T00:00:00Z',
        to_created_at: '2026-11-23T00:00:00Z',
        from_reason: 'created',
        to_reason: 'manual update',
        changes: [{ field: 'content', before: 'old', after: 'new' }],
        content_diff: '-old content\n+new content',
        risk_flags: ['content_changed'],
      },
    }),
  )
  await page.route('**/api/memories/mem-1/relations', (route) =>
    route.fulfill({ json: [] }),
  )
  await page.route('**/api/memories?**', (route) => route.fulfill({ json: [] }))
}

test('memory dashboard shows completeness, usage and lifecycle', async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem('ai_power_refresh_token', 'e2e-refresh-token-0123456789'),
  )
  await mockMemory(page)
  await page.goto('/memory')
  await expect(page.getByText('平均完整度', { exact: true })).toBeVisible()
  await expect(page.getByText('使用聚合', { exact: true })).toBeVisible()
  await expect(page.getByText('生命周期', { exact: true })).toBeVisible()
  await expect(page.getByText('保留 30 天')).toBeVisible()
})

test('memory version diff renders in the detail dialog', async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem('ai_power_refresh_token', 'e2e-refresh-token-0123456789'),
  )
  await mockMemory(page)
  await page.goto('/memory')
  await page.getByText('Answer style').first().click()
  await page.getByRole('button', { name: '对比上一版' }).click()
  await expect(page.getByText('版本差异')).toBeVisible()
  await expect(page.getByText('内容变化')).toBeVisible()
  await expect(page.getByText(/old content/)).toBeVisible()
})