import { expect, test } from '@playwright/test'

test('UI credentials: replace once, blank preserves, confirmed deletion, no browser persistence', async ({ page }) => {
  let configured = true
  const writes: Record<string, unknown>[] = []
  const deletes: string[] = []
  await page.addInitScript(() => {
    localStorage.setItem('personal_kb_token', 'fixture-token')
    localStorage.setItem('personal_kb_selected_tenant_id', 'tenant-1')
    localStorage.setItem('personal_kb_user', JSON.stringify({ username: 'owner', is_system_admin: true }))
  })
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const model = { id: 'fixture-model', name: 'Fixture model', type: 'KnowledgeQA', source: 'openai', is_default: true,
      parameters: { base_url: 'https://fixture.invalid/v1', model: 'fixture' }, credentials_configured: configured }
    const respond = (data: unknown) => route.fulfill({ json: { success: true, data } })
    if (path.endsWith('/models')) return respond({ items: [model], total: 1 })
    if (path.endsWith('/models/fixture-model') && request.method() === 'PUT') {
      writes.push(request.postDataJSON() as Record<string, unknown>)
      return respond(model)
    }
    if (path.endsWith('/credentials/api_key') && request.method() === 'DELETE') {
      deletes.push(path); configured = false; return respond({})
    }
    if (path.endsWith('/auth/me')) return respond({ user: { username: 'owner', is_system_admin: true } })
    return respond({ items: [] })
  })
  await page.goto('/platform/settings?section=models')
  await page.getByRole('button', { name: '编辑', exact: true }).click()
  let dialog = page.locator('.t-dialog:visible')
  const key = dialog.locator('input[type="password"]')
  await expect(key).toHaveValue('')
  await key.fill('offline-fixture-new-key')
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0]?.parameters).toMatchObject({ api_key: 'offline-fixture-new-key' })
  await expect(dialog).toHaveCount(0)
  await page.getByRole('button', { name: '编辑', exact: true }).click()
  dialog = page.locator('.t-dialog:visible')
  await expect(dialog.locator('input[type="password"]')).toHaveValue('')
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await expect.poll(() => writes.length).toBe(2)
  expect(writes[1]?.parameters).not.toHaveProperty('api_key')
  await expect(dialog).toHaveCount(0)
  await page.getByRole('button', { name: '清密钥', exact: true }).click()
  expect(deletes).toHaveLength(0)
  await page.locator('.t-dialog:visible').getByRole('button', { name: '确认', exact: true }).click()
  await expect.poll(() => deletes.length).toBe(1)
  await expect(page.getByRole('button', { name: '清密钥', exact: true })).toBeDisabled()
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain('offline-fixture-new-key')
})
