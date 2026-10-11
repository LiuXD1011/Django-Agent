import type { JsonObject } from '../contracts.js';
import { type CallScope, type IntegrationCallOptions, endpoint, fail, responseJSON, restrictedFetch } from './network.js';

export interface LangfuseSessionOptions extends IntegrationCallOptions { requestOrigin: string; remoteAddress: string; existingCookies?: Record<string, string> }
export interface SessionCookie { name: string; value: string; secure: boolean; maxAge: number }
/** Cookies are trusted adapter output, never renderer JSON. */
export interface LangfuseSessionResult { result: JsonObject; cookies: SessionCookie[] }
export interface NativeLangfusePlan { ticket: string; ownerScope: string; origin: string; projectPath: string; open_url: string; mode: 'automatic' | 'manual'; reason: string }
export interface NativeLangfuseRequest { id: string; action: 'prepare' | 'session' | 'validate' | 'clear'; ticket?: string; existingCookies?: Record<string, string>; tenantId?: string }
export const sessionName = /^(?:__Secure-)?next-auth\.session-token(?:\.\d+)?$/;
const loopback = (host: string) => ['localhost', '127.0.0.1', '::1', '[::1]'].includes(host);
export function openURL(config: JsonObject): string {
  const base = endpoint(config.ui_base_url || config.base_url || 'http://localhost:3000');
  if (typeof config.ui_project_id !== 'string' || !config.ui_project_id || config.ui_project_id.length > 256) return fail(400, 'invalid_ui_configuration', 'Configure the Langfuse UI address and project');
  return base.toString().replace(/\/$/, '') + `/project/${encodeURIComponent(config.ui_project_id)}/traces`;
}
export function localGuard(config: JsonObject, options: LangfuseSessionOptions): URL {
  const base = endpoint(config.base_url || 'http://localhost:3000'), ui = endpoint(config.ui_base_url || base.toString()), origin = endpoint(options.requestOrigin);
  if (!loopback(base.hostname) || base.hostname !== ui.hostname || base.hostname !== origin.hostname || !['', '/'].includes(base.pathname) || !loopback(options.remoteAddress.replace(/^::ffff:/, ''))) return fail(400, 'local_host_required', 'Local login requires the same loopback host for the core and Langfuse');
  return base;
}
export function existingSession(options: { existingCookies?: Record<string, string> }): Record<string, string> {
  const cookies: Record<string, string> = {};
  for (const [name, value] of Object.entries(options.existingCookies || {})) if (sessionName.test(name)) {
    if (typeof value !== 'string' || /[\s;,\r\n]/.test(value)) return fail(400, 'invalid_session_cookie', 'Invalid local session cookie');
    cookies[name] = value;
  }
  if (JSON.stringify(cookies).length > 32768 || Object.keys(cookies).length > 20) return fail(400, 'invalid_session_cookie', 'Local session cookies exceed the size limit');
  return cookies;
}
/** Native capability comes from the private parent process, never an HTTP Origin header. */
export function nativeGuard(config: JsonObject): URL {
  const base = endpoint(config.base_url), ui = endpoint(config.ui_base_url || config.base_url);
  if (!loopback(base.hostname) || base.origin !== ui.origin || !['', '/'].includes(base.pathname) || !['', '/'].includes(ui.pathname)) return fail(400, 'local_host_required', 'Native automatic login requires the same configured loopback origin for the API and UI');
  return base;
}
export function validateNativeLangfuseRequest(input: unknown): asserts input is NativeLangfuseRequest {
  const invalid = () => fail(400, 'invalid_native_langfuse_request', 'Langfuse 桌面请求不正确。');
  if (!input || Object.getPrototypeOf(input) !== Object.prototype) invalid();
  const value = input as Record<string, unknown>;
  if (Object.keys(value).some(key => !['id', 'action', 'ticket', 'existingCookies', 'tenantId'].includes(key)) || typeof value.id !== 'string' || !value.id || value.id.length > 200 || /[\x00-\x1f\x7f]/.test(value.id) || !['prepare', 'session', 'validate', 'clear'].includes(String(value.action))) invalid();
  if (value.tenantId !== undefined && (typeof value.tenantId !== 'string' || !value.tenantId || value.tenantId.length > 128)) invalid();
  if (['session', 'validate'].includes(String(value.action)) ? typeof value.ticket !== 'string' || !/^[a-f0-9-]{36}$/.test(value.ticket) : value.ticket !== undefined) invalid();
  if (value.existingCookies !== undefined) {
    if (value.action !== 'session' || !value.existingCookies || Object.getPrototypeOf(value.existingCookies) !== Object.prototype || Object.keys(value.existingCookies).some(name => !sessionName.test(name))) invalid();
    existingSession({ existingCookies: value.existingCookies as Record<string, string> });
  }
}
function validSession(data: any, local: JsonObject, config: JsonObject): boolean {
  return typeof data?.user?.email === 'string' && data.user.email.toLowerCase() === String(local.login_email).toLowerCase() && Array.isArray(data.user.organizations) && data.user.organizations.some((org: any) => Array.isArray(org?.projects) && org.projects.some((project: any) => project?.id === config.ui_project_id));
}
export async function login(scope: CallScope, config: JsonObject, local: JsonObject, options: LangfuseSessionOptions): Promise<LangfuseSessionResult> {
  return loginAt(scope, config, local, localGuard(config, options), options);
}
export async function nativeLogin(scope: CallScope, config: JsonObject, local: JsonObject, existingCookies?: Record<string, string>): Promise<LangfuseSessionResult> {
  return loginAt(scope, config, local, nativeGuard(config), { existingCookies });
}
async function loginAt(scope: CallScope, config: JsonObject, local: JsonObject, base: URL, options: { existingCookies?: Record<string, string> }): Promise<LangfuseSessionResult> {
  const destination = openURL(config);
  if (!local.login_email || !local.password) return fail(409, 'credentials_missing', 'Configure the local Langfuse login account and password');
  let jar = existingSession(options); const fetch = restrictedFetch(scope, base.origin);
  const request = async (path: string, init: RequestInit = {}) => {
    const headers = new Headers(init.headers); headers.set('accept', 'application/json');
    if (Object.keys(jar).length) headers.set('cookie', Object.entries(jar).map(([name, value]) => `${name}=${value}`).join('; '));
    const response = await fetch(new URL(path, base), { ...init, headers });
    for (const line of response.headers.getSetCookie()) {
      const cookie = line.split(';', 1)[0]!, equal = cookie.indexOf('=');
      const name = cookie.slice(0, equal), value = cookie.slice(equal + 1);
      if (equal > 0 && /^[a-zA-Z0-9_.-]{1,128}$/.test(name) && !/[\s;,\r\n]/.test(value)) jar[name] = value;
    }
    if (JSON.stringify(jar).length > 32768 || Object.keys(jar).length > 40) { await response.body?.cancel(); return fail(502, 'login_failed', 'Langfuse returned invalid local session cookies'); }
    return responseJSON(response);
  };
  const projection = (state: string): LangfuseSessionResult => ({ result: { state, open_url: destination }, cookies: Object.entries(jar).filter(([name]) => sessionName.test(name)).map(([name, value]) => ({ name, value, secure: base.protocol === 'https:' || name.startsWith('__Secure-'), maxAge: 3600 })) });
  if (Object.keys(jar).length) {
    const session = await request('/api/auth/session') as any;
    if (validSession(session, local, config)) return projection('reused');
    if (session?.user) return fail(409, 'account_conflict', 'The browser is logged in to another Langfuse account');
    jar = {};
  }
  const csrf = await request('/api/auth/csrf') as any;
  if (typeof csrf?.csrfToken !== 'string' || !csrf.csrfToken || csrf.csrfToken.length > 4096) return fail(502, 'login_failed', 'Langfuse login verification failed');
  const form = new URLSearchParams({ csrfToken: csrf.csrfToken, email: String(local.login_email), password: String(local.password), json: 'true', callbackUrl: destination });
  await request('/api/auth/callback/credentials', { method: 'POST', headers: { 'content-type': 'application/x-www-form-urlencoded' }, body: form.toString() });
  if (!validSession(await request('/api/auth/session'), local, config)) return fail(502, 'login_failed', 'Langfuse login verification failed');
  const result = projection('connected'); if (!result.cookies.length) return fail(502, 'login_failed', 'Langfuse did not establish a local browser session');
  return result;
}
export function clearSession(config: JsonObject, options: LangfuseSessionOptions): LangfuseSessionResult {
  const base = localGuard(config, options);
  return { result: { state: 'cleared' }, cookies: Object.keys(existingSession(options)).map(name => ({ name, value: '', maxAge: 0, secure: base.protocol === 'https:' || name.startsWith('__Secure-') })) };
}
