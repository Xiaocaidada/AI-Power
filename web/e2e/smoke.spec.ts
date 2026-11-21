import { expect, test } from '@playwright/test'

const workspace = {
  id: '00000000-0000-0000-0000-000000000001',
  name: 'Personal',
  plan: 'free',
  is_personal: true,
  role: 'owner',
  created_at: '2026-11-21T00:00:00Z',
}

test('login opens the new chat screen', async ({ page }) => {
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
  await page.route('**/api/conversations**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/knowledge-bases', (route) => route.fulfill({ json: [] }))
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
          tags: ['fast'],
          priority: 10,
          available: true,
        },
      ],
    }),
  )

  await page.goto('/login')
  await page.getByLabel('邮箱').fill('e2e@example.com')
  await page.getByLabel('密码').fill('E2e!pass123')
  await page.getByLabel('密码').press('Enter')

  await expect(page).toHaveURL(/\/chat$/)
  await expect(page.getByRole('heading', { name: '开始新对话' })).toBeVisible()
})