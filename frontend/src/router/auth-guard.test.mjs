import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import { createRequire } from 'node:module'
import { transformSync } from 'esbuild'

// Execute the real router guard and the real auth store module.
// Boundaries (vue-router, api client, langfuse service, localStorage) are stubbed.
const require = createRequire(import.meta.url)
const pinia = require('pinia')

const FAKE_TOKEN = 'fixture-token-not-real'
const FAKE_TMP_PASSWORD = 'fixture-tmp-9137-not-real'

function toCjs(relPath) {
  return transformSync(readFileSync(new URL(relPath, import.meta.url), 'utf8'), {
    loader: 'ts', format: 'cjs', target: 'es2022',
  }).code
}

function makeStorage(initial = {}) {
  const map = new Map(Object.entries(initial))
  const writes = []
  return {
    storage: {
      getItem: (k) => (map.has(k) ? map.get(k) : null),
      setItem: (k, v) => { writes.push([k, String(v)]); map.set(k, String(v)) },
      removeItem: (k) => { map.delete(k) },
    },
    writes,
    map,
  }
}

function envelope({ withTempPassword = true } = {}) {
  const data = {
    user: { username: 'fixture-admin', email: 'fixture-admin@example.invalid' },
    tenant: { id: 7, name: 'fixture space' },
    token: FAKE_TOKEN,
    refresh_token: 'fixture-refresh-not-real',
  }
  if (withTempPassword) data.temp_password = FAKE_TMP_PASSWORD
  return { success: true, message: 'success', data }
}

function makeApi({ autoSetup, login } = {}) {
  const calls = { autoSetup: [], login: [] }
  const impl = {
    autoSetup: autoSetup || (async () => envelope()),
    login: login || (async () => envelope()),
  }
  const api = {
    autoSetup: (...args) => { calls.autoSetup.push(args); return impl.autoSetup(...args) },
    login: (...args) => { calls.login.push(args); return impl.login(...args) },
  }
  return { api, calls }
}

// auth.ts executed in a sandbox: langfuse + api stubbed, storage/pinia real-ish
function loadAuthModule({ localStorage, api }) {
  const loaded = {}
  const context = vm.createContext({
    module: { exports: {} },
    require: (name) => {
      if (name === '../services/langfuse') return { clearLangfuseSession: async () => {} }
      if (name === 'pinia') return pinia
      if (name === '../api') return { api }
      if (name === './auth-storage.mjs') {
        if (!loaded.storage) {
          const ctx = vm.createContext({ module: { exports: {} }, require: () => { throw new Error('unexpected require from auth-storage') } })
          vm.runInContext(toCjs('../stores/auth-storage.mjs'), ctx, { filename: 'auth-storage.mjs' })
          loaded.storage = ctx.module.exports
        }
        return loaded.storage
      }
      throw new Error(`auth.ts unexpectedly requires ${name}`)
    },
    localStorage,
  })
  vm.runInContext(toCjs('../stores/auth.ts'), context, { filename: 'auth.ts' })
  return context.module.exports
}

function makeStore({ token = '', api } = {}) {
  const bundle = api || makeApi()
  const storage = makeStorage(token ? { personal_kb_token: token } : {})
  const authModule = loadAuthModule({ localStorage: storage.storage, api: bundle.api })
  pinia.setActivePinia(pinia.createPinia())
  const store = authModule.useAuthStore()
  return { store, storage, api: bundle }
}

function loadRouterModule({ authModule, storage }) {
  const registered = []
  const context = vm.createContext({
    module: { exports: {} },
    require: (name) => {
      if (name === 'vue-router') {
        return {
          createRouter: () => ({ beforeEach: (guard) => registered.push(guard) }),
          createWebHistory: () => ({}),
        }
      }
      if (name === '../stores/auth') return authModule
      if (name === '../views/Login.vue') return {}
      if (name === '../views/Platform.vue') return {}
      throw new Error(`router/index.ts unexpectedly requires ${name}`)
    },
    localStorage: storage.storage,
  })
  vm.runInContext(toCjs('../router/index.ts'), context, { filename: 'router/index.ts' })
  return { exports: context.module.exports, registered }
}

function makeRouterHarness({ token = '' } = {}) {
  const api = makeApi()
  const { store, storage } = makeStore({ token, api })
  const authModule = { useAuthStore: () => store }
  const { exports, registered } = loadRouterModule({ authModule, storage })
  assert.equal(registered.length, 1, 'router must register exactly the auth guard')
  assert.equal(registered[0], exports.authGuard, 'registered guard must be the exported authGuard')
  return { guard: exports.authGuard, api, store, storage }
}

test('router with no token sends protected pages to /login and never initializes accounts', async () => {
  const { guard, api } = makeRouterHarness({ token: '' })
  const target = { meta: {} }
  assert.equal(await guard(target), '/login')
  assert.equal(api.calls.autoSetup.length, 0, 'no silent account creation from navigation')
})

test('router passes public pages and tokened protected pages through without initialization', async () => {
  for (const [to, token] of [
    [{ meta: { public: true } }, ''],
    [{ meta: {} }, FAKE_TOKEN],
    [{ meta: { public: true } }, FAKE_TOKEN],
  ]) {
    const { guard, api } = makeRouterHarness({ token })
    assert.equal(await guard(to), true)
    assert.equal(api.calls.autoSetup.length, 0)
  }
})

test('autoSetup returns the response data including temp_password but storage never sees it', async () => {
  const { store, storage, api } = makeStore({})
  assert.equal(api.calls.autoSetup.length, 0)
  const data = await store.autoSetup()
  assert.equal(api.calls.autoSetup.length, 1)
  assert.equal(data.temp_password, FAKE_TMP_PASSWORD, 'caller needs the one-time password')
  assert.equal(store.token, FAKE_TOKEN)
  assert.deepEqual(storage.writes.filter(([key]) => key.startsWith('personal_kb')), [
    ['personal_kb_user', JSON.stringify(envelope().data.user)],
    ['personal_kb_tenant', JSON.stringify(envelope().data.tenant)],
    ['personal_kb_token', FAKE_TOKEN],
    ['personal_kb_selected_tenant_id', '7'],
    ['personal_kb_refresh_token', 'fixture-refresh-not-real'],
  ])
  for (const [key, value] of storage.writes) {
    assert.ok(!String(value).includes(FAKE_TMP_PASSWORD), `temp_password leaked into ${key}`)
  }
  assert.ok(!storage.map.has('personal_kb_temp_password'), 'temp_password must not gain its own storage key')
})

test('autoSetup without a temp_password in the response still persists known auth fields', async () => {
  const noTemp = makeApi({ autoSetup: async () => envelope({ withTempPassword: false }) })
  const { store, storage } = makeStore({ api: noTemp })
  const data = await store.autoSetup()
  assert.equal(data.temp_password, undefined)
  assert.equal(store.token, FAKE_TOKEN)
  assert.ok(storage.map.get('personal_kb_token'))
  assert.ok(storage.writes.every(([, value]) => !String(value).includes('temp_password')))
})

test('normal login keeps persisting credentials and needs no temp_password', async () => {
  const { store, storage, api } = makeStore({})
  await store.login('fixture-admin@example.invalid', FAKE_TMP_PASSWORD)
  assert.equal(api.calls.login.length, 1)
  assert.deepEqual({ ...api.calls.login[0][0] }, { email: 'fixture-admin@example.invalid', password: FAKE_TMP_PASSWORD })
  assert.equal(store.token, FAKE_TOKEN)
  assert.ok(storage.map.get('personal_kb_token'))
  assert.ok(storage.writes.every(([, value]) => !String(value).includes(FAKE_TMP_PASSWORD)))
})
