import { expect, test } from '@playwright/test'

async function setup(page: import('@playwright/test').Page, section: string, options: { admin?: boolean, fail?: boolean } = {}) {
  const writes: any[] = []
  let passwordConfigured = true
  const admin = options.admin !== false
  await page.addInitScript(({ admin }) => {
    localStorage.setItem('personal_kb_token', 'fixture-token')
    localStorage.setItem('personal_kb_selected_tenant_id', 'tenant-1')
    localStorage.setItem('personal_kb_user', JSON.stringify({ username: 'owner', is_system_admin: admin }))
  }, { admin })
  const values: Record<string, any> = {
    application: { name: 'Fixture app' },
    neo4j: { enabled: false, uri: 'bolt://localhost:7687', username: 'neo4j' },
    startup: { debug: false, allowed_hosts: ['localhost', '127.0.0.1'], cors_origins: ['http://localhost:5173'],
      task_workers: 4, sqlite_timeout: 30, log_level: 'INFO', model_timeout: 60, model_retries: 2,
      no_proxy: 'localhost,127.0.0.1', proxy_url: '' },
  }
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const respond = (data: unknown) => route.fulfill({ json: { success: true, data } })
    if (path.includes('/system/config/')) {
      if (options.fail) return route.fulfill({ status: 503, json: { error: { message: '配置服务暂时不可用' } } })
      const key = path.split('/').at(-1)!
      if (request.method() === 'PUT' || request.method() === 'DELETE') {
        const body = request.postDataJSON()
        writes.push({ section: key, method: request.method(), body })
        if (request.method() === 'PUT') Object.assign(values[key], body)
        else { passwordConfigured = false; values[key].enabled = false }
      }
      return respond({ values: values[key], fields: { password: { configured: passwordConfigured } },
        restart_required: key === 'startup' && writes.length > 0, active: { task_workers: 4 },
        data_root: '/fixture-data', database_path: '/fixture-data/db.sqlite3', environment_overrides: ['DJANGO_DEBUG'] })
    }
    if (path.endsWith('/auth/me')) return respond({ user: { username: 'owner', is_system_admin: admin } })
    if (path.endsWith('/system/info')) return respond({ name: values.application.name })
    return respond({ items: [] })
  })
  await page.goto('/platform/settings?section=' + section)
  return writes
}

test('system admin saves the application name from the general page', async ({ page }) => {
  const writes = await setup(page, 'general')
  const panel = page.getByTestId('system-config-application')
  await panel.getByLabel('项目名称', { exact: true }).fill('Changed fixture')
  await panel.getByRole('button', { name: '保存应用配置', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].body).toEqual({ name: 'Changed fixture' })
  await expect(page.locator('.setting-value').filter({ hasText: 'Changed fixture' })).toBeVisible()
})

test('Neo4j password is blank on reload and blank edits preserve its saved value', async ({ page }) => {
  const writes = await setup(page, 'neo4j')
  const panel = page.getByTestId('system-config-neo4j')
  const secret = panel.locator('input[type=password]')
  await expect(secret).toHaveValue('')
  await secret.fill('fixture-neo4j-secret')
  await panel.getByRole('button', { name: '保存Neo4j 图数据库', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].body.password).toBe('fixture-neo4j-secret')
  await expect(secret).toHaveValue('')
  await panel.getByRole('button', { name: '保存Neo4j 图数据库', exact: true }).click()
  await expect.poll(() => writes.length).toBe(2)
  expect(writes[1].body).not.toHaveProperty('password')
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain('fixture-neo4j-secret')
})

test('startup edits explain restart and process environment overrides', async ({ page }) => {
  const writes = await setup(page, 'system')
  const panel = page.getByTestId('system-config-startup')
  await panel.getByLabel('后台任务线程数').fill('8')
  await panel.getByLabel('允许的主机（逗号分隔）').fill('localhost, 127.0.0.1, extra.fixture')
  await panel.getByRole('button', { name: '保存启动配置', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].body.task_workers).toBe(8)
  expect(writes[0].body.allowed_hosts).toEqual(['localhost', '127.0.0.1', 'extra.fixture'])
  await expect(panel.getByText('有启动配置等待重启生效。')).toBeVisible()
  await expect(panel.getByText(/部署环境覆盖：DJANGO_DEBUG/)).toBeVisible()
})

test('failed loads cannot submit default values over existing configuration', async ({ page }) => {
  const writes = await setup(page, 'neo4j', { fail: true })
  const panel = page.getByTestId('system-config-neo4j')
  await expect(panel.getByText('配置服务暂时不可用')).toBeVisible()
  await expect(panel.getByRole('button', { name: '保存Neo4j 图数据库', exact: true })).toHaveCount(0)
  expect(writes).toHaveLength(0)
})

test('non-admin sees no global configuration editor', async ({ page }) => {
  await setup(page, 'neo4j', { admin: false })
  await expect(page.getByTestId('system-config-neo4j')).toHaveCount(0)
  await expect(page.getByText('图数据库由系统管理员统一配置。')).toBeVisible()
})

test('clearing a global secret requires confirmation and sends only its field name', async ({ page }) => {
  const writes = await setup(page, 'neo4j')
  const panel = page.getByTestId('system-config-neo4j')
  await panel.getByRole('button', { name: '清除', exact: true }).click()
  expect(writes).toHaveLength(0)
  await page.locator('.t-dialog:visible').getByRole('button', { name: '确认', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0]).toEqual({ section: 'neo4j', method: 'DELETE', body: { field: 'password' } })
  await expect(panel.getByRole('button', { name: '清除', exact: true })).toBeDisabled()
  await expect(panel.getByText('凭据已清除，相关服务已停用')).toBeVisible()
})
