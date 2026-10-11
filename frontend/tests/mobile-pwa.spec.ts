import { expect, test } from '@playwright/test'

async function authorized(page: any) {
  await page.addInitScript(() => localStorage.setItem('personal_kb_auth_mode', 'cookie'))
  await page.route('**/api/v1/**', async (route: any) => {
    const path = new URL(route.request().url()).pathname
    const respond = (data: unknown) => route.fulfill({ json: { success: true, data } })
    if (path.endsWith('/capabilities')) return respond({ service_id: 'fixture-service', client_protocol: 1, auth_modes: ['cookie'] })
    if (path.endsWith('/auth/me')) return respond({ auth_mode: 'cookie', user: { id: 'owner', username: 'mobile-owner' }, tenant: { id: 'space', name: '我的空间' } })
    if (path === '/api/v1/knowledge-bases') return respond({ items: [{ id: 'kb-mobile', name: '手机资料', description: '私有资料', knowledge_count: 1 }] })
    if (path === '/api/v1/knowledge-bases/kb-mobile') return respond({ id: 'kb-mobile', name: '手机资料', indexing_strategy: { vector_enabled: true }, knowledge_count: 1 })
    if (path.endsWith('/knowledge')) return respond({ items: [{ id: 'doc', title: '手机采集文档', file_name: 'x'.repeat(160) + '.pdf', parse_status: 'completed' }] })
    return respond({ items: [] })
  })
}

for (const width of [360, 390, 430]) {
  test(`mobile ${width}: four tabs, scoped capture and bounded layout`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 })
    await authorized(page)
    await page.goto('/platform/knowledge-bases')
    const nav = page.getByRole('navigation', { name: '移动端主导航' })
    await expect(nav.locator('button')).toHaveCount(4)
    for (const label of ['知识库', '问答', '收集', '我的']) await expect(nav.getByRole('button', { name: label, exact: true })).toBeVisible()
    const box = await nav.getByRole('button', { name: '收集', exact: true }).boundingBox()
    expect(box!.height).toBeGreaterThanOrEqual(44)
    await nav.getByRole('button', { name: '收集', exact: true }).click()
    await page.locator('.t-dialog:visible').getByRole('button', { name: '手机资料', exact: true }).click()
    await expect(page).toHaveURL(/knowledge-bases\/kb-mobile\?collect=1/)
    const collect = page.locator('.t-dialog:visible').filter({ hasText: '采集文件' })
    await expect(collect).toContainText('目标知识库：手机资料')
    await expect(collect.locator('input[capture="environment"]')).toHaveAttribute('accept', 'image/jpeg,image/png,image/webp')
    await collect.locator('input[type="file"]').first().setInputFiles({ name: 'mobile.txt', mimeType: 'text/plain', buffer: Buffer.from('mobile fixture') })
    const confirm = page.locator('.t-dialog:visible').filter({ hasText: '上传解析设置' })
    await expect(confirm).toContainText('mobile.txt')
    await expect(confirm).toContainText('目标：手机资料')
    await expect(confirm).toContainText('确认后上传到服务器')
    await expect(page.locator('.t-dialog:visible')).toHaveCount(1)
    await page.screenshot({ animations: 'disabled', path: `../.cache/cross-device-p1/mobile-${width}-upload.png` })
    await confirm.getByRole('button', { name: '取消', exact: true }).click()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
    expect(overflow).toBe(false)
    await nav.getByRole('button', { name: '问答', exact: true }).click()
    const input = page.locator('.rich-input-container textarea')
    await input.fill('第一行')
    await input.press('Enter')
    await expect(input).toHaveValue('第一行\n')
    await page.screenshot({ animations: 'disabled', path: `../.cache/cross-device-p1/mobile-${width}-chat.png` })
    await expect(page).toHaveURL(/creatChat/)
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
    await nav.getByRole('button', { name: '我的', exact: true }).click()
    await expect(page).toHaveURL(/settings\?section=user/)
    await page.getByRole('button', { name: '管理设备', exact: true }).click()
    await expect(page).toHaveURL(/settings\/devices/)
    await expect(page.getByRole('heading', { name: '登录设备', exact: true })).toBeVisible()
    expect(await page.evaluate(() => localStorage.getItem('personal_kb_token'))).toBeNull()
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  })
}

test('real Chromium SW persists only versioned public assets and offline private API fails', async ({ page, context }) => {
  await page.goto('/login')
  await page.evaluate(async () => { await navigator.serviceWorker.ready })
  const cached = await page.evaluate(async () => {
    const names = await caches.keys()
    const keys = await Promise.all(names.map(async name => (await (await caches.open(name)).keys()).map(request => new URL(request.url).pathname)))
    return { names, keys: keys.flat() }
  })
  expect(cached.names.every(name => name.startsWith('personal-kb-public-static-'))).toBe(true)
  expect(cached.keys.length).toBeGreaterThan(5)
  expect(cached.keys.every(path => path.startsWith('/assets/') || /^\/pwa-shell\/shell-[0-9a-f]{20}\.html$/.test(path))).toBe(true)
  const before = [...cached.keys].sort()
  await page.evaluate(async () => {
    for (const path of ['/api/v1/auth/me', '/media/private.png', '/files/private', '/uploads/private', '/downloads/private', '/api/v1/agent-chat/private']) {
      try { await fetch(path) } catch { /* network/API may be unavailable in the isolated preview */ }
    }
  })
  const after = await page.evaluate(async () => (await Promise.all((await caches.keys()).map(async name => (await (await caches.open(name)).keys()).map(request => new URL(request.url).pathname)))).flat().sort())
  expect(after).toEqual(before)
  await context.setOffline(true)
  await page.reload()
  await expect(page.getByText('网络已断开。云端内容、登录和问答需要联网；未提交输入仅留在当前页面。')).toBeVisible()
  expect(await page.evaluate(async () => { try { await fetch('/api/v1/auth/me'); return false } catch { return true } })).toBe(true)
})
