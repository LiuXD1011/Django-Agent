import { expect, test, type Page } from '@playwright/test'

const password = 'Fixture-cookie-knowledge-2026'
const uniqueEmail = (label: string) => `${label}-${Date.now()}@example.invalid`

async function register(page: Page, email: string) {
  await page.goto('/login')
  await page.getByRole('button', { name: '创建个人账号', exact: true }).click()
  await page.getByPlaceholder('邮箱', { exact: true }).fill(email)
  await page.getByPlaceholder('密码', { exact: true }).fill(password)
  await page.getByPlaceholder('确认密码', { exact: true }).fill(password)
  await page.getByRole('button', { name: '注册并进入', exact: true }).click()
  await expect(page).toHaveURL(/\/platform\/knowledge-bases$/)
}
async function login(page: Page, email: string) {
  await page.goto('/login')
  await page.getByPlaceholder('邮箱', { exact: true }).fill(email)
  await page.getByPlaceholder('密码', { exact: true }).fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).toHaveURL(/\/platform\/knowledge-bases$/)
}
async function request(page: Page, path: string, method = 'GET', data?: unknown) {
  return page.evaluate(async ({ path, method, data }) => {
    const csrf = document.cookie.split(';').map(part => part.trim()).find(part => part.startsWith('csrftoken='))?.split('=')[1] || ''
    const result = await fetch(path, {
      method, credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(csrf) },
      ...(data !== undefined ? { body: JSON.stringify(data) } : {}),
    })
    return { status: result.status, body: await result.json() }
  }, { path, method, data })
}

// CD-01/CD-11: real TypeScript Core + Vue + real Chromium, independent cookie jars, no mocked APIs.
test('real two-device login shares knowledge and one-device revocation leaves the other logged in', async ({ browser, baseURL }) => {
  const a = await browser.newContext({ baseURL, serviceWorkers: 'block' })
  const b = await browser.newContext({ baseURL, viewport: { width: 390, height: 844 }, serviceWorkers: 'block' })
  try {
    const desktop = await a.newPage(), mobile = await b.newPage()
    const email = uniqueEmail('two-device')
    await register(desktop, email)
    await login(mobile, email)
    for (const page of [desktop, mobile]) {
      expect(await page.evaluate(() => [localStorage.getItem('personal_kb_token'), localStorage.getItem('personal_kb_refresh_token')])).toEqual([null, null])
      expect(await page.evaluate(() => document.cookie.includes('marlin_access') || document.cookie.includes('marlin_refresh'))).toBe(false)
    }
    for (const context of [a, b]) {
      const cookies = await context.cookies()
      expect(cookies.find(cookie => cookie.name === 'marlin_access')?.httpOnly).toBe(true)
      expect(cookies.find(cookie => cookie.name === 'marlin_refresh')?.httpOnly).toBe(true)
    }
    const knowledgeName = '跨设备真实保存验证'
    const created = await request(desktop, '/api/v1/knowledge-bases', 'POST', { name: knowledgeName })
    expect(created.status).toBe(200)
    await mobile.reload()
    await expect(mobile.getByRole('heading', { name: knowledgeName, exact: true })).toBeVisible()
    const listing = await request(mobile, '/api/v1/knowledge-bases')
    expect(listing.body.data.items.some((item: any) => item.id === created.body.data.id)).toBe(true)
    const currentA = (await request(desktop, '/api/v1/auth/me')).body.data.device.id
    const currentB = (await request(mobile, '/api/v1/auth/me')).body.data.device.id
    expect(currentA).not.toBe(currentB)
    const devices = await request(mobile, '/api/v1/auth/devices')
    expect(devices.body.data.items.filter((device: any) => !device.is_revoked)).toHaveLength(2)
    expect((await request(mobile, `/api/v1/auth/devices/${currentA}`, 'DELETE')).status).toBe(200)
    await desktop.reload()
    await expect(desktop).toHaveURL(/\/login$/)
    await mobile.reload()
    await expect(mobile).toHaveURL(/\/platform\/knowledge-bases$/)
    await expect(mobile.getByRole('heading', { name: knowledgeName, exact: true })).toBeVisible()
  } finally { await a.close(); await b.close() }
})

// CD-15: two tabs share cookies, so switching account must fence the previous live store.
test('real same-browser account switch reloads the other tab into the new private space', async ({ context, page }) => {
  const emailA = uniqueEmail('account-a')
  await register(page, emailA)
  const privateName = '账号A私有资料'
  expect((await request(page, '/api/v1/knowledge-bases', 'POST', { name: privateName })).status).toBe(200)
  await page.reload()
  await expect(page.getByRole('heading', { name: privateName, exact: true })).toBeVisible()
  const second = await context.newPage()
  const emailB = uniqueEmail('account-b')
  await register(second, emailB)
  await expect(page).toHaveURL(/\/platform\/knowledge-bases$/)
  await expect.poll(async () => (await request(page, '/api/v1/auth/me')).body.data.user.email).toBe(emailB)
  await expect(page.getByText(privateName, { exact: true })).toHaveCount(0)
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('personal_kb_user') || '{}').email)).toBe(emailB)
  expect(await page.evaluate(() => localStorage.getItem('personal_kb_token'))).toBeNull()
})

// CD-12: browser credential storage and refresh recovery use real HttpOnly cookies.
test('real browser restores access via HttpOnly refresh after the access cookie is absent', async ({ page, context }) => {
  await register(page, uniqueEmail('refresh'))
  const cookies = await context.cookies()
  const refresh = cookies.find(cookie => cookie.name === 'marlin_refresh')
  expect(refresh?.httpOnly).toBe(true)
  await context.clearCookies({ name: 'marlin_access' })
  await page.reload()
  await expect(page).toHaveURL(/\/platform\/knowledge-bases$/)
  await expect.poll(async () => (await context.cookies()).some(cookie => cookie.name === 'marlin_access')).toBe(true)
  expect(await page.evaluate(() => localStorage.getItem('personal_kb_refresh_token'))).toBeNull()
})
