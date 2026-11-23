import { expect, test } from '@playwright/test'

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
  title: '回答风格',
  content: '偏好简洁中文回答。',
  importance: 4,
  source: 'manual',
  source_type: 'manual',
  source_id: null,
  source_ref: {},
  confidence: 1,
  sensitivity: 'normal',
  enabled: true,
  pinned: true,
  favorite: false,
  tags: ['style'],
  valid_until: null,
  use_count: 3,
  version: 2,
  metadata: {},
  last_used_at: null,
  created_at: '2026-11-23T00:00:00Z',
  updated_at: '2026-11-23T00:00:00Z',
}

async function mockBase(page: import('@playwright/test').Page) {
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
}

test('Memory hub renders overview, list, detail and settings', async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem('ai_power_refresh_token', 'e2e-refresh-token-0123456789'),
  )
  await mockBase(page)
  const stats = {
    total: 1,
    active: 1,
    pending: 0,
    conflict: 0,
    expired: 0,
    archived: 0,
    by_category: { preference: 1 },
    by_scope: { global: 1 },
    recent: [memory],
    top_used: [memory],
  }
  const settings = {
    enabled: false,
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
    retention_days: null,
    updated_at: '2026-11-23T00:00:00Z',
  }
  await page.route('**/api/memories/stats', (route) => route.fulfill({ json: stats }))
  await page.route('**/api/memories/settings', (route) =>
    route.fulfill({ json: settings }),
  )
  await page.route('**/api/memories/mem-1/versions', (route) =>
    route.fulfill({
      json: [
        {
          id: 'v-2',
          version: 2,
          snapshot: { content: memory.content },
          changed_by: null,
          change_reason: 'refine',
          created_at: '2026-11-23T00:00:00Z',
        },
        {
          id: 'v-1',
          version: 1,
          snapshot: { content: memory.content },
          changed_by: null,
          change_reason: 'created',
          created_at: '2026-11-23T00:00:00Z',
        },
      ],
    }),
  )
  await page.route('**/api/memories/mem-1/relations', (route) =>
    route.fulfill({ json: [] }),
  )
  await page.route('**/api/memories/candidates?status=pending', (route) =>
    route.fulfill({
      json: [
        {
          id: 'cand-1',
          project_id: null,
          agent_id: null,
          target_memory_id: null,
          source_type: 'chat',
          source_id: 'msg-1',
          source_ref: {},
          extracted_by: 'fake/fake-model',
          suggested_action: 'create',
          category: 'preference',
          scope_type: 'global',
          title: '回答风格',
          content: '偏好简洁中文回答。',
          tags: ['style'],
          confidence: 0.9,
          sensitivity: 'normal',
          status: 'pending',
          reason: 'stable preference',
          created_at: '2026-11-23T00:00:00Z',
          reviewed_at: null,
        },
      ],
    }),
  )
  await page.route('**/api/memories?*', (route) => route.fulfill({ json: [memory] }))
  await page.route('**/api/memories/quality', (route) =>
    route.fulfill({
      json: {
        analysis: {
          total: 1,
          duplicates: 0,
          duplicate_groups: [],
          conflicts: 0,
          expired: 0,
          unused: 0,
          missing_source: 0,
          incomplete: 0,
          orphans: 0,
        },
        suggestions: [],
      },
    }),
  )
  await page.route('**/api/memories/eval/cases', (route) =>
    route.fulfill({ json: [] }),
  )
  await page.route('**/api/memories/eval/runs?*', (route) =>
    route.fulfill({ json: [] }),
  )
  await page.route('**/api/memories/graph?*', (route) =>
    route.fulfill({
      json: {
        nodes: [
          {
            id: `memory:${memory.id}`,
            type: 'memory',
            label: memory.title,
            memory_id: memory.id,
            ref_id: memory.id,
            category: 'preference',
            scope_type: 'global',
            status: 'active',
            pinned: true,
            importance: 4,
          },
          {
            id: 'project:p1',
            type: 'project',
            label: '示例项目',
            memory_id: null,
            ref_id: 'p1',
            category: null,
            scope_type: null,
            status: null,
            pinned: false,
            importance: null,
          },
        ],
        edges: [
          {
            id: 'rel-1',
            source: `memory:${memory.id}`,
            target: 'project:p1',
            relation_type: 'related',
            confidence: 1,
            basis: 'scope: project',
            source_kind: 'auto',
          },
        ],
        stats: { memories: 1, external: 1, relations: 1, orphans: 0 },
      },
    }),
  )
  await page.route('**/api/projects', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/agents?scope=mine', (route) =>
    route.fulfill({ json: [] }),
  )

  await page.goto('/memory')
  await expect(page.getByRole('heading', { name: /记忆中心/ })).toBeVisible()
  await expect(page.getByText('记忆总量')).toBeVisible()
  await page.getByRole('button', { name: '全部记忆' }).click()
  await expect(page.getByText('回答风格')).toBeVisible()
  await page.getByText('回答风格').click()
  await expect(page.getByText('历史版本')).toBeVisible()
  await expect(
    page.getByRole('dialog').getByText('v2', { exact: true }),
  ).toBeVisible()
  await page.getByRole('button', { name: '关闭' }).click()
  await page.getByRole('button', { name: '关系图谱' }).click()
  await expect(page.getByText('记忆节点: 1')).toBeVisible()
  await expect(page.getByText('外部节点: 1')).toBeVisible()
  await page.getByRole('button', { name: '质量分析' }).click()
  await expect(page.getByText('记忆质量分析')).toBeVisible()
  await expect(page.getByText('有效记忆')).toBeVisible()
  await page.getByRole('button', { name: '规则设置' }).click()
  await expect(page.getByText('记忆规则')).toBeVisible()
  await expect(page.getByText('未开启').last()).toBeVisible()
  await page.getByRole('button', { name: '待确认' }).click()
  await expect(page.getByText('stable preference')).toBeVisible()
  await expect(page.getByRole('button', { name: '接受' })).toBeVisible()
})