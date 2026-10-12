import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Worker } from 'node:worker_threads';
import test from 'node:test';
import type { CoreRequest, HttpMethod, JsonObject } from '../src/contracts.js';
import { CoreOwner } from '../src/runtime/owner-client.js';

const request = (method: HttpMethod, path: string, body?: JsonObject): CoreRequest => ({ protocol: 1, id: randomUUID(), method, path, ...(body ? { body } : {}) });
test('abort before actual stream header delivery ignores already queued frames without killing owner', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-stream-header ')), authority = new SharedArrayBuffer(8), barrier = new SharedArrayBuffer(12), replyBarrier = new SharedArrayBuffer(8), reply = new Int32Array(replyBarrier), generation = randomUUID();
  let owner: CoreOwner | undefined;
  try {
    const worker = new Worker(new URL('./fixtures/core-owner-publication-worker.ts', import.meta.url), { workerData: { config: { dataRoot: root }, authority, generation, barrier, replyBarrier }, execArgv: [], stdout: true, stderr: true });
    owner = await CoreOwner.connect(worker, { authority, generation });
    assert.equal((await owner.invoke(request('POST', '/api/v1/auth/auto-setup', { password: 'stream-header-password' }))).status, 200);
    await owner.invoke(request('PUT', '/api/v1/auth/me/preferences', { enable_memory: false }));
    const session = await owner.invoke(request('POST', '/api/v1/sessions', { title: 'early abort', knowledge_base_ids: [] })), sessionId = (session.body as any).data.id;
    await owner.invoke(request('POST', '/api/v1/fixture/arm-stream-reply'));
    const controller = new AbortController(), reason = new Error('abort before stream header');
    const stream = owner.openStream(request('POST', `/api/v1/knowledge-chat/${sessionId}`, { query: '没有配置模型', stream: true, knowledge_base_ids: [] }), {}, controller.signal);
    const rejected = assert.rejects(stream, error => error === reason);
    assert.notEqual(await Atomics.waitAsync(reply, 0, 0, 5000).value, 'timed-out');
    controller.abort(reason); await rejected;
    Atomics.store(reply, 1, 1); Atomics.notify(reply, 1);
    assert.equal((await owner.invoke(request('GET', '/api/v1/capabilities'))).status, 200);
    assert.equal((await owner.invoke(request('GET', '/api/v1/auth/me'))).status, 200);
  } finally { Atomics.store(reply, 1, 1); Atomics.notify(reply, 1); await owner?.close(); await rm(root, { recursive: true, force: true }); }
});
