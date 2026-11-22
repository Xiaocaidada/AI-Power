import { expect, test } from '@playwright/test'

const workspace = {
  id: '00000000-0000-0000-0000-000000000001',
  name: 'Personal',
  plan: 'free',
  is_personal: true,
  role: 'owner',
  created_at: '2026-11-21T00:00:00Z',
}

const workflow = {
  id: 'workflow-1',
  name: 'Demo',
  description: 'Demo workflow',
  created_at: '2026-11-21T00:00:00Z',
  versions: [
    {
      id: 'version-1',
      version: 1,
      definition: {
        nodes: [
          {
            id: 'draft',
            type: 'llm',
            config: { provider_id: 'fake', model: 'fake-model', prompt: '{{input}}' },
          },
        ],
        edges: [],
      },
      created_at: '2026-11-21T00:00:00Z',
    },
  ],
}

const sseBody = [
  'id: 1',
  'event: workflow_start',
  'data: {"run_id":"run-1","workflow_id":"workflow-1","version":1}',
  '',
  'id: 2',
  'event: node_start',
  'data: {"run_id":"run-1","node_id":"draft","node_type":"llm"}',
  '',
  'id: 3',
  'event: node_end',
  'data: {"run_id":"run-1","node_id":"draft","status":"completed","attempts":1,"duration_ms":12,"output":"FINAL"}',
  '',
  'id: 4',
  'event: workflow_end',
  'data: {"run_id":"run-1","status":"completed","total_ms":20,"prompt_tokens":1,"completion_tokens":1,"cost":0,"output":"FINAL"}',
  '',
  '',
].join('\n')

const runDetail = {
  id: 'run-1',
  workflow_id: 'workflow-1',
  version_id: 'version-1',
  kb_id: null,
  status: 'completed',
  input_text: 'hello',
  error_code: null,
  cancel_requested_at: null,
  prompt_tokens: 1,
  completion_tokens: 1,
  cost: 0,
  total_ms: 20,
  started_at: '2026-11-21T00:00:00Z',
  finished_at: '2026-11-21T00:00:01Z',
  nodes: [],
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
}

async function mockWorkflow(page: import('@playwright/test').Page) {
  await page.route('**/api/workflows', (route) =>
    route.request().method() === 'GET'
      ? route.fulfill({ json: [workflow] })
      : route.fulfill({ json: workflow }),
  )
  await page.route('**/api/workflows/workflow-1/runs**', (route) =>
    route.request().method() === 'POST'
      ? route.fulfill({ status: 202, json: { run_id: 'run-1', status: 'queued' } })
      : route.fulfill({ json: [runDetail] }),
  )
  await page.route('**/api/workflows/runs/run-1', (route) =>
    route.fulfill({ json: runDetail }),
  )
  await page.route('**/api/workflows/runs/run-1/events**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: sseBody,
    }),
  )
}

test('workflow run shows node timeline and output', async ({ page }) => {
  await mockBase(page)
  await mockWorkflow(page)

  await page.goto('/login')
  await page.getByLabel('邮箱').fill('e2e@example.com')
  await page.getByLabel('密码').fill('E2e!pass123')
  await page.getByLabel('密码').press('Enter')
  await expect(page).toHaveURL(/\/chat$/)

  await page.getByRole('link', { name: '工作流' }).click()
  await page.getByRole('button', { name: /Demo/ }).click()
  await page.getByRole('button', { name: '运行工作流' }).click()

  await expect(page.getByText('draft')).toBeVisible()
  await expect(page.getByText('completed').first()).toBeVisible()
  await expect(page.getByText('FINAL').first()).toBeVisible()
})

test('workflow run reconnects from the run URL after reload', async ({ page }) => {
  await mockBase(page)
  await mockWorkflow(page)

  await page.goto('/login')
  await page.getByLabel('邮箱').fill('e2e@example.com')
  await page.getByLabel('密码').fill('E2e!pass123')
  await page.getByLabel('密码').press('Enter')
  await expect(page).toHaveURL(/\/chat$/)

  await page.goto('/workflows?workflow=workflow-1&run=run-1')

  await expect(page.getByText('draft')).toBeVisible()
  await expect(page.getByText('FINAL').first()).toBeVisible()
})