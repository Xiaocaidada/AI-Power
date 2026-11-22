import { expect, test } from '@playwright/test'

const workspace = {
  id: '00000000-0000-0000-0000-000000000001',
  name: 'Personal',
  plan: 'free',
  is_personal: true,
  role: 'owner',
  created_at: '2026-11-21T00:00:00Z',
}

const project = {
  id: 'project-1',
  name: 'Demo project',
  description: 'Existing project',
  instructions: 'Be concise',
  default_provider_id: 'fake',
  default_model: 'fake-model',
  default_kb_id: null,
  default_agent: false,
  archived: false,
  conversation_count: 0,
  owned: true,
  created_at: '2026-11-23T00:00:00Z',
  updated_at: '2026-11-23T00:00:00Z',
}

test('projects page creates a project', async ({ page }) => {
  const projects = [project]
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
  await page.route('**/api/projects', async (route) => {
    if (route.request().method() === 'POST') {
      const created = {
        ...project,
        id: 'project-2',
        name: 'New project',
        description: 'From E2E',
        instructions: '',
        default_provider_id: 'auto',
        default_model: 'auto',
      }
      projects.push(created)
      await route.fulfill({ status: 201, json: created })
      return
    }
    await route.fulfill({ json: projects })
  })
  await page.route('**/api/conversations**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/knowledge-bases', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/models', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/provider-configs/models', (route) =>
    route.fulfill({ json: [] }),
  )

  await page.goto('/projects')
  await expect(page.getByRole('heading', { name: '项目', exact: true })).toBeVisible()
  await expect(page.getByText('Demo project')).toBeVisible()

  await page.getByRole('button', { name: '新建项目' }).click()
  await page.getByLabel('项目名称').fill('New project')
  await page.getByLabel('简介').fill('From E2E')
  await page.getByRole('button', { name: '保存' }).click()

  await expect(page.getByText('New project')).toBeVisible()
})