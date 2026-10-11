import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'
import { registerStaticWorker, installMobileViewport } from './client.mjs'

const template = readFileSync(new URL('./service-worker.template.js', import.meta.url), 'utf8')
const shell = '/pwa-shell/shell-fixture.html'
const assets = ['/assets/index-fixture1.js', '/assets/index-fixture1.css']
function fixture({ badAsset = false, offline = false } = {}) {
  const handlers = new Map(), stores = new Map(), calls = []
  class PublicRequest {
    constructor(url, options = {}) { this.url = new URL(url, 'https://kb.example').href; Object.assign(this, options) }
  }
  const caches = {
    async open(name) { if (!stores.has(name)) stores.set(name, new Map()); const data = stores.get(name)
      return { async put(path, response) { data.set(path, response) }, async match(path) { return data.get(path) } } },
    async keys() { return [...stores.keys()] }, async delete(name) { return stores.delete(name) },
  }
  const response = (type, content = 'public') => ({ type: 'basic', ok: true, redirected: false, headers: new Headers({ 'content-type': type }), content })
  const fetcher = async (request) => { calls.push(request)
    if (offline || request.mode === 'navigate' && request.fail) throw new Error('offline')
    const path = new URL(request.url).pathname
    return response(path === shell ? 'text/html' : path.endsWith('.css') ? 'text/css' : badAsset ? 'text/html' : 'application/javascript')
  }
  vm.runInNewContext(template.replace('__STATIC_VERSION__', '"fixture"').replace('__STATIC_SHELL__', JSON.stringify(shell))
    .replace('__STATIC_ASSETS__', JSON.stringify(assets)), {
    self: { location: { origin: 'https://kb.example' }, clients: { claim: async () => {} },
      addEventListener: (name, handler) => handlers.set(name, handler) },
    caches, fetch: fetcher, Request: PublicRequest, Response: { error: () => 'error' }, URL, Set,
  })
  async function lifecycle(name) { let wait; handlers.get(name)({ waitUntil: value => { wait = value } }); return wait }
  function fetchEvent(path, options = {}) { let result
    const request = { url: new URL(path, 'https://kb.example').href, method: 'GET', headers: new Headers(), ...options }
    handlers.get('fetch')({ request, respondWith: value => { result = value } })
    return result
  }
  return { stores, calls, lifecycle, fetchEvent }
}

test('PWA caches only the exact build public shell/assets without credentials', async () => {
  const app = fixture(); await app.lifecycle('install')
  assert.deepEqual([...app.stores.values()][0].keys().toArray(), [shell, ...assets])
  assert(app.calls.every(request => request.credentials === 'omit' && request.redirect === 'error' && request.cache === 'no-store'))
  for (const path of ['/api/v1/auth/me', '/api/v1/models', '/api/v1/agent-chat/x', '/media/a.png', '/files/x', '/uploads/x', '/downloads/x', '/export/x', '/assets/not-in-build.js']) {
    assert.equal(app.fetchEvent(path), undefined, path)
  }
  assert.equal(app.fetchEvent(assets[0], { method: 'POST' }), undefined)
  assert.equal(app.fetchEvent(assets[0], { headers: new Headers({ Authorization: 'Bearer private' }) }), undefined)
  assert.equal(app.fetchEvent(assets[0] + '?token=private'), undefined)
  assert.equal(app.fetchEvent('https://other.example' + assets[0]), undefined)
})

test('PWA network navigation is never persisted; offline navigation returns only the static shell', async () => {
  const app = fixture(); await app.lifecycle('install')
  const before = [...app.stores.values()][0].size
  await app.fetchEvent('/platform/chat/one', { mode: 'navigate' })
  assert.equal([...app.stores.values()][0].size, before)
  const offline = await app.fetchEvent('/platform/chat/one', { mode: 'navigate', fail: true })
  assert.equal(offline.content, 'public')
  assert.equal(app.fetchEvent('/files/private', { mode: 'navigate' }), undefined)
})

test('PWA refuses HTML/auth redirects masquerading as a public script and removes partial cache', async () => {
  const app = fixture({ badAsset: true })
  await assert.rejects(app.lifecycle('install'), /Invalid public asset/)
  assert.equal(app.stores.size, 0)
})

test('PWA activation cleans only its own old static cache and preserves other account/draft stores', async () => {
  const app = fixture(); await app.lifecycle('install')
  app.stores.set('personal-kb-public-static-old', new Map())
  app.stores.set('other-app-or-private-drafts', new Map())
  await app.lifecycle('activate')
  assert.deepEqual([...app.stores.keys()], ['personal-kb-public-static-fixture', 'other-app-or-private-drafts'])
  assert.doesNotMatch(template, /skipWaiting|location\.reload/)
})

test('waiting update reports readiness but never forces reload or skips the old worker', async () => {
  let ready = 0, registered
  const registration = { waiting: {}, addEventListener() {} }
  await registerStaticWorker({ navigator: { serviceWorker: { register: async (...args) => { registered = args; return registration } } },
    location: { protocol: 'https:' }, onWaiting: () => ready++ })
  assert.deepEqual(registered, ['/sw.js', { scope: '/', updateViaCache: 'none' }])
  assert.equal(ready, 1)
  assert.equal(await registerStaticWorker({ navigator: {}, location: { protocol: 'https:' }, onWaiting() {} }), null)
})

test('mobile viewport handles keyboard shrink without treating pinch zoom as a keyboard', () => {
  let value, keyboard
  const handlers = new Map()
  const target = { innerHeight: 800, visualViewport: { height: 480, scale: 1, addEventListener() {}, removeEventListener() {} },
    addEventListener: (name, fn) => handlers.set(name, fn), removeEventListener() {}, document: {
      documentElement: { style: { setProperty: (_key, height) => { value = height } }, classList: { toggle: (_name, enabled) => { keyboard = enabled } } },
      activeElement: { matches: () => true }, addEventListener() {}, removeEventListener() {},
    } }
  const cleanup = installMobileViewport(target)
  assert.equal(value, '480px'); assert.equal(keyboard, true)
  target.visualViewport.scale = 2; handlers.get('resize')()
  assert.equal(value, '800px'); assert.equal(keyboard, false)
  cleanup()
})
