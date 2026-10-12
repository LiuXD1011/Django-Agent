import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import type { CoreFrame } from '../src/application.js';
import type { CoreRequest, HttpMethod, JsonObject } from '../src/contracts.js';
import { CoreOwner } from '../src/runtime/owner-client.js';

const request = (method: HttpMethod, path: string, body?: JsonObject): CoreRequest => ({ protocol: 1, id: randomUUID(), method, path, ...(body ? { body } : {}) });
const data = (response: { body: unknown }): any => (response.body as any).data;
async function fixture() {
  const directory = await mkdtemp(join(tmpdir(), 'marlin-owner-stream '));
  const owner = await CoreOwner.start({ dataRoot: directory, allowAutoSetup: true });
  try {
    assert.equal((await owner.invoke(request('POST', '/api/v1/auth/auto-setup', { password: 'owner-stream-test-password' }))).status, 200);
    await owner.invoke(request('PUT', '/api/v1/auth/me/preferences', { enable_memory: false }));
    const session = await owner.invoke(request('POST', '/api/v1/sessions', { title: '无模型 实际错误流', knowledge_base_ids: [] }));
    assert.equal(session.status, 200);
    const sessionId = String(data(session).id);
    const question = request('POST', `/api/v1/knowledge-chat/${sessionId}`, { query: '明确缺少模型', stream: true, knowledge_base_ids: [] });
    return { owner, sessionId, question, async close() { try { await owner.close(); } finally { await rm(directory, { recursive: true, force: true }); } } };
  } catch (error) { await owner.close(); await rm(directory, { recursive: true, force: true }); throw error; }
}

test('actual no-model core stream preserves frame order and buffers one frame until the consumer advances', async () => {
  const f = await fixture();
  const framesOnPort: number[] = [];
  const observe = (message: any) => { if (message.type === 'frame') framesOnPort.push(message.sequence); };
  f.owner.worker.on('message', observe);
  try {
    const opened = await f.owner.openStream(f.question);
    assert.equal(opened.response.status, 200); assert.ok(opened.frames);
    const iterator = opened.frames[Symbol.asyncIterator]();
    const first = await iterator.next(); assert.equal(first.value?.event, 'message_start');
    // Cross the actual owner message turn; GET is processed while its first frame waits for ACK.
    assert.equal((await f.owner.invoke(request('GET', '/api/v1/auth/me'))).status, 200);
    assert.deepEqual(framesOnPort, [0]);
    const second = await iterator.next(); assert.equal(second.value?.data.response_type, 'agent_query');
    assert.equal((await f.owner.invoke(request('GET', '/api/v1/auth/me'))).status, 200);
    assert.deepEqual(framesOnPort, [0, 1]);
    const frames: CoreFrame[] = [first.value!, second.value!];
    for (;;) { const next = await iterator.next(); if (next.done) break; frames.push(next.value); }
    assert.equal(frames.at(-1)?.event, 'done');
    assert.ok(frames.some(frame => frame.data.error), 'missing model must produce the existing explicit runtime error');
    assert.deepEqual(framesOnPort, frames.map((_, i) => i));
    assert.equal(JSON.stringify(frames).includes('owner-stream-test-password'), false);
    const replay = await f.owner.openStream(request('GET', `/api/v1/sessions/continue-stream/${f.sessionId}?request_id=${f.question.id}`));
    const replayed = []; for await (const frame of replay.frames!) replayed.push(frame);
    assert.equal(replayed.at(-1)?.event, 'done');
  } finally { f.owner.worker.off('message', observe); await f.close(); }
});

test('return before first next and abort after a consumed frame release actual Worker subscriptions', async () => {
  const f = await fixture();
  try {
    const opened = await f.owner.openStream(f.question); assert.ok(opened.frames);
    const iterator = opened.frames[Symbol.asyncIterator]();
    assert.equal((await iterator.return!()).done, true);
    assert.equal((await iterator.next()).done, true);
    const controller = new AbortController(), reason = new Error('isolated stream cancel');
    const replay = await f.owner.openStream(request('GET', `/api/v1/sessions/continue-stream/${f.sessionId}?request_id=${f.question.id}`), {}, controller.signal);
    const source = replay.frames![Symbol.asyncIterator]();
    assert.equal((await source.next()).value?.event, 'message_start');
    controller.abort(reason);
    await assert.rejects(source.next(), error => error === reason);
    assert.equal((await f.owner.invoke(request('GET', '/api/v1/auth/me'))).status, 200);
    await source.return!();
  } finally { await f.close(); }
});

test('close releases a stream blocked awaiting acknowledgment and waits for actual Worker exit', async () => {
  const f = await fixture();
  try {
    const opened = await f.owner.openStream(f.question), source = opened.frames![Symbol.asyncIterator]();
    assert.equal((await source.next()).value?.event, 'message_start');
    const first = f.owner.close(), second = f.owner.close(); assert.equal(first, second);
    await first;
    assert.equal(f.owner.worker.threadId, -1);
    await assert.rejects(source.next(), { code: 'owner_closed' });
    await assert.rejects(f.owner.invoke(request('GET', '/api/v1/capabilities')), { code: 'owner_closed' });
  } finally { await f.close(); }
});

test('bounded active streams queue requests, cancel queued writes and reject overflow without executing it', { timeout: 30000 }, async () => {
  const f = await fixture();
  try {
    const held = await Promise.all(Array.from({ length: 64 }, () => f.owner.openStream({ ...f.question, id: randomUUID() })));
    assert.ok(held.every(opened => opened.response.status === 200 && opened.frames));
    // Account page reads now have their own bounded query queue. Saturate an
    // owner-only endpoint to retain the original owner queue/cancel assertion.
    const queued = Array.from({ length: 63 }, () => f.owner.invoke(request('GET', '/api/v1/capabilities')));
    const controller = new AbortController(), reason = new Error('queued write must never start');
    const cancelled = f.owner.invoke(request('PUT', '/api/v1/auth/me/preferences', { enable_memory: true }), {}, controller.signal);
    const cancelledAssertion = assert.rejects(cancelled, error => error === reason);
    await assert.rejects(f.owner.invoke(request('POST', '/api/v1/knowledge-bases', { name: 'must never exist' })), { code: 'owner_busy', status: 429 });
    controller.abort(reason); await cancelledAssertion;
    for (const stream of held) await stream.frames![Symbol.asyncIterator]().return!();
    assert.ok((await Promise.all(queued)).every(response => response.status === 200));
    assert.equal(data(await f.owner.invoke(request('GET', '/api/v1/auth/me'))).user.preferences.enable_memory, false);
    assert.equal(data(await f.owner.invoke(request('GET', '/api/v1/knowledge-bases'))).total, 0);
  } finally { await f.close(); }
});

test('actual unexpected owner thread exit rejects an open stream and new requests with safe errors', async () => {
  const f = await fixture();
  try {
    const opened = await f.owner.openStream(f.question), source = opened.frames![Symbol.asyncIterator]();
    assert.equal((await source.next()).value?.event, 'message_start');
    await f.owner.worker.terminate();
    await assert.rejects(source.next(), { code: 'owner_failed' });
    await assert.rejects(f.owner.invoke(request('GET', '/api/v1/auth/me')), { code: 'owner_failed' });
    await assert.rejects(f.owner.close(), { code: 'owner_failed' });
  } finally { await f.close().catch(() => {}); }
});
