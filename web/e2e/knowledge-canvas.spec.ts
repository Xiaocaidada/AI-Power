import { expect, test, type Page } from '@playwright/test'

const workspace = {
  id: '00000000-0000-0000-0000-000000000001',
  name: 'Personal',
  plan: 'free',
  is_personal: true,
  role: 'owner',
  created_at: '2026-11-23T00:00:00Z',
}

const knowledgeBase = {
  id: 'kb-1',
  name: 'Canvas KB',
  description: '',
  created_at: '2026-11-23T00:00:00Z',
  document_count: 0,
  chunk_count: 0,
  total_chars: 0,
}

const workflow = {
  id: 'wf-k',
  name: 'Knowledge workflow',
  description: '',
  kind: 'knowledge_process',
  created_at: '2026-11-23T00:00:00Z',
  versions: [
    {
      id: 'ver-k',
      version: 1,
      definition: {
        nodes: [
          { id: 'start', type: 'start', config: {}, ui: { x: 80, y: 120 } },
          { id: 'out', type: 'output', config: {}, ui: { x: 520, y: 120 } },
        ],
        edges: [{ from: 'start', to: 'out' }],
      },
      created_at: '2026-11-23T00:00:00Z',
    },
  ],
  draft_definition: null,
  draft_saved_at: null,
}

const retrievalWorkflow = {
  ...workflow,
  id: 'wf-r',
  name: 'Retrieval workflow',
  kind: 'knowledge_retrieval',
  versions: [
    {
      id: 'ver-r',
      version: 1,
      definition: {
        nodes: [
          { id: 'start', type: 'start', config: {}, ui: { x: 80, y: 120 } },
          {
            id: 'hybrid',
            type: 'hybrid_search',
            config: { top_k: 10, candidate_k: 20 },
            ui: { x: 300, y: 120 },
          },
          { id: 'out', type: 'output', config: {}, ui: { x: 520, y: 120 } },
        ],
        edges: [
          { from: 'start', to: 'hybrid' },
          { from: 'hybrid', to: 'out' },
        ],
      },
      created_at: '2026-11-23T00:00:00Z',
    },
  ],
}

function catalogNodes(includeHybrid: boolean) {
  return [
    { type: 'start', label: '开始', description: '', icon: 'Play', config_fields: [] },
    ...(includeHybrid
      ? [
          {
            type: 'hybrid_search',
            label: '混合检索',
            description: '',
            icon: 'GitMerge',
            config_fields: [],
          },
        ]
      : []),
    { type: 'output', label: '输出', description: '', icon: 'Flag', config_fields: [] },
  ]
}

async function mockKnowledgeApi(page: Page) {
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
  await page.route('**/api/knowledge-bases/kb-1', (route) =>
    route.fulfill({ json: knowledgeBase }),
  )
  await page.route('**/api/knowledge-bases/kb-1/documents**', (route) =>
    route.fulfill({ json: [] }),
  )
  await page.route('**/api/knowledge-bases/kb-1/stats', (route) =>
    route.fulfill({
      json: {
        document_count: 0,
        ready_count: 0,
        processing_count: 0,
        failed_count: 0,
        chunk_count: 0,
        char_count: 0,
      },
    }),
  )
  await page.route('**/api/knowledge-bases/kb-1/folders', (route) =>
    route.fulfill({ json: [] }),
  )
  await page.route('**/api/knowledge-bases/kb-1/settings', (route) =>
    route.fulfill({ json: {} }),
  )
  await page.route('**/api/knowledge-bases/kb-1/processing/analytics**', (route) =>
    route.fulfill({
      json: {
        days: 30,
        total: 2,
        completed: 1,
        failed: 1,
        cancelled: 0,
        running: 0,
        success_rate: 0.5,
        avg_duration_ms: 120,
        p95_duration_ms: 120,
        avg_chunks: 4,
        applied_count: 1,
        pending_apply: 0,
        failure_codes: { parse_failed: 1 },
        recent: [],
      },
    }),
  )
  await page.route('**/api/knowledge-bases/kb-1/processing/binding', (route) =>
    route.fulfill({ json: { workflow_id: 'wf-k', workflow_version_id: 'ver-k' } }),
  )
  await page.route('**/api/knowledge-bases/kb-1/retrieval/binding', (route) =>
    route.fulfill({ json: { workflow_id: 'wf-r', workflow_version_id: 'ver-r' } }),
  )
  await page.route('**/api/workflows/catalog**', (route) => {
    const url = new URL(route.request().url())
    const kind = url.searchParams.get('kind')
    return route.fulfill({
      json: {
        nodes: catalogNodes(kind === 'knowledge_retrieval'),
        limits: { max_nodes: 30, max_kbs: 10 },
        variables: { input: '用户输入' },
      },
    })
  })
  await page.route('**/api/workflows?**', (route) => {
    const url = new URL(route.request().url())
    const kind = url.searchParams.get('kind')
    return route.fulfill({
      json: [kind === 'knowledge_retrieval' ? retrievalWorkflow : workflow],
    })
  })
  await page.route('**/api/workflows/wf-k', (route) => route.fulfill({ json: workflow }))
  await page.route('**/api/workflows/wf-r', (route) =>
    route.fulfill({ json: retrievalWorkflow }),
  )
}

test('knowledge processing canvas renders after loading', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.addInitScript(() =>
    localStorage.setItem('ai_power_refresh_token', 'e2e-refresh-token-0123456789'),
  )
  await mockKnowledgeApi(page)
  await page.goto('/knowledge/kb-1/studio')
  await expect(
    page.getByRole('heading', { name: 'Canvas KB · Knowledge Studio' }),
  ).toBeVisible()
  await expect(page.getByText('节点', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '保存画布' })).toBeVisible()
  expect(errors).toEqual([])
})

test('knowledge processing analytics tab renders', async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem('ai_power_refresh_token', 'e2e-refresh-token-0123456789'),
  )
  await mockKnowledgeApi(page)
  await page.goto('/knowledge/kb-1')
  await page.getByRole('button', { name: '运行分析' }).click()
  await expect(page.getByText('处理运行分析')).toBeVisible()
  await expect(page.getByText('成功率', { exact: true })).toBeVisible()
  await expect(page.getByText('parse_failed')).toBeVisible()
})

test('knowledge retrieval canvas renders after loading', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.addInitScript(() =>
    localStorage.setItem('ai_power_refresh_token', 'e2e-refresh-token-0123456789'),
  )
  await mockKnowledgeApi(page)
  await page.goto('/knowledge/kb-1/retrieval')
  await expect(
    page.getByRole('heading', { name: 'Canvas KB · 检索 Studio' }),
  ).toBeVisible()
  await expect(page.getByText('节点', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '保存画布' })).toBeVisible()
  expect(errors).toEqual([])
})