import { expect, test } from '@playwright/test'

const workspace = {
  id: '00000000-0000-0000-0000-000000000001',
  name: 'Personal',
  plan: 'free',
  is_personal: true,
  role: 'owner',
  created_at: '2026-11-23T00:00:00Z',
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
  await page.route('**/api/models', (route) =>
    route.fulfill({
      json: [
        {
          id: 'model-1',
          provider_id: 'fake',
          model_id: 'fake-model',
          display_name: 'Fake Model',
          context_window: 8192,
          input_price: 0,
          output_price: 0,
          tags: [],
          priority: 10,
          available: true,
        },
      ],
    }),
  )
  await page.route('**/api/provider-configs/models', (route) =>
    route.fulfill({ json: [] }),
  )
  await page.route('**/api/arena/rounds**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/prompt-templates**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/prompt-lab/experiments**', (route) =>
    route.fulfill({ json: [] }),
  )
  await page.route('**/api/model-eval/datasets**', (route) =>
    route.fulfill({ json: [] }),
  )
  await page.route('**/api/model-eval/runs**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/conversations**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/knowledge-bases', (route) => route.fulfill({ json: [] }))
}

test('P7 workbenches render', async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem('ai_power_refresh_token', 'e2e-refresh-token-0123456789'),
  )
  await mockBase(page)
  await page.goto('/arena')
  await expect(page.getByRole('heading', { name: '模型擂台' })).toBeVisible()

  await page.goto('/prompt-lab')
  await expect(page.getByRole('heading', { name: 'Prompt 实验室' })).toBeVisible()

  await page.goto('/model-eval')
  await expect(page.getByRole('heading', { name: '模型评测中心' })).toBeVisible()
})

test('P7 admin platform prompts render', async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem('ai_power_refresh_token', 'e2e-refresh-token-0123456789'),
  )
  await mockBase(page)
  await page.route('**/api/auth/me', (route) =>
    route.fulfill({
      json: {
        id: '00000000-0000-0000-0000-000000000002',
        email: 'e2e@example.com',
        role: 'admin',
        created_at: '2026-11-23T00:00:00Z',
      },
    }),
  )
  await page.route('**/api/admin/prompt-templates', (route) =>
    route.fulfill({ json: [] }),
  )
  await page.goto('/admin/prompts')
  await expect(page.getByRole('heading', { name: '平台提示词管理' })).toBeVisible()
  await expect(page.getByText('还没有平台模板。')).toBeVisible()
})