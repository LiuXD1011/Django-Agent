import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { CoreApplication } from '../src/application.js';
import { CoreIpcAdapter } from '../src/adapters/ipc.js';
import type { HttpMethod, JsonObject } from '../src/contracts.js';

async function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'marlin-ipc-stream-'));
  const app = new CoreApplication(root, { allowAutoSetup: true }), ipc = new CoreIpcAdapter(app);
  let calls = 0;
  const server = createServer(async (req, res) => {
    let raw = ''; for await (const part of req) raw += part;
    assert.equal(JSON.parse(raw).stream, true); calls++;
    res.setHeader('Content-Type', 'text/event-stream');
    res.end(`data: ${JSON.stringify({ choices: [{ delta: { content: 'IPC 实际流' }, finish_reason: 'stop' }], usage: { prompt_tokens: 2, completion_tokens: 2, total_tokens: 4 } })}\n\ndata: [DONE]\n\n`);
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const request = (method: HttpMethod, path: string, body?: JsonObject) => ({ protocol: 1 as const, id: randomUUID(), method, path, ...(body ? { body } : {}) });
  const initial = await ipc.invoke(request('POST', '/api/v1/auth/auto-setup', { password: 'ipc-stream-only-chosen-password' })); assert.equal(initial.status, 200);
  await ipc.invoke(request('PUT', '/api/v1/auth/me/preferences', { enable_memory: false }));
  const model = await ipc.invoke(request('POST', '/api/v1/models', { name: 'IPC controlled fixture', type: 'KnowledgeQA', source: 'openai', is_default: true, parameters: { model: 'fixture', base_url: `http://127.0.0.1:${(server.address() as { port: number }).port}/v1`, api_key: 'ipc-stream-fixture-secret' } })); assert.equal(model.status, 200);
  const session = await ipc.invoke(request('POST', '/api/v1/sessions', { title: 'IPC 流验收', knowledge_base_ids: [] })); assert.equal(session.status, 200);
  return { app, ipc, request, sessionId: String((session.body as JsonObject).data && ((session.body as JsonObject).data as JsonObject).id), calls: () => calls, async close() { await app.close(); server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); rmSync(root, { recursive: true, force: true }); } };
}

test('native IPC exposes only public stream frames and persists actual runtime output without HTTP or credential transport', async () => {
  const f = await fixture(); try {
    assert.equal(typeof f.ipc.openStream, 'function', 'IPC requires a separate bounded stream transport');
    const request = f.request('POST', `/api/v1/knowledge-chat/${f.sessionId}`, { query: '原生流', stream: true, knowledge_base_ids: [] });
    const opened = await f.ipc.openStream(request); assert.equal(opened.response.status, 200); assert.ok(opened.frames);
    const frames = []; for await (const frame of opened.frames) frames.push(frame);
    assert.equal(frames[0]?.event, 'message_start'); assert.equal(frames.at(-1)?.event, 'done');
    assert.ok(frames.some(frame => frame.data.content === 'IPC 实际流' && frame.data.done === true)); assert.equal(f.calls(), 1);
    assert.equal(JSON.stringify({ response: opened.response, frames }).includes('ipc-stream-fixture-secret'), false);
    const history = await f.ipc.invoke(f.request('GET', `/api/v1/messages/${f.sessionId}/load`));
    const items = ((history.body as JsonObject).data as JsonObject).items as JsonObject[]; assert.equal(items[1]!.content, 'IPC 实际流');
    const replay = await f.ipc.openStream(f.request('GET', `/api/v1/sessions/continue-stream/${f.sessionId}?message_id=${items[1]!.id}`)); for await (const _frame of replay.frames!) { /* drain actual persisted stream */ }
    assert.equal(f.calls(), 1); assert.equal(f.app.database.get('SELECT sum(total_tokens) AS n FROM model_usage')?.n, 4);
  } finally { await f.close(); }
});

test('nonstream native invocation rejects stream requests before a paid job; stream channel cannot mutate authentication', async () => {
  const f = await fixture(); try {
    const rejected = await f.ipc.invoke(f.request('POST', `/api/v1/knowledge-chat/${f.sessionId}`, { query: '禁止丢弃流', stream: true, knowledge_base_ids: [] })); assert.equal(rejected.status, 406);
    assert.equal(f.app.database.get('SELECT count(*) AS n FROM messages')?.n, 0); assert.equal(f.calls(), 0);
    assert.equal(typeof f.ipc.openStream, 'function');
    const hostile = await f.ipc.openStream(f.request('POST', '/api/v1/auth/logout', {})); assert.equal(hostile.response.status, 400); assert.equal(hostile.frames, undefined);
    assert.equal((await f.ipc.invoke(f.request('GET', '/api/v1/auth/me'))).status, 200);
    const outsider = f.app.auth.register({ email: 'outside-ipc@example.invalid', password: 'outside-only-password' });
    const foreign = f.app.chat.create(outsider.context, { title: 'Foreign session' });
    const denied = await f.ipc.openStream(f.request('GET', `/api/v1/sessions/continue-stream/${foreign.id}?message_id=forged`)); assert.equal(denied.response.status, 404); assert.equal(denied.frames, undefined);
  } finally { await f.close(); }
});
