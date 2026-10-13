import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import { transformSync } from 'esbuild'
import { EndpointResolver } from './endpoint.mjs'
import { DeviceStore } from '../stores/device-store.mjs'

// CD-15: execute the complete production transport across document lifetimes.
// Only browser storage/navigation and HTTP boundaries are substituted.
const source = transformSync(readFileSync(new URL('./auth-transport.mjs', import.meta.url), 'utf8'), {
  format: 'cjs', target: 'es2022',
}).code
const identityEvent = (identity, event) => JSON.stringify({ identity, event })
const identityA = JSON.stringify(['fixture-service', 'user-a', 'space-a'])
const identityB = JSON.stringify(['fixture-service', 'user-b', 'space-b'])
const eventA = identityEvent(identityA, 'fixture-event-a')
const eventB = identityEvent(identityB, 'fixture-event-b')
function memoryStorage(initial = {}) {
  const items = new Map(Object.entries(initial))
  return { getItem: key => items.get(key) ?? null, setItem: (key, value) => items.set(key, String(value)),
    removeItem: key => items.delete(key), key: index => [...items.keys()][index], get length() { return items.size }, items }
}
function sharedStorage() {
  return memoryStorage({ personal_kb_service_id: 'fixture-service', personal_kb_auth_mode: 'cookie',
    personal_kb_user: JSON.stringify({ id: 'user-a' }), personal_kb_tenant: JSON.stringify({ id: 'space-a' }),
    personal_kb_selected_tenant_id: 'space-a', personal_kb_identity_event: eventA })
}
function commitIdentity(storage, { sameAccount = false } = {}) {
  storage.setItem('personal_kb_auth_mode', 'cookie')
  storage.setItem('personal_kb_user', JSON.stringify({ id: sameAccount ? 'user-a' : 'user-b' }))
  storage.setItem('personal_kb_tenant', JSON.stringify({ id: sameAccount ? 'space-a' : 'space-b' }))
  storage.setItem('personal_kb_identity_event', sameAccount ? identityEvent(identityA, 'fixture-event-a-new-login') : eventB)
}
function beginLogout(storage) {
  for (const key of ['personal_kb_auth_mode', 'personal_kb_user', 'personal_kb_tenant', 'personal_kb_selected_tenant_id']) storage.removeItem(key)
  storage.setItem('personal_kb_logout_event', 'fixture-logout')
}
function documentHarness(storage, tabStorage, pathname = '/platform/knowledge-bases') {
  const navigation = [], listeners = new Map(), calls = []
  const resolver = new EndpointResolver('https://fixture.example.invalid')
  const cache = new DeviceStore(storage)
  const context = vm.createContext({ module: { exports: {} }, localStorage: storage, sessionStorage: tabStorage,
    location: { origin: resolver.origin, pathname, assign: path => navigation.push(path) },
    addEventListener: (name, listener) => listeners.set(name, listener),
    require: name => {
      if (name === './endpoint.mjs') return { endpoint: resolver }
      if (name === '../stores/device-store.mjs') return { deviceStore: cache }
      if (name === './desktop-transport.mjs') return { desktopBridge: null,
        applicationFetch: (...args) => { calls.push(args); throw new Error('navigation must not authenticate from metadata') } }
      throw new Error(`unexpected import: ${name}`)
    } })
  vm.runInContext(source, context)
  assert.equal(typeof listeners.get('storage'), 'function', 'the new document must listen before reconciling a handoff')
  return { navigation, cache, auth: context.module.exports.authTransport, calls,
    storageEvent: (key, newValue) => listeners.get('storage')({ key, newValue }) }
}

test('CD-15 missed identity event is recovered after cross-tab logout loads a new document', () => {
  const storage = sharedStorage(), tabStorage = memoryStorage()
  const old = documentHarness(storage, tabStorage)
  const generation = old.auth.generation()
  old.cache.bind('fixture-service', 'user-a', 'space-a')
  old.cache.write('draft', 'private-a', 'private draft')
  beginLogout(storage)
  old.storageEvent('personal_kb_logout_event', 'fixture-logout')
  assert.deepEqual(old.navigation, ['/login'])
  assert.ok(old.auth.generation() > generation)
  assert.equal(old.auth.mode(), '')
  assert.throws(() => old.cache.read('draft', 'private-a'))
  commitIdentity(storage) // B finishes while A's old listener is gone and the new one is not installed.
  const next = documentHarness(storage, tabStorage, '/login')
  assert.deepEqual(next.navigation, ['/platform/knowledge-bases'])
  assert.deepEqual(next.calls, [], 'only the existing protected router guard may prove server authentication')
  assert.equal(tabStorage.items.size, 0, 'consume the handoff once')
})

