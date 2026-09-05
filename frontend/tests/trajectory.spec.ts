import { expect, test } from '@playwright/test'

function jsonResponse(route: any, data: any) {
  return route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, data }),
  })
}

const trajectoryFixture = {
  session_id: 'session-1',
  turns: [
    {
      request_id: 'req-1',
      seq_range: [1, 12],
      started_at: new Date('2026-09-04T10:00:00Z').toISOString(),
      completed_at: new Date('2026-09-04T10:00:08Z').toISOString(),
      mode: 'agent',
      model_id: 'glm-test',
      provider: 'siliconflow',
      stopped_reason: 'completed',
      duration_ms: 8300,
      error: '',
      user: { content: '什么是 RAG？', images: 0, attachments: [], mentioned_items: 0, channel: 'web' },
      assistant: { content: 'RAG 是检索增强生成。' },
      retrievals: [
        {
          query: 'RAG 原理',
          kb_count: 1,
          top_k: 5,
          count: 3,
          intent: 'kb_search',
          degradations: [],
          refs: [{ chunk_id: 'c1', title: 'RAG 论文' }],
        },
      ],
      steps: [
        {
          iteration: 1,
          thought: '## 分析思路\n用户问的是 RAG 的定义，**必须先检索知识库**再回答。\n\n1. 调用 knowledge_search 检索\n2. 汇总片段后给出结论\n3. 补充与传统向量检索的差异',
          tools: [
            {
              tool_call_id: 'call-9',
              name: 'knowledge_search',
              argument_keys: ['query'],
              output_excerpt: '检索到 2 条相关内容',
              error: '',
              duration_ms: 95,
              started_at: new Date('2026-09-04T10:00:02Z').toISOString(),
              ended_at: new Date('2026-09-04T10:00:02.095Z').toISOString(),
              schema: { name: 'knowledge_search', description: 'Search the knowledge base', required: ['query'], properties: { query: 'string', top_k: 'integer' } },
            },
          ],
          llm: {
            duration_ms: 640,
            model: 'glm-test',
            usage: { prompt_tokens: 88, completion_tokens: 12 },
          },
          started_at: new Date('2026-09-04T10:00:01Z').toISOString(),
          ended_at: new Date('2026-09-04T10:00:01.640Z').toISOString(),
        },
        {
          iteration: 2,
          thought: '',
          tools: [
            {
              tool_call_id: 'call-10',
              name: 'grep_chunks',
              argument_keys: ['keywords'],
              output_excerpt: '命中 1 条',
              error: '',
              duration_ms: 40,
              started_at: new Date('2026-09-04T10:00:03Z').toISOString(),
              ended_at: new Date('2026-09-04T10:00:03.040Z').toISOString(),
            },
            {
              tool_call_id: 'call-11',
              name: 'wiki_read_page',
              argument_keys: ['slug'],
              output_excerpt: '# Singh 等 - 2023.pdf\n\n## 相关页面\n\n- [[entity/multi-domain-learning|Multi Domain Learning]]\n- [[entity/jasdeep-singh]]',
              error: '',
              duration_ms: 6,
              started_at: new Date('2026-09-04T10:00:03.1Z').toISOString(),
              ended_at: new Date('2026-09-04T10:00:03.106Z').toISOString(),
            },
          ],
          llm: {
            duration_ms: 900,
            model: 'glm-test',
            usage: { prompt_tokens: 1200, completion_tokens: 8, cached_tokens: 600, reasoning_tokens: 64 },
          },
          started_at: new Date('2026-09-04T10:00:02.5Z').toISOString(),
          ended_at: new Date('2026-09-04T10:00:03.4Z').toISOString(),
        },
      ],
      actors: [],
      request: { model: 'glm-test', temperature: 0.7, tools: ['knowledge_search', 'grep_chunks', 'wiki_search'], tool_schemas: { knowledge_search: { name: 'knowledge_search', description: 'Search the knowledge base', required: ['query'], properties: { query: 'string', top_k: 'integer' } } }, max_iterations: 5, history_messages: 6, agent_mode: 'multi_agent' },
      retries: [{ attempt: 1, reason: 'rate limit', wait_seconds: 2 }],
      compactions: [{ before_tokens: 90000, after_tokens: 52000, iteration: 1 }],
      usage: { prompt_tokens: 1288, completion_tokens: 20, llm_calls: 2, total_tokens: 1308, cached_tokens: 600 },
    },
    {
      request_id: 'req-2',
      seq_range: [13, 15],
      started_at: new Date('2026-09-04T10:01:00Z').toISOString(),
      completed_at: new Date('2026-09-04T10:01:03Z').toISOString(),
      mode: 'rag',
      model_id: 'glm-test',
      stopped_reason: 'error',
      duration_ms: 900,
      error: '生成失败',
      user: { content: '再来一个失败的提问', images: 0, attachments: [], mentioned_items: 0, channel: 'web' },
      assistant: { content: '' },
      retrievals: [],
      steps: [],
      actors: [],
      request: null,
      retries: [],
      compactions: [],
      usage: { prompt_tokens: 0, completion_tokens: 0, llm_calls: 0, total_tokens: 0 },
    },
  ],
}

