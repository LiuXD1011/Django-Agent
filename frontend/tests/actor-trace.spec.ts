import { expect, test } from '@playwright/test'

test('renders and independently collapses sub-agent markdown output', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('personal_kb_token', 'playwright-token')
    localStorage.setItem('personal_kb_selected_tenant_id', 'tenant-1')
    localStorage.setItem('personal_kb_user', JSON.stringify({ username: 'researcher' }))
  })

  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const response = (data: any) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data }),
    })
    if (path === '/api/v1/messages/session-1/load') {
      return response({
        items: [{
          id: 'message-1',
          session_id: 'session-1',
          role: 'assistant',
          content: '最终答案',
          is_completed: true,
          actor_traces: [
            {
              actor_id: 'wiki-1',
              agent_type: 'wiki_researcher',
              name: 'Wiki 研究子 Agent',
              status: 'idle',
              last_outcome: 'success',
              output: '## 知识库概览\n\n| 项目 | 数量 |\n| --- | --- |\n| 页面 | 22 |\n\n```text\ncompleted\n```',
            },
            {
              actor_id: 'doc-1',
              agent_type: 'doc_retriever',
              name: '文档检索子 Agent',
              status: 'idle',
              last_outcome: 'success',
              output: '## 文档证据\n\n- 证据 A',
            },
          ],
        }],
        has_more: false,
      })
    }
    if (path === '/api/v1/sessions/session-1') return response({ id: 'session-1', last_request_state: {} })
    if (path === '/api/v1/sessions') return response({ items: [{ id: 'session-1', title: '研究会话' }] })
    return response({ items: [] })
  })

  await page.goto('/platform/chat/session-1')
  await expect(page.getByRole('button', { name: /Wiki 研究子 Agent/ })).toBeVisible()
  const wikiButton = page.getByRole('button', { name: /Wiki 研究子 Agent/ })
  const docButton = page.getByRole('button', { name: /文档检索子 Agent/ })
  const wikiDetails = page.locator('#actor-detail-wiki-1')
  const docDetails = page.locator('#actor-detail-doc-1')

  await wikiButton.click()
  await expect(wikiDetails.locator('h3')).toHaveText('知识库概览')
  await expect(wikiDetails.locator('table')).toBeVisible()
  await expect(wikiDetails.locator('pre')).toContainText('completed')
  await wikiButton.click()
  await expect(wikiDetails).toBeHidden()
  await expect(docDetails).toBeHidden()
  await docButton.click()
  await expect(docDetails).toBeVisible()
  await expect(wikiDetails).toBeHidden()
})

test('keeps streamed sub-agent markdown after completion', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('personal_kb_token', 'playwright-token')
    localStorage.setItem('personal_kb_selected_tenant_id', 'tenant-1')
    localStorage.setItem('personal_kb_user', JSON.stringify({ username: 'researcher' }))
  })

  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/v1/agent-chat/session-1') {
      const messages = [
        ['message_start', { id: 'assistant-1', request_id: 'request-1' }],
        ['message', { response_type: 'agent_query', assistant_message_id: 'assistant-1', session_id: 'session-1' }],
        ['message', { response_type: 'actor_started', assistant_message_id: 'assistant-1', actor_id: 'wiki-stream', agent_type: 'wiki_researcher', name: '流式 Wiki 子 Agent', status: 'running' }],
        ['message', { response_type: 'actor_update', assistant_message_id: 'assistant-1', actor_id: 'wiki-stream', content: '## 流式研究结果\n\n| 状态 | 数量 |\n| --- | --- |\n| 完成 | 22 |' }],
        ['message', { response_type: 'actor_completed', assistant_message_id: 'assistant-1', actor_id: 'wiki-stream', status: 'idle', last_outcome: 'success' }],
        ['message', { response_type: 'answer', assistant_message_id: 'assistant-1', content: '最终答案', done: true }],
        ['message', { response_type: 'complete', assistant_message_id: 'assistant-1', done: true }],
        ['done', { message_id: 'assistant-1' }],
      ]
      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: messages.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join(''),
      })
    }
    const data = path === '/api/v1/messages/session-1/load'
      ? { items: [], has_more: false }
      : path === '/api/v1/sessions/session-1'
        ? { id: 'session-1', last_request_state: {} }
        : path === '/api/v1/sessions'
          ? { items: [{ id: 'session-1', title: '研究会话' }] }
          : { items: [] }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data }),
    })
  })

  await page.goto('/platform/chat/session-1')
  await page.getByPlaceholder('直接问模型提问').fill('开始研究')
  await page.getByPlaceholder('直接问模型提问').press('Enter')

  const actorButton = page.getByRole('button', { name: /流式 Wiki 子 Agent/ })
  await expect(actorButton).toBeVisible()
  await expect(page.getByText('最终答案', { exact: true })).toBeVisible()
  await actorButton.click()
  const details = page.locator('#actor-detail-wiki-stream')
  await expect(details.locator('h3')).toHaveText('流式研究结果')
  await expect(details.locator('table')).toContainText('完成')
})
