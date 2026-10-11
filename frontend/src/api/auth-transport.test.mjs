import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createAuthTransport } from './auth-transport.mjs'
import { EndpointResolver } from './endpoint.mjs'
import { DeviceStore } from '../stores/device-store.mjs'

function memoryStorage(initial = {}) {
  const items = new Map(Object.entries(initial))
  return { getItem: (key) => items.get(key) ?? null, setItem: (key, value) => items.set(key, String(value)),
    removeItem: (key) => items.delete(key), key: (index) => [...items.keys()][index], get length() { return items.size }, items }
}
const response = (data, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => ({ success: status === 200, data }) })
const session = { device: { id: 'device-a' }, auth_mode: 'cookie', user: { id: 'user-a', email: 'fixture@example.invalid', preferences: { secret_fixture: 'not-for-storage' } }, tenant: { id: 'space-a', name: 'Private', api_key: 'not-for-storage' } }
function fixture({ storage = memoryStorage(), fetcher = async () => response(session), cookie = () => 'csrftoken=fixture-csrf', locks = null } = {}) {
  const resolver = new EndpointResolver('https://kb.example.invalid')
  const cache = new DeviceStore(storage)
  const auth = createAuthTransport({ storage, fetcher, cookie, resolver, cache, locks })
  return { auth, storage, resolver, cache }
}

// Cross-device acceptance CD-07/CD-10: endpoints and credentials must stay inside one service.
test('EndpointResolver rejects foreign hosts, credentials and non-API paths', () => {
  const { resolver } = fixture()
  assert.equal(resolver.resolve('/api/v1/auth/me'), 'https://kb.example.invalid/api/v1/auth/me')
  for (const path of ['//evil.invalid/api/v1/auth/me', 'https://evil.invalid/api/v1/auth/me', '/media/a.png',
    'https://u:p@kb.example.invalid/api/v1/auth/me', '/api/v1/auth/me#fragment']) assert.throws(() => resolver.resolve(path))
})

test('capabilities bind a real service identity and reject missing or incompatible protocols', () => {
  const { resolver } = fixture()
  for (const value of [null, {}, { service_id: 'service', client_protocol: 9, auth_modes: ['cookie'] }]) assert.throws(() => resolver.bind(value))
  assert.equal(resolver.bind({ service_id: 'service-a', client_protocol: 1, auth_modes: ['cookie'] }).service_id, 'service-a')
})

test('cookie authentication removes legacy tokens and stores only low-sensitivity identity fields', () => {
  const { auth, storage } = fixture({ storage: memoryStorage({ personal_kb_token: 'old', personal_kb_refresh_token: 'old-refresh' }) })
  auth.persist({ ...session, token: 'must-not-persist', refresh_token: 'must-not-persist' })
  assert.equal(auth.mode(), 'cookie')
  assert.equal(storage.getItem('personal_kb_token'), null)
  assert.equal(storage.getItem('personal_kb_refresh_token'), null)
  assert.ok(!JSON.stringify([...storage.items]).includes('not-for-storage'))
  assert.equal(auth.headers('POST').Authorization, undefined)
  assert.equal(auth.headers('POST')['X-CSRFToken'], 'fixture-csrf')
})

test('an existing saved Bearer session remains usable until cookie login replaces it', () => {
  const { auth } = fixture({ storage: memoryStorage({ personal_kb_token: 'legacy-fixture' }) })
  assert.equal(auth.mode(), 'legacy_bearer')
  assert.equal(auth.headers('GET').Authorization, 'Bearer legacy-fixture')
  assert.equal(auth.headers('GET', {}, { anonymous: true }).Authorization, undefined)
})

test('parallel CSRF initializations share one anonymous same-origin request', async () => {
  const calls = []
  const { auth } = fixture({ cookie: () => '', fetcher: async (...args) => { calls.push(args); return response({ csrf_token: 'csrf-fixture' }) } })
  assert.deepEqual(await Promise.all([auth.csrf(), auth.csrf()]), ['csrf-fixture', 'csrf-fixture'])
  assert.equal(calls.length, 1)
  assert.equal(calls[0][1].credentials, 'same-origin')
  assert.equal(calls[0][1].headers.Authorization, undefined)
})