async function mockChatApi(page: any, trajectoryPayload: any = trajectoryFixture, trajectoryStatus = 200) {
  await page.route('**/api/v1/**', (route: any) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/v1/sessions/session-1/trajectory') {
      if (trajectoryStatus !== 200) {
        return route.fulfill({
          status: trajectoryStatus,
          contentType: 'application/json',
          body: JSON.stringify({ success: false, message: 'session not found', error: { code: 'error', message: 'session not found' } }),
        })
      }
      return jsonResponse(route, trajectoryPayload)
    }
    if (path === '/api/v1/messages/session-1/load') {
      return jsonResponse(route, {
        items: [{ id: 'm1', role: 'user', content: '什么是 RAG？', is_completed: true }],
        has_more: false,
      })
    }
    if (path === '/api/v1/sessions') {
      return jsonResponse(route, { items: [{ id: 'session-1', title: '轨迹演示会话' }] })
    }
    if (path.startsWith('/api/v1/sessions/session-1')) {
      return jsonResponse(route, { id: 'session-1', title: '轨迹演示会话', last_request_state: {} })
    }
    return jsonResponse(route, { items: [] })
  })
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('personal_kb_token', 'playwright-token')
    localStorage.setItem('personal_kb_selected_tenant_id', 'tenant-1')
    localStorage.setItem('personal_kb_user', JSON.stringify({ username: 'researcher' }))
  })
})