test('CD-15 queued logout snapshots the observed identity, even if B committed before its handler runs', () => {
  const storage = sharedStorage(), tabStorage = memoryStorage()
  const old = documentHarness(storage, tabStorage)
  beginLogout(storage)
  commitIdentity(storage)
  old.storageEvent('personal_kb_logout_event', 'fixture-logout')
  const next = documentHarness(storage, tabStorage, '/login')
  assert.deepEqual(next.navigation, ['/platform/knowledge-bases'])
})

test('CD-15 a handoff consumed before B commits stays logged out until the live identity event', () => {
  const storage = sharedStorage(), tabStorage = memoryStorage()
  const old = documentHarness(storage, tabStorage)
  beginLogout(storage)
  old.storageEvent('personal_kb_logout_event', 'fixture-logout')
  const next = documentHarness(storage, tabStorage, '/login')
  assert.deepEqual(next.navigation, [])
  assert.equal(next.auth.mode(), '')
  commitIdentity(storage)
  next.storageEvent('personal_kb_identity_event', eventB)
  assert.deepEqual(next.navigation, ['/platform/knowledge-bases'])
})

test('CD-15 explicit navigation to login keeps registration available while a cookie session exists', () => {
  const storage = sharedStorage(), tabStorage = memoryStorage()
  commitIdentity(storage)
  const page = documentHarness(storage, tabStorage, '/login')
  assert.deepEqual(page.navigation, [])
  assert.deepEqual(page.calls, [])
})

test('CD-15 true logout or failed replacement cannot revive A on the login page', () => {
  const storage = sharedStorage(), tabStorage = memoryStorage()
  const old = documentHarness(storage, tabStorage)
  beginLogout(storage)
  old.storageEvent('personal_kb_logout_event', 'fixture-logout')
  const next = documentHarness(storage, tabStorage, '/login')
  assert.deepEqual(next.navigation, [])
  assert.equal(next.auth.mode(), '')
  assert.deepEqual(next.calls, [])
})

test('CD-15 a later logout removes the established mode before missed-event reconciliation', () => {
  const storage = sharedStorage(), tabStorage = memoryStorage()
  const old = documentHarness(storage, tabStorage)
  beginLogout(storage)
  old.storageEvent('personal_kb_logout_event', 'fixture-logout')
  commitIdentity(storage)
  beginLogout(storage) // A fresh logout/revocation wins over B's earlier successful identity.
  const next = documentHarness(storage, tabStorage, '/login')
  assert.deepEqual(next.navigation, [])
  assert.equal(next.auth.mode(), '')
})

test('CD-15 unavailable tab storage still fences old requests and navigates safely to login', () => {
  const unavailable = { getItem() { throw new Error('blocked') }, setItem() { throw new Error('blocked') }, removeItem() { throw new Error('blocked') } }
  const storage = sharedStorage()
  const old = documentHarness(storage, unavailable)
  beginLogout(storage)
  assert.doesNotThrow(() => old.storageEvent('personal_kb_logout_event', 'fixture-logout'))
  assert.deepEqual(old.navigation, ['/login'])
  assert.equal(old.auth.mode(), '')
  commitIdentity(storage)
  const next = documentHarness(storage, unavailable, '/login')
  assert.deepEqual(next.navigation, [], 'unavailable storage must not fabricate a handoff')
})

test('CD-15 reopening a protected page consumes old handoff without a navigation loop', () => {
  const storage = sharedStorage(), tabStorage = memoryStorage()
  const old = documentHarness(storage, tabStorage)
  beginLogout(storage)
  old.storageEvent('personal_kb_logout_event', 'fixture-logout')
  commitIdentity(storage)
  const next = documentHarness(storage, tabStorage)
  assert.deepEqual(next.navigation, [])
  assert.equal(tabStorage.items.size, 0)
})

test('CD-15 re-login to the same account announces a new successful session to other tabs', () => {
  const storage = sharedStorage(), tabStorage = memoryStorage()
  const page = documentHarness(storage, tabStorage, '/login')
  const before = storage.getItem('personal_kb_identity_event')
  page.auth.invalidate({ clearCache: false })
  page.auth.persist({ auth_mode: 'cookie', user: { id: 'user-a' }, tenant: { id: 'space-a' }, device: { id: 'new-device-a' } }, { explicitLogin: true })
  assert.notEqual(storage.getItem('personal_kb_identity_event'), before)
  assert.equal(storage.getItem('personal_kb_token'), null)
  assert.equal(storage.getItem('personal_kb_refresh_token'), null)
})
