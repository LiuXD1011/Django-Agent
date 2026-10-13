import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import vm from 'node:vm'
import { transformSync } from 'esbuild'
import { compileScript, parse } from '@vue/compiler-sfc'

const require = createRequire(import.meta.url)
const vue = require('vue')
const apiCode = transformSync(readFileSync(new URL('../api/index.ts', import.meta.url), 'utf8'), { loader: 'ts', format: 'cjs' }).code
const { descriptor } = parse(readFileSync(new URL('./Platform.vue', import.meta.url), 'utf8'))
const platformCode = transformSync(compileScript(descriptor, { id: 'recent-sync-regression' }).content, { loader: 'ts', format: 'cjs' }).code
const flush = () => new Promise(resolve => setImmediate(resolve))
const response = (items, field = 'items') => ({ success: true, data: { [field]: items, total: items.length, page: 1, page_size: 5 } })
const recent = items => Array.from(items, item => ({ id: item.id, label: item.label, path: item.path }))
const kb = (id, name = id) => ({ id, name })

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

// R-KB-SIDEBAR-SYNC: real Orca evidence 059, 119-127 (no separate issue number).
// Production API and SFC scripts run unchanged; only HTTP and lifecycle hosts
// are controlled. No browser, QA data, auth transport, or real server is used.
function fixture(path = '/platform/knowledge-bases') {
  const mounted = [], unmounted = [], requests = []
  const route = vue.reactive({ path })
  let getResult = () => Promise.resolve(response([kb('before', '旧名称')]))
  let mutationResult = () => Promise.resolve({ success: true, data: {} })
  const client = {
    get: (url, config) => { requests.push({ method: 'get', url, config }); return getResult(url) },
    ...Object.fromEntries(['post', 'put', 'delete'].map(method => [method, (url, body) => {
      requests.push({ method, url, body }); return mutationResult()
    }])),
  }
  const apiContext = vm.createContext({ module: { exports: {} }, require: name => {
    if (name === './client') return client
    if (name === './auth-transport.mjs') return { authTransport: {} }
    if (name === './endpoint.mjs') return { endpoint: {} }
    throw new Error(`Unexpected API import: ${name}`)
  } })
  vm.runInContext(apiCode, apiContext)
  const apiModule = apiContext.module.exports
  const scope = vue.effectScope()
  const context = vm.createContext({ module: { exports: {} }, require: name => {
    if (name === 'vue') return { ...vue, onMounted: fn => mounted.push(fn), onUnmounted: fn => unmounted.push(fn) }
    if (name === 'vue-router') return { useRoute: () => route, useRouter: () => ({ push: () => {} }) }
    if (name === '../api') return apiModule
    if (name === '../stores/auth') return { useAuthStore: () => ({ user: { username: 'fixture' } }) }
    if (name === 'tdesign-vue-next') return { MessagePlugin: {} }
    if (name === 'tdesign-icons-vue-next') return {}
    throw new Error(`Unexpected Platform import: ${name}`)
  } })
  vm.runInContext(platformCode, context)
  const b = scope.run(() => context.module.exports.default.setup({}, { expose: () => {} }))
  let disposed = false
  return {
    b, route, requests, api: apiModule.api,
    setGet: handler => { getResult = handler },
    setMutation: handler => { mutationResult = handler },
    mount: async () => { for (const fn of mounted) await fn(); await flush() },
    dispose: () => { if (disposed) return; disposed = true; for (const fn of unmounted) fn(); scope.stop() },
    get reads() { return requests.filter(request => request.method === 'get') },
  }
}

