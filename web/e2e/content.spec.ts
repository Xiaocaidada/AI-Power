import { expect, test } from '@playwright/test'

const feed = {
  banners: [
    {
      id: 'banner-1',
      kind: 'banner',
      title: 'Welcome banner',
      subtitle: 'Try the new portal',
      body: '',
      image_url: '',
      link_url: '/models',
      link_label: 'Browse models',
      sort_order: 100,
      enabled: true,
      starts_at: null,
      ends_at: null,
      created_at: '2026-11-23T00:00:00Z',
      updated_at: '2026-11-23T00:00:00Z',
    },
  ],
  featured: [],
  activities: [],
  announcements: [
    {
      id: 'ann-1',
      title: 'Platform update',
      summary: 'New features are live',
      body: 'Detailed announcement body.',
      cover_url: '',
      category: 'update',
      pinned: true,
      status: 'published',
      published_at: '2026-11-23T00:00:00Z',
      expires_at: null,
      created_at: '2026-11-23T00:00:00Z',
      updated_at: '2026-11-23T00:00:00Z',
    },
  ],
}

test('public home shows placements and announcements', async ({ page }) => {
  await page.route(/\/api\/home$/, (route) => route.fulfill({ json: feed }))
  await page.route(/\/api\/market\/models(\?.*)?$/, (route) =>
    route.fulfill({ json: [] }),
  )
  await page.route(/\/api\/announcements(\?.*)?$/, (route) =>
    route.fulfill({ json: feed.announcements }),
  )
  await page.route(/\/api\/announcements\/ann-1$/, (route) =>
    route.fulfill({ json: feed.announcements[0] }),
  )

  await page.goto('/')
  await expect(page.getByText('Welcome banner')).toBeVisible()
  await expect(page.getByText('Platform update').first()).toBeVisible()

  await page.getByRole('link', { name: '查看全部公告' }).click()
  await expect(page.getByRole('heading', { name: '公告中心' })).toBeVisible()
  await expect(page.getByText('Platform update').first()).toBeVisible()

  await page.getByText('Platform update').first().click()
  await expect(page.getByText('Detailed announcement body.')).toBeVisible()
})