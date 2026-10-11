import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { CoreApplication } from '../src/application.js';
import { CoreIpcAdapter } from '../src/adapters/ipc.js';
import { createCoreHttpServer } from '../src/adapters/http.js';
import type { CoreResponse, HttpMethod, JsonObject } from '../src/contracts.js';

const data = (response: CoreResponse): JsonObject => (response.body as JsonObject).data as JsonObject;

test('new native devices have an accurate desktop default while explicit saved names remain unchanged', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-legacy-device-'));
  const app = new CoreApplication(root, { allowAutoSetup: true });
  try {
    const ipc = new CoreIpcAdapter(app);
    const setup = await ipc.invoke({ protocol: 1, id: randomUUID(), method: 'POST', path: '/api/v1/auth/auto-setup', body: { password: 'desktop-name-fixture' } });
    assert.equal(setup.status, 200);
    const device = data(setup).device as JsonObject;
    assert.equal(device.client_type, 'desktop'); assert.equal(device.name, '桌面设备');
    const web = app.auth.login({ login: 'admin', password: 'desktop-name-fixture', clientType: 'web' });
    assert.equal(web.public.device?.name, '网页设备');
    const named = app.auth.login({ login: 'admin', password: 'desktop-name-fixture', clientType: 'desktop', deviceName: 'Chosen fixture device' });
    assert.equal(named.public.device?.name, 'Chosen fixture device');
  } finally { await app.close(); rmSync(root, { recursive: true, force: true }); }
});

test('legacy tenant creation, member authority, key rotation and audit are real through HTTP', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-legacy-http-'));
  const app = new CoreApplication(root, { allowAutoSetup: true });
  const http = createCoreHttpServer(app, { port: 0 });
  try {
    const owner = app.auth.autoSetup({ password: 'legacy-http-owned-fixture' });
    const member = app.auth.register({ email: 'legacy-member@example.invalid', password: 'legacy-member-fixture' });
    const { origin } = await http.listen();
    const request = async (method: HttpMethod, path: string, body?: JsonObject, access = owner.credentials.access, tenant?: string) => {
      const response = await fetch(origin + path, { method, headers: { authorization: `Bearer ${access}`, ...(tenant ? { 'x-tenant-id': tenant } : {}), ...(body ? { 'content-type': 'application/json' } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}) });
      return { status: response.status, body: await response.json() as JsonObject };
    };
    const created = await request('POST', '/api/v1/tenants', { name: 'Legacy shared fixture', description: 'scope fixture', business: 'test' });
    assert.equal(created.status, 200);
    const tenant = String((created.body.data as JsonObject).id);
    assert.equal((created.body.data as JsonObject).space_type, 'legacy');
    assert.equal((created.body.data as JsonObject).api_key, undefined);
    assert.equal(app.database.get('SELECT count(*) AS n FROM tenant_members WHERE tenant_id=? AND user_id=? AND role=?', tenant, owner.context.userId, 'owner')?.n, 1);
    const add = await request('POST', `/api/v1/tenants/${tenant}/members`, { user_id: member.context.userId, role: 'viewer' });
    assert.equal(add.status, 200); assert.equal((add.body.data as JsonObject).role, 'viewer');
    assert.equal((await request('PUT', `/api/v1/tenants/${tenant}/members/${owner.context.userId}`, { role: 'owner' }, member.credentials.access, tenant)).status, 403);
    assert.equal((await request('GET', `/api/v1/tenants/${owner.context.tenantId}/members`, undefined, member.credentials.access)).status, 404);
    const before = app.database.read('tenants', tenant)!.api_key;
    const rotate = await request('POST', `/api/v1/tenants/${tenant}/api-key`, {});
    assert.equal(rotate.status, 200);
    const key = (rotate.body.data as JsonObject).api_key;
    assert.equal(typeof key, 'string'); assert.notEqual(key, before);
    assert.throws(() => app.auth.authenticateApiKey(String(before)), { code: 'unauthorized' });
    assert.equal(app.auth.authenticateApiKey(String(key)).tenantId, tenant);
    const get = await request('GET', `/api/v1/tenants/${tenant}`);
    assert.equal(get.status, 200); assert.equal((get.body.data as JsonObject).api_key, undefined);
    assert.equal((await request('POST', `/api/v1/tenants/${tenant}/api-key`, {}, member.credentials.access, tenant)).status, 403);
    const audit = await request('GET', `/api/v1/tenants/${tenant}/audit-log`);
    assert.equal(audit.status, 200);
    assert.ok(((audit.body.data as JsonObject).items as JsonObject[]).some(item => item.action === 'tenant.api_key_rotated'));
    assert.equal(JSON.stringify(audit.body).includes(String(key)), false);
    assert.equal((await request('DELETE', `/api/v1/tenants/${tenant}/members/${member.context.userId}`)).status, 200);
    assert.equal(app.database.get('SELECT status FROM tenant_members WHERE tenant_id=? AND user_id=?', tenant, member.context.userId)?.status, 'revoked');
    assert.throws(() => app.auth.authenticateAccess(member.credentials.access, tenant), { code: 'unauthorized' });
    assert.equal((await request('DELETE', `/api/v1/tenants/${tenant}`)).status, 200);
    assert.ok(app.database.read('tenants', tenant)!.deleted_at);
    assert.equal(app.database.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
  } finally { await http.close(); await app.close(); rmSync(root, { recursive: true, force: true }); }
});

