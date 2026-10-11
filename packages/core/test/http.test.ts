import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { request as httpRequest } from 'node:http';
import { test } from 'node:test';

async function fixture(options: { allowAutoSetup?: boolean; now?: () => number } = {}) {
  const appModule = await import('../src/application.js').catch(() => null);
  const httpModule = await import('../src/adapters/http.js').catch(() => null);
  assert.ok(appModule && httpModule, 'Browser adapter must invoke the independent TypeScript application');
  const root = mkdtempSync(join(tmpdir(), 'marlin-http-'));
  const app = new appModule.CoreApplication(root, { allowAutoSetup: true, ...options });
  const adapter = httpModule.createCoreHttpServer(app, { port: 0 });
  const { origin } = await adapter.listen();
  const jar = new Map<string, string>();
  const request = async (path: string, options: { method?: string; body?: unknown; headers?: Record<string, string>; cookie?: boolean; csrf?: boolean } = {}) => {
    const method = options.method ?? 'GET';
    const cookie = [...jar].map(([name, value]) => `${name}=${value}`).join('; ');
    const response = await fetch(origin + path, {
      method, headers: { Origin: origin, ...(options.body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...(options.cookie !== false && cookie ? { Cookie: cookie } : {}), ...(options.csrf !== false && jar.get('csrftoken') && method !== 'GET' ? { 'X-CSRFToken': jar.get('csrftoken')! } : {}), ...options.headers },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    for (const value of response.headers.getSetCookie()) {
      const pair = value.split(';')[0]!; const index = pair.indexOf('=');
      if (pair.slice(index + 1)) jar.set(pair.slice(0, index), pair.slice(index + 1));
      else jar.delete(pair.slice(0, index));
    }
    return { response, body: await response.json() as any };
  };
  const setup = async () => {
    assert.equal((await request('/api/v1/auth/csrf')).response.status, 200);
    return request('/api/v1/auth/auto-setup', { method: 'POST', body: { email: 'qa@example.invalid', password: '验收账户 密码🪸', auth_mode: 'cookie' } });
  };
  return { app, adapter, origin, jar, request, setup, async close() { await adapter.close(); await app.close(); rmSync(root, { recursive: true, force: true }); } };
}

test('new HTTP application initializes explicitly and persists identity through private cookies; no credentials in renderer JSON', async () => {
  const f = await fixture();
  try {
    const before = await f.request('/api/v1/capabilities');
    assert.equal(before.body.data.setup_required, true);
    const result = await f.setup();
    assert.equal(result.response.status, 200);
    assert.equal(result.body.data.user.is_system_admin, true);
    assert.equal(result.body.data.tenant.space_type, 'personal');
    assert.equal(result.body.data.auth_mode, 'cookie');
    assert.equal(JSON.stringify(result.body).includes('验收账户 密码🪸'), false);
    for (const forbidden of ['password', 'temp_password', 'token', 'refresh_token', 'credentials', 'api_key']) assert.equal(Object.hasOwn(result.body.data, forbidden), false);
    assert.equal(Object.hasOwn(result.body.data.tenant, 'api_key'), false);
    const cookies = result.response.headers.getSetCookie();
    assert.ok(cookies.some(value => value.startsWith('marlin_access=') && value.includes('HttpOnly') && value.includes('SameSite=Strict')));
    assert.ok(cookies.some(value => value.startsWith('marlin_refresh=') && value.includes('HttpOnly')));
    assert.equal((await f.request('/api/v1/auth/me')).body.data.user.id, result.body.data.user.id);
    const later = await f.request('/api/v1/capabilities');
    assert.equal(later.body.data.setup_required, false);
    assert.equal(later.body.data.service_id, before.body.data.service_id);
    assert.equal((await f.setup()).response.status, 401, 'initialization cannot replace an existing administrator');
  } finally { await f.close(); }
});

test('loopback Host, Origin, fetch-site and signed CSRF are checked before unsafe operations', async () => {
  const f = await fixture();
  try {
    await f.request('/api/v1/auth/csrf');
    const body = { email: 'other@example.invalid', password: 'other-password' };
    assert.equal((await f.request('/api/v1/auth/register', { method: 'POST', body, csrf: false })).response.status, 403);
    assert.equal((await f.request('/api/v1/auth/register', { method: 'POST', body, headers: { Origin: 'https://attacker.invalid' } })).response.status, 403);
    assert.equal((await f.request('/api/v1/auth/register', { method: 'POST', body, headers: { 'Sec-Fetch-Site': 'cross-site' } })).response.status, 403);
    // Node's fetch normalizes Host, so send this hostile header on the actual HTTP wire.
    const hostileHostStatus = await new Promise<number>(resolve => {
      const req = httpRequest(f.origin + '/api/v1/capabilities', { headers: { Host: 'attacker.invalid' } }, response => { response.resume(); resolve(response.statusCode!); });
      req.end();
    });
    assert.equal(hostileHostStatus, 403);
    f.jar.set('csrftoken', 'forged-double-submit-token');
    assert.equal((await f.request('/api/v1/auth/register', { method: 'POST', body })).response.status, 403);
    assert.equal(f.app.database.get('select count(*) as n from users')?.n, 0);
  } finally { await f.close(); }
});

test('expired access refresh rotates cookies; replay revokes the actual device and logout is authoritative', async () => {
  let now = Date.now(); const f = await fixture({ now: () => now });
  try {
    await f.setup(); const oldRefresh = f.jar.get('marlin_refresh')!;
    now += 11 * 60000;
    assert.equal((await f.request('/api/v1/auth/me')).response.status, 401);
    assert.equal((await f.request('/api/v1/auth/refresh', { method: 'POST', body: { auth_mode: 'cookie' } })).response.status, 200);
    assert.notEqual(f.jar.get('marlin_refresh'), oldRefresh);
    assert.equal((await f.request('/api/v1/auth/me')).response.status, 200);
    const newRefresh = f.jar.get('marlin_refresh')!;
    f.jar.set('marlin_refresh', oldRefresh);
    assert.equal((await f.request('/api/v1/auth/refresh', { method: 'POST', body: { auth_mode: 'cookie' } })).response.status, 401);
    f.jar.set('marlin_refresh', newRefresh);
    assert.equal((await f.request('/api/v1/auth/me')).response.status, 401);
    assert.equal((await f.request('/api/v1/auth/logout', { method: 'POST', body: {} })).response.status, 200);
    assert.equal(f.jar.has('marlin_access'), false); assert.equal(f.jar.has('marlin_refresh'), false);
  } finally { await f.close(); }
});

test('account preferences persist, wrong password preserves sessions, correct change revokes all sessions', async () => {
  const f = await fixture();
  try {
    await f.setup();
    assert.equal((await f.request('/api/v1/auth/me/preferences', { method: 'PUT', body: { enable_memory: false } })).response.status, 200);
    assert.equal((await f.request('/api/v1/auth/me')).body.data.user.preferences.enable_memory, false);
    assert.equal((await f.request('/api/v1/auth/change-password', { method: 'POST', body: { old_password: 'wrong', new_password: 'new-test-password' } })).response.status, 400);
    assert.equal((await f.request('/api/v1/auth/me')).response.status, 200);
    assert.equal((await f.request('/api/v1/auth/change-password', { method: 'POST', body: { old_password: '验收账户 密码🪸', new_password: 'new-test-password' } })).response.status, 200);
    assert.equal((await f.request('/api/v1/auth/me')).response.status, 401);
    assert.equal((await f.request('/api/v1/auth/login', { method: 'POST', body: { email: 'qa@example.invalid', password: 'new-test-password' } })).response.status, 200);
  } finally { await f.close(); }
});

test('selected tenant and device requests cannot bypass actual membership and user ownership', async () => {
  const f = await fixture();
  try {
    await f.setup(); const originalJar = new Map(f.jar);
    const other = await f.request('/api/v1/auth/register', { method: 'POST', body: { email: 'other@example.invalid', password: 'other-password' } });
    const otherTenant = other.body.data.tenant.id;
    const otherDevice = other.body.data.device.id;
    f.jar.clear(); for (const [key, value] of originalJar) f.jar.set(key, value);
    assert.equal((await f.request('/api/v1/auth/me', { headers: { 'X-Tenant-ID': otherTenant } })).response.status, 401);
    assert.equal((await f.request('/api/v1/auth/devices/' + otherDevice, { method: 'DELETE' })).response.status, 404);
    assert.equal((await f.request('/api/v1/auth/devices')).body.data.items.length, 1);
  } finally { await f.close(); }
});

test('unsafe body format and unknown routes fail explicitly, without serializing exception details', async () => {
  const f = await fixture();
  try {
    await f.request('/api/v1/auth/csrf');
    const malformed = await fetch(f.origin + '/api/v1/auth/login', { method: 'POST', headers: { Origin: f.origin, 'Content-Type': 'application/json', Cookie: `csrftoken=${f.jar.get('csrftoken')}`, 'X-CSRFToken': f.jar.get('csrftoken')! }, body: '{"password":"do-not-echo-secret"' });
    assert.equal(malformed.status, 400); assert.equal((await malformed.text()).includes('do-not-echo-secret'), false);
    const unknown = await f.request('/api/v1/not-implemented');
    assert.equal(unknown.response.status, 404); assert.equal(unknown.body.success, false);
    assert.equal((await f.request('/api/v1/auth/me', { cookie: false })).response.status, 401);
  } finally { await f.close(); }
});
