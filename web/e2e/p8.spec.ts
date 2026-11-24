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
  memory_enabled: false,
  rating_avg: 0,
  rating_count: 0,
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
  await page.route('**/api/mcp-servers', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/database-connections', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/memories**', (route) => route.fulfill({ json: [] }))
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
  await page.route('**/api/agents/agent-1/runs**', (route) =>
    route.fulfill({ json: [] }),
  )
  await page.route('**/api/agent-builder/sessions**', (route) =>
    route.fulfill({ json: [] }),
  )
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
        draft_definition: null,
        draft_saved_at: null,
      },
    }),
  )
  await page.route('**/api/workflows/wf-1/draft', (route) => {
    if (route.request().method() === 'DELETE') {
      return route.fulfill({ status: 204, body: '' })
    }
    return route.fulfill({
      json: { definition, saved_at: '2026-11-24T00:00:00Z' },
    })
  })
  await page.route('**/api/workflows/wf-1/nodes/*/debug', (route) =>
    route.fulfill({
      json: {
        run_id: 'run-debug',
        node_id: 'start',
        node_type: 'start',
        status: 'completed',
        output: 'debug ok',
        input_summary: 'hello',
        error_code: null,
        duration_ms: 2,
        node_run_id: 'node-run-1',
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
  await expect(page.getByRole('button', { name: '导出 JSON' })).toBeVisible()
  await expect(page.getByLabel('历史版本')).toBeVisible()
  await expect(page.getByRole('button', { name: '撤销' })).toBeDisabled()
  await page.getByRole('button', { name: '开始', exact: true }).click()
  await expect(page.getByRole('button', { name: '撤销' })).toBeEnabled()
  await expect(page.getByText(/草稿已保存/)).toBeVisible({ timeout: 5000 })
  await page.getByRole('button', { name: '撤销' }).click()
  await expect(page.getByRole('button', { name: '撤销' })).toBeDisabled()

  await page.locator('.react-flow__node').filter({ hasText: 'start' }).first().click()
  await expect(page.getByText('单节点调试')).toBeVisible()
  await page.getByPlaceholder('测试输入 [[input]]').fill('hello')
  await page.getByRole('button', { name: '测试节点' }).click()
  await expect(page.getByText('debug ok')).toBeVisible()

  await page.getByRole('button', { name: '运行' }).click()
  await expect(page.getByLabel('从指定节点开始')).toBeVisible()
  await page.getByLabel('从指定节点开始').selectOption('out')
  await expect(page.getByText('上游节点输出（JSON）')).toBeVisible()

  await page.getByRole('button', { name: 'AI 构建' }).click()
  await expect(page.getByText('AI 构建工作流')).toBeVisible()

  await page.getByRole('button', { name: '运行' }).click()
  await expect(page.getByText('运行时间线')).toBeVisible()
})

test('Canvas restores an unsaved draft and can discard it', async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem('ai_power_refresh_token', 'e2e-refresh-token-0123456789'),
  )
  await mockBase(page)
  await page.unroute('**/api/workflows/wf-1')
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
        draft_definition: definition,
        draft_saved_at: '2026-11-24T00:00:00Z',
      },
    }),
  )
  await page.goto('/studio/agent-1')
  await page.getByRole('button', { name: '画布' }).click()
  await expect(page.getByText('已恢复上次未保存的草稿')).toBeVisible()
  await page.getByRole('button', { name: '丢弃草稿' }).click()
  await expect(page.getByText('已恢复上次未保存的草稿')).toHaveCount(0)
})

test('Agent builder shows a diff and applies it to the canvas', async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem('ai_power_refresh_token', 'e2e-refresh-token-0123456789'),
  )
  await mockBase(page)
  const session = {
    id: 'bs-1',
    agent_id: 'agent-1',
    workflow_id: 'wf-1',
    provider_id: 'fake',
    model: 'fake-model',
    messages: [],
    draft_definition: definition,
    created_at: '2026-11-23T00:00:00Z',
    updated_at: '2026-11-23T00:00:00Z',
  }
  const proposed = {
    nodes: [
      { id: 'start', type: 'start', config: {}, ui: { x: 80, y: 120 } },
      {
        id: 'ask',
        type: 'llm',
        config: { provider_id: 'fake', model: 'fake-model', prompt: '{{input}}' },
        ui: { x: 300, y: 120 },
      },
      { id: 'out', type: 'output', config: {}, ui: { x: 520, y: 120 } },
    ],
    edges: [
      { from: 'start', to: 'ask' },
      { from: 'ask', to: 'out' },
    ],
  }
  await page.route(/\/api\/agent-builder\/sessions\?agent_id=agent-1$/, (route) =>
    route.fulfill({ json: [session] }),
  )
  await page.route('**/api/agent-builder/sessions/bs-1', (route) =>
    route.fulfill({ json: session }),
  )
  await page.route('**/api/agent-builder/sessions/bs-1/messages', (route) =>
    route.fulfill({
      json: {
        session_id: 'bs-1',
        message: 'Added an LLM step.',
        definition: proposed,
        diff: {
          added_nodes: [{ id: 'ask', type: 'llm' }],
          removed_nodes: [],
          updated_nodes: [],
          added_edges: [{ from: 'start', to: 'ask' }],
          removed_edges: [],
        },
        missing_resources: [],
        suggestions: ['Add a KB search step.'],
      },
    }),
  )
  await page.route('**/api/agent-builder/sessions/bs-1/apply', (route) =>
    route.fulfill({ json: { ...session, messages: [] } }),
  )

  await page.goto('/studio/agent-1')
  await page.getByRole('button', { name: 'AI 构建' }).click()
  await expect(page.getByText('AI 构建对话')).toBeVisible()
  await page.getByPlaceholder('需求描述').fill('Add an LLM step')
  await page.getByRole('button', { name: '发送' }).click()
  await expect(page.getByText('变更预览')).toBeVisible()
  await expect(page.getByText('ask · llm')).toBeVisible()
  await expect(page.getByRole('checkbox').first()).toBeChecked()
  await page.getByRole('checkbox').first().uncheck()
  await page.getByRole('checkbox').first().check()
  await page.getByRole('button', { name: '应用到画布' }).click()
  await expect(page.getByText('节点', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '保存画布' })).toBeVisible()
})