const mutations = [
  ['create', 'createKb', [{ name: 'new' }], 'post', '/api/v1/knowledge-bases', { name: 'new' }],
  ['edit', 'updateKb', ['before', { name: 'renamed' }], 'put', '/api/v1/knowledge-bases/before', { name: 'renamed' }],
  ['copy', 'copyKb', ['before'], 'post', '/api/v1/knowledge-bases/copy', { source_id: 'before' }],
  ['pin', 'pinKb', ['before', true], 'put', '/api/v1/knowledge-bases/before/pin', { is_pinned: true }],
  ['unpin', 'pinKb', ['before', false], 'put', '/api/v1/knowledge-bases/before/pin', { is_pinned: false }],
  ['delete', 'deleteKb', ['before'], 'delete', '/api/v1/knowledge-bases/before', undefined],
]

for (const [label, method, args, verb, url, body] of mutations) {
  test(`${label} refreshes the same-route sidebar only after API success and preserves the response`, async () => {
    const f = fixture()
    try {
      await f.mount()
      const pending = deferred(), result = { success: true, data: { id: 'returned' } }
      const items = label === 'delete' ? [] : [kb('after', '真实新结果')]
      f.setMutation(() => pending.promise)
      f.setGet(() => Promise.resolve(response(items)))
      const mutation = f.api[method](...args)
      await flush()
      assert.equal(f.reads.length, 1, 'pending mutation must not publish success')
      assert.equal(f.b.recentItems.value[0].label, '旧名称')
      assert.deepEqual(JSON.parse(JSON.stringify(f.requests.at(-1))), JSON.parse(JSON.stringify({ method: verb, url, body })))
      pending.resolve(result)
      assert.equal(await mutation, result, 'API response identity must be preserved')
      await flush()
      assert.equal(f.reads.length, 2, 'successful mutation must refresh without route navigation')
      assert.deepEqual(recent(f.b.recentItems.value), items.map(item => ({ id: item.id, label: item.name, path: `/platform/knowledge-bases/${item.id}` })))
      assert.equal(f.route.path, '/platform/knowledge-bases')
      assert.equal(f.b.recentLoading.value, false)
    } finally { f.dispose() }
  })
}

test('failed mutations retain existing entries and reject with the original failure', async () => {
  const f = fixture()
  try {
    await f.mount()
    const failure = { success: false, status: 403, error: { code: 'forbidden', message: 'Denied' } }
    f.setMutation(() => Promise.reject(failure))
    for (const [, method, args] of mutations) await assert.rejects(f.api[method](...args), error => error === failure)
    await flush()
    assert.equal(f.reads.length, 1)
    assert.equal(f.b.recentItems.value[0].label, '旧名称')
  } finally { f.dispose() }
})

test('detail save refreshes the sidebar name without changing the detail route', async () => {
  const f = fixture('/platform/knowledge-bases/before')
  try {
    await f.mount()
    f.setGet(() => Promise.resolve(response([kb('before', '改名已保存')])) )
    await f.api.updateKb('before', { name: '改名已保存' })
    await flush()
    assert.equal(f.b.recentItems.value[0].label, '改名已保存')
    assert.equal(f.route.path, '/platform/knowledge-bases/before')
  } finally { f.dispose() }
})

test('old load cannot restore a deleted entry after the mutation refresh finishes', async () => {
  const f = fixture()
  try {
    await f.mount()
    const old = deferred()
    f.setGet(() => old.promise)
    const oldLoad = f.b.loadRecentItems()
    f.setGet(() => Promise.resolve(response([])))
    await f.api.deleteKb('before')
    await flush()
    old.resolve(response([kb('before', '已删除旧数据')]))
    await oldLoad
    assert.deepEqual(recent(f.b.recentItems.value), [])
    assert.equal(f.b.recentLoading.value, false)
  } finally { f.dispose() }
})

test('older failure cannot clear a newer successful load', async () => {
  const f = fixture()
  try {
    await f.mount()
    const old = deferred()
    f.setGet(() => old.promise)
    const oldLoad = f.b.loadRecentItems()
    f.setGet(() => Promise.resolve(response([kb('newest')])))
    await f.b.loadRecentItems()
    old.reject(new Error('old network failure'))
    await oldLoad
    assert.equal(f.b.recentItems.value[0].id, 'newest')
    assert.equal(f.b.recentError.value, '')
  } finally { f.dispose() }
})

