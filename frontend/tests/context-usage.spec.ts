import { expect, test } from '@playwright/test'

function jsonResponse(route: any, data: any) {
  return route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, data }),
  })
}

const modelsFixture = {
  items: [
    { id: 'env-aliyun-bailian-knowledgeqa-qwen-test', display_name: 'Qwen 测试模型', type: 'chat', source: 'aliyun-bailian', context_window: 128000 },
    { id: 'chat-big-model', display_name: '长上下文模型', type: 'chat', source: 'openai', context_window: 1000000 },
  ],
}

const usageFixture = {
  session_id: 'session-1',
  model_id: 'env-aliyun-bailian-knowledgeqa-qwen-test',
  context_window: 128000,
  reserve_tokens: 8000,
  compact_threshold: 120000,
  used_tokens: 35200,
  percent: 28,
}

async function mockApis(page: any, usagePayload: any = usageFixture) {
  await page.route('**/api/v1/**', (route: any) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/v1/models') return jsonResponse(route, { items: modelsFixture.items, models: modelsFixture.items })
    if (path === '/api/v1/sessions/session-1/context-usage') return jsonResponse(route, usagePayload)
    if (path === '/api/v1/messages/session-1/load') return jsonResponse(route, { items: [], has_more: false })
    if (path === '/api/v1/sessions') return jsonResponse(route, { items: [{ id: 'session-1', title: '上下文占用演示会话' }] })
    return jsonResponse(route, { id: 'session-1', title: '上下文占用演示会话', last_request_state: {} })
  })
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('personal_kb_token', 'playwright-token')
    localStorage.setItem('personal_kb_selected_tenant_id', 'tenant-1')
    localStorage.setItem('personal_kb_user', JSON.stringify({ username: 'researcher' }))
  })
})

test('context button shows window size and opens usage popover', async ({ page }) => {
  await mockApis(page)
  await page.goto('/platform/chat/session-1')

  // 按钮显示当前所选模型的上下文窗口
  const btn = page.getByTestId('ctx-usage-btn')
  await expect(btn).toBeVisible()
  await expect(page.getByTestId('ctx-window-label')).toContainText('128K')

  // 点击展开占用弹窗：进度条 + 窗口/已用/阈值三行
  await btn.click()
  const panel = page.getByTestId('ctx-usage-panel')
  await expect(panel).toBeVisible()
  await expect(panel).toContainText('上下文窗口')
  await expect(panel).toContainText('128,000')
  await expect(page.getByTestId('ctx-used')).toContainText('35,200')
  await expect(panel).toContainText('28%')
  await expect(panel).toContainText('自动压缩历史')

  // 切换模型后按钮标签跟随变化
  await page.getByTestId('ctx-usage-btn').click()
  await page.locator('.model-selector-trigger').click()
  await page.getByText('长上下文模型', { exact: true }).click()
  await expect(page.getByTestId('ctx-window-label')).toContainText('1M')
})

test('context popover shows guidance for sessions without history', async ({ page }) => {
  await mockApis(page, { ...usageFixture, used_tokens: 0, percent: 0 })
  await page.goto('/platform/chat/session-1')
  await page.getByTestId('ctx-usage-btn').click()
  await expect(page.getByTestId('ctx-usage-panel')).toBeVisible()
})