test('explicit login protection validation replaces a cookie retained from a different service', async () => {
  const calls = []
  const { auth } = fixture({ cookie: () => 'csrftoken=old-service-cookie', fetcher: async (...args) => { calls.push(args); return response({ csrf_token: 'new-service-cookie' }) } })
  assert.equal(await auth.csrf(), 'old-service-cookie')
  assert.deepEqual(await Promise.all([auth.csrf({ revalidate: true }), auth.csrf({ revalidate: true })]), ['new-service-cookie', 'new-service-cookie'])
  assert.equal(calls.length, 1)
  assert.equal(calls[0][1].credentials, 'same-origin')
  assert.equal(calls[0][1].headers.Authorization, undefined)
})

test('parallel 401 refresh calls rotate once without persisting web credentials', async () => {
  const calls = []
  let complete
  const pending = new Promise((resolve) => { complete = resolve })
  let valid = false
  const { auth, storage } = fixture({ fetcher: async (...args) => {
    if (args[0].endsWith('/auth/me')) return response(session, valid ? 200 : 401)
    calls.push(args); const result = await pending; valid = true; return result
  } })
  auth.persist(session)
  const one = auth.refresh(), two = auth.refresh()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(calls.length, 1)
  complete(response(session))
  await Promise.all([one, two])
  assert.deepEqual(JSON.parse(calls[0][1].body), { auth_mode: 'cookie' })
  assert.equal(calls[0][1].headers['X-CSRFToken'], 'fixture-csrf')
  assert.equal(storage.getItem('personal_kb_token'), null)
})

test('Web Locks use the same per-origin lock to serialize refresh across tabs', async () => {
  const names = []
  const { auth } = fixture({ locks: { request: async (name, run) => { names.push(name); return run() } } })
  auth.persist(session)
  await auth.refresh()
  assert.deepEqual(names, ['personal-kb-refresh:https://kb.example.invalid'])
})

test('logout aborts a pending refresh and even an ignored abort cannot resurrect authentication', async () => {
  let complete, options
  const pending = new Promise((resolve) => { complete = resolve })
  const { auth, storage } = fixture({ fetcher: async (_url, init) => { if (_url.endsWith('/auth/me')) return response({}, 401); options = init; return pending } })
  auth.persist(session)
  const refreshing = auth.refresh()
  await new Promise(resolve => setImmediate(resolve))
  auth.invalidate()
  assert.equal(options.signal.aborted, true)
  complete(response(session))
  await assert.rejects(refreshing, /登录已结束/)
  assert.equal(auth.mode(), '')
  assert.equal(storage.getItem('personal_kb_auth_mode'), null)
  await assert.rejects(auth.refresh(), /登录已结束/)
})

test('stream transport retries only the unauthorized request and reads rotated CSRF cookies', async () => {
  let csrf = 'before', count = 0
  const calls = []
  const { auth } = fixture({ cookie: () => `csrftoken=${csrf}`, fetcher: async (url, options) => {
    calls.push([url, options])
    if (url.endsWith('/auth/me')) return response(session, csrf === 'after' ? 200 : 401)
    if (url.endsWith('/auth/refresh')) { csrf = 'after'; return response(session) }
    count += 1
    return response({}, count === 1 ? 401 : 200)
  } })
  auth.persist(session)
  const result = await auth.request('/api/v1/knowledge-chat/session-a', { method: 'POST', body: '{}', headers: { Accept: 'text/event-stream' } })
  assert.equal(result.status, 200)
  assert.equal(calls.length, 5)
  assert.equal(calls[0][1].headers['X-CSRFToken'], 'before')
  assert.equal(calls[4][1].headers['X-CSRFToken'], 'after')
  assert.equal(calls[4][1].credentials, 'same-origin')
  assert.equal(calls[4][1].redirect, 'error')
})

