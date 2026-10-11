import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { CoreApplication } from '../src/application.js';
import { createCoreHttpServer } from '../src/adapters/http.js';
import type { JsonObject } from '../src/contracts.js';

test('fixed public embed dispatch receives only trusted HTTP origin and bearer and preserves CSRF', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-public-boundary-'));
  const app = new CoreApplication(root, { allowAutoSetup: true });
  const http = createCoreHttpServer(app, { port: 0 });
  try {
    assert.equal(typeof app.publicRoute, 'function');
    const { origin } = await http.listen();
    const owner = app.auth.autoSetup({ password: 'public-boundary-fixture' });
    const kb = app.knowledge.knowledgeBases.create(owner.context, { name: 'Public boundary fixture' });
    const created = await fetch(origin + '/api/v1/embed-channels', { method: 'POST', headers: { origin, authorization: `Bearer ${owner.credentials.access}`, 'content-type': 'application/json' }, body: JSON.stringify({ name: 'Origin fixture', allowed_origins: [origin], knowledge_base_ids: [kb.id] }) });
    assert.equal(created.status, 200);
    const channel = String(((await created.json() as JsonObject).data as JsonObject).id);
    const csrf = await fetch(origin + '/api/v1/auth/csrf');
    const token = ((await csrf.json() as JsonObject).data as JsonObject).csrf_token as string;
    const request = (headers: Record<string, string>) => fetch(origin + `/api/v1/embed/${channel}/exchange`, { method: 'POST', headers: { origin, 'content-type': 'application/json', ...headers }, body: JSON.stringify({ origin: 'https://forged.invalid', bearer: 'forged-body', transport: 'ipc', auth: { isSystemAdmin: true } }) });
    assert.equal((await request({})).status, 403);
    const response = await request({ cookie: `csrftoken=${token}`, 'x-csrftoken': token });
    assert.equal(response.status, 200);
    const grant = (await response.json() as JsonObject).data as JsonObject;
    assert.equal(grant.channel_id, channel);
    assert.equal(typeof grant.token, 'string');
    assert.equal((await request({ origin: 'https://forged.invalid', authorization: 'Bearer fixture-grant' })).status, 403);
    const alias = await fetch(origin + `/api/v1/embed/${channel}/config`, { headers: { origin, 'x-embed-token': String(grant.token) } });
    assert.equal(alias.status, 200);
    assert.equal(((await alias.json() as JsonObject).data as JsonObject).id, channel);
    assert.equal((await app.dispatch({ protocol: 1, id: randomUUID(), method: 'GET', path: '/api/v1/auth/me' }, { transport: 'http', embedToken: String(grant.token) })).response.status, 401);
  } finally { await http.close(); await app.close(); rmSync(root, { recursive: true, force: true }); }
});

test('public registration cannot expose arbitrary APIs or bypass native authentication', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-public-registration-'));
  const app = new CoreApplication(root);
  try {
    assert.equal(typeof app.publicRoute, 'function');
    assert.throws(() => app.publicRoute('GET', '/api/v1/auth/me', () => ({ leaked: true })));
    assert.throws(() => app.publicRoute('GET', '/api/v1/embed/:channel/exchange', () => ({})));
    assert.throws(() => app.publicRoute('GET', '/api/v1/embed/:channel/config', () => ({})));
    const ipc = await app.dispatch({ protocol: 1, id: randomUUID(), method: 'GET', path: '/api/v1/embed/owned/config' }, { transport: 'ipc', bearer: 'forged', origin: 'https://forged.invalid' });
    assert.equal(ipc.response.status, 404);
  } finally { await app.close(); rmSync(root, { recursive: true, force: true }); }
});
