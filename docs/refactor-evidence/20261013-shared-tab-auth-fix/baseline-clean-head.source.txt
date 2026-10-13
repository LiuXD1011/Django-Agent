import { endpoint } from './endpoint.mjs'
import { deviceStore } from '../stores/device-store.mjs'
import { applicationFetch, desktopBridge } from './desktop-transport.mjs'

const AUTH_KEYS = ['personal_kb_user', 'personal_kb_tenant', 'personal_kb_auth_mode',
  'personal_kb_selected_tenant_id', 'personal_kb_token', 'personal_kb_refresh_token', 'personal_kb_refresh_uncertain']
const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])
const dataOf = (payload) => payload?.data || payload

export function createAuthTransport({ storage = globalThis.localStorage, fetcher = applicationFetch,
  resolver = endpoint, cache = deviceStore, cookie = () => globalThis.document?.cookie || '',
  locks = globalThis.navigator?.locks, native = Boolean(desktopBridge) } = {}) {
  let epoch = 0
  let ended = false
  let refreshInFlight = null
  let csrfInFlight = null
  let refreshController = null
  let activeDeviceId = ''
  let sensitiveCheck = null
  let uncertainRefresh = ''
  let verifiedLegacyAccess = ''
  let privateSessionTail = Promise.resolve()
  let cookieOperationTail = Promise.resolve()
  const listeners = new Set()
  const sessionListeners = new Set()
  function storedIdentity() {
    try {
      const user = JSON.parse(storage.getItem('personal_kb_user') || 'null')
      const tenant = JSON.parse(storage.getItem('personal_kb_tenant') || 'null')
      return user?.id && tenant?.id ? JSON.stringify([storage.getItem('personal_kb_service_id'), user.id, tenant.id]) : ''
    } catch { return '' }
  }
  let activeIdentity = storedIdentity()

  function mode() {
    if (ended) return ''
    if (native && storage.getItem('personal_kb_auth_mode') === 'ipc') return 'ipc'
    if (storage.getItem('personal_kb_auth_mode') === 'cookie') return 'cookie'
    return storage.getItem('personal_kb_token') ? 'legacy_bearer' : ''
  }

  function csrfToken() {
    const raw = cookie().split(';').map((item) => item.trim()).find((item) => item.startsWith('csrftoken='))
    return raw ? decodeURIComponent(raw.slice('csrftoken='.length)) : ''
  }

  async function csrf({ revalidate = false } = {}) {
    const check = sensitiveCheck
    check?.()
    if (native) return ''
    if (!revalidate && csrfToken()) return csrfToken()
    if (!csrfInFlight) {
      csrfInFlight = fetcher(resolver.resolve('/api/v1/auth/csrf'), {
        credentials: 'same-origin', redirect: 'error', headers: { Accept: 'application/json' },
      }).then(async (response) => {
        if (!response.ok) throw new Error('初始化登录保护失败')
        const data = dataOf(await response.json())
        if (!data?.csrf_token) throw new Error('服务未返回登录保护令牌')
        return data.csrf_token
      }).finally(() => { csrfInFlight = null })
    }
    const token = await csrfInFlight
    check?.()
    return token
  }

  /** @returns {Record<string, string>} */
  function headers(method = 'GET', extra = {}, { anonymous = false } = {}) {
    sensitiveCheck?.()
    /** @type {Record<string, string>} */
    const result = { 'X-Request-ID': Math.random().toString(36).slice(2), ...extra }
    const tenant = storage.getItem('personal_kb_selected_tenant_id')
    if (!anonymous && tenant) result['X-Tenant-ID'] = tenant
    // Existing saved Bearer sessions keep working until explicitly replaced by cookie login.
    if (!anonymous && mode() === 'legacy_bearer') result.Authorization = `Bearer ${storage.getItem('personal_kb_token')}`
    if (!native && UNSAFE.has(method.toUpperCase()) && csrfToken()) result['X-CSRFToken'] = csrfToken()
    return result
  }

  function persist(data, { explicitLogin = false } = {}) {
    const nextIdentity = data?.user?.id && data?.tenant?.id
      ? JSON.stringify([storage.getItem('personal_kb_service_id'), data.user.id, data.tenant.id]) : activeIdentity
    const identityChanged = nextIdentity && activeIdentity !== nextIdentity
    if (identityChanged && activeIdentity) {
      epoch += 1
      cache.unbind({ clear: false })
    }
    if (data?.auth_mode === 'cookie' || native && data?.auth_mode === 'ipc') {
      storage.removeItem('personal_kb_token')
      storage.removeItem('personal_kb_refresh_token')
      storage.setItem('personal_kb_auth_mode', data.auth_mode)
    } else if (data?.token) {
      storage.setItem('personal_kb_token', data.token)
      if (data.refresh_token) storage.setItem('personal_kb_refresh_token', data.refresh_token)
      storage.removeItem('personal_kb_auth_mode')
    } else throw new Error('认证响应缺少会话状态')
    ended = false
    if (data.user) {
      const { id, email, username, name, is_system_admin } = data.user
      storage.setItem('personal_kb_user', JSON.stringify({ id, email, username, name, is_system_admin }))
    }
    if (data.tenant) {
      storage.setItem('personal_kb_tenant', JSON.stringify({ id: data.tenant.id, name: data.tenant.name }))
      storage.setItem('personal_kb_selected_tenant_id', String(data.tenant.id || ''))
    }
    // Only confirmed session establishment/new device or local logout clears an uncertain
    // refresh. A normal me/refresh for the same device never silently removes this fence.
    let uncertainDevice = activeDeviceId
    if (!uncertainDevice) {
      try { uncertainDevice = JSON.parse(storage.getItem('personal_kb_refresh_uncertain') || 'null')?.[2] || '' } catch { /* explicit login can clear malformed metadata */ }
    }
    if (explicitLogin || data.device?.id && uncertainDevice && String(data.device.id) !== uncertainDevice) {
      uncertainRefresh = ''
      storage.removeItem('personal_kb_refresh_uncertain')
    }
    activeIdentity = nextIdentity
    if (identityChanged) activeDeviceId = ''
    if (data.device?.id) activeDeviceId = String(data.device.id)
    for (const listener of sessionListeners) listener(data)
    if (identityChanged) storage.setItem('personal_kb_identity_event', JSON.stringify({ identity: nextIdentity, event: String(Date.now()) + Math.random() }))
  }

  function invalidate({ clearCache = true, broadcast = true, clearStorage = true } = {}) {
    epoch += 1
    ended = true
    activeDeviceId = ''
    verifiedLegacyAccess = ''
    refreshController?.abort()
    refreshInFlight = null
    cache.unbind({ clear: clearCache })
    if (clearStorage) { uncertainRefresh = ''; AUTH_KEYS.forEach((key) => storage.removeItem(key)) }
    if (broadcast) storage.setItem('personal_kb_logout_event', String(Date.now()) + Math.random())
    for (const listener of listeners) listener()
  }

  async function sessionOperation(generation, work, { cookie = true } = {}) {
    const check = () => {
      if (generation !== epoch) throw new Error('登录已结束')
    }
    const run = () => { check(); return work(check) }
    // Every operation that can set/delete the browser's Cookie pair uses this one origin lock.
    if (!cookie) return run()
    if (locks?.request) return locks.request(`personal-kb-refresh:${resolver.origin}`, run)
    // Without Web Locks, preserve ordering in this page; cross-tab ordering remains unsupported.
    const operation = cookieOperationTail.then(run)
    cookieOperationTail = operation.catch(() => {})
    return operation
  }

  function cachedId(key) {
    try { const value = JSON.parse(storage.getItem(key) || 'null'); return value?.id == null ? '' : String(value.id) }
    catch { return '' }
  }

  // This intent is private: callers cannot replace the authenticated identity or bypass the lock.
  function sessionIntent(generation) {
    const intent = { generation, selectedMode: mode(), origin: resolver.origin,
      service: storage.getItem('personal_kb_service_id') || '', boundService: resolver.service?.service_id || '',
      user: cachedId('personal_kb_user'), tenant: cachedId('personal_kb_tenant'),
      selectedTenant: storage.getItem('personal_kb_selected_tenant_id') || '',
      localDevice: activeDeviceId, device: activeDeviceId,
      legacyAccess: mode() === 'legacy_bearer' ? storage.getItem('personal_kb_token') : null }
    intent.check = () => {
      if (generation !== epoch || ended || !intent.selectedMode) throw new Error('登录已结束')
      if (mode() !== intent.selectedMode || resolver.origin !== intent.origin ||
        (storage.getItem('personal_kb_service_id') || '') !== intent.service ||
        (resolver.service?.service_id || '') !== intent.boundService ||
        cachedId('personal_kb_user') !== intent.user || cachedId('personal_kb_tenant') !== intent.tenant ||
        (storage.getItem('personal_kb_selected_tenant_id') || '') !== intent.selectedTenant || activeDeviceId !== intent.localDevice) {
        throw new Error('登录身份已改变，请重新确认操作')
      }
      if (intent.selectedMode === 'legacy_bearer' && storage.getItem('personal_kb_token') !== intent.legacyAccess) {
        // Only a completed, identity-proven rotation in this coordinator may update a queued intent.
        if (verifiedLegacyAccess && storage.getItem('personal_kb_token') === verifiedLegacyAccess) intent.legacyAccess = verifiedLegacyAccess
        else throw new Error('登录身份已改变，请重新确认操作')
      }
    }
    return intent
  }

  function verifyIdentity(intent, data, { primaryTenant = false } = {}) {
    intent.check()
    if (!data?.user?.id || !data?.tenant?.id || intent.user && String(data.user.id) !== intent.user ||
      !primaryTenant && intent.selectedTenant && String(data.tenant.id) !== intent.selectedTenant ||
      intent.device && String(data.device?.id || '') !== intent.device) {
      throw new Error('登录身份已改变，请重新确认操作')
    }
    if (['cookie', 'ipc'].includes(intent.selectedMode)) {
      if (!data.device?.id) throw new Error('服务未返回受保护的设备身份')
      if (!intent.device) intent.device = String(data.device.id)
    }
  }

  async function readSession(intent, path, rotatedAccess = '') {
    intent.check()
    const response = await fetcher(resolver.resolve(path), {
      credentials: 'same-origin', redirect: 'error', headers: { Accept: 'application/json', ...headers('GET'), ...(rotatedAccess ? { Authorization: `Bearer ${rotatedAccess}` } : {}) },
    })
    intent.check()
    const payload = await response.json()
    intent.check()
    if (!response.ok) throw { ...payload, status: response.status }
    return dataOf(payload)
  }

  // Only lock-owning closures below call this primitive. Never await refreshInFlight from here:
  // that promise may itself be queued behind the lock currently held by a sensitive operation.
  function refreshIdentity(intent) {
    return JSON.stringify([intent.service || intent.boundService, intent.user, intent.device])
  }

  function refreshIsUncertain(intent) {
    for (const marker of [uncertainRefresh, storage.getItem('personal_kb_refresh_uncertain')]) {
      if (!marker) continue
      try {
        const [service, user, device] = JSON.parse(marker)
        if (service === (intent.service || intent.boundService) && user === intent.user && (!intent.device || device === intent.device)) return true
      } catch { return true }
    }
    return false
  }

  function markRefreshUncertain(intent) {
    uncertainRefresh = refreshIdentity(intent)
    storage.setItem('personal_kb_refresh_uncertain', uncertainRefresh)
  }

  function preparedOperation(intent, work) {
    if (intent.selectedMode === 'cookie') return sessionOperation(intent.generation, work)
    // IPC/legacy have no Cookie pair, but must not consume the same private refresh concurrently.
    const pending = privateSessionTail.then(() => sessionOperation(intent.generation, work, { cookie: false }))
    privateSessionTail = pending.catch(() => {})
    return pending
  }

  async function rotateSession(intent) {
    intent.check()
    if (refreshIsUncertain(intent)) throw new Error('刷新结果尚未确认，请重新登录后核对')
    const controller = new AbortController()
    refreshController = controller
    let sent = false
    try {
      const body = ['cookie', 'ipc'].includes(intent.selectedMode) ? { auth_mode: intent.selectedMode }
        : { refresh_token: storage.getItem('personal_kb_refresh_token') }
      if (intent.selectedMode === 'legacy_bearer' && !body.refresh_token) throw new Error('旧登录缺少刷新凭据')
      const token = intent.selectedMode === 'cookie' ? await csrf() : ''
      intent.check()
      sent = true
      const response = await fetcher(resolver.resolve('/api/v1/auth/refresh'), {
        method: 'POST', credentials: 'same-origin', redirect: 'error', signal: controller.signal,
        headers: { 'Content-Type': 'application/json', ...(token ? { 'X-CSRFToken': token } : {}) }, body: JSON.stringify(body),
      })
      intent.check()
      const payload = await response.json()
      intent.check()
      if (!response.ok) throw { ...payload, status: response.status }
      const data = dataOf(payload)
      // Refresh may return the primary tenant. It proves user/device, never the selected scope.
      verifyIdentity(intent, data, { primaryTenant: true })
      if (intent.selectedMode === 'legacy_bearer' && (typeof data.token !== 'string' || !data.token)) throw new Error('服务未返回刷新凭据')
      // Rotation is confirmed consumed, but final selected-scope proof/persistence can still fail.
      markRefreshUncertain(intent)
      return data
    } catch (error) {
      if (sent && intent.generation === epoch && ![401, 403].includes(error?.status)) {
        // No credential is recorded. Shared metadata prevents another tab from replaying a
        // refresh whose consumption is unknown. Explicit login creates a different device.
        markRefreshUncertain(intent)
      }
      throw error
    } finally { if (refreshController === controller) refreshController = null }
  }

  async function prepareSession(intent, { proveService = true } = {}) {
    intent.check()
    if (proveService && (intent.service || intent.boundService)) {
      const service = await readSession(intent, '/api/v1/capabilities')
      intent.check()
      if (service?.service_id !== (intent.service || intent.boundService) ||
        intent.boundService && service.service_id !== intent.boundService) throw new Error('服务身份已改变，请重新登录')
    }
    let data, rotated
    try { data = await readSession(intent, '/api/v1/auth/me') }
    catch (error) {
      intent.check()
      if (error?.status !== 401) throw error
      rotated = await rotateSession(intent)
      intent.check()
      // Explicitly use the original selected tenant, which headers() still reads under the fence.
      data = await readSession(intent, '/api/v1/auth/me', intent.selectedMode === 'legacy_bearer' ? rotated.token : '')
    }
    intent.check()
    verifyIdentity(intent, data)
    // Existing Bearer refresh keeps its rotated secrets; new cookie/ipc sessions never expose them.
    const legacyCredentials = intent.selectedMode === 'legacy_bearer' ? { token: rotated?.token || storage.getItem('personal_kb_token'), refresh_token: rotated?.refresh_token || storage.getItem('personal_kb_refresh_token') } : {}
    const session = { ...rotated, ...data, ...legacyCredentials, auth_mode: intent.selectedMode === 'legacy_bearer' ? 'legacy_bearer' : intent.selectedMode }
    persist(session)
    // Ordinary restore may begin without cached metadata; sensitive intents require it upfront.
    if (!intent.user) intent.user = cachedId('personal_kb_user')
    if (!intent.tenant) intent.tenant = cachedId('personal_kb_tenant')
    if (!intent.selectedTenant) intent.selectedTenant = storage.getItem('personal_kb_selected_tenant_id') || ''
    intent.localDevice = activeDeviceId
    if (intent.selectedMode === 'legacy_bearer') intent.legacyAccess = storage.getItem('personal_kb_token')
    intent.check()
    if (rotated) { uncertainRefresh = ''; storage.removeItem('personal_kb_refresh_uncertain') }
    if (intent.selectedMode === 'legacy_bearer') verifiedLegacyAccess = intent.legacyAccess
    return session
  }

  async function authenticatedSessionOperation(generation, work) {
    const intent = sessionIntent(generation)
    if (!intent.user || !intent.selectedTenant) throw new Error('登录已结束，请重新登录')
    return preparedOperation(intent, async () => {
      try { await prepareSession(intent, { proveService: true }) }
      catch (error) {
        intent.check()
        if ([401, 403].includes(error?.status)) invalidate()
        throw error
      }
      intent.check()
      // Also fence the Axios headers/CSRF await without changing its 401 or retry semantics.
      sensitiveCheck = intent.check
      try { return await work(intent.check) }
      finally { if (sensitiveCheck === intent.check) sensitiveCheck = null }
    })
  }

  function assertSensitiveSession() { sensitiveCheck?.() }

  async function refresh() {
    if (refreshInFlight) return refreshInFlight
    const intent = sessionIntent(epoch)
    if (!intent.selectedMode) throw new Error('登录已结束')
    // Recheck me after obtaining the lock: another operation/tab may already have renewed cookies.
    const promise = preparedOperation(intent, () => prepareSession(intent))
    refreshInFlight = promise
    try { return await promise }
    finally { if (refreshInFlight === promise) refreshInFlight = null }
  }

  async function request(path, options = {}) {
    const startedEpoch = epoch
    const method = String(options.method || 'GET').toUpperCase()
    const token = UNSAFE.has(method) && mode() !== 'legacy_bearer' ? await csrf() : ''
    const send = () => fetcher(resolver.resolve(path), {
      ...options, credentials: 'same-origin', redirect: 'error',
      headers: { ...headers(method), ...(token ? { 'X-CSRFToken': csrfToken() || token } : {}), ...options.headers },
    })
    let response = await send()
    if (response.status === 401 && !(/^\/api\/v1\/auth\/(?:login|register|auto-setup|refresh|csrf|logout)$/.test(path)) && mode()) {
      try { await refresh() }
      catch (error) {
        if (startedEpoch === epoch && [401, 403].includes(error?.status)) invalidate()
        throw error
      }
      if (startedEpoch !== epoch) throw new Error('登录已结束')
      response = await send()
    }
    return response
  }

  return { mode, csrf, headers, persist, invalidate, refresh, request, sessionOperation, authenticatedSessionOperation, assertSensitiveSession, isNative: () => native,
    generation: () => epoch, onSession: (listener) => { sessionListeners.add(listener); return () => sessionListeners.delete(listener) }, onInvalidate: (listener) => { listeners.add(listener); return () => listeners.delete(listener) } }
}

export const authTransport = createAuthTransport()
// A logout in another tab invalidates in-memory stores and pending refresh responses here as well.
if (globalThis.addEventListener) globalThis.addEventListener('storage', (event) => {
  if (['personal_kb_logout_event', 'personal_kb_identity_event'].includes(event.key) && event.newValue) {
    authTransport.invalidate({ clearCache: false, broadcast: false, clearStorage: false })
    if (event.key === 'personal_kb_identity_event') globalThis.location?.assign('/platform/knowledge-bases')
    else if (globalThis.location?.pathname !== '/login') globalThis.location?.assign('/login')
  }
})
