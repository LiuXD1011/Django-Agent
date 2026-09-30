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

function service({ post = async () => ({ data: { open_url: manual } }), get = async () => ({ data: { open_url: manual, auto_login: false } }), popup = true } = {}) {
  const opened = [], assigned = [], calls = []
  const browserPopup = { opener: {} }
  const client = {
    post: async (...args) => { calls.push(['post', ...args]); return post(...args) },
    get: async (...args) => { calls.push(['get', ...args]); return get(...args) },
  }
  const context = vm.createContext({
    module: { exports: {} }, URL, localStorage: { getItem: () => null },
    require: (name) => { assert.equal(name, '../api/client'); return client },
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
