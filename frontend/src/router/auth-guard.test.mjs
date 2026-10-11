import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import { createRequire } from 'node:module'
import { transformSync } from 'esbuild'
import { createAuthTransport } from '../api/auth-transport.mjs'
import { EndpointResolver } from '../api/endpoint.mjs'
import { DeviceStore } from '../stores/device-store.mjs'
import { safeParseStorage } from '../stores/auth-storage.mjs'

// Execute the actual router guard/store/transport; only HTTP and browser boundaries are stubbed.
const require = createRequire(import.meta.url)
const pinia = require('pinia')
const FAKE_TOKEN = 'fixture-token-not-real'
const FAKE_TMP_PASSWORD = 'fixture-tmp-9137-not-real'
const toCjs = (path) => transformSync(readFileSync(new URL(path, import.meta.url), 'utf8'), { loader: 'ts', format: 'cjs', target: 'es2022' }).code
function makeStorage(initial = {}) {
  const map = new Map(Object.entries(initial)), writes = []
  return { storage: { getItem: (k) => map.get(k) ?? null,
    setItem: (k, v) => { writes.push([k, String(v)]); map.set(k, String(v)) }, removeItem: (k) => map.delete(k),
    key: (index) => [...map.keys()][index], get length() { return map.size } }, writes, map }
}
function envelope({ withTempPassword = true, legacy = false } = {}) {
  const data = { device: legacy ? null : { id: 'fixture-device' }, auth_mode: legacy ? 'legacy_bearer' : 'cookie', user: { id: 'fixture-user', username: 'fixture-admin', email: 'fixture-admin@example.invalid' }, tenant: { id: 7, name: 'fixture space' } }
  if (legacy) Object.assign(data, { token: FAKE_TOKEN, refresh_token: 'fixture-refresh-not-real' })
  if (withTempPassword) data.temp_password = FAKE_TMP_PASSWORD
  return { success: true, data }
}
function makeApi({ autoSetup, login, loggedIn = false, legacy = false, me, changePassword } = {}) {
  const calls = { autoSetup: [], login: [], me: [], logout: [], changePassword: [] }
  const api = {
    capabilities: async () => ({ data: { service_id: 'fixture-service', client_protocol: 1, auth_modes: ['cookie', 'legacy_bearer'] } }),
    autoSetup: (...args) => { calls.autoSetup.push(args); return (autoSetup || (async () => envelope()))(...args) },
    login: (...args) => { calls.login.push(args); return (login || (async () => envelope({ withTempPassword: false })))(...args) },
    me: async () => { calls.me.push([]); if (me) return me(); if (!loggedIn) throw { status: 401 }; return envelope({ legacy, withTempPassword: false }) },
    logout: async (...args) => { calls.logout.push(args); return { data: {} } },
    changePassword: async (...args) => { calls.changePassword.push(args); return changePassword ? changePassword(...args) : { data: {} } },
  }
  return { api, calls }
}
function makeStore({ token = '', api, initialStorage = {}, locks = null, fetcher } = {}) {
  const bundle = api || makeApi({ loggedIn: !!token, legacy: !!token })
  const storage = makeStorage({ ...initialStorage, ...(token ? { personal_kb_token: token } : {}) })
  const endpoint = new EndpointResolver('https://fixture.example.invalid')
  const deviceStore = new DeviceStore(storage.storage)
  const authTransport = createAuthTransport({ storage: storage.storage, resolver: endpoint, cache: deviceStore, cookie: () => 'csrftoken=fixture', locks, fetcher: fetcher || (async url => {
    if (url.endsWith('/capabilities')) return { ok: true, status: 200, json: async () => ({ data: { service_id: 'fixture-service' } }) };
    if (url.endsWith('/auth/me')) return { ok: true, status: 200, json: async () => envelope({ withTempPassword: false }) };
    throw new Error('unexpected refresh');
  }) })
  const context = vm.createContext({ module: { exports: {} }, localStorage: storage.storage,
    require: (name) => {
      if (name === '../services/langfuse') return { clearLangfuseSession: async () => {} }
      if (name === 'pinia') return pinia
      if (name === '../api') return { api: bundle.api }
      if (name === './auth-storage.mjs') return { safeParseStorage }
      if (name === '../api/auth-transport.mjs') return { authTransport }
      if (name === '../api/endpoint.mjs') return { endpoint }
      if (name === './device-store.mjs') return { deviceStore }
      throw new Error(`unexpected require: ${name}`)
    } })
  vm.runInContext(toCjs('../stores/auth.ts'), context)
  pinia.setActivePinia(pinia.createPinia())
  return { store: context.module.exports.useAuthStore(), storage, api: bundle, endpoint, authTransport, deviceStore }
}
function makeRouterHarness(options) {
  const setup = makeStore(options), registered = []
  const context = vm.createContext({ module: { exports: {} }, require: (name) => {
    if (name === 'vue-router') return { createRouter: () => ({ beforeEach: (guard) => registered.push(guard) }), createWebHistory: () => ({}) }
    if (name === '../stores/auth') return { useAuthStore: () => setup.store }
    if (name.endsWith('.vue')) return {}
    throw new Error(`unexpected router require: ${name}`)
  } })
  vm.runInContext(toCjs('../router/index.ts'), context)
  assert.equal(registered.length, 1)
  assert.equal(registered[0], context.module.exports.authGuard)
  return { ...setup, guard: context.module.exports.authGuard }
}