test('older completion cannot stop the current loading indicator or publish its entries', async () => {
  const f = fixture()
  try {
    await f.mount()
    const old = deferred(), current = deferred()
    f.setGet(() => old.promise)
    const oldLoad = f.b.loadRecentItems()
    f.setGet(() => current.promise)
    const currentLoad = f.b.loadRecentItems()
    old.resolve(response([kb('obsolete')]))
    await oldLoad
    assert.equal(f.b.recentLoading.value, true)
    assert.equal(f.b.recentItems.value[0].id, 'before')
    current.resolve(response([kb('current')]))
    await currentLoad
    assert.equal(f.b.recentItems.value[0].id, 'current')
    assert.equal(f.b.recentLoading.value, false)
  } finally { f.dispose() }
})

test('route change to chat preserves session results against a late knowledge-base response', async () => {
  const f = fixture()
  try {
    await f.mount()
    const old = deferred()
    f.setGet(() => old.promise)
    const oldLoad = f.b.loadRecentItems()
    f.setGet(() => Promise.resolve(response([{ id: 'session', title: '真实对话' }])))
    f.route.path = '/platform/chat/session'
    await flush()
    old.resolve(response([kb('old-kb')]))
    await oldLoad
    assert.deepEqual(recent(f.b.recentItems.value), [{ id: 'session', label: '真实对话', path: '/platform/chat/session' }])
  } finally { f.dispose() }
})

test('evaluation clears items and invalidates a late pending knowledge-base load', async () => {
  const f = fixture()
  try {
    await f.mount()
    const old = deferred()
    f.setGet(() => old.promise)
    const oldLoad = f.b.loadRecentItems()
    f.route.path = '/platform/evaluation'
    await flush()
    assert.equal(f.b.recentLoading.value, false)
    old.resolve(response([kb('old-kb')]))
    await oldLoad
    assert.deepEqual(recent(f.b.recentItems.value), [])
  } finally { f.dispose() }
})

for (const path of ['/platform/chat/session', '/platform/creatChat', '/platform/evaluation']) {
  test(`knowledge-base mutation leaves ${path} recent branch untouched`, async () => {
    const f = fixture(path)
    try {
      await f.mount()
      const before = recent(f.b.recentItems.value), count = f.reads.length
      await f.api.createKb({ name: 'new' })
      await flush()
      assert.equal(f.reads.length, count)
      assert.deepEqual(recent(f.b.recentItems.value), before)
    } finally { f.dispose() }
  })
}

test('unmount unsubscribes notifications and invalidates pending reads without mutating disposed state', async () => {
  const f = fixture()
  try {
    await f.mount()
    const old = deferred()
    f.setGet(() => old.promise)
    const pendingLoad = f.b.loadRecentItems()
    f.dispose()
    const items = recent(f.b.recentItems.value), loading = f.b.recentLoading.value, count = f.reads.length
    await f.api.deleteKb('before')
    await flush()
    assert.equal(f.reads.length, count)
    old.resolve(response([kb('late')]))
    await pendingLoad
    assert.deepEqual(recent(f.b.recentItems.value), items)
    assert.equal(f.b.recentLoading.value, loading)
  } finally { f.dispose() }
})

// KB-SIDEBAR-003: Root real transport failure 049/050 and recovery 055/056.
test('latest list failure preserves two successful entries and exposes a safe error without failing a successful mutation', async () => {
  const f = fixture()
  try {
    f.setGet(() => Promise.resolve(response([kb('before', '旧名称'), kb('second', '第二条')])))
    await f.mount()
    const before = recent(f.b.recentItems.value)
    f.setGet(() => Promise.reject(new Error('private endpoint /api/token=secret list failed')))
    await f.api.deleteKb('before')
    await flush()
    assert.deepEqual(recent(f.b.recentItems.value), before)
    assert.equal(f.b.recentError.value, '最近访问加载失败，请稍后重试')
    assert.equal(f.b.recentLoading.value, false)
  } finally { f.dispose() }
})

