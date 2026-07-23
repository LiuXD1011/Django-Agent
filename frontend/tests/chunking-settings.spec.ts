import { expect, test } from '@playwright/test'

const headingConfig = {
  strategy: 'heading',
  chunk_size: 512,
  chunk_overlap: 0,
  enable_parent_child: true,
  parent_chunk_size: 2048,
  child_chunk_size: 384,
  child_chunk_overlap: 0,
  token_limit: 0,
  semantic_window_size: 3,
  semantic_breakpoint_percentile: 90,
}

const semanticConfig = {
  ...headingConfig,
  strategy: 'semantic',
  chunk_size: 640,
  semantic_window_size: 5,
  semantic_breakpoint_percentile: 92.5,
}

test('configures adaptive chunking and distinguishes requested from effective state', async ({ page }) => {
  let createPayload: Record<string, any> | undefined
  const kb = {
    id: 'kb-1',
    name: 'Research archive',
    description: 'Policy corpus',
    type: 'document',
    chunking_config: semanticConfig,
    needs_reindex: true,
    last_effective_strategy: 'heading',
    indexing_strategy: { vector_enabled: true, keyword_enabled: true, wiki_enabled: false, graph_enabled: false },
    capabilities: { vector: true, keyword: true, wiki: false, graph: false },
    knowledge_count: 1,
    document_count: 1,
    chunk_count: 4,
    processing_count: 0,
  }

  await page.addInitScript(() => {
    localStorage.setItem('personal_kb_token', 'playwright-token')
    localStorage.setItem('personal_kb_selected_tenant_id', 'tenant-1')
    localStorage.setItem('personal_kb_user', JSON.stringify({ username: 'researcher' }))
  })
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const json = (data: any, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data }),
    })

    if (path === '/api/v1/knowledge-bases' && request.method() === 'POST') {
      createPayload = request.postDataJSON()
      return json({ ...kb, id: 'kb-created', name: createPayload?.name, chunking_config: createPayload?.chunking_config }, 201)
    }
    if (path === '/api/v1/knowledge-bases') return json({ items: [kb], knowledge_bases: [kb], total: 1 })
    if (path === '/api/v1/knowledge-bases/kb-1') return json(kb)
    if (path === '/api/v1/knowledge-bases/kb-1/tags') return json({ items: [] })
    if (path === '/api/v1/knowledge-bases/kb-1/knowledge') {
      return json({ items: [], status_counts: {}, tag_counts: {}, processing_records: [] })
    }
    return json({})
  })

  await page.goto('/platform/knowledge-bases')
  await page.waitForLoadState('networkidle')
  await page.getByRole('button', { name: '新建知识库', exact: true }).last().click()
  const createDialog = page.locator('.t-dialog:visible')
  await createDialog.getByPlaceholder('例如：合同资料库').fill('Semantic corpus')
  await createDialog.getByLabel('分块策略').selectOption('semantic')
  await expect(createDialog.getByText('Experimental', { exact: true })).toBeVisible()
  await createDialog.getByLabel('分块长度').fill('640')
  await createDialog.getByLabel('重叠字符').fill('0')
  await createDialog.getByLabel('子块重叠').fill('0')
  await createDialog.getByLabel('语义窗口').fill('5')
  await createDialog.getByLabel('语义断点百分位').fill('92.5')
  await createDialog.getByRole('button', { name: '创建', exact: true }).click()
  await expect.poll(() => createPayload).toBeTruthy()
  expect(createPayload?.chunking_config).toEqual(semanticConfig)
  expect(createPayload?.chunking_config.chunk_overlap).toBe(0)

  await page.goto('/platform/knowledge-bases/kb-1?tab=settings')
  await page.waitForLoadState('networkidle')
  const settingsDialog = page.locator('.t-dialog:visible')
  await expect(settingsDialog.getByText('需要重建索引', { exact: true })).toBeVisible()
  await expect(settingsDialog.getByText('当前生效：Heading', { exact: true })).toBeVisible()
  await expect(settingsDialog.getByText('Experimental', { exact: true })).toBeVisible()
  await expect(settingsDialog.getByLabel('重叠字符')).toHaveValue('0')

  const viewport = page.viewportSize()
  const bounds = await settingsDialog.boundingBox()
  expect(viewport).not.toBeNull()
  expect(bounds).not.toBeNull()
  expect(bounds!.x).toBeGreaterThanOrEqual(0)
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport!.width)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})
