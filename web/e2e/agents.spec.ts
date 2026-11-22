import { expect, test } from '@playwright/test'

const workspace = {
  id: '00000000-0000-0000-0000-000000000001',
  name: 'Personal',
  plan: 'free',
  is_personal: true,
  role: 'owner',
  created_at: '2026-11-21T00:00:00Z',
}

const builtin = {
  id: 'builtin:supervisor',
  name: 'Supervisor',
  description: 'Decomposes tasks',
  instructions: 'Supervise',
  category: 'orchestration',
  default_provider_id: null,
  default_model: null,
  default_kb_id: null,
  tools: ['delegate_to_agent'],
  plugin_ids: [],
  visibility: 'shared',
  enabled: true,
  archived: false,
  owned: false,
  builtin: true,
  conversation_count: 0,
  created_at: null,
  updated_at: null,
}

test('agents page creates a custom agent', async ({ page }) => {
  const agents = [builtin]
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
  await page.route(/\/api\/agents(\?.*)?$/, async (route) => {
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON()
      const created = {
        ...builtin,
        id: 'agent-2',
        name: body.name,
        description: body.description,
        instructions: body.instructions,
        category: body.category,
        tools: body.tools,
        owned: true,
        builtin: false,
      }
      agents.push(created)
      await route.fulfill({ status: 201, json: created })
      return
    }
    await route.fulfill({ json: agents })
  })
  await page.route('**/api/models', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/provider-configs/models', (route) =>
    route.fulfill({ json: [] }),
  )
  await page.route('**/api/knowledge-bases', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/plugins', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/conversations**', (route) => route.fulfill({ json: [] }))

  await page.goto('/agents')
  await expect(page.getByRole('heading', { name: 'Agent 广场' })).toBeVisible()
  await expect(page.getByText('Supervisor')).toBeVisible()

  await page.getByRole('button', { name: '新建 Agent' }).click()
  await page.getByLabel('名称').fill('New agent')
  await page.getByLabel('角色指令').fill('Answer briefly.')
  await page.getByRole('button', { name: '保存' }).click()

  await expect(page.getByText('New agent')).toBeVisible()
})