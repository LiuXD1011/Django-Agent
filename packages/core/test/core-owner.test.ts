import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import type { CoreRequest, HttpMethod, JsonObject } from '../src/contracts.js';
import { CoreOwner } from '../src/runtime/owner-client.js';

const request = (method: HttpMethod, path: string, body?: JsonObject): CoreRequest => ({ protocol: 1, id: randomUUID(), method, path, ...(body ? { body } : {}) });
const data = (response: { body: unknown }): any => (response.body as any).data;

test('real complete owner Worker restores its private session and authoritative SQLite identity after restart', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'marlin-owner 真实 '));
  let owner: any;
  try {
    owner = await CoreOwner.start({ dataRoot: directory, allowAutoSetup: true });
    assert.equal((await owner.invoke(request('GET', '/api/v1/auth/me'))).status, 401);
    const setup = await owner.invoke(request('POST', '/api/v1/auth/auto-setup', { password: 'owner-isolated-test-password' }));
    assert.equal(setup.status, 200);
    assert.equal(data(setup).auth_mode, 'ipc');
    for (const forbidden of ['credentials', 'token', 'refresh_token', 'password']) assert.equal(Object.hasOwn(data(setup), forbidden), false);
    const kb = await owner.invoke(request('POST', '/api/v1/knowledge-bases', { name: '唯一写者 真实库' }));
    assert.equal(kb.status, 200);
    const id = owner.serviceId;
    await owner.close();
    owner = await CoreOwner.start({ dataRoot: directory, allowAutoSetup: true });
    assert.equal(owner.serviceId, id);
    assert.equal((await owner.invoke(request('GET', '/api/v1/auth/me'))).status, 200);
    assert.equal(data(await owner.invoke(request('GET', `/api/v1/knowledge-bases/${data(kb).id}`))).name, '唯一写者 真实库');
    assert.equal((await owner.invoke(request('POST', '/api/v1/auth/logout'))).status, 200);
    assert.equal((await owner.invoke(request('GET', '/api/v1/auth/me'))).status, 401);
  } finally { await owner?.close(); await rm(directory, { recursive: true, force: true }); }
});

test('owner startup loads actual native SQLite, FTS5 and sqlite-vec inside its Worker', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'marlin-owner-native '));
  let owner: any;
  try {
    owner = await CoreOwner.start({ dataRoot: directory, allowAutoSetup: true });
    assert.equal((await owner.invoke(request('POST', '/api/v1/auth/auto-setup', { password: 'owner-native-test-password' }))).status, 200);
    const result = await owner.invoke(request('GET', '/api/v1/system/storage-engine-status'));
    assert.equal(result.status, 200);
    assert.equal(data(result).status, 'available');
    assert.equal(data(result).checks.fts5, true); assert.equal(data(result).checks.vector_extension, true);
    assert.equal(data(result).database.journal_mode, 'wal');
    assert.match(data(result).vector.version, /\d/);
  } finally { await owner?.close(); await rm(directory, { recursive: true, force: true }); }
});
