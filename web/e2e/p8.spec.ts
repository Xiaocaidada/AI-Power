import { expect, test } from '@playwright/test'

const workspace = {
  id: '00000000-0000-0000-0000-000000000001',
  name: 'Personal',
  plan: 'free',
  is_personal: true,
  role: 'owner',
  created_at: '2026-11-23T00:00:00Z',
}

const agent = {
  id: 'agent-1',
  name: 'Studio Agent',
  description: 'A canvas agent',
  instructions: 'Be helpful.',
  category: 'general',
  mode: 'hybrid',
  icon: '🧪',
  welcome_message: 'Hello',
  examples: ['Summarize this'],
  usage_instructions: 'Give it a task.',
  generation_settings: {},
  default_provider_id: 'fake',
  default_model: 'fake-model',
  default_kb_id: null,
  kb_ids: [],
  tools: [],
  plugin_ids: [],
  workflow_id: 'wf-1',
  visibility: 'private',
  enabled: true,
  archived: false,
  owned: true,
  builtin: false,
  published: false,
  public_slug: null,
  allow_copy: true,
  show_structure: true,
  favorite: false,
  favorite_count: 0,
  usage_count: 0,
  copy_count: 0,
  conversation_count: 0,
  created_at: '2026-11-23T00:00:00Z',
  updated_at: '2026-11-23T00:00:00Z',
}

const definition = {
  nodes: [
    { id: 'start', type: 'start', config: {}, ui: { x: 80, y: 120 } },
    { id: 'out', type: 'output', config: {}, ui: { x: 420, y: 120 } },
  ],
  edges: [{ from: 'start', to: 'out' }],
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
  await page.route('**/api/knowledge-bases', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/plugins', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/agents', (route) => route.fulfill({ json: [agent] }))
  await page.route('**/api/agents/agent-1', (route) => route.fulfill({ json: agent }))
  await page.route('**/api/workflows/catalog', (route) =>
    route.fulfill({
      json: {
        nodes: [
          { type: 'start', label: '开始', description: '', icon: 'Play', config_fields: [] },
          { type: 'output', label: '输出', description: '', icon: 'Flag', config_fields: [] },
        ],
        limits: { max_nodes: 30, max_kbs: 10 },
        variables: { input: '用户输入' },
      },
    }),
  )
  await page.route('**/api/workflows/wf-1', (route) =>
    route.fulfill({
      json: {
        id: 'wf-1',
        name: 'Studio workflow',
        description: '',
        created_at: '2026-11-23T00:00:00Z',
        versions: [
          {
            id: 'ver-1',
            version: 1,
            definition,
            created_at: '2026-11-23T00:00:00Z',
          },
        ],
      },
    }),
  )
}

test('Agent Studio config, canvas, builder, and run tabs render', async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem('ai_power_refresh_token', 'e2e-refresh-token-0123456789'),
  )
  await mockBase(page)
  await page.goto('/studio/agent-1')
  await expect(page.getByRole('heading', { name: 'Studio Agent' })).toBeVisible()
  await expect(page.getByText('角色与能力')).toBeVisible()

  await page.getByRole('button', { name: '画布' }).click()
  await expect(page.getByText('节点', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '保存画布' })).toBeVisible()

  await page.getByRole('button', { name: 'AI 构建' }).click()
  await expect(page.getByText('AI 构建工作流')).toBeVisible()

  await page.getByRole('button', { name: '运行' }).click()
  await expect(page.getByText('运行时间线')).toBeVisible()
})

test('Agent plaza lists and opens a public agent', async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem('ai_power_refresh_token', 'e2e-refresh-token-0123456789'),
  )
  await mockBase(page)
  const summary = {
    id: 'public-1',
    slug: 'public-agent',
    name: 'Public Agent',
    description: 'Shared with everyone',
    icon: '🌍',
    category: 'research',
    mode: 'workflow',
    usage_count: 3,
    favorite_count: 1,
    copy_count: 2,
    allow_copy: true,
    published_at: '2026-11-23T00:00:00Z',
  }
  await page.route('**/api/market/agents**', (route) =>
    route.fulfill({ json: [summary] }),
  )
  await page.route('**/api/market/agents/public-agent', (route) =>
    route.fulfill({
      json: {
        ...summary,
        welcome_message: 'Hi',
        examples: ['Research this'],
        usage_instructions: 'Give a topic',
        tools: [],
        model_hint: 'fake-model',
        kb_requirements: ['Docs'],
        plugin_requirements: [],
        instructions: 'Be careful',
        workflow: definition,
      },
    }),
  )
  await page.goto('/market/agents')
  await expect(page.getByRole('heading', { name: 'Agent 广场' })).toBeVisible()
  await page.getByText('Public Agent').click()
  await expect(page.getByRole('heading', { name: 'Public Agent' })).toBeVisible()
  await expect(page.getByRole('button', { name: '复制到我的工作区' })).toBeVisible()
})