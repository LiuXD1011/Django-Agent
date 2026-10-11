import assert from 'node:assert/strict'
import test from 'node:test'
import vm from 'node:vm'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import compilerSfc from '@vue/compiler-sfc'
import { transformSync } from 'esbuild'
import { createAuthTransport } from '../../api/auth-transport.mjs'
import { EndpointResolver } from '../../api/endpoint.mjs'
const require = createRequire(import.meta.url)
const vue = require('vue')
const { descriptor, errors } = compilerSfc.parse(readFileSync(new URL('./DeviceSessions.vue', import.meta.url), 'utf8'))
assert.deepEqual(errors, [])
const code = transformSync(compilerSfc.compileScript(descriptor, { id: 'device-session-test' }).content, { loader: 'ts', format: 'cjs' }).code
function mount({ revokeDevice = async () => ({}), devices = async () => ({ data: { items: [] } }), logoutAll = async () => ({}), locks = null } = {}) {
  const pushes = [], revoked = [], invalidated = [], configs = []
  const map = new Map()
  const storage = { getItem: (key) => map.get(key) || null, setItem: (key, value) => map.set(key, value), removeItem: (key) => map.delete(key) }
  const authTransport = createAuthTransport({ storage, locks, resolver: new EndpointResolver('https://fixture.invalid'), cache: { unbind() {} }, cookie: () => 'csrftoken=fixture',
    fetcher: async url => { assert.ok(url.endsWith('/auth/me')); return { ok: true, status: 200, json: async () => ({ data: { auth_mode: 'cookie', user: { id: 'user' }, tenant: { id: 'space' }, device: { id: 'device-a' } } }) } } })
  authTransport.persist({ auth_mode: 'cookie', user: { id: 'user' }, tenant: { id: 'space' }, device: { id: 'device-a' } })
  authTransport.onInvalidate(() => invalidated.push(true))
  const context = vm.createContext({ module: { exports: {} }, require: (name) => {
    if (name === 'vue') return { ...vue, onMounted: () => {} }
    if (name === 'vue-router') return { useRouter: () => ({ replace: async (path) => pushes.push(path) }) }
    if (name === '../../api') return { api: { devices, logoutAll: async (config) => { configs.push(config); return logoutAll(config) }, revokeDevice: async (id, config) => { revoked.push(id); configs.push(config); return revokeDevice(id, config) } } }
    if (name === '../../stores/auth') return { useAuthStore: () => ({ subscribe() {} }) }
    if (name === '../../api/auth-transport.mjs') return { authTransport }
    throw new Error(name)
  } })
  vm.runInContext(code, context)
  const b = context.module.exports.default.setup({}, { expose: () => {} })
  return { b, pushes, revoked, invalidated, configs, authTransport }
}
test('revoking another device reloads the server list without logging out this device', async () => {
  const { b, revoked, pushes, invalidated } = mount()
  b.selected.value = { id: 'device-b', current: false }
  await b.revoke()
  assert.deepEqual(revoked, ['device-b'])
  assert.deepEqual(pushes, [])
  assert.deepEqual(invalidated, [])
  assert.equal(b.selected.value, null)
})
test('revoking this device waits for confirmed revocation before clearing the local session', async () => {
  const { b, pushes, invalidated } = mount()
  b.selected.value = { id: 'device-a', current: true }
  await b.revoke()
  assert.deepEqual(pushes, ['/login'])
  assert.deepEqual(invalidated, [true])
})
test('failed revocation preserves login and surfaces a retryable error', async () => {
  const { b, pushes, invalidated } = mount({ revokeDevice: async () => { throw { message: 'fixture-offline' } } })
  b.selected.value = { id: 'device-a', current: true }
  await b.revoke()
  assert.equal(b.error.value, 'fixture-offline')
  assert.equal(b.selected.value.id, 'device-a')
  assert.deepEqual(pushes, [])
  assert.deepEqual(invalidated, [])
})
test('logout-all clears authentication only after a successful server response', async () => {
  const { b, invalidated, pushes } = mount()
  await b.logoutAll()
  assert.deepEqual(invalidated, [true])
  assert.deepEqual(pushes, ['/login'])
  const failed = mount({ logoutAll: async () => { throw new Error('fixture-offline') } })
  await failed.b.logoutAll()
  assert.deepEqual(failed.invalidated, [])
})

test('device expiry labels match idle and absolute backend fields', () => {
  const source = readFileSync(new URL('./DeviceSessions.vue', import.meta.url), 'utf8')
  assert.match(source, /不活动到期：\{\{ device\.expires_at/)
  assert.match(source, /最长到期：\{\{ device\.absolute_expires_at/)
})

test('queued device revocation does not authorize under a later account generation', async () => {
  let queued
  const locks = { request: (_name, work) => new Promise((resolve, reject) => { queued = () => Promise.resolve().then(work).then(resolve, reject) }) }
  const { b, revoked, authTransport, pushes } = mount({ locks })
  b.selected.value = { id: 'old-device', current: true }
  const revoking = b.revoke()
  authTransport.invalidate()
  queued()
  await revoking
  assert.deepEqual(revoked, [])
  assert.deepEqual(pushes, [])
  assert.match(b.error.value, /登录已结束/)
})

test('late logout-all response cannot invalidate a newer queued login intent', async () => {
  let complete
  const pending = new Promise((resolve) => { complete = resolve })
  const { b, authTransport, invalidated, pushes, configs } = mount({ logoutAll: () => pending })
  const ending = b.logoutAll()
  await new Promise(resolve => setImmediate(resolve))
  authTransport.invalidate()
  complete({})
  await ending
  assert.equal(invalidated.length, 1, 'stale response cannot add another invalidation')
  assert.deepEqual(pushes, [])
  assert.equal(configs[0].skipAuthRefresh, true)
})

test('device mutation endpoints disable refresh re-entry inside their Cookie lock', async () => {
  const { b, configs } = mount()
  b.selected.value = { id: 'other', current: false }
  await b.revoke()
  await b.logoutAll()
  assert.ok(configs.every(config => config.skipAuthRefresh === true))
})
