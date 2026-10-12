import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Worker } from 'node:worker_threads';
import test from 'node:test';
import { createCoreHttpServer } from '../src/adapters/http.js';
import type { CoreRequest, HttpMethod, JsonObject } from '../src/contracts.js';
import { CoreOwner } from '../src/runtime/owner-client.js';

const request = (method: HttpMethod, path: string, body?: JsonObject): CoreRequest => ({ protocol: 1, id: randomUUID(), method, path, ...(body ? { body } : {}) });
test('actual SQLite discard failure closes both transports instead of exposing an unconfirmed identity', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-auth-cleanup-failure ')), authority = new SharedArrayBuffer(8), barrier = new SharedArrayBuffer(12), replyBarrier = new SharedArrayBuffer(8), reply = new Int32Array(replyBarrier), generation = randomUUID();
  let owner: CoreOwner | undefined, http: ReturnType<typeof createCoreHttpServer> | undefined;
  try {
    const worker = new Worker(new URL('./fixtures/core-owner-publication-worker.ts', import.meta.url), { workerData: { config: { dataRoot: root }, authority, generation, barrier, replyBarrier }, execArgv: [], stdout: true, stderr: true });
    owner = await CoreOwner.connect(worker, { authority, generation });
    http = createCoreHttpServer(await owner.httpTransport(), { port: 0 }); const { origin } = await http.listen();
    await owner.invoke(request('POST', '/api/v1/auth/auto-setup', { password: 'cleanup-failure-password' }));
    await owner.invoke(request('POST', '/api/v1/fixture/fail-auth-discard'));
    await owner.invoke(request('POST', '/api/v1/fixture/arm-auth-reply'));
    const earlier = owner.invoke(request('POST', '/api/v1/auth/login', { login: 'admin', password: 'cleanup-failure-password' }));
    const rejected = assert.rejects(earlier, { status: 503, code: 'owner_failed' });
    assert.notEqual(await Atomics.waitAsync(reply, 0, 0, 5000).value, 'timed-out');
    const later = owner.invoke(request('POST', '/api/v1/auth/login', { login: 'admin', password: 'incorrect-cleanup-password' }));
    Atomics.store(reply, 1, 1); Atomics.notify(reply, 1);
    assert.equal((await later).status, 401); await rejected;
    await assert.rejects(owner.invoke(request('GET', '/api/v1/auth/me')), { status: 503, code: 'owner_failed' });
    assert.equal((await fetch(origin + '/health')).status, 503);
    assert.equal((await fetch(origin + '/api/v1/auth/me')).status, 503);
  } finally { Atomics.store(reply, 1, 1); Atomics.notify(reply, 1); await http?.close(); await owner?.close().catch(() => {}); await rm(root, { recursive: true, force: true }); }
});
