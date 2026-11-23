import { expect, test } from '@playwright/test'

const workspace = {
  id: '00000000-0000-0000-0000-000000000001',
  name: 'Personal',
  plan: 'free',
  is_personal: true,
  role: 'owner',
  created_at: '2026-11-23T00:00:00Z',
}

const definition = {
  nodes: [
    { id: 'start', type: 'start', config: {}, ui: { x: 80, y: 120 } },
    { id: 'parse', type: 'parse_document', config: {}, ui: { x: 260, y: 120 } },
    {
      id: 'chunk',
      type: 'chunk_text',
      config: { strategy: 'markdown', chunk_size: 800, chunk_overlap: 120 },
      ui: { x: 440, y: 120 },
    },
    { id: 'out', type: 'output', config: {}, ui: { x: 620, y: 120 } },
  ],
  edges: [
    { from: 'start', to: 'parse' },
    { from: 'parse', to: 'chunk' },
    { from: 'chunk', to: 'out' },
  ],
}

const workflow = {
  id: 'wf-knowledge',
  name: 'Technical docs',
  description: 'P9',
  kind: 'knowledge_process',
  created_at: '2026-11-23T00:00:00Z',
  versions: [
    {
      id: 'wfv-1',
      version: 1,
      definition,
      created_at: '2026-11-23T00:00:00Z',
    },
  ],
}

const catalogNode = (type: string, label: string) => ({
  type,
  label,
  description: label,
  icon: 'FileText',
  config_fields: [],
})

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

test('Knowledge Studio renders the processing canvas and run tab', async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem('ai_power_refresh_token', 'e2e-refresh-token-0123456789'),
  )
  await mockBase(page)
  await page.route('**/api/knowledge-bases/kb-1', (route) =>
    route.fulfill({
      json: {
        id: 'kb-1',
        name: '技术知识库',
        description: '',
        created_at: '2026-11-23T00:00:00Z',
      },
    }),
  )
  await page.route('**/api/knowledge-bases/kb-1/documents**', (route) =>
    route.fulfill({ json: [] }),
  )
  await page.route('**/api/knowledge-bases/kb-1/processing/binding', (route) =>
    route.fulfill({
      json: {
        workflow_version_id: null,
        workflow_id: null,
        version: null,
        kind: 'knowledge_process',
        name: '',
      },
    }),
  )
  await page.route('**/api/workflows/catalog?kind=knowledge_process', (route) =>
    route.fulfill({
      json: {
        kind: 'knowledge_process',
        nodes: [
          catalogNode('start', '文档输入'),
          catalogNode('parse_document', '文档解析'),
          catalogNode('chunk_text', '文本切片'),
          catalogNode('output', '输出'),
        ],
        limits: { max_nodes: 30, linear: true },
        variables: {},
        templates: [{ name: '技术文档处理', description: '', definition }],
      },
    }),
  )
  await page.route('**/api/workflows?kind=knowledge_process', (route) =>
    route.fulfill({ json: [workflow] }),
  )
  await page.route('**/api/workflows/wf-knowledge', (route) =>
    route.fulfill({ json: workflow }),
  )

  await page.goto('/knowledge/kb-1/studio')
  await expect(page.getByRole('heading', { name: /Knowledge Studio/ })).toBeVisible()
  await expect(page.getByTestId('rf__node-parse')).toBeVisible()
  await page.getByRole('button', { name: '运行与预览' }).click()
  await expect(page.getByLabel('测试文档选择文档')).toBeVisible()
  await expect(page.getByText('试运行')).toBeVisible()
})


test('Knowledge retrieval studio renders canvas and test tab', async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem('ai_power_refresh_token', 'e2e-refresh-token-0123456789'),
  )
  await mockBase(page)
  await page.route('**/api/knowledge-bases/kb-1', (route) =>
    route.fulfill({
      json: {
        id: 'kb-1',
        name: '技术知识库',
        description: '',
        created_at: '2026-11-23T00:00:00Z',
      },
    }),
  )
  await page.route('**/api/knowledge-bases/kb-1/retrieval/binding', (route) =>
    route.fulfill({
      json: {
        workflow_version_id: null,
        workflow_id: null,
        version: null,
        kind: 'knowledge_retrieval',
        name: '',
      },
    }),
  )
  const retrievalWorkflow = {
    id: 'wf-retrieval',
    name: 'Hybrid retrieval',
    description: '',
    kind: 'knowledge_retrieval',
    created_at: '2026-11-23T00:00:00Z',
    versions: [
      {
        id: 'wfr-1',
        version: 1,
        definition: {
          nodes: [
            { id: 'start', type: 'start', config: {}, ui: { x: 80, y: 120 } },
            {
              id: 'hybrid',
              type: 'hybrid_search',
              config: { top_k: 10, candidate_k: 20 },
              ui: { x: 280, y: 120 },
            },
            { id: 'out', type: 'output', config: {}, ui: { x: 500, y: 120 } },
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
  await page.route('**/api/workflows/catalog?kind=knowledge_retrieval', (route) =>
    route.fulfill({
      json: {
        kind: 'knowledge_retrieval',
        nodes: [
          catalogNode('start', '查询输入'),
          catalogNode('hybrid_search', '混合检索'),
          catalogNode('output', '输出'),
        ],
        limits: { max_nodes: 20, linear: true },
        variables: {},
        templates: [
          {
            name: '混合检索 + 重排',
            description: '',
            definition: retrievalWorkflow.versions[0].definition,
          },
        ],
      },
    }),
  )
  await page.route('**/api/workflows?kind=knowledge_retrieval', (route) =>
    route.fulfill({ json: [retrievalWorkflow] }),
  )
  await page.route('**/api/workflows/wf-retrieval', (route) =>
    route.fulfill({ json: retrievalWorkflow }),
  )

  await page.goto('/knowledge/kb-1/retrieval')
  await expect(page.getByRole('heading', { name: /检索 Studio/ })).toBeVisible()
  await expect(page.getByTestId('rf__node-hybrid')).toBeVisible()
  await page.getByRole('button', { name: '检索测试' }).click()
  await expect(page.getByPlaceholder('输入测试问题…')).toBeVisible()
  await expect(page.getByRole('button', { name: '运行检索' })).toBeVisible()
})