// KB-SIDEBAR-003: failure, empty success, pending retry and stale completions.
test('first read failure exposes an error and a successful empty retry clears it', async () => {
  const f = fixture()
  try {
    f.setGet(() => Promise.reject(new Error('first read failed')))
    await f.mount()
    assert.equal(f.b.recentError.value, '最近访问加载失败，请稍后重试')
    assert.deepEqual(recent(f.b.recentItems.value), [])
    assert.equal(f.b.recentLoading.value, false)
    f.setGet(() => Promise.resolve(response([])))
    await f.b.retryRecentItems()
    assert.equal(f.b.recentError.value, '')
    assert.deepEqual(recent(f.b.recentItems.value), [])
  } finally { f.dispose() }
})

test('retry ignores duplicate invocations while pending and restores the latest successful list', async () => {
  const f = fixture()
  try {
    await f.mount()
    f.setGet(() => Promise.reject(new Error('offline')))
    await f.b.loadRecentItems()
    const pending = deferred(), count = f.reads.length
    f.setGet(() => pending.promise)
    const retry = f.b.retryRecentItems()
    await f.b.retryRecentItems()
    assert.equal(f.reads.length, count + 1)
    assert.equal(f.b.recentLoading.value, true)
    assert.equal(f.b.recentItems.value[0].id, 'before')
    pending.resolve(response([kb('recovered', '恢复后结果')]))
    await retry
    assert.equal(f.b.recentItems.value[0].id, 'recovered')
    assert.equal(f.b.recentError.value, '')
    assert.equal(f.b.recentLoading.value, false)
  } finally { f.dispose() }
})

test('older success cannot clear a newer failure or replace the last successful list', async () => {
  const f = fixture()
  try {
    await f.mount()
    const old = deferred()
    f.setGet(() => old.promise)
    const oldLoad = f.b.loadRecentItems()
    f.setGet(() => Promise.reject(new Error('current failure')))
    await f.b.loadRecentItems()
    old.resolve(response([kb('obsolete')]))
    await oldLoad
    assert.equal(f.b.recentItems.value[0].id, 'before')
    assert.equal(f.b.recentError.value, '最近访问加载失败，请稍后重试')
    assert.equal(f.b.recentLoading.value, false)
  } finally { f.dispose() }
})

test('disposed retry failure settles without publishing errors or starting another read', async () => {
  const f = fixture()
  try {
    await f.mount()
    const pending = deferred()
    f.setGet(() => pending.promise)
    const retry = f.b.retryRecentItems()
    f.dispose()
    const before = recent(f.b.recentItems.value), loading = f.b.recentLoading.value, count = f.reads.length
    pending.reject(new Error('late failure'))
    await retry
    await f.b.retryRecentItems()
    assert.equal(f.reads.length, count)
    assert.deepEqual(recent(f.b.recentItems.value), before)
    assert.equal(f.b.recentError.value, '')
    assert.equal(f.b.recentLoading.value, loading)
  } finally { f.dispose() }
})

test('existing page size, server order, limit, legacy result field and fallback names remain intact', async () => {
  const f = fixture()
  try {
    const items = [kb('z'), kb('a'), kb('blank', ''), kb('4'), kb('5'), kb('6')]
    f.setGet(() => Promise.resolve(response(items, 'knowledge_bases')))
    await f.mount()
    assert.deepEqual(Array.from(f.b.recentItems.value, item => item.id), ['z', 'a', 'blank', '4', '5'])
    assert.equal(f.b.recentItems.value[2].label, '未命名知识库')
    assert.deepEqual(JSON.parse(JSON.stringify(f.reads[0].config)), { params: { page: 1, page_size: 5 } })
  } finally { f.dispose() }
})
