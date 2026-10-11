import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import { transformSync } from 'esbuild'

// Execute the actual TypeScript service. Only its HTTP and browser boundaries are stubbed.
const source = transformSync(readFileSync(new URL('./langfuse.ts', import.meta.url), 'utf8'), {
  loader: 'ts', format: 'cjs', target: 'es2022',
}).code
const manual = 'https://ui.example.invalid/console/project/fixture/traces'
const disabled = { error: { code: 'auto_login_disabled' } }

function service({ post = async () => ({ data: { open_url: manual } }), get = async () => ({ data: { open_url: manual, auto_login: false } }), popup = true, authMode = '', userId = null, boundService = true, native, tenantId } = {}) {
  const opened = [], assigned = [], calls = []
  const browserPopup = { opener: {} }
  const client = {
    post: async (...args) => { calls.push(['post', ...args]); return post(...args) },
    get: async (...args) => { calls.push(['get', ...args]); return get(...args) },
  }
  const context = vm.createContext({
    module: { exports: {} }, URL, crypto: { randomUUID: () => 'native-request-one' }, localStorage: { getItem: (key) => key === 'personal_kb_user' ? JSON.stringify({ id: userId }) : null },
    require: (name) => {
      if (name === '../api/auth-transport.mjs') return { authTransport: { mode: () => authMode, headers: () => ({ ...(tenantId ? { 'X-Tenant-ID': tenantId } : {}), Authorization: 'must-never-forward' }) } }
      if (name === '../api/endpoint.mjs') return { endpoint: { service: boundService ? { service_id: 'fixture-service' } : null } }
      if (name === '../api/desktop-transport.mjs') return { desktopBridge: native ? { langfuse: native } : null }
      assert.equal(name, '../api/client'); return client
    },
    window: { open: (...args) => { opened.push(args); return popup ? browserPopup : null }, location: { assign: (url) => assigned.push(url) } },
  })
  vm.runInContext(source, context, { filename: 'langfuse.ts' })
  return { ...context.module.exports, opened, assigned, calls, browserPopup }
}

test('manual fallback opens authorized configured remote UI after disabled auto login', async () => {
  const api = service({ post: async () => { throw disabled } })
  await api.openLangfuse()
  assert.deepEqual(api.calls.map(([method]) => method), ['post', 'get'])
  assert.deepEqual(api.opened, [[manual, '_blank']])
  assert.equal(api.browserPopup.opener, null)
})

test('unsafe configured URL cannot create a popup or navigate', async () => {
  for (const url of ['javascript:alert(1)', 'data:text/html,bad', '//ui.example.invalid/project/fixture/traces',
    'https://user:password@ui.example.invalid/project/fixture/traces', 'https://ui.example.invalid/', '', undefined,
    'https://ui.example.invalid\\@evil.invalid/project/fixture/traces', '\n' + manual]) {
    const api = service({ post: async () => { throw disabled }, get: async () => ({ data: { open_url: url } }) })
    await assert.rejects(api.openLangfuse(), undefined, String(url))
    assert.deepEqual(api.opened, [])
    assert.deepEqual(api.assigned, [])
  }
})

test('failed login and account conflict never fall back or open a blank tab', async () => {
  for (const code of ['login_failed', 'account_conflict', 'local_account_required', 'origin_mismatch']) {
    const error = { error: { code } }
    const api = service({ post: async () => { throw error } })
    await assert.rejects(api.openLangfuse(), (caught) => caught === error)
    assert.deepEqual(api.calls.map(([method]) => method), ['post'])
    assert.deepEqual(api.opened, [])
  }
})

test('manual fallback status still requires authorization', async () => {
  const forbidden = { error: { code: 'local_account_required' } }
  const api = service({ post: async () => { throw disabled }, get: async () => { throw forbidden } })
  await assert.rejects(api.openLangfuse(), (caught) => caught === forbidden)
  assert.deepEqual(api.opened, [])
})

