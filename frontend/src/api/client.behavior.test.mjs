import assert from 'node:assert/strict'
import test from 'node:test'
import vm from 'node:vm'
import { readFileSync } from 'node:fs'
import axios from 'axios'
import { transformSync } from 'esbuild'
import { createAuthTransport } from './auth-transport.mjs'
import { EndpointResolver } from './endpoint.mjs'
import * as desktopTransport from './desktop-transport.mjs'

const code = transformSync(readFileSync(new URL('./client.ts', import.meta.url), 'utf8'), { loader: 'ts', format: 'cjs' }).code

test('a 401 inside the Cookie mutation lock ends without recursively acquiring the refresh lock', { timeout: 2000 }, async () => {
  const names = [], storage = new Map()
  const resolver = new EndpointResolver('https://fixture.invalid')
  const auth = createAuthTransport({
    resolver, storage: { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    cache: { unbind() {} }, cookie: () => 'csrftoken=fixture',
    locks: { request: async (name, work) => { names.push(name); return work() } },
    fetcher: async () => { throw new Error('refresh must not run inside a Cookie mutation lock') },
  })
  auth.persist({ auth_mode: 'cookie', user: { id: 'user' }, tenant: { id: 'space' } })
  const location = { pathname: '/platform/settings', href: '' }
  const context = vm.createContext({ module: { exports: {} }, location, require: name => {
    if (name === 'axios') return axios
    if (name === './auth-transport.mjs') return { authTransport: auth }
    if (name === './endpoint.mjs') return { endpoint: resolver }
    if (name === './desktop-transport.mjs') return desktopTransport
    throw new Error(name)
  } })
  vm.runInContext(code, context)
  const client = context.module.exports.default
  client.defaults.adapter = async config => {
    const response = { status: 401, statusText: 'Unauthorized', headers: {}, config, data: { error: { code: 'unauthorized' } } }
    throw new axios.AxiosError('unauthorized', 'ERR_BAD_RESPONSE', config, undefined, response)
  }
  await assert.rejects(auth.sessionOperation(auth.generation(), async check => {
    await client.post('/api/v1/auth/change-password', {}, { skipAuthRefresh: true })
    check()
  }), error => error.status === 401)
  assert.equal(names.length, 1, 'only the mutation acquired the lock, never refresh')
  assert.equal(auth.mode(), '')
  assert.equal(location.href, '/login')
})

test('anonymous initialization validates existing CSRF cookies with the current service before sending chosen credentials', async () => {
  const resolver = new EndpointResolver('https://fixture.invalid')
  let csrfCalls = 0, sentHeaders
  const auth = createAuthTransport({ resolver, storage: { getItem: () => null, setItem() {}, removeItem() {} },
    cache: { unbind() {} }, cookie: () => 'csrftoken=old-service-cookie', locks: null,
    fetcher: async url => { assert.equal(url, 'https://fixture.invalid/api/v1/auth/csrf'); csrfCalls += 1; return { ok: true, json: async () => ({ data: { csrf_token: 'current-service-cookie' } }) } },
  })
  const context = vm.createContext({ module: { exports: {} }, location: { pathname: '/login', href: '' }, require: name => {
    if (name === 'axios') return axios
    if (name === './auth-transport.mjs') return { authTransport: auth }
    if (name === './endpoint.mjs') return { endpoint: resolver }
    if (name === './desktop-transport.mjs') return desktopTransport
    throw new Error(name)
  } })
  vm.runInContext(code, context)
  const client = context.module.exports.default
  client.defaults.adapter = async config => { sentHeaders = config.headers; return { status: 200, statusText: 'OK', headers: {}, config, data: { success: true, data: {} } } }
  await client.post('/api/v1/auth/auto-setup', { email: 'qa@example.invalid', password: 'chosen-fixture-password' })
  assert.equal(csrfCalls, 1)
  assert.equal(sentHeaders.get('X-CSRFToken'), 'current-service-cookie', 'a stale cookie must not overwrite the validated header')
  assert.equal(sentHeaders.get('Authorization'), undefined)
})


// Actual store/component + Axios + transport boundary. All I/O is an in-memory fake.
const { createRequire } = await import('node:module')
const requireForTests = createRequire(import.meta.url)
const pinia = requireForTests('pinia')
const vue = requireForTests('vue')
const { parse, compileScript } = requireForTests('@vue/compiler-sfc')
const storeCode = transformSync(readFileSync(new URL('../stores/auth.ts', import.meta.url), 'utf8'), { loader: 'ts', format: 'cjs' }).code
const { descriptor: deviceDescriptor } = parse(readFileSync(new URL('../views/settings/DeviceSessions.vue', import.meta.url), 'utf8'))
const deviceCode = transformSync(compileScript(deviceDescriptor, { id: 'sensitive-integration' }).content, { loader: 'ts', format: 'cjs' }).code
const tick = () => new Promise(resolve => setImmediate(resolve))
function serialLocks() {
  let tail = Promise.resolve(), active = 0
  const names = []
  return { names, request(name, work) {
    names.push(name)
    const next = tail.then(async () => {
      assert.equal(active, 0, 'lock is strictly exclusive and never reentrant')
      active += 1
      try { return await work() } finally { active -= 1 }
    })
    tail = next.catch(() => {})
    return next
  } }
}
function renewalHarness({ locks = serialLocks(), expired = true, refreshStatus = 200, mutationFailure,
  onFetch, onCookieRead, unknownRefresh = false, csrfValue = 'before', selectedTenant = 'space-a', refreshTenant = 'space-a' } = {}) {
  const rows = [], map = new Map([['personal_kb_service_id', 'service-a']])
  const storage = { getItem: key => map.get(key) ?? null, setItem: (key, value) => map.set(key, String(value)), removeItem: key => map.delete(key) }
  const resolver = new EndpointResolver('https://fixture.invalid')
  resolver.bind({ service_id: 'service-a', client_protocol: 1, auth_modes: ['cookie'] })
  let csrf = csrfValue, now = 1000000, accessUntil = expired ? now - 1 : now + 600000
  const identity = (tenant = selectedTenant) => ({ auth_mode: 'cookie', user: { id: 'user-a' }, tenant: { id: tenant }, device: { id: 'device-a', current: true }, access_expires_at: new Date(accessUntil).toISOString() })
  const response = (data, status = 200) => ({ status, ok: status >= 200 && status < 300, json: async () => ({ success: status === 200, data }) })
  let auth
  const fetcher = async (url, init = {}) => {
    const path = new URL(url).pathname
    rows.push({ path, method: init.method || 'GET' })
    if (onFetch) { const overridden = await onFetch(path, { storage, map, auth, identity, response, resolver }); if (overridden) return overridden }
    if (path === '/api/v1/auth/csrf') { csrf = 'initialized'; return response({ csrf_token: csrf }) }
    if (path === '/api/v1/capabilities') return response({ service_id: 'service-a', client_protocol: 1, auth_modes: ['cookie'] })
    if (path === '/api/v1/auth/me') return response(identity(), accessUntil > now ? 200 : 401)
    if (path === '/api/v1/auth/refresh') {
      assert.equal(init.headers['X-CSRFToken'], csrf)
      if (unknownRefresh) throw new Error('refresh outcome unknown')
      if (refreshStatus !== 200) return response({}, refreshStatus)
      accessUntil = now + 600000; csrf = 'after'
      return response(identity(refreshTenant))
    }
    throw new Error('unexpected fake path: ' + path)
  }
  let cookieReads = 0
  auth = createAuthTransport({ storage, resolver, locks, cache: { unbind() {} }, cookie: () => {
    cookieReads += 1; onCookieRead?.(cookieReads, { map, auth }); return 'csrftoken=' + csrf
  }, fetcher })
  auth.persist(identity())
  const location = { pathname: '/platform/settings', href: '' }
  const axiosContext = vm.createContext({ module: { exports: {} }, location, require: name => {
    if (name === 'axios') return axios
    if (name === './auth-transport.mjs') return { authTransport: auth }
    if (name === './endpoint.mjs') return { endpoint: resolver }
    if (name === './desktop-transport.mjs') return desktopTransport
    throw new Error(name)
  } })
  vm.runInContext(code, axiosContext)
  const client = axiosContext.module.exports.default
  let mutationCount = 0
  client.defaults.adapter = async config => {
    const path = new URL(config.url).pathname, unsafe = ['post', 'delete'].includes(config.method)
    if (unsafe) {
      mutationCount += 1
      rows.push({ path, method: config.method.toUpperCase(), csrf: config.headers.get('X-CSRFToken'), skip: config.skipAuthRefresh })
      if (mutationFailure) await mutationFailure(config)
    }
    const status = accessUntil > now ? 200 : 401
    const result = { status, statusText: '', headers: {}, config, data: { data: unsafe ? {} : { items: [] } } }
    if (status === 401) throw new axios.AxiosError('access expired', 'ERR_BAD_RESPONSE', config, undefined, result)
    return result
  }
  const api = { capabilities: () => client.get('/api/v1/capabilities'), devices: () => client.get('/api/v1/auth/devices'),
    changePassword: (data, config) => client.post('/api/v1/auth/change-password', data, config),
    revokeDevice: (id, config) => client.delete('/api/v1/auth/devices/' + id, config), logoutAll: config => client.post('/api/v1/auth/logout-all', {}, config) }
  const context = vm.createContext({ module: { exports: {} }, localStorage: storage, require: name => {
    if (name === 'pinia') return pinia
    if (name === '../services/langfuse') return { clearLangfuseSession: async () => {} }
    if (name === '../api') return { api }
    if (name === './auth-storage.mjs') return { safeParseStorage: key => key ? JSON.parse(key) : null }
    if (name === '../api/auth-transport.mjs') return { authTransport: auth }
    if (name === '../api/endpoint.mjs') return { endpoint: resolver }
    if (name === './device-store.mjs') return { deviceStore: { bind() {} } }
    throw new Error(name)
  } })
  vm.runInContext(storeCode, context); pinia.setActivePinia(pinia.createPinia())
  const store = context.module.exports.useAuthStore(); store.subscribe()
  const pushes = []
  const componentContext = vm.createContext({ module: { exports: {} }, require: name => {
    if (name === 'vue') return { ...vue, onMounted() {} }
    if (name === 'vue-router') return { useRouter: () => ({ replace: path => pushes.push(path) }) }
    if (name === '../../api') return { api }
    if (name === '../../stores/auth') return { useAuthStore: () => store }
    if (name === '../../api/auth-transport.mjs') return { authTransport: auth }
    throw new Error(name)
  } })
  vm.runInContext(deviceCode, componentContext)
  const scope = vue.effectScope()
  const component = scope.run(() => componentContext.module.exports.default.setup({}, { expose() {} }))
  const run = kind => kind === 'password' ? store.changePassword({ old_password: 'fixture-old', new_password: 'fixture-new' }) :
    kind === 'all' ? component.logoutAll() : (component.selected.value = { id: 'device-other', current: false }, component.revoke())
  return { auth, storage, map, rows, locks, location, component, store, run, pushes, resolver, fetcher, identity, cookie: () => 'csrftoken=' + csrf,
    get mutationCount() { return mutationCount }, advance: ms => { now += ms }, dispose: () => scope.stop() }
}

for (const lockMode of ['WebLocks', 'fallback']) for (const kind of ['password', 'revoke', 'all']) {
  test(`expired access is renewed before the first ${kind} mutation with ${lockMode}`, { timeout: 2000 }, async () => {
    const f = renewalHarness({ locks: lockMode === 'WebLocks' ? serialLocks() : null })
    try {
      await f.run(kind)
      assert.equal(f.component.error.value, '')
      assert.equal(f.mutationCount, 1)
      assert.equal(f.rows.filter(row => row.path === '/api/v1/auth/refresh').length, 1)
      const mutation = f.rows.find(row => row.method === 'DELETE' || row.path.endsWith('/change-password') || row.path.endsWith('/logout-all'))
      assert.equal(mutation.csrf, 'after'); assert.equal(mutation.skip, true)
      assert.equal(f.location.href, '')
      assert.equal(f.auth.mode(), kind === 'revoke' ? 'cookie' : '')
    } finally { f.dispose() }
  })
}

for (const kind of ['password', 'revoke', 'all']) for (const refreshStatus of [401, 403]) {
  test(`invalid refresh ${refreshStatus} blocks ${kind} before mutation`, async () => {
    const f = renewalHarness({ refreshStatus })
    try {
      if (kind === 'password') await assert.rejects(f.run(kind))
      else await f.run(kind)
      assert.equal(f.mutationCount, 0); assert.equal(f.auth.mode(), '')
    } finally { f.dispose() }
  })
}
for (const locks of [serialLocks(), null]) {
  test(`queued refresh behind sensitive work rechecks instead of deadlocking (${locks ? 'WebLocks' : 'fallback'})`, { timeout: 2000 }, async () => {
    let release, entered
    const held = new Promise(resolve => { release = resolve })
    const start = new Promise(resolve => { entered = resolve })
    let first = true
    const f = renewalHarness({ locks, onFetch: async path => {
      if (path.endsWith('/auth/me') && first) { first = false; entered(); await held }
    } })
    try {
      const revoking = f.run('revoke')
      await start
      const refreshing = f.auth.refresh()
      release()
      await Promise.all([revoking, refreshing])
      assert.equal(f.rows.filter(row => row.path.endsWith('/auth/refresh')).length, 1)
      assert.equal(f.mutationCount, 1); assert.equal(f.auth.mode(), 'cookie')
    } finally { f.dispose() }
  })
}
for (const field of ['user', 'service', 'boundService', 'tenant', 'selectedTenant', 'generation', 'device']) {
  test(`changed ${field} during preflight rejects the original sensitive intent`, async () => {
    let changed = false
    const f = renewalHarness({ onFetch: async (path, context) => {
      if (!path.endsWith('/auth/me') || changed) return
      changed = true
      if (field === 'user') context.map.set('personal_kb_user', '{"id":"user-b"}')
      if (field === 'service') context.map.set('personal_kb_service_id', 'service-b')
      if (field === 'tenant') context.map.set('personal_kb_tenant', '{"id":"space-b"}')
      if (field === 'selectedTenant') context.map.set('personal_kb_selected_tenant_id', 'space-b')
      if (field === 'generation') context.auth.invalidate({ clearCache: false })
      if (field === 'boundService') context.resolver.bind({ service_id: 'service-b', client_protocol: 1, auth_modes: ['cookie'] })
      if (field === 'device') context.auth.persist({ ...context.identity(), device: { id: 'device-b' } })
    } })
    try {
      // Storage mutation deliberately has no storage event; epoch alone is insufficient.
      await assert.rejects(f.run('password'))
      assert.equal(f.mutationCount, 0)
      assert.equal(f.rows.filter(row => row.path.endsWith('/auth/refresh')).length, 0)
    } finally { f.dispose() }
  })
}

test('refresh primary tenant does not replace the originally selected operation tenant', async () => {
  const f = renewalHarness({ selectedTenant: 'selected-space', refreshTenant: 'primary-space' })
  try {
    await f.run('revoke')
    assert.equal(f.component.error.value, '')
    assert.equal(f.map.get('personal_kb_selected_tenant_id'), 'selected-space')
    assert.equal(JSON.parse(f.map.get('personal_kb_tenant')).id, 'selected-space')
    assert.equal(f.mutationCount, 1)
  } finally { f.dispose() }
})

for (const kind of ['password', 'revoke', 'all']) {
  test(`${kind} unknown response is never automatically resent`, async () => {
    const f = renewalHarness({ mutationFailure: async () => { throw new Error('mutation outcome unknown') } })
    try {
      if (kind === 'password') await assert.rejects(f.run(kind))
      else await f.run(kind)
      assert.equal(f.mutationCount, 1)
      assert.equal(f.auth.mode(), 'cookie')
      assert.deepEqual(f.pushes, [])
    } finally { f.dispose() }
  })
}

test('unknown refresh result never replays the refresh or sends the mutation', async () => {
  const f = renewalHarness({ unknownRefresh: true })
  try {
    await assert.rejects(f.run('password'))
    assert.equal(f.mutationCount, 0)
    assert.equal(f.rows.filter(row => row.path.endsWith('/auth/refresh')).length, 1)
    assert.equal(f.auth.mode(), 'cookie')
  } finally { f.dispose() }
})

test('unknown refresh forbids later automatic consumption in this page and another tab', async () => {
  const f = renewalHarness({ unknownRefresh: true })
  try {
    await assert.rejects(f.run('password'))
    const other = createAuthTransport({ storage: f.storage, resolver: f.resolver, locks: f.locks, cache: { unbind() {} }, cookie: f.cookie, fetcher: f.fetcher })
    other.persist(f.identity())
    await assert.rejects(f.auth.refresh())
    await assert.rejects(other.refresh())
    assert.equal(f.rows.filter(row => row.path.endsWith('/auth/refresh')).length, 1)
    assert.equal(f.mutationCount, 0)
  } finally { f.dispose() }
})

test('two tabs serialize sensitive renewal and queued ordinary refresh without a second rotation', { timeout: 2000 }, async () => {
  let release, enter, first = true
  const hold = new Promise(resolve => { release = resolve }), entered = new Promise(resolve => { enter = resolve })
  const f = renewalHarness({ onFetch: async path => { if (path.endsWith('/auth/me') && first) { first = false; enter(); await hold } } })
  try {
    const other = createAuthTransport({ storage: f.storage, resolver: f.resolver, locks: f.locks, cache: { unbind() {} }, cookie: f.cookie, fetcher: f.fetcher })
    other.persist(f.identity())
    const revoke = f.run('revoke')
    await entered
    const refresh = other.refresh()
    release()
    await Promise.all([revoke, refresh])
    assert.equal(f.rows.filter(row => row.path.endsWith('/auth/refresh')).length, 1)
    assert.equal(f.mutationCount, 1)
  } finally { f.dispose() }
})

for (const phase of ['me', 'refresh']) for (const field of ['user', 'device']) {
  test(`${phase} response with different ${field} cannot authorize or replace the original account`, async () => {
    const f = renewalHarness({ expired: phase === 'refresh', onFetch: async (path, context) => {
      if (!path.endsWith('/auth/' + phase)) return
      const data = context.identity()
      data[field] = { id: field === 'user' ? 'user-b' : 'device-b' }
      return context.response(data)
    } })
    try {
      await assert.rejects(f.run('password'))
      assert.equal(f.mutationCount, 0)
      assert.equal(JSON.parse(f.map.get('personal_kb_user')).id, 'user-a')
    } finally { f.dispose() }
  })
}

test('changed live service proof prevents renewal and mutation', async () => {
  const f = renewalHarness({ onFetch: async (path, context) => path.endsWith('/capabilities') ? context.response({ service_id: 'service-b' }) : undefined })
  try {
    await assert.rejects(f.run('password'), /服务身份已改变/)
    assert.equal(f.mutationCount, 0)
    assert.equal(f.rows.filter(row => row.path.endsWith('/auth/refresh')).length, 0)
  } finally { f.dispose() }
})

test('selected tenant must also be proven after refresh rather than assumed from primary', async () => {
  let meCount = 0
  const f = renewalHarness({ refreshTenant: 'primary-space', onFetch: async (path, context) => {
    if (path.endsWith('/auth/me') && ++meCount === 2) return context.response(context.identity('primary-space'))
  } })
  try {
    await assert.rejects(f.run('password'))
    assert.equal(f.mutationCount, 0)
    assert.equal(f.map.get('personal_kb_selected_tenant_id'), 'space-a')
  } finally { f.dispose() }
})

for (const phase of ['me', 'refresh']) {
  test(`identity changed while parsing ${phase} JSON is fenced after that await`, async () => {
    const f = renewalHarness({ expired: phase === 'refresh', onFetch: async (path, context) => {
      if (!path.endsWith('/auth/' + phase)) return
      return { ok: true, status: 200, json: async () => {
        context.map.set('personal_kb_user', '{"id":"user-b"}')
        return { data: context.identity() }
      } }
    } })
    try {
      await assert.rejects(f.run('password'))
      assert.equal(f.mutationCount, 0)
      assert.equal(JSON.parse(f.map.get('personal_kb_user')).id, 'user-b')
    } finally { f.dispose() }
  })
}

for (const kind of ['password', 'revoke', 'all']) {
  test(`${kind} late success does not invalidate a newer account`, async () => {
    let finish, enter
    const hold = new Promise(resolve => { finish = resolve }), entered = new Promise(resolve => { enter = resolve })
    const f = renewalHarness({ mutationFailure: async () => { enter(); await hold } })
    try {
      const pending = f.run(kind)
      const rejected = kind === 'password' ? assert.rejects(pending, /登录/) : pending
      await entered
      f.auth.invalidate({ clearCache: false })
      f.auth.persist({ ...f.identity(), user: { id: 'user-b' }, tenant: { id: 'space-b' }, device: { id: 'device-b' } })
      const generation = f.auth.generation()
      finish(); await rejected
      assert.equal(f.auth.generation(), generation)
      assert.equal(f.auth.mode(), 'cookie')
      assert.equal(JSON.parse(f.map.get('personal_kb_user')).id, 'user-b')
      assert.equal(f.mutationCount, 1)
      assert.deepEqual(f.pushes, [])
    } finally { f.dispose() }
  })
}

test('CSRF failure before refresh send is not recorded as uncertain token consumption', async () => {
  const f = renewalHarness({ csrfValue: '', onFetch: async path => { if (path.endsWith('/auth/csrf')) throw new Error('csrf unavailable') } })
  try {
    await assert.rejects(f.run('password'))
    assert.equal(f.mutationCount, 0)
    assert.equal(f.rows.filter(row => row.path.endsWith('/auth/refresh')).length, 0)
    assert.equal(f.map.get('personal_kb_refresh_uncertain'), undefined)
    assert.equal(f.auth.mode(), 'cookie')
  } finally { f.dispose() }
})

test('different user during mutation CSRF await is rejected before Axios sends', async () => {
  const f = renewalHarness({ expired: false, csrfValue: '', onFetch: async (path, context) => {
    if (path.endsWith('/auth/csrf')) context.map.set('personal_kb_user', '{"id":"user-b"}')
  } })
  try {
    await assert.rejects(f.run('password'))
    assert.equal(f.mutationCount, 0)
    assert.equal(JSON.parse(f.map.get('personal_kb_user')).id, 'user-b')
  } finally { f.dispose() }
})

for (const field of ['user', 'tenant', 'selectedTenant', 'service', 'device']) {
  test(`actual Axios cached-CSRF await fences microtask ${field} change before mutation send`, async () => {
    const f = renewalHarness({ expired: false, onCookieRead: (count, context) => {
      if (count !== 3) return
      queueMicrotask(() => {
        if (field === 'user') context.map.set('personal_kb_user', '{"id":"user-b"}')
        if (field === 'tenant') context.map.set('personal_kb_tenant', '{"id":"space-b"}')
        if (field === 'selectedTenant') context.map.set('personal_kb_selected_tenant_id', 'space-b')
        if (field === 'service') context.map.set('personal_kb_service_id', 'service-b')
        if (field === 'device') context.auth.persist({ auth_mode: 'cookie', user: { id: 'user-a' }, tenant: { id: 'space-a' }, device: { id: 'device-b' } })
      })
    } })
    try {
      await assert.rejects(f.run('password'))
      assert.equal(f.mutationCount, 0)
    } finally { f.dispose() }
  })
}
