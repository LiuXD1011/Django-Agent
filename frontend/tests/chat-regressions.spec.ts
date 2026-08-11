import { expect, test } from '@playwright/test'

function jsonResponse(route: any, data: any) {
  return route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, data }),
  })
}

test('starts with malformed persisted auth JSON', async ({ page }) => {
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await page.addInitScript(() => {
    localStorage.setItem('personal_kb_token', 'playwright-token')
    localStorage.setItem('personal_kb_user', '{malformed')
    localStorage.setItem('personal_kb_tenant', '{malformed')
  })
  await page.route('**/api/v1/**', (route) => jsonResponse(route, { items: [], knowledge_bases: [] }))

  await page.goto('/platform/knowledge-bases')
  await expect(page).toHaveURL(/\/platform\/knowledge-bases$/)
  await expect(page.locator('body')).toBeVisible()
  expect(await page.evaluate(() => localStorage.getItem('personal_kb_user'))).toBeNull()
  expect(await page.evaluate(() => localStorage.getItem('personal_kb_tenant'))).toBeNull()
  expect(pageErrors).toEqual([])
})

test('ignores a stale message response after switching sessions', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('personal_kb_token', 'playwright-token')
    localStorage.setItem('personal_kb_selected_tenant_id', 'tenant-1')
    localStorage.setItem('personal_kb_user', JSON.stringify({ username: 'researcher' }))
  })
  let releaseFirstResponse: (() => void) | undefined
  const firstResponseBlocked = new Promise<void>((resolve) => { releaseFirstResponse = resolve })
  let markFirstRequested: (() => void) | undefined
  const firstRequested = new Promise<void>((resolve) => { markFirstRequested = resolve })

  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/v1/messages/session-1/load') {
      markFirstRequested?.()
      await firstResponseBlocked
      return jsonResponse(route, {
        items: [{ id: 'old-answer', role: 'assistant', content: 'session one stale answer', is_completed: true }],
        has_more: false,
      })
    }
    if (path === '/api/v1/messages/session-2/load') {
      return jsonResponse(route, {
        items: [{ id: 'new-answer', role: 'assistant', content: 'session two current answer', is_completed: true }],
        has_more: false,
      })
    }
    if (path.startsWith('/api/v1/sessions/session-')) {
      return jsonResponse(route, { id: path.split('/').pop(), last_request_state: {} })
    }
    if (path === '/api/v1/sessions') {
      return jsonResponse(route, { items: [
        { id: 'session-1', title: 'First session' },
        { id: 'session-2', title: 'Second session' },
      ] })
    }
    return jsonResponse(route, { items: [] })
  })

  await page.goto('/platform/chat/session-1')
  await firstRequested
  await page.evaluate(() => {
    history.pushState({}, '', '/platform/chat/session-2')
    window.dispatchEvent(new PopStateEvent('popstate'))
  })
  await expect(page.getByText('session two current answer', { exact: true })).toBeVisible()
  releaseFirstResponse?.()
  await page.waitForTimeout(250)
  await expect(page.getByText('session one stale answer', { exact: true })).toHaveCount(0)
  await expect(page.getByText('session two current answer', { exact: true })).toBeVisible()
})