test('same project trace is used and foreign origin or project cannot redirect', async () => {
  for (const [trace, expected] of [
    ['https://ui.example.invalid/console/project/fixture/traces/trace-one', 'https://ui.example.invalid/console/project/fixture/traces/trace-one'],
    ['https://evil.example.invalid/console/project/fixture/traces/trace-one', manual],
    ['https://ui.example.invalid/console/project/other/traces/trace-one', manual],
    ['https://user:password@ui.example.invalid/console/project/fixture/traces/trace-one', manual],
  ]) {
    const api = service()
    await api.openLangfuse(trace)
    assert.deepEqual(api.opened, [[expected, '_blank']])
  }
})

test('blocked popup assigns the validated destination directly', async () => {
  const api = service({ popup: false })
  await api.openLangfuse()
  assert.deepEqual(api.assigned, [manual])
  assert.deepEqual(api.opened, [[manual, '_blank']])
})

test('concurrent browser session calls share the actual request', async () => {
  let complete
  const pending = new Promise((resolve) => { complete = resolve })
  const api = service({ post: () => pending })
  const first = api.langfuseSession(), second = api.langfuseSession()
  assert.equal(api.calls.length, 1)
  complete({ data: { open_url: manual } })
  assert.deepEqual(await first, await second)
})

test('cookie login starts Langfuse without reading a browser access token', async () => {
  const api = service({ authMode: 'cookie', userId: 'fixture-user' })
  await api.autoLoginLangfuse()
  await api.autoLoginLangfuse()
  assert.equal(api.calls.length, 1)
  assert.equal(api.calls[0][1], '/api/v1/observability/langfuse/session')
})

test('automatic Langfuse login waits for verified service capabilities', async () => {
  const api = service({ authMode: 'cookie', userId: 'fixture-user', boundService: false })
  await api.autoLoginLangfuse()
  assert.equal(api.calls.length, 0)
})

test('native Langfuse uses fixed window/session/clear capabilities without browser popups or renderer cookies', async () => {
  const commands = [], api = service({ native: async request => { commands.push(request); return { protocol: 1, id: request.id, status: 200, body: { success: true, data: { state: 'manual', manual_reason: 'credentials_missing', message: '已打开 Langfuse，请在新页面手动登录' } } }; } })
  const opened = await api.openLangfuse('https://ui.example.invalid/console/project/fixture/traces/one')
  assert.equal(opened.state, 'manual'); assert.equal(opened.manual_reason, 'credentials_missing')
  assert.equal(commands[0].action, 'open'); assert.equal(commands[0].traceUrl, 'https://ui.example.invalid/console/project/fixture/traces/one')
  await api.langfuseSession(); await api.clearLangfuseSession()
  assert.deepEqual(commands.map(v => v.action), ['open', 'session', 'clear'])
  assert.deepEqual(api.opened, []); assert.deepEqual(api.assigned, []); assert.deepEqual(api.calls, [])
  assert.equal(JSON.stringify(commands).includes('cookies'), false)
})

test('native login failure stays explicit and cannot fall back to a system browser', async () => {
  const api = service({ native: async request => ({ protocol: 1, id: request.id, status: 502, body: { success: false, error: { code: 'login_failed' }, message: '登录失败' } }) })
  await assert.rejects(api.openLangfuse(), error => error.error.code === 'login_failed')
  assert.deepEqual(api.opened, []); assert.deepEqual(api.calls, [])
})

test('native clear reaches main immediately while an automatic login is still pending', async () => {
  let finish
  const pending = new Promise(resolve => { finish = resolve }), actions = []
  const api = service({ native: async request => {
    actions.push(request.action)
    if (request.action === 'session') await pending
    return { protocol: 1, id: request.id, status: 200, body: { success: true, data: { state: request.action === 'clear' ? 'cleared' : 'connected' } } }
  } })
  const login = api.langfuseSession(), clear = api.clearLangfuseSession()
  try { await new Promise(resolve => setImmediate(resolve)); assert.deepEqual(actions, ['session', 'clear']) }
  finally { finish(); await Promise.all([login, clear]) }
})

test('native fixed capability carries the selected tenant without forwarding transport credentials', async () => {
  const commands = [], api = service({ tenantId: 'selected-tenant', native: async input => { commands.push(input); return { status: 200, body: { data: { state: 'ready' } } } } })
  await api.langfuseSession()
  assert.equal(commands[0].tenantId, 'selected-tenant')
  assert.equal(JSON.stringify(commands).includes('must-never-forward'), false)
})
