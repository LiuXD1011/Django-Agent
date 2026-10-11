import { expect, test } from '@playwright/test'

async function setup(page: import('@playwright/test').Page, model?: Record<string, unknown>) {
  const writes: any[] = []
  await page.addInitScript(() => {
    localStorage.setItem('personal_kb_token', 'fixture-token')
    localStorage.setItem('personal_kb_selected_tenant_id', 'tenant-1')
    localStorage.setItem('personal_kb_user', JSON.stringify({ username: 'owner', is_system_admin: true }))
  })
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const respond = (data: unknown) => route.fulfill({ json: { success: true, data } })
    if (path.endsWith('/models') && request.method() === 'POST') {
      writes.push(request.postDataJSON())
      return respond({ id: 'created-model', ...writes.at(-1) })
    }
    if (path.endsWith('/models')) return respond({ items: model ? [model] : [], total: model ? 1 : 0 })
    if (path.endsWith('/models/existing-model') && request.method() === 'PUT') {
      writes.push(request.postDataJSON())
      return respond(model)
    }
    if (path.endsWith('/auth/me')) return respond({ user: { username: 'owner', is_system_admin: true } })
    return respond({ items: [] })
  })
  await page.goto('/platform/settings?section=models')
  return writes
}

async function choose(page: import('@playwright/test').Page, select: import('@playwright/test').Locator, label: string) {
  await select.click()
  await page.getByRole('listitem', { name: label, exact: true }).click()
}

test('choose a provider and only enter its key to save the complete configuration', async ({ page }) => {
  const writes = await setup(page)
  await page.getByRole('button', { name: '+ 添加模型', exact: true }).click()
  const dialog = page.locator('.t-dialog:visible')
  await choose(page, dialog.getByTestId('model-provider-select'), 'DeepSeek')
  await dialog.locator('input[type="password"]').fill('fixture-deepseek-key')
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0]).toMatchObject({ name: 'deepseek-chat', type: 'KnowledgeQA', source: 'deepseek',
    parameters: { base_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat', api_key: 'fixture-deepseek-key' } })
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain('fixture-deepseek-key')
})

test('type and provider changes refill model defaults and prevent cross-provider key reuse', async ({ page }) => {
  const writes = await setup(page)
  await page.getByRole('button', { name: '+ 添加模型', exact: true }).click()
  const dialog = page.locator('.t-dialog:visible')
  await dialog.locator('input[type="password"]').fill('fixture-old-key')
  await choose(page, dialog.getByTestId('model-provider-select'), 'OpenAI')
  await expect(dialog.locator('input[type="password"]')).toHaveValue('')
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  expect(writes).toHaveLength(0)
  await expect(page.getByText('请输入所选厂商的 API Key')).toBeVisible()
  await choose(page, dialog.locator('.t-select').first(), 'Embedding')
  await dialog.locator('input[type="password"]').fill('fixture-openai-key')
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0]).toMatchObject({ type: 'Embedding', parameters: { model: 'text-embedding-3-small', dimension: 1536 } })
})

test('rerank only offers compatible providers and saves its preset with just a key', async ({ page }) => {
  const writes = await setup(page)
  await page.getByRole('button', { name: '+ 添加模型', exact: true }).click()
  const dialog = page.locator('.t-dialog:visible')
  await choose(page, dialog.locator('.t-select').first(), 'ReRank')
  await expect(dialog.getByTestId('model-provider-select').locator('input')).toHaveValue('硅基流动 / SiliconFlow')
  await dialog.getByTestId('model-provider-select').click()
  await expect(page.locator('.t-select-option:visible')).toHaveCount(2)
  await page.locator('.t-select-option:visible').filter({ hasText: '硅基流动' }).click()
  await dialog.locator('input[type="password"]').fill('fixture-rerank-key')
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0]).toMatchObject({ type: 'Rerank', source: 'siliconflow',
    parameters: { base_url: 'https://api.siliconflow.cn/v1', model: 'BAAI/bge-reranker-v2-m3' } })
})

test('opening an existing custom model keeps its address, model, name and saved credentials', async ({ page }) => {
  const model = { id: 'existing-model', name: 'Existing model', display_name: 'Existing label', type: 'KnowledgeQA',
    source: 'openai', is_default: true, credentials_configured: true,
    parameters: { base_url: 'https://custom.example/v1', model: 'custom-provider-model', dimension: 3072 } }
  const writes = await setup(page, model)
  await page.getByRole('button', { name: '编辑', exact: true }).click()
  const dialog = page.locator('.t-dialog:visible')
  await expect(dialog.getByTestId('model-provider-select').locator('input')).toHaveValue('自定义 / OpenAI 兼容')
  await expect(dialog.locator('input[type="password"]')).toHaveValue('')
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0]).toMatchObject({ name: model.name, display_name: model.display_name, source: model.source, parameters: model.parameters })
  expect(writes[0].parameters).not.toHaveProperty('api_key')
})

test('local preset can be saved without a key and customized before saving', async ({ page }) => {
  const writes = await setup(page)
  await page.getByRole('button', { name: '+ 添加模型', exact: true }).click()
  const dialog = page.locator('.t-dialog:visible')
  await choose(page, dialog.getByTestId('model-provider-select'), 'Ollama / 本地模型')
  await dialog.locator('summary').click()
  const inputs = dialog.locator('.model-advanced input')
  await inputs.nth(0).fill('My local model')
  await inputs.nth(2).fill('http://localhost:18100/v1')
  await inputs.nth(3).fill('installed-local-model')
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0]).toMatchObject({ name: 'My local model', source: 'local',
    parameters: { base_url: 'http://localhost:18100/v1', model: 'installed-local-model' } })
  expect(writes[0].parameters).not.toHaveProperty('api_key')
})

test('an existing key is not silently retained when switching to another endpoint', async ({ page }) => {
  const model = { id: 'existing-model', name: 'deepseek-chat', type: 'KnowledgeQA', source: 'deepseek',
    credentials_configured: true, parameters: { base_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat' } }
  const writes = await setup(page, model)
  await page.getByRole('button', { name: '编辑', exact: true }).click()
  const dialog = page.locator('.t-dialog:visible')
  await choose(page, dialog.getByTestId('model-provider-select'), 'Ollama / 本地模型')
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByText('更换 API 地址时请输入新密钥；无密钥的本地服务请先清除原密钥')).toBeVisible()
  expect(writes).toHaveLength(0)
})