test('protected navigation validates server identity and never silently creates accounts', async () => {
  const { guard, api } = makeRouterHarness()
  assert.equal(await guard({ meta: {} }), '/login')
  assert.equal(api.calls.me.length, 1)
  assert.equal(api.calls.autoSetup.length, 0)
})

test('public navigation makes no authentication or initialization requests', async () => {
  const { guard, api } = makeRouterHarness()
  assert.equal(await guard({ meta: { public: true } }), true)
  assert.equal(api.calls.me.length, 0)
  assert.equal(api.calls.autoSetup.length, 0)
})

test('cookie and legacy sessions pass only after a server-authenticated me response', async () => {
  for (const options of [{ api: makeApi({ loggedIn: true }) }, { token: FAKE_TOKEN }]) {
    const { guard, api, store } = makeRouterHarness(options)
    assert.equal(await guard({ meta: {} }), true)
    assert.equal(store.authenticated, true)
    assert.equal(api.calls.me.length, 1)
    assert.equal(api.calls.autoSetup.length, 0)
  }
})

test('cached user metadata is not proof of a valid cookie session', async () => {
  const { guard } = makeRouterHarness({ initialStorage: { personal_kb_user: '{"id":"cached"}' } })
  assert.equal(await guard({ meta: {} }), '/login')
})

test('autoSetup returns one-time credentials but persists no password or web tokens', async () => {
  const { store, storage, api } = makeStore()
  const data = await store.autoSetup()
  assert.equal(api.calls.autoSetup.length, 1)
  assert.equal(data.temp_password, FAKE_TMP_PASSWORD)
  assert.equal(store.token, '')
  assert.equal(storage.map.get('personal_kb_auth_mode'), 'cookie')
  assert.equal(storage.map.get('personal_kb_token'), undefined)
  assert.equal(storage.map.get('personal_kb_refresh_token'), undefined)
  assert.ok(storage.writes.every(([, value]) => !value.includes(FAKE_TMP_PASSWORD)))
})

test('autoSetup without temporary credentials still establishes a cookie session', async () => {
  const { store, storage } = makeStore({ api: makeApi({ autoSetup: async () => envelope({ withTempPassword: false }) }) })
  assert.equal((await store.autoSetup()).temp_password, undefined)
  assert.equal(store.authenticated, true)
  assert.equal(storage.map.get('personal_kb_token'), undefined)
})

test('normal login stores a cookie marker, never reusable browser credentials', async () => {
  const { store, storage, api } = makeStore({ token: FAKE_TOKEN })
  await store.login('fixture-admin@example.invalid', FAKE_TMP_PASSWORD)
  assert.equal(api.calls.login.length, 1)
  assert.deepEqual({ ...api.calls.login[0][0] }, { email: 'fixture-admin@example.invalid', password: FAKE_TMP_PASSWORD })
  assert.equal(store.token, '')
  assert.equal(storage.map.get('personal_kb_token'), undefined)
  assert.equal(storage.map.get('personal_kb_refresh_token'), undefined)
  assert.equal(store.authenticated, true)
  assert.ok(storage.writes.every(([, value]) => !value.includes(FAKE_TMP_PASSWORD)))
})