test('legacy scoped tenant list and switch retain personal isolation through real IPC', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-legacy-ipc-'));
  const app = new CoreApplication(root, { allowAutoSetup: true });
  try {
    const ipc = new CoreIpcAdapter(app);
    await ipc.invoke({ protocol: 1, id: randomUUID(), method: 'POST', path: '/api/v1/auth/auto-setup', body: { password: 'legacy-ipc-owned-fixture' } });
    const other = app.auth.register({ email: 'legacy-other@example.invalid', password: 'legacy-other-fixture' });
    const created = await ipc.invoke({ protocol: 1, id: randomUUID(), method: 'POST', path: '/api/v1/tenants', body: { name: 'IPC legacy fixture' } });
    assert.equal(created.status, 200); const tenant = String(data(created).id);
    const listed = await ipc.invoke({ protocol: 1, id: randomUUID(), method: 'GET', path: '/api/v1/tenants/all' });
    assert.equal(listed.status, 200);
    assert.ok((data(listed).items as JsonObject[]).some(item => String(item.id) === tenant));
    assert.equal((data(listed).items as JsonObject[]).some(item => String(item.id) === other.context.tenantId), false);
    const switched = await ipc.invoke({ protocol: 1, id: randomUUID(), method: 'POST', path: '/api/v1/auth/switch-tenant', body: { tenant_id: tenant } });
    assert.equal(switched.status, 200); assert.equal(String((data(switched).tenant as JsonObject).id), tenant);
    assert.equal((await ipc.invoke({ protocol: 1, id: randomUUID(), method: 'POST', path: '/api/v1/auth/switch-tenant', body: { tenant_id: other.context.tenantId } })).status, 403);
    assert.equal((await ipc.invoke({ protocol: 1, id: randomUUID(), method: 'POST', path: `/api/v1/tenants/${other.context.tenantId}/members`, body: { user_id: String((data(switched).user as JsonObject).id), role: 'owner' } })).status, 404);
    const oldKey = app.database.read('tenants', tenant)!.api_key;
    const rotated = await ipc.invoke({ protocol: 1, id: randomUUID(), method: 'POST', path: `/api/v1/tenants/${tenant}/api-key`, body: { transport: 'http', revealKey: true } });
    assert.equal(rotated.status, 200); assert.equal(data(rotated).rotated, true); assert.equal(data(rotated).api_key, undefined);
    const nextKey = app.database.read('tenants', tenant)!.api_key;
    assert.notEqual(nextKey, oldKey); assert.equal(JSON.stringify(rotated).includes(String(nextKey)), false);
    assert.throws(() => app.auth.authenticateApiKey(String(oldKey)), { code: 'unauthorized' });
    assert.equal(app.auth.authenticateApiKey(String(nextKey)).tenantId, tenant);
    assert.equal((await ipc.invoke({ protocol: 1, id: randomUUID(), method: 'GET', path: '/api/v1/system/admin/audit-log' })).status, 200);
  } finally { await app.close(); rmSync(root, { recursive: true, force: true }); }
});
