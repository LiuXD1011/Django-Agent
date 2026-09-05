import { expect, test } from '@playwright/test'

function jsonResponse(route: any, data: any) {
  return route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, data }),
  })
}

const kbs = [
  { id: 'kb-1', name: '知识库A', document_count: 3 },
  { id: 'kb-2', name: '知识库B', document_count: 6 },
]

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('personal_kb_token', 'playwright-token')
    localStorage.setItem('personal_kb_selected_tenant_id', 'tenant-1')
    localStorage.setItem('personal_kb_user', JSON.stringify({ username: 'researcher' }))
  })
  await page.route('**/api/v1/**', (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/v1/messages/session-1/load') {
      return jsonResponse(route, { items: [], has_more: false })
    }
    if (path === '/api/v1/sessions/session-1') {
      return jsonResponse(route, {
        id: 'session-1',
        last_request_state: {
          // 故意带一个已删除知识库的幽灵 id
          knowledge_base_ids: ['kb-1', 'kb-ghost'],
          model_id: '',
          mcp_service_ids: [],
        },
      })
    }
    if (path === '/api/v1/sessions') return jsonResponse(route, { items: [{ id: 'session-1', title: '选择语义会话' }] })
    if (path === '/api/v1/knowledge-bases') return jsonResponse(route, { items: kbs })
    if (path.startsWith('/api/v1/sessions/session-1')) return jsonResponse(route, { id: 'session-1', last_request_state: {} })
    return jsonResponse(route, { items: [] })
  })
})

test('ghost KB ids are excluded from counter, chips and payload', async ({ page }) => {
  await page.goto('/platform/chat/session-1')
  await page.waitForTimeout(300)

  // 打开知识库弹层
  await page.locator('button[title="知识库"]').click()
  const popover = page.locator('.chat-popover')
  await expect(popover).toBeVisible()

  // 幽灵 id 不计入"已选"，也不渲染 chip
  await expect(popover.getByText('1 已选')).toBeVisible()
  await expect(popover.locator('.chat-option.selected')).toHaveCount(1)
  await expect(popover.locator('.chat-option.selected')).toContainText('知识库A')

  // 输入区 chip 只有一个
  await expect(page.locator('.mention-chip--kb')).toHaveCount(1)

  // 发送时载荷只含真实存在的知识库 id
  let sentBody: any = null
  await page.route('**/api/v1/agent-chat/session-1', async (route) => {
    sentBody = route.request().postDataJSON()
    return route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'event: done\ndata: {}\n\n' })
  })
  await page.locator('.rich-input-container textarea').fill('测试选择')
  await page.locator('.send-btn').click()
  await expect.poll(() => sentBody).toBeTruthy()
  expect(sentBody.knowledge_base_ids).toEqual(['kb-1'])
})

test('empty selection shows the search-all hint', async ({ page }) => {
  await page.route('**/api/v1/sessions/session-1', (route) =>
    jsonResponse(route, { id: 'session-1', last_request_state: { knowledge_base_ids: [] } }))
  await page.goto('/platform/chat/session-1')
  await page.waitForTimeout(300)

  await page.locator('button[title="知识库"]').click()
  const popover = page.locator('.chat-popover')
  await expect(popover).toBeVisible()
  await expect(popover.getByText('0 已选')).toBeVisible()
  await expect(page.getByTestId('kb-empty-hint')).toContainText('将检索全部知识库')
})
