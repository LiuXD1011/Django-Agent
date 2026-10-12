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
test('later auth intent fences a real HTTP login reply paused after the owner save check', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-auth-reply 真实 ')), authority = new SharedArrayBuffer(8), barrier = new SharedArrayBuffer(12), replyBarrier = new SharedArrayBuffer(8), reply = new Int32Array(replyBarrier), generation = randomUUID();
  let owner: CoreOwner | undefined, earlier: ReturnType<CoreOwner['dispatch']> | undefined, later: ReturnType<CoreOwner['dispatch']> | undefined;
  try {
    const worker = new Worker(new URL('./fixtures/core-owner-publication-worker.ts', import.meta.url), { workerData: { config: { dataRoot: root }, authority, generation, barrier, replyBarrier }, execArgv: [], stdout: true, stderr: true });
    owner = await CoreOwner.connect(worker, { authority, generation });
    assert.equal((await owner.invoke(request('POST', '/api/v1/auth/auto-setup', { password: 'auth-fence-password' }))).status, 200);
    const login = await owner.dispatch(request('POST', '/api/v1/auth/login', { login: 'admin', password: 'auth-fence-password' }), { transport: 'http' });
    const binding = { transport: 'http' as const, access: login.authChange!.issue!.credentials.access };
    await owner.invoke(request('POST', '/api/v1/fixture/arm-auth-reply'));
    earlier = owner.dispatch(request('POST', '/api/v1/auth/login?intent=earlier', { login: 'admin', password: 'auth-fence-password' }), { transport: 'http' });
    assert.notEqual(await Atomics.waitAsync(reply, 0, 0, 5000).value, 'timed-out');
    later = owner.dispatch(request('POST', '/api/v1/auth/logout?intent=later'), binding);
    // Even a call whose reply is pending must fence new reads immediately.
    assert.equal((await owner.invoke(request('GET', '/api/v1/auth/me'))).status, 409);
    Atomics.store(reply, 1, 1); Atomics.notify(reply, 1);
    const old = await earlier; assert.equal(old.response.status, 409); assert.equal(old.authChange, undefined);
    assert.equal((await later).response.status, 200);
    const devices = await owner.invoke(request('GET', '/api/v1/auth/devices'));
    assert.equal(devices.status, 200);
    assert.equal((devices.body as any).data.items.filter((row: any) => !row.is_revoked).length, 1, 'Only the original IPC device remains active');
    assert.equal((await owner.dispatch(request('GET', '/api/v1/auth/me'), binding)).response.status, 401);
  } finally {
    Atomics.store(reply, 1, 1); Atomics.notify(reply, 1);
    await Promise.allSettled([earlier, later]); await owner?.close(); await rm(root, { recursive: true, force: true });
  }
});

test('normal owner close rolls back an undisclosed IPC issue before closing SQLite', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-ipc-close 真实 ')), authority = new SharedArrayBuffer(8), barrier = new SharedArrayBuffer(12), replyBarrier = new SharedArrayBuffer(8), reply = new Int32Array(replyBarrier), generation = randomUUID();
  let owner: CoreOwner | undefined;
  try {
    const worker = new Worker(new URL('./fixtures/core-owner-publication-worker.ts', import.meta.url), { workerData: { config: { dataRoot: root }, authority, generation, barrier, replyBarrier }, execArgv: [], stdout: true, stderr: true });
    owner = await CoreOwner.connect(worker, { authority, generation });
    const setup = await owner.invoke(request('POST', '/api/v1/auth/auto-setup', { password: 'ipc-close-password' })), initialDevice = (setup.body as any).data.device.id;
    await owner.invoke(request('POST', '/api/v1/fixture/arm-auth-reply'));
    const pending = owner.invoke(request('POST', '/api/v1/auth/login', { login: 'admin', password: 'ipc-close-password' }));
    const rejected = assert.rejects(pending, { code: 'owner_closed' });
    assert.notEqual(await Atomics.waitAsync(reply, 0, 0, 5000).value, 'timed-out');
    const closing = owner.close(); await rejected;
    Atomics.store(reply, 1, 1); Atomics.notify(reply, 1); await closing;
    owner = await CoreOwner.start({ dataRoot: root });
    const restored = await owner.invoke(request('GET', '/api/v1/auth/me'));
    assert.equal(restored.status, 200); assert.equal((restored.body as any).data.device.id, initialDevice);
    const devices = await owner.invoke(request('GET', '/api/v1/auth/devices'));
    assert.equal((devices.body as any).data.items.filter((row: any) => !row.is_revoked).length, 1);
  } finally { Atomics.store(reply, 1, 1); Atomics.notify(reply, 1); await owner?.close(); await rm(root, { recursive: true, force: true }); }
});

test('a later failed IPC login cannot retain the earlier undisclosed saved session', async () => {
  const root = await mkdtemp(join(tmpdir(), 'marlin-ipc-reply 真实 ')), authority = new SharedArrayBuffer(8), barrier = new SharedArrayBuffer(12), replyBarrier = new SharedArrayBuffer(8), reply = new Int32Array(replyBarrier), generation = randomUUID();
  let owner: CoreOwner | undefined, earlier: ReturnType<CoreOwner['invoke']> | undefined, later: ReturnType<CoreOwner['invoke']> | undefined;
  try {
    const worker = new Worker(new URL('./fixtures/core-owner-publication-worker.ts', import.meta.url), { workerData: { config: { dataRoot: root }, authority, generation, barrier, replyBarrier }, execArgv: [], stdout: true, stderr: true });
    owner = await CoreOwner.connect(worker, { authority, generation });
    const setup = await owner.invoke(request('POST', '/api/v1/auth/auto-setup', { password: 'ipc-fence-password' }));
    const initialDevice = (setup.body as any).data.device.id;
    await owner.invoke(request('POST', '/api/v1/fixture/arm-auth-reply'));
    earlier = owner.invoke(request('POST', '/api/v1/auth/login?intent=earlier', { login: 'admin', password: 'ipc-fence-password' }));
    assert.notEqual(await Atomics.waitAsync(reply, 0, 0, 5000).value, 'timed-out');
    later = owner.invoke(request('POST', '/api/v1/auth/login?intent=later', { login: 'admin', password: 'incorrect-ipc-password' }));
    Atomics.store(reply, 1, 1); Atomics.notify(reply, 1);
    assert.equal((await earlier).status, 409); assert.equal((await later).status, 401);
    const me = await owner.invoke(request('GET', '/api/v1/auth/me'));
    assert.equal(me.status, 200); assert.equal((me.body as any).data.device.id, initialDevice);
    const devices = await owner.invoke(request('GET', '/api/v1/auth/devices'));
    assert.equal((devices.body as any).data.items.filter((row: any) => !row.is_revoked).length, 1);
    await owner.close(); owner = await CoreOwner.start({ dataRoot: root });
    const restored = await owner.invoke(request('GET', '/api/v1/auth/me'));
    assert.equal((restored.body as any).data.device.id, initialDevice);
  } finally {
    Atomics.store(reply, 1, 1); Atomics.notify(reply, 1);
    await Promise.allSettled([earlier, later]); await owner?.close(); await rm(root, { recursive: true, force: true });
  }
});