test('a changed service identity invalidates credentials and allows explicit re-login next time', async () => {
  const { store, storage } = makeStore({ token: FAKE_TOKEN, initialStorage: { personal_kb_service_id: 'other-service' } })
  await assert.rejects(store.bindService(), error => error.code === 'service_identity_changed' && /服务身份已改变/.test(error.message))
  assert.equal(storage.map.get('personal_kb_token'), undefined)
  await store.login('fixture@example.invalid', 'fixture-password')
  assert.equal(store.authenticated, true)
})

test('logout unbinds and clears the active device cache, then revokes server session', async () => {
  const { store, deviceStore, api, storage } = makeStore()
  await store.login('fixture@example.invalid', 'fixture-password')
  deviceStore.write('draft', 'fixture-session', 'private draft')
  await store.logout()
  assert.equal(store.authenticated, false)
  assert.equal(api.calls.logout.length, 1)
  assert.equal(storage.map.get('personal_kb_auth_mode'), undefined)
  assert.throws(() => deviceStore.read('draft', 'fixture-session'))
})

test('a pending cookie login cannot persist after logout invalidates its generation', async () => {
  let complete
  const pending = new Promise((resolve) => { complete = resolve })
  const { store, storage } = makeStore({ api: makeApi({ login: () => pending }) })
  const loggingIn = store.login('fixture@example.invalid', 'fixture-password')
  await new Promise((resolve) => setImmediate(resolve))
  const rejected = assert.rejects(loggingIn, /登录已结束/)
  const loggingOut = store.logout()
  complete(envelope({ withTempPassword: false }))
  await rejected
  await loggingOut
  assert.equal(store.authenticated, false)
  assert.equal(storage.map.get('personal_kb_auth_mode'), undefined)
})

test('a pending initialization cannot persist after logout', async () => {
  let complete
  const pending = new Promise((resolve) => { complete = resolve })
  const { store, storage } = makeStore({ api: makeApi({ autoSetup: () => pending }) })
  const settingUp = store.autoSetup()
  await new Promise((resolve) => setImmediate(resolve))
  const rejected = assert.rejects(settingUp, /登录已结束/)
  const loggingOut = store.logout()
  complete(envelope())
  await rejected
  await loggingOut
  assert.equal(store.authenticated, false)
  assert.equal(storage.map.get('personal_kb_auth_mode'), undefined)
})

test('refresh session updates the live Pinia identity rather than only browser metadata', async () => {
  const { store, authTransport } = makeStore()
  await store.login('fixture@example.invalid', 'fixture-password')
  authTransport.persist({ ...envelope().data, user: { id: 'new-user', username: 'new-account' }, tenant: { id: 'new-space' } })
  assert.equal(store.user.id, 'new-user')
  assert.equal(store.tenant.id, 'new-space')
  assert.equal(store.token, '')
})

function queuedLocks() {
  let tail = Promise.resolve()
  const names = []
  return { names, request: (name, work) => {
    names.push(name)
    const next = tail.then(work)
    tail = next.catch(() => {})
    return next
  } }
}

test('Cookie login and logout share the origin lock until the late login response has finished', async () => {
  let complete
  const pending = new Promise((resolve) => { complete = resolve })
  const locks = queuedLocks()
  const { store, storage, api } = makeStore({ locks, api: makeApi({ login: () => pending }) })
  const loggingIn = store.login('fixture@example.invalid', 'fixture-password')
  const rejectedLogin = assert.rejects(loggingIn, /登录已结束/)
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(api.calls.login.length, 1)
  const loggingOut = store.logout()
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(api.calls.logout.length, 0, 'logout cannot clear Cookie before a still-pending login sets it')
  complete(envelope({ withTempPassword: false }))
  await rejectedLogin
  await loggingOut
  assert.equal(api.calls.logout.length, 1)
  assert.equal(storage.map.get('personal_kb_auth_mode'), undefined)
  assert.equal(store.authenticated, false)
  assert.deepEqual(locks.names, ['personal-kb-refresh:https://fixture.example.invalid', 'personal-kb-refresh:https://fixture.example.invalid'])
  assert.equal(api.calls.logout[0][0].headers['X-CSRFToken'], undefined, 'no captured stale CSRF overrides the client interceptor')
})