test('trajectory ledger renders turns, tools and usage from the API', async ({ page }) => {
  await mockChatApi(page)
  await page.goto('/platform/chat/session-1')

  // 对话视图是默认视图
  await expect(page.getByTestId('view-conversation')).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByText('什么是 RAG？', { exact: true }).first()).toBeVisible()

  // 切换到轨迹视图
  await page.getByTestId('view-trajectory').click()
  const panel = page.getByTestId('trajectory-panel')
  await expect(panel).toBeVisible()

  // 轮次 1：完整台账
  const turn0 = page.getByTestId('trajectory-turn-0')
  await expect(turn0).toBeVisible()
  await expect(turn0.getByText('USER', { exact: true })).toBeVisible()
  await expect(turn0.getByText('什么是 RAG？', { exact: true })).toBeVisible()
  await expect(turn0.getByText('RETRIEVAL', { exact: true })).toBeVisible()
  await expect(turn0.getByText('引用：RAG 论文')).toBeVisible()
  await expect(turn0.getByTestId('tool-0-knowledge_search')).toContainText('knowledge_search')
  await expect(turn0.getByTestId('tool-0-knowledge_search')).toContainText('95ms')
  await expect(turn0.getByTestId('answer-0')).toContainText('RAG 是检索增强生成')
  await expect(turn0.getByTestId('turn-footer-0')).toContainText('正常完成')
  await expect(turn0.getByTestId('turn-footer-0')).toContainText('8.3s')
  await expect(turn0.getByTestId('turn-footer-0')).toContainText('1288+20 tokens（2 次调用）')

  // 请求上下文（REQUEST）：调用时的供应商/温度/工具清单/轮次上限
  await expect(turn0.getByTestId('request-0')).toContainText('允许工具 3 个')
  await expect(turn0.getByTestId('request-0')).toContainText('temperature 0.7')
  await expect(turn0.getByTestId('request-0')).toContainText('最多 5 轮')
  await expect(turn0.getByTestId('request-0')).toContainText('携带历史 6 条')

  // 步骤级 token 用量（含缓存/推理细分）
  await expect(turn0.getByTestId('thinking-0-1')).toContainText('88+12 tokens')
  await expect(turn0.getByTestId('thinking-0-2')).toContainText('缓存 600')
  await expect(turn0.getByTestId('thinking-0-2')).toContainText('推理 64')

  // Markdown 折叠预览：不露出 ## / ** 等标记符号
  const thoughtPreview = turn0.getByTestId('thought-preview-0-1')
  await expect(thoughtPreview).toContainText('分析思路')
  await expect(thoughtPreview).not.toContainText('##')
  await expect(thoughtPreview).not.toContainText('**')

  // 点击卡片展开：渲染为 Markdown（出现标题元素），不再显示纯文本预览
  await turn0.getByTestId('thinking-0-1').click()
  const expandedThought = turn0.getByTestId('thinking-0-1').getByTestId('expanded-content')
  await expect(expandedThought).toBeVisible()
  await expect(expandedThought.locator('h3')).toContainText('分析思路')
  await expect(expandedThought.locator('strong')).toContainText('必须先检索知识库')

  // 再次点击收起，回到纯文本预览
  await turn0.getByTestId('thinking-0-1').click()
  await expect(thoughtPreview).toBeVisible()

  // 压缩与重试记录
  await expect(turn0.getByTestId('compaction-0-0')).toContainText('90000 → 52000 tokens')
  await expect(turn0.getByTestId('turn-footer-0')).toContainText('LLM 重试 1 次')

  // 空思考迭代：显示占位卡片（无 ## 符号问题，也不在台账里隐形）
  await expect(turn0.getByTestId('thinking-0-2')).toContainText('1200+8 tokens')
  await expect(turn0.getByTestId('thought-preview-0-2')).toContainText('本轮无文本输出')

  // 工具输出预览剥离 Markdown/Wikilink 符号；展开后显示逐字原文
  const wikiTool = turn0.getByTestId('tool-0-wiki_read_page')
  // 调用时 Schema 快照与计时来源标注
  await expect(turn0.getByTestId('tool-0-knowledge_search')).toContainText('调用时 Schema')
  await page.getByTestId('schema-toggle-0-knowledge_search').click()
  await expect(page.getByTestId('schema-0-knowledge_search')).toContainText('Search the knowledge base')
  await expect(turn0.getByTestId('tool-0-knowledge_search')).toContainText('计时来源：服务端事件时间戳')
  const wikiPreview = wikiTool.getByTestId('tool-output-0-wiki_read_page')
  await expect(wikiPreview).toContainText('相关页面')
  await expect(wikiPreview).toContainText('Multi Domain Learning')
  await expect(wikiPreview).not.toContainText('##')
  await expect(wikiPreview).not.toContainText('[[')
  await wikiTool.click()
  const wikiExpanded = wikiTool.getByTestId('expanded-content')
  await expect(wikiExpanded).toBeVisible()
  await expect(wikiExpanded).toContainText('## 相关页面')
  await expect(wikiExpanded).toContainText('[[entity/jasdeep-singh]]')

  // 时间轴条：真实事件时间戳的思考/工具 span（思考×2 + 工具×3）
  // wiki_read_page 仅 6ms，占轮次时长 0.075% < 0.5% 最小可见宽度，被有意丢弃
  await expect(turn0.getByTestId('timeline-0')).toBeVisible()
  await expect(turn0.getByTestId('timeline-0').locator('.timeline-seg')).toHaveCount(4)

  // 点击展开：思考文本从 3 行截断切换为完整显示
  const thoughtText = turn0.getByTestId('thinking-0-1').locator('p.record-text')
  await expect(thoughtText).toHaveClass(/clamp/)
  await thoughtText.click()
  await expect(turn0.getByTestId('thinking-0-1').getByTestId('expanded-content')).toBeVisible()

  // 类型过滤：只看工具
  await page.getByTestId('filter-tool').click()
  await expect(turn0.getByTestId('tool-0-knowledge_search')).toBeVisible()
  await expect(turn0.getByTestId('retrieval-0-0')).toHaveCount(0)
  await expect(turn0.getByTestId('thinking-0-1')).toHaveCount(0)
  await expect(turn0.getByTestId('answer-0')).toHaveCount(0)
  await page.getByTestId('filter-all').click()
  await expect(turn0.getByTestId('answer-0')).toBeVisible()

  // 轮次 2：失败轮次的可见性
  const turn1 = page.getByTestId('trajectory-turn-1')
  await expect(turn1.getByTestId('turn-footer-1')).toContainText('出错')
  await expect(turn1.getByTestId('answer-1')).toContainText('生成失败')

  // 切回对话视图，时间轴仍然可见
  await page.getByTestId('view-conversation').click()
  await expect(page.getByText('什么是 RAG？', { exact: true }).first()).toBeVisible()
})

test('empty trajectory shows guidance copy', async ({ page }) => {
  await mockChatApi(page, { session_id: 'session-1', turns: [] })
  await page.goto('/platform/chat/session-1')
  await page.getByTestId('view-trajectory').click()
  await expect(page.getByTestId('trajectory-empty')).toContainText('还没有轨迹记录')
})

test('trajectory 404 surfaces an error note instead of crashing', async ({ page }) => {
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await mockChatApi(page, null, 404)
  await page.goto('/platform/chat/session-1')
  await page.getByTestId('view-trajectory').click()
  await expect(page.getByTestId('trajectory-error')).toContainText('会话不存在或不可见')
  expect(pageErrors).toEqual([])
})