test('revoked stream credentials invalidate while network failures retain local drafts', async () => {
  const denied = fixture({ fetcher: async () => response({}, 401) })
  denied.auth.persist(session)
  await assert.rejects(denied.auth.request('/api/v1/sessions/x'))
  assert.equal(denied.auth.mode(), '')
  const offline = fixture({ fetcher: async () => { throw new Error('offline') } })
  offline.auth.persist(session)
  offline.cache.bind('service', 'user', 'space')
  offline.cache.write('draft', 'session', { text: 'unsent' })
  await assert.rejects(offline.auth.request('/api/v1/sessions/x'), /offline/)
  assert.deepEqual(offline.cache.read('draft', 'session'), { text: 'unsent' })
  assert.equal(offline.auth.mode(), 'cookie')
})

// Cross-device acceptance CD-01/CD-15: no cache namespace is shared by service, account or space.
test('DeviceStore isolates drafts by service, user and space, with no active identity after logout', () => {
  const { cache, auth } = fixture()
  assert.throws(() => cache.write('draft', 'a', 'x'))
  cache.bind('service-a', 'user-a', 'space-a')
  cache.write('draft', 'a', { text: 'private' })
  cache.bind('service-a', 'user-b', 'space-a')
  assert.equal(cache.read('draft', 'a'), null)
  cache.bind('service-b', 'user-a', 'space-a')
  assert.equal(cache.read('draft', 'a'), null)
  cache.bind('service-a', 'user-a', 'space-b')
  assert.equal(cache.read('draft', 'a'), null)
  cache.bind('service-a', 'user-a', 'space-a')
  assert.deepEqual(cache.read('draft', 'a'), { text: 'private' })
  auth.invalidate()
  assert.throws(() => cache.read('draft', 'a'))
  cache.bind('service-a', 'user-a', 'space-a')
  assert.equal(cache.read('draft', 'a'), null)
})