test('a queued Cookie login is fenced before sending when logout is the later user intent', async () => {
  const locks = queuedLocks()
  let release
  const block = locks.request('personal-kb-refresh:https://fixture.example.invalid', () => new Promise((resolve) => { release = resolve }))
  await new Promise((resolve) => setImmediate(resolve))
  const { store, api } = makeStore({ locks })
  const loggingIn = store.login('fixture@example.invalid', 'fixture-password')
  const rejected = assert.rejects(loggingIn, /登录已结束/)
  const loggingOut = store.logout()
  release()
  await block
  await rejected
  await loggingOut
  assert.equal(api.calls.login.length, 0)
  assert.equal(api.calls.logout.length, 1)
})

test('a completed refresh stays inside the shared lock before the next login is sent', async () => {
  let complete
  const pending = new Promise((resolve) => { complete = resolve })
  const order = [], locks = queuedLocks()
  const bundle = makeApi({ login: async () => { order.push('login'); return envelope({ withTempPassword: false }) } })
  const { store, authTransport } = makeStore({ locks, api: bundle, initialStorage: { personal_kb_auth_mode: 'cookie' }, fetcher: async url => { if (url.endsWith('/auth/me')) return { ok: false, status: 401, json: async () => ({}) }; order.push('refresh'); return pending } })
  const refreshing = authTransport.refresh()
  const refreshRejected = assert.rejects(refreshing, /登录已结束/)
  await new Promise((resolve) => setImmediate(resolve))
  const loggingIn = store.login('fixture@example.invalid', 'fixture-password')
  await new Promise((resolve) => setImmediate(resolve))
  assert.deepEqual(order, ['refresh'])
  complete({ ok: true, json: async () => envelope({ withTempPassword: false }) })
  await refreshRejected
  await loggingIn
  assert.deepEqual(order, ['refresh', 'login'])
  assert.equal(store.authenticated, true)
})

test('legacy Bearer logout retains Authorization without using the Cookie operation lock', async () => {
  const locks = queuedLocks()
  const { store, api } = makeStore({ token: FAKE_TOKEN, locks })
  await store.logout()
  assert.equal(api.calls.logout[0][0].headers.Authorization, `Bearer ${FAKE_TOKEN}`)
  assert.deepEqual(locks.names, [])
})

test('password change uses the Cookie lock and clears the live session after confirmed success', async () => {
  const locks = queuedLocks()
  const { store, api, authTransport } = makeStore({ locks })
  await store.login('fixture@example.invalid', 'fixture-password')
  await store.changePassword({ old_password: 'fixture-password', new_password: 'fixture-new-password' })
  assert.equal(api.calls.changePassword.length, 1)
  assert.equal(api.calls.changePassword[0][1].skipAuthRefresh, true)
  assert.equal(authTransport.mode(), '')
  assert.equal(store.authenticated, false)
  assert.ok(locks.names.every(name => name === 'personal-kb-refresh:https://fixture.example.invalid'))
})

test('failed password validation keeps the current live session', async () => {
  const { store } = makeStore({ api: makeApi({ changePassword: async () => { throw { status: 400, message: 'old password mismatch' } } }) })
  await store.login('fixture@example.invalid', 'fixture-password')
  await assert.rejects(store.changePassword({}), error => error.status === 400)
  assert.equal(store.authenticated, true)
})

test('late password change response cannot invalidate a newer login intent', async () => {
  let complete
  const pending = new Promise(resolve => { complete = resolve })
  const { store, authTransport } = makeStore({ api: makeApi({ changePassword: () => pending }) })
  await store.login('fixture@example.invalid', 'fixture-password')
  const changing = store.changePassword({})
  const rejected = assert.rejects(changing, /登录已结束/)
  await new Promise(resolve => setImmediate(resolve))
  authTransport.invalidate()
  const newerGeneration = authTransport.generation()
  complete({ data: {} })
  await rejected
  assert.equal(authTransport.generation(), newerGeneration)
})

test('without Web Locks, same-page Cookie logout still waits for a pending login response', async () => {
  let complete
  const pending = new Promise(resolve => { complete = resolve })
  const { store, api } = makeStore({ locks: null, api: makeApi({ login: () => pending }) })
  const loggingIn = store.login('fixture@example.invalid', 'fixture-password')
  const rejected = assert.rejects(loggingIn, /登录已结束/)
  await new Promise(resolve => setImmediate(resolve))
  const loggingOut = store.logout()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(api.calls.logout.length, 0)
  complete(envelope({ withTempPassword: false }))
  await rejected
  await loggingOut
  assert.equal(api.calls.logout.length, 1)
  assert.equal(store.authenticated, false)
})
