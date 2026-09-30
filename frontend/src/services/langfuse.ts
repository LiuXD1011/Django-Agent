import client from '../api/client'

let inFlight: Promise<any> | null = null
let attemptedIdentity = ''
export async function langfuseSession() {
  if (!inFlight) {
    inFlight = client.post('/api/v1/observability/langfuse/session', {}).then((r: any) => r.data)
      .finally(() => { inFlight = null })
  }
  return inFlight
}
export async function autoLoginLangfuse() {
  const token = localStorage.getItem('personal_kb_token')
  let user: any
  try { user = JSON.parse(localStorage.getItem('personal_kb_user') || '{}') } catch { return }
  if (!token || !user.id) return
  // Authorization remains server-side: system admin or the explicitly bound local account.
  const identity = String(user.id)
  if (attemptedIdentity === identity) return
  attemptedIdentity = identity
  try { await langfuseSession() } catch { /* Settings shows a retryable diagnostic. */ }
}
export async function clearLangfuseSession() {
  attemptedIdentity = ''
  try {
    if (inFlight) await inFlight.catch(() => {})
    await client.post('/api/v1/observability/langfuse/session/clear', {})
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
  // Verify first: failed authentication must not create/close a blank tab.
  {
    let result: any
    try { result = await langfuseSession() }
    catch (error: any) {
      if ((error.error?.code || error.response?.data?.error?.code) !== 'auto_login_disabled') throw error
      const status: any = await client.get('/api/v1/observability/langfuse/status')
      result = status.data
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
  }
}
