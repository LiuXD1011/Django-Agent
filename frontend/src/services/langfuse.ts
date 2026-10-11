import client from '../api/client'
import { authTransport } from '../api/auth-transport.mjs'
import { endpoint } from '../api/endpoint.mjs'
import { desktopBridge } from '../api/desktop-transport.mjs'

let inFlight: Promise<any> | null = null
let attemptedIdentity = ''
async function nativeLangfuse(action: 'session' | 'open' | 'clear', traceUrl?: string) {
  const tenantId = authTransport.headers('GET')['X-Tenant-ID']
  const response = await desktopBridge.langfuse({ id: crypto.randomUUID(), action, ...(traceUrl ? { traceUrl } : {}), ...(tenantId ? { tenantId } : {}) })
  if (response.status >= 400) throw { ...response.body, status: response.status }
  return response.body.data
}
export async function langfuseSession() {
  if (!inFlight) {
    inFlight = (desktopBridge ? nativeLangfuse('session') : client.post('/api/v1/observability/langfuse/session', {}).then((r: any) => r.data))
      .finally(() => { inFlight = null })
  }
  return inFlight
}
export async function autoLoginLangfuse() {
  const mode = authTransport.mode()
  let user: any
  try { user = JSON.parse(localStorage.getItem('personal_kb_user') || '{}') } catch { return }
  if (!mode || !user.id || !endpoint.service) return
  // Authorization remains server-side: system admin or the explicitly bound local account.
  const identity = `${endpoint.service.service_id}:${user.id}`
  if (attemptedIdentity === identity) return
  attemptedIdentity = identity
  try { await langfuseSession() } catch { /* Settings shows a retryable diagnostic. */ }
}
export async function clearLangfuseSession() {
  attemptedIdentity = ''
  try {
    if (desktopBridge) await nativeLangfuse('clear')
    else {
      if (inFlight) await inFlight.catch(() => {})
      await client.post('/api/v1/observability/langfuse/session/clear', {})
    }
  } catch { /* App logout must still complete. Server cookie also has a short TTL. */ }
}
function validatedDestination(value: unknown) {
  if (typeof value !== 'string' || /[\s\\]/.test(value)) throw new Error('Langfuse 界面地址无效')
  const url = new URL(value)
  if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password
      || url.search || url.hash || !/\/project\/[^/]+\/traces$/.test(url.pathname)) {
    throw new Error('Langfuse 界面地址无效')
  }
  return url
}
export async function openLangfuse(traceUrl?: string) {
  if (desktopBridge) return nativeLangfuse('open', traceUrl)
  // Verify first: failed authentication must not create/close a blank tab.
  {
    let result: any
    try { result = await langfuseSession() }
    catch (error: any) {
      if (!['auto_login_disabled', 'credentials_missing'].includes(error.error?.code || error.response?.data?.error?.code)) throw error
      const status: any = await client.get('/api/v1/observability/langfuse/status')
      result = { ...status.data, state: 'manual', message: '已打开 Langfuse，请在新页面手动登录' }
    }
    const allowed = validatedDestination(result?.open_url)
    let destination = allowed.href
    if (traceUrl) {
      const trace = new URL(traceUrl)
      const projectPath = allowed.pathname.replace(/\/traces$/, '/')
      if (trace.origin === allowed.origin && trace.pathname.startsWith(projectPath)
          && !trace.username && !trace.password) destination = trace.href
    }
    const popup = window.open(destination, '_blank')
    if (popup) popup.opener = null
    else window.location.assign(destination)
    return result
  }
}
