import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Worker } from 'node:worker_threads';
import test from 'node:test';
import { CoreApplication } from '../src/application.js';
import { QueryClient } from '../src/runtime/query-client.js';
import type { QueryBootstrap } from '../src/runtime/query-contracts.js';

test('actual readonly worker bounds admission, validates every token, preserves tenants, aborts, and closes', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-query-private ')), app = new CoreApplication(root);
  const issue = app.auth.register({ username: 'query-client', password: 'query-client-password' });
  const other = app.auth.register({ username: 'other-client', password: 'other-client-password' });
  const kb = app.knowledge.knowledgeBases.create(issue.context, { name: '受保护资料' });
  const authority = new SharedArrayBuffer(8), bootstrap: QueryBootstrap = { databasePath: app.database.path, dataRoot: root, generation: randomUUID(), parserEnabled: false };
  let alive = true, client: QueryClient | undefined;
  const request = (path = '/api/v1/auth/me') => ({ protocol: 1 as const, id: randomUUID(), method: 'GET' as const, path });
  const binding = { transport: 'ipc' as const, access: issue.credentials.access };
  try {
    client = await QueryClient.start(bootstrap, authority, () => alive);
    const pending = Array.from({ length: 33 }, () => client!.dispatch(request(), binding, '0'));
    await assert.rejects(client.dispatch(request(), binding, '0'), { status: 429, code: 'query_busy' });
    assert.equal(client.pendingCount, 33);
    for (const result of await Promise.all(pending)) { assert.equal(result.status, 200); assert.equal((result.body as any).data.auth_mode, 'ipc'); }
    assert.equal(client.pendingCount, 0);
    assert.equal((await client.dispatch(request(`/api/v1/knowledge-bases/${kb.id}`), { transport: 'http', access: other.credentials.access }, '0')).status, 404);
    assert.equal((await client.dispatch(request(), { ...binding, selectedTenant: other.context.tenantId }, '0')).status, 401);
    const cancelled = new AbortController(), reason = new Error('isolated query abort');
    const first = client.dispatch(request(), binding, '0'), second = client.dispatch(request(), binding, '0', cancelled.signal);
    cancelled.abort(reason); await assert.rejects(second, error => error === reason); assert.equal((await first).status, 200);
    const stale = client.dispatch(request(), binding, '0'); Atomics.add(new BigUint64Array(authority), 0, 1n);
    await assert.rejects(stale, { status: 409, code: 'auth_superseded' });
    app.auth.logout(issue.context);
    assert.equal((await client.dispatch(request(), binding, '1')).status, 401);
    assert.equal((await client.dispatch(request(`/api/v1/knowledge/${randomUUID()}/stages`), { transport: 'http', access: other.credentials.access }, '1')).status, 503);
    alive = false; await assert.rejects(client.dispatch(request(), binding, '1'), { status: 503 });
    const close = client.close(); assert.equal(client.close(), close); await close;
  } finally { await client?.close(); await app.close(); await rm(root, { recursive: true, force: true }); }
});

test('actual query worker crash gives safe failures and one controlled readonly restart', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-query-crash ')), app = new CoreApplication(root);
  const issue = app.auth.register({ username: 'query-crash', password: 'query-crash-password' });
  const authority = new SharedArrayBuffer(8), bootstrap: QueryBootstrap = { databasePath: app.database.path, dataRoot: root, generation: randomUUID(), parserEnabled: false };
  let client: QueryClient | undefined;
  const request = () => ({ protocol: 1 as const, id: randomUUID(), method: 'GET' as const, path: '/api/v1/auth/me' });
  const binding = { transport: 'http' as const, access: issue.credentials.access };
  try {
    const worker = new Worker(new URL('../src/runtime/query-worker.ts', import.meta.url), { workerData: { bootstrap, authority }, execArgv: [], stdout: true, stderr: true });
    client = await QueryClient.connect(worker, bootstrap, authority, () => true);
    assert.equal((await client.dispatch(request(), binding, '0')).status, 200);
    const pending = client.dispatch(request(), binding, '0'); void worker.terminate();
    await assert.rejects(pending, { status: 503 });
    // Wait for an actual readiness transition, bounded by a deadline; never
    // count polling delay as product latency or use an owner fallback.
    const limit = Date.now() + 10000;
    let result;
    while (Date.now() < limit) {
      try { result = await client.dispatch(request(), binding, '0'); break; }
      catch (error) { assert.equal((error as any).status, 503); await new Promise(resolve => setTimeout(resolve, 20)); }
    }
    assert.equal(result?.status, 200);
  } finally { await client?.close(); await app.close(); await rm(root, { recursive: true, force: true }); }
});