test('Agent builder surfaces clarification questions', async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem('ai_power_refresh_token', 'e2e-refresh-token-0123456789'),
  )
  await mockBase(page)
  const session = {
    id: 'bs-2',
    agent_id: 'agent-1',
    workflow_id: 'wf-1',
    provider_id: 'fake',
    model: 'fake-model',
    messages: [],
    draft_definition: definition,
    created_at: '2026-11-23T00:00:00Z',
    updated_at: '2026-11-23T00:00:00Z',
  }
  await page.route(/\/api\/agent-builder\/sessions\?agent_id=agent-1$/, (route) =>
    route.fulfill({ json: [session] }),
  )
  await page.route('**/api/agent-builder/sessions/bs-2', (route) =>
    route.fulfill({ json: session }),
  )
  await page.route('**/api/agent-builder/sessions/bs-2/messages', (route) =>
    route.fulfill({
      json: {
        session_id: 'bs-2',
        message: 'I need one detail.',
        definition: null,
        diff: null,
        missing_resources: [],
        suggestions: [],
        clarification: 'Should it use web search?',
      },
    }),
  )
  await page.goto('/studio/agent-1')
  await page.getByRole('button', { name: 'AI 构建' }).click()
  await page.getByPlaceholder('需求描述').fill('Build a research assistant')
  await page.getByRole('button', { name: '发送' }).click()
  await expect(page.getByText(/需要澄清/).first()).toBeVisible()
  await expect(page.getByText(/Should it use web search\?/).first()).toBeVisible()
  await expect(page.getByRole('button', { name: '应用到画布' })).toHaveCount(0)
})

test('Agent experience page renders chat and workflow modes', async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem('ai_power_refresh_token', 'e2e-refresh-token-0123456789'),
  )
  await mockBase(page)
  await page.goto('/agents/agent-1/experience')
  await expect(page.getByRole('heading', { name: 'Studio Agent' })).toBeVisible()
  await expect(page.getByRole('button', { name: '对话体验' })).toBeVisible()
  await expect(page.getByRole('button', { name: '工作流运行' })).toBeVisible()
  await expect(page.getByText('最近运行')).toBeVisible()
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
    featured: true,
    usage_count: 3,
    favorite_count: 1,
    copy_count: 2,
    rating_avg: 4.5,
    rating_count: 1,
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
  await page.route('**/api/market/agents/public-agent/reviews', (route) =>
    route.fulfill({
      json: {
        rating_avg: 4.5,
        rating_count: 1,
        reviews: [
          {
            id: 'review-1',
            rating: 5,
            content: 'Very useful agent.',
            author: 'e***@example.com',
            created_at: '2026-11-23T00:00:00Z',
            updated_at: '2026-11-23T00:00:00Z',
          },
        ],
      },
    }),
  )
  await page.route('**/api/agents/public-1/review', (route) =>
    route.fulfill({ json: null }),
  )
  await page.goto('/market/agents')
  await expect(page.getByRole('heading', { name: 'Agent 广场' })).toBeVisible()
  await expect(page.getByText('精选').first()).toBeVisible()
  await page.getByText('Public Agent').click()
  await expect(page.getByRole('heading', { name: 'Public Agent' })).toBeVisible()
  await expect(page.getByRole('button', { name: '复制到我的工作区' })).toBeVisible()
  await expect(page.getByText('用户评价')).toBeVisible()
  await expect(page.getByText('Very useful agent.')).toBeVisible()
  await expect(page.getByText('★ 4.5 (1)').first()).toBeVisible()
})