import { expect, test, type Locator, type Page } from '@playwright/test'

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

const semanticProcessConfig = {
  chunking_config: semanticConfig,
  graph_enabled: false,
  extract_config: { enabled: false },
}

type DialogMetric = {
  name: string
  viewport: { width: number; height: number }
  dialog: { x: number; y: number; width: number; height: number }
  bodyClientHeight: number
  bodyScrollHeight: number
  bodyScrollRange: number
  bodyOverflowY: string
  footerGap: number
  footerShiftAfterScroll: number
  pageOverflowX: number
  overflowingElements: string[]
}

async function assertDialogLayout(page: Page, dialog: Locator, name: string): Promise<DialogMetric> {
  await expect(dialog).toBeVisible()
  await page.waitForTimeout(350)
  const metric = await dialog.evaluate((node, dialogName) => {
    const element = node as HTMLElement
    const body = element.querySelector<HTMLElement>('.t-dialog__body')!
    const footer = element.querySelector<HTMLElement>('.t-dialog__footer')!
    const viewport = { width: window.innerWidth, height: window.innerHeight }
    const dialogRect = element.getBoundingClientRect()
    const bodyRect = body.getBoundingClientRect()
    const footerBefore = footer.getBoundingClientRect()
    const overflowingElements = [...element.querySelectorAll<HTMLElement>('*')]
      .filter((child) => {
        const rect = child.getBoundingClientRect()
        if (rect.width === 0 || rect.height === 0) return false
        const style = getComputedStyle(child)
        const spillsViewport = rect.left < -1 || rect.right > viewport.width + 1
        const spillsContent = child.scrollWidth > child.clientWidth + 1 && !['auto', 'scroll', 'hidden', 'clip'].includes(style.overflowX)
        return spillsViewport || spillsContent
      })
      .map((child) => `${child.tagName.toLowerCase()}.${child.className}`)
    body.scrollTop = body.scrollHeight
    const footerAfter = footer.getBoundingClientRect()
    return {
      name: dialogName,
      viewport,
      dialog: { x: dialogRect.x, y: dialogRect.y, width: dialogRect.width, height: dialogRect.height },
      bodyClientHeight: body.clientHeight,
      bodyScrollHeight: body.scrollHeight,
      bodyScrollRange: body.scrollHeight - body.clientHeight,
      bodyOverflowY: getComputedStyle(body).overflowY,
      footerGap: footerBefore.top - bodyRect.bottom,
      footerShiftAfterScroll: footerAfter.top - footerBefore.top,
      pageOverflowX: document.documentElement.scrollWidth - window.innerWidth,
      overflowingElements,
    }
  }, name)

  expect(metric.dialog.x, `${name} left edge`).toBeGreaterThanOrEqual(0)
  expect(metric.dialog.y, `${name} top edge`).toBeGreaterThanOrEqual(0)
  expect(metric.dialog.x + metric.dialog.width, `${name} right edge`).toBeLessThanOrEqual(metric.viewport.width)
  expect(metric.dialog.y + metric.dialog.height, `${name} bottom edge`).toBeLessThanOrEqual(metric.viewport.height)
  expect(metric.bodyOverflowY).toMatch(/auto|scroll/)
  expect(metric.footerGap, `${name} body/footer separation`).toBeGreaterThanOrEqual(-1)
  expect(Math.abs(metric.footerShiftAfterScroll), `${name} fixed footer while body scrolls`).toBeLessThanOrEqual(1)
  expect(metric.pageOverflowX, `${name} page horizontal overflow`).toBeLessThanOrEqual(0)
  expect(metric.overflowingElements, `${name} element horizontal overflow`).toEqual([])
  if (metric.viewport.width === 390) {
    expect(metric.bodyScrollRange, `${name} mobile body scroll range`).toBeGreaterThan(0)
  }
  return metric
}

function multipartJson(body: string, field: string): Record<string, any> {
  const marker = `name="${field}"`
  const start = body.indexOf(marker)
  expect(start, `${field} multipart field`).toBeGreaterThanOrEqual(0)
  const valueStart = body.indexOf('\r\n\r\n', start) + 4
  const valueEnd = body.indexOf('\r\n--', valueStart)
  return JSON.parse(body.slice(valueStart, valueEnd))
}

test('configures adaptive chunking and distinguishes requested from effective state', async ({ page }, testInfo) => {
  let createPayload: Record<string, any> | undefined
  let settingsPayload: Record<string, any> | undefined
  let uploadPayload: Record<string, any> | undefined
  let reparsePayload: Record<string, any> | undefined
  const dialogMetrics: DialogMetric[] = []
  const document = {
    id: 'doc-1',
    title: 'Policy source.txt',
    source: 'Policy source.txt',
    file_name: 'Policy source.txt',
    file_type: 'txt',
    file_size: 128,
    parse_status: 'completed',
    summary_status: 'completed',
    updated_at: '2026-07-23T12:00:00Z',
  }
  const kb: Record<string, any> = {
    id: 'kb-1',
    name: 'Research archive',
    description: 'Policy corpus',
    type: 'document',
    chunking_config: { ...headingConfig },
    needs_reindex: false,
    last_effective_strategy: 'heading',
    indexing_strategy: { vector_enabled: true, keyword_enabled: true, wiki_enabled: false, graph_enabled: false },
    extract_config: { enabled: false },
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
    if (path === '/api/v1/knowledge-bases/kb-1' && request.method() === 'PUT') {
      settingsPayload = request.postDataJSON()
      kb.chunking_config = { ...settingsPayload!.chunking_config }
      kb.needs_reindex = true
      kb.last_effective_strategy = 'heading'
      return json(kb)
    }
    if (path === '/api/v1/knowledge-bases/kb-1/knowledge/file' && request.method() === 'POST') {
      uploadPayload = multipartJson(request.postData() || '', 'process_config')
      kb.needs_reindex = true
      document.parse_status = 'pending'
      return json({ knowledge: document, task_id: 'upload-task' }, 201)
    }
    if (path === '/api/v1/knowledge/doc-1/reparse' && request.method() === 'POST') {
      reparsePayload = request.postDataJSON()
      kb.needs_reindex = true
      document.parse_status = 'pending'
      return json({ knowledge: document, task_id: 'reparse-task' })
    }
    if (path === '/api/v1/knowledge-bases') return json({ items: [kb], knowledge_bases: [kb], total: 1 })
    if (path === '/api/v1/knowledge-bases/kb-1') return json(kb)
    if (path === '/api/v1/knowledge-bases/kb-1/tags') return json({ items: [] })
    if (path === '/api/v1/knowledge-bases/kb-1/knowledge') {
      return json({ items: [document], status_counts: { [document.parse_status]: 1 }, tag_counts: {}, processing_records: [] })
    }
    return json({})
  })

  await page.goto('/platform/knowledge-bases')
  await page.waitForLoadState('networkidle')
  await page.getByRole('button', { name: '新建知识库', exact: true }).last().click()
  const createDialog = page.locator('.t-dialog:visible')
  dialogMetrics.push(await assertDialogLayout(page, createDialog, 'create'))
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

  await page.goto('/platform/knowledge-bases/kb-1')
  await page.waitForLoadState('networkidle')
  await page.getByRole('button', { name: '知识库设置', exact: true }).click()
  const settingsDialog = page.locator('.t-dialog:visible')
  dialogMetrics.push(await assertDialogLayout(page, settingsDialog, 'settings'))
  await settingsDialog.getByLabel('分块策略').selectOption('semantic')
  await settingsDialog.getByLabel('分块长度').fill('640')
  await settingsDialog.getByLabel('语义窗口').fill('5')
  await settingsDialog.getByLabel('语义断点百分位').fill('92.5')
  await settingsDialog.getByRole('button', { name: '保存', exact: true }).click()
  await expect.poll(() => settingsPayload).toBeTruthy()
  expect(settingsPayload?.chunking_config).toEqual(semanticConfig)
  await expect(settingsDialog.getByText('需要重建索引', { exact: true })).toBeVisible()
  await expect(settingsDialog.getByText('当前生效：Heading', { exact: true })).toBeVisible()
  await expect(settingsDialog.getByText('Experimental', { exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(settingsDialog).toBeHidden()

  await page.locator('label.upload-button input[type="file"]').setInputFiles({
    name: 'new-policy.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('policy text'),
  })
  const uploadDialog = page.locator('.t-dialog:visible')
  dialogMetrics.push(await assertDialogLayout(page, uploadDialog, 'upload'))
  await expect(uploadDialog.getByText('Experimental', { exact: true })).toBeVisible()
  await uploadDialog.getByRole('button', { name: '开始解析', exact: true }).click()
  await expect.poll(() => uploadPayload).toBeTruthy()
  await expect(uploadDialog).toBeHidden()
  expect(uploadPayload).toEqual(semanticProcessConfig)

  const isMobile = page.viewportSize()?.width === 390
  const reparseButton = isMobile
    ? page.locator('.document-card-actions').getByRole('button', { name: '重解析', exact: true })
    : page.locator('.document-table').getByRole('button', { name: '重解析', exact: true })
  if (isMobile) {
    await page.locator('.kb-detail-page').evaluate((element) => element.scrollTo({ top: element.scrollHeight }))
    const actionBounds = await reparseButton.boundingBox()
    const navBounds = await page.locator('.mobile-tab-bar').boundingBox()
    expect(actionBounds).not.toBeNull()
    expect(navBounds).not.toBeNull()
    expect(actionBounds!.y + actionBounds!.height, 'mobile reparse action above fixed navigation').toBeLessThanOrEqual(navBounds!.y)
  }
  await reparseButton.click()
  await expect.poll(() => reparsePayload).toBeTruthy()
  expect(reparsePayload).toEqual({ process_config: semanticProcessConfig })

  await page.getByRole('button', { name: '知识库设置', exact: true }).click()
  await expect(page.locator('.t-dialog:visible').getByText('需要重建索引', { exact: true })).toBeVisible()
  await page.keyboard.press('Escape')

  kb.needs_reindex = false
  kb.last_effective_strategy = 'semantic'
  document.parse_status = 'completed'
  await page.reload()
  await page.waitForLoadState('networkidle')
  await page.getByRole('button', { name: '知识库设置', exact: true }).click()
  const completedDialog = page.locator('.t-dialog:visible')
  await expect(completedDialog.getByText('需要重建索引', { exact: true })).toHaveCount(0)
  await expect(completedDialog.getByText('当前生效：Semantic (Experimental)', { exact: true })).toBeVisible()
  await expect(completedDialog.getByText('Experimental', { exact: true })).toBeVisible()

  expect(createPayload?.chunking_config.chunk_overlap).toBe(0)
  expect(settingsPayload?.chunking_config.child_chunk_overlap).toBe(0)
  expect(uploadPayload?.chunking_config.token_limit).toBe(0)
  expect(reparsePayload?.process_config.chunking_config.semantic_breakpoint_percentile).toBe(92.5)
  console.log(`TASK8_DIALOG_METRICS ${testInfo.project.name} ${JSON.stringify(dialogMetrics)}`)
})