test('cookie API login and both stream routes all use the unified transport', () => {
  const source = readFileSync(new URL('./index.ts', import.meta.url), 'utf8')
  assert.doesNotMatch(source, /\bfetch\(/)
  assert.doesNotMatch(source, /localStorage|getItem\('personal_kb_token/)
  assert.equal((source.match(/authTransport\.request\(url/g) || []).length, 2)
  assert.match(source, /login:.*auth_mode: 'cookie'/)
})

test('account replacement publishes a cross-tab identity event, fences old requests and unbinds prior cache', () => {
  const { auth, storage, cache } = fixture()
  const seen = []
  auth.onSession((data) => seen.push(data.user.id))
  auth.persist(session)
  cache.bind('service', 'user-a', 'space-a')
  cache.write('draft', 'session-a', 'account-a draft')
  const oldGeneration = auth.generation()
  const oldEvent = storage.getItem('personal_kb_identity_event')
  auth.persist({ ...session, user: { id: 'user-b' }, tenant: { id: 'space-b' } })
  assert.notEqual(storage.getItem('personal_kb_identity_event'), oldEvent)
  assert.ok(auth.generation() > oldGeneration)
  assert.deepEqual(seen, ['user-a', 'user-b'])
  assert.throws(() => cache.read('draft', 'session-a'))
  cache.bind('service', 'user-b', 'space-b')
  assert.equal(cache.read('draft', 'session-a'), null)
})

test('native device session refresh and unsafe requests use private transport without a web CSRF call or stored credentials', async () => {
  const storage = memoryStorage({ personal_kb_token: 'stale-web-token', personal_kb_refresh_token: 'stale-web-refresh' });
  let valid = false;
  const calls = [], resolver = new EndpointResolver('https://marlin.local');
  const nativeSession = { ...session, auth_mode: 'ipc' };
  const auth = createAuthTransport({ native: true, storage, resolver, cache: { unbind() {} }, cookie: () => 'csrftoken=stale-browser-cookie', locks: null,
    fetcher: async (url, init) => { calls.push([url, init]); assert.ok(!url.endsWith('/auth/csrf'));
      if (url.endsWith('/auth/me')) return response(nativeSession, valid ? 200 : 401);
      if (url.endsWith('/auth/refresh')) valid = true; return response(nativeSession); },
  });
  auth.persist(nativeSession); assert.equal(auth.mode(), 'ipc');
  assert.equal(await auth.csrf(), ''); assert.equal(auth.headers('POST')['X-CSRFToken'], undefined);
  await auth.refresh(); await auth.request('/api/v1/sessions', { method: 'POST', body: '{}' });
  assert.equal(calls.length, 4); assert.deepEqual(JSON.parse(calls[1][1].body), { auth_mode: 'ipc' });
  assert.equal(calls[0][1].headers['X-CSRFToken'], undefined); assert.equal(calls[1][1].headers.Authorization, undefined);
  assert.equal(storage.getItem('personal_kb_token'), null); assert.equal(storage.getItem('personal_kb_refresh_token'), null);
});

test('legacy Bearer sensitive preflight preserves existing credentials when me is already valid', async () => {
  const storage = memoryStorage({ personal_kb_token: 'legacy-existing', personal_kb_refresh_token: 'legacy-existing-refresh' })
  const { auth } = fixture({ storage, fetcher: async url => {
    assert.ok(url.endsWith('/auth/me'))
    return response({ user: { id: 'legacy-user' }, tenant: { id: 'legacy-space' }, auth_mode: 'bearer', device: null })
  } })
  auth.persist({ auth_mode: 'legacy_bearer', token: 'legacy-existing', refresh_token: 'legacy-existing-refresh', user: { id: 'legacy-user' }, tenant: { id: 'legacy-space' } })
  let sent = 0
  await auth.authenticatedSessionOperation(auth.generation(), async check => { check(); sent += 1 })
  assert.equal(sent, 1)
  assert.equal(auth.mode(), 'legacy_bearer')
  assert.equal(storage.getItem('personal_kb_token'), 'legacy-existing')
})

test('ordinary refresh can restore server identity when only the cookie mode marker is known', async () => {
  const { auth } = fixture({ storage: memoryStorage({ personal_kb_auth_mode: 'cookie' }) })
  const data = await auth.refresh()
  assert.equal(data.user.id, session.user.id)
  assert.equal(auth.mode(), 'cookie')
})

for (const action of ['explicitLogin', 'newDevice', 'logout']) {
  test(`uncertain refresh metadata is cleared by ${action}`, () => {
    const storage = memoryStorage({ personal_kb_service_id: 'service-a' })
    const { auth } = fixture({ storage })
    auth.persist(session)
    storage.setItem('personal_kb_refresh_uncertain', JSON.stringify(['service-a', session.user.id, session.device.id]))
    if (action === 'explicitLogin') auth.persist(session, { explicitLogin: true })
    if (action === 'newDevice') auth.persist({ ...session, device: { id: 'new-device' } })
    if (action === 'logout') auth.invalidate()
    assert.equal(storage.getItem('personal_kb_refresh_uncertain'), null)
  })
}

test('an explicitly established new device can renew despite the old device uncertainty', async () => {
  const storage = memoryStorage({ personal_kb_service_id: 'service-a' })
  const newSession = { ...session, device: { id: 'device-new' } }
  let valid = false, rotations = 0
  const { auth } = fixture({ storage, fetcher: async url => {
    if (url.endsWith('/capabilities')) return response({ service_id: 'service-a' })
    if (url.endsWith('/auth/me')) return response(newSession, valid ? 200 : 401)
    assert.ok(url.endsWith('/auth/refresh')); rotations += 1; valid = true; return response(newSession)
  } })
  auth.persist(session)
  storage.setItem('personal_kb_refresh_uncertain', JSON.stringify(['service-a', session.user.id, session.device.id]))
  auth.persist(newSession, { explicitLogin: true })
  const result = await auth.refresh()
  assert.equal(result.device.id, 'device-new')
  assert.equal(rotations, 1)
  assert.equal(storage.getItem('personal_kb_refresh_uncertain'), null)
})

test('expired legacy Bearer proves the selected tenant using the rotated access before persisting', async () => {
  const storage = memoryStorage()
  const old = { auth_mode: 'legacy_bearer', token: 'legacy-old', refresh_token: 'legacy-refresh-old', user: { id: 'legacy-user' }, tenant: { id: 'selected-space' } }
  const selected = { auth_mode: 'bearer', user: old.user, tenant: old.tenant, device: null }
  const rotated = { ...old, token: 'legacy-new', refresh_token: 'legacy-refresh-new', tenant: { id: 'primary-space' } }
  const calls = []
  const { auth } = fixture({ storage, fetcher: async (url, options) => {
    calls.push([url, options])
    if (url.endsWith('/auth/me')) return response(selected, options.headers.Authorization === 'Bearer legacy-new' ? 200 : 401)
    assert.ok(url.endsWith('/auth/refresh'))
    assert.equal(JSON.parse(options.body).refresh_token, 'legacy-refresh-old')
    return response(rotated)
  } })
  auth.persist(old)
  let mutation = 0
  await auth.authenticatedSessionOperation(auth.generation(), async check => { check(); mutation += 1 })
  assert.equal(mutation, 1)
  assert.equal(calls.length, 3)
  assert.equal(storage.getItem('personal_kb_token'), 'legacy-new')
  assert.equal(storage.getItem('personal_kb_refresh_token'), 'legacy-refresh-new')
  assert.equal(storage.getItem('personal_kb_selected_tenant_id'), 'selected-space')
})

for (const selectedMode of ['ipc', 'legacy_bearer']) {
  test(`${selectedMode} sensitive and ordinary renewal serialize without replaying the same refresh`, { timeout: 2000 }, async () => {
    const storage = memoryStorage()
    let release, enter, valid = false, rotations = 0
    const hold = new Promise(resolve => { release = resolve }), entered = new Promise(resolve => { enter = resolve })
    const data = { auth_mode: selectedMode, user: { id: 'user-a' }, tenant: { id: 'space-a' }, device: selectedMode === 'ipc' ? { id: 'device-a' } : null,
      ...(selectedMode === 'legacy_bearer' ? { token: 'old-access', refresh_token: 'old-refresh' } : {}) }
    const rotated = { ...data, ...(selectedMode === 'legacy_bearer' ? { token: 'new-access', refresh_token: 'new-refresh' } : {}) }
    const auth = createAuthTransport({ native: selectedMode === 'ipc', storage, resolver: new EndpointResolver('https://fixture.invalid'), cache: { unbind() {} }, locks: null,
      fetcher: async (url, options) => {
        if (url.endsWith('/auth/me')) return response({ ...data, token: undefined, refresh_token: undefined }, valid ? 200 : 401)
        assert.ok(url.endsWith('/auth/refresh'))
        const attempt = ++rotations
        enter(); await hold
        if (attempt !== 1) return response({}, 401)
        valid = true; return response(rotated)
      } })
    auth.persist(data)
    let sent = 0
    const sensitive = auth.authenticatedSessionOperation(auth.generation(), async check => { check(); sent += 1 })
    await entered
    const ordinary = auth.refresh()
    const finished = Promise.all([sensitive, ordinary])
    release()
    await finished
    assert.equal(rotations, 1)
    assert.equal(sent, 1)
  })
}

test('confirmed legacy rotation followed by unknown final me never consumes the old refresh again', async () => {
  const storage = memoryStorage()
  const data = { auth_mode: 'legacy_bearer', token: 'old-access', refresh_token: 'old-refresh', user: { id: 'user-a' }, tenant: { id: 'space-a' }, device: null }
  const used = []
  const { auth } = fixture({ storage, fetcher: async (url, options) => {
    if (url.endsWith('/auth/me')) {
      if (options.headers.Authorization === 'Bearer new-access') throw new Error('final me outcome unknown')
      return response({}, 401)
    }
    used.push(JSON.parse(options.body).refresh_token)
    return response({ ...data, token: 'new-access', refresh_token: 'new-refresh' })
  } })
  auth.persist(data)
  await assert.rejects(auth.refresh())
  await assert.rejects(auth.refresh())
  assert.deepEqual(used, ['old-refresh'])
  assert.equal(storage.getItem('personal_kb_token'), 'old-access', 'unproven scope must not be persisted')
})
