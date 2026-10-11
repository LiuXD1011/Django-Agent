import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { setTimeout as delay } from 'node:timers/promises';
import { CoreApplication } from '../src/application.js';
import { createCoreHttpServer } from '../src/adapters/http.js';

async function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'marlin-http-chat-'));
  const app = new CoreApplication(root, { allowAutoSetup: true });
  let paidCalls = 0; const modelBodies: any[] = [];
  let release: (() => void) | undefined;
  const service = createServer(async (req, res) => {
    res.setHeader('Content-Type', 'application/json');
    if (req.url === '/api/public/health') { res.end('{"status":"OK"}'); return; }
    if (req.url === '/api/public/projects') { assert.equal(req.headers.authorization, `Basic ${Buffer.from('protocol-public-key:protocol-integration-secret').toString('base64')}`); res.end('{"data":[{"id":"qa-project","name":"验收项目"}]}'); return; }
    if (req.url?.startsWith('/search?')) {
      const query = new URL(req.url, 'http://fixture').searchParams;
      assert.equal(query.get('format'), 'json');
      res.end('{"results":[{"title":"海盐预算","url":"https://example.invalid/budget","content":"预算资料"}]}'); return;
    }
    if (req.url === '/api/auth/csrf') { res.setHeader('Set-Cookie', 'next-auth.csrf-token=protocol-csrf; Path=/; HttpOnly'); res.end('{"csrfToken":"protocol-csrf"}'); return; }
    if (req.url === '/api/auth/callback/credentials') {
      let raw = ''; for await (const bytes of req) raw += bytes;
      assert.equal(new URLSearchParams(raw).get('password'), 'protocol-login-secret');
      res.setHeader('Set-Cookie', 'next-auth.session-token=protocol-session-secret; Path=/; HttpOnly'); res.end('{}'); return;
    }
    if (req.url === '/api/auth/session') { res.end('{"user":{"email":"qa@local","organizations":[{"projects":[{"id":"qa-project"}]}]}}'); return; }
    if (req.url !== '/v1/chat/completions') { res.statusCode = 404; res.end('{}'); return; }
    let raw = ''; for await (const bytes of req) raw += bytes;
    assert.equal(app.database.sqlite.inTransaction, false);
    const body = JSON.parse(raw); paidCalls++; modelBodies.push(body);
    res.setHeader('Content-Type', 'text/event-stream');
    res.write(`data: ${JSON.stringify({ choices: [{ delta: { content: '预算为' } }] })}\n\n`);
    if (JSON.stringify(body.messages).includes('HOLD_HTTP')) await new Promise<void>(resolve => { release = resolve; res.once('close', resolve); });
    if (res.destroyed) return;
    res.end(`data: ${JSON.stringify({ choices: [{ delta: { content: '468000 元。' }, finish_reason: 'stop' }], usage: { prompt_tokens: 10, completion_tokens: 2, total_tokens: 12 } })}\n\ndata: [DONE]\n\n`);
  });
  await new Promise<void>(resolve => service.listen(0, '127.0.0.1', resolve));
  const serviceURL = `http://127.0.0.1:${(service.address() as { port: number }).port}`;
  const adapter = createCoreHttpServer(app, { port: 0 }); const { origin } = await adapter.listen();
  const jar = new Map<string, string>();
  const request = async (path: string, options: { method?: string; body?: any; signal?: AbortSignal; headers?: Record<string, string> } = {}) => {
    const method = options.method ?? 'GET';
    const response = await fetch(origin + path, {
      method, signal: options.signal, headers: { Origin: origin, Cookie: [...jar].map(([key, value]) => `${key}=${value}`).join('; '),
        ...(method !== 'GET' && jar.has('csrftoken') ? { 'X-CSRFToken': jar.get('csrftoken')! } : {}), ...(options.body === undefined ? {} : { 'Content-Type': 'application/json' }), ...options.headers },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    for (const cookie of response.headers.getSetCookie()) { const pair = cookie.split(';')[0]!; const i = pair.indexOf('='); const name = pair.slice(0, i), value = pair.slice(i + 1); if (value) jar.set(name, value); else jar.delete(name); }
    return response;
  };
  const json = async (path: string, options: Parameters<typeof request>[1] = {}) => { const response = await request(path, options); return { status: response.status, body: await response.json() as any }; };
  await json('/api/v1/auth/csrf');
  const initial = await json('/api/v1/auth/auto-setup', { method: 'POST', body: { email: 'http-business@example.invalid', password: 'http-business-only-password' } }); assert.equal(initial.status, 200);
  await json('/api/v1/auth/me/preferences', { method: 'PUT', body: { enable_memory: false } });
  const model = await json('/api/v1/models', { method: 'POST', body: { name: 'Controlled HTTP fixture', type: 'KnowledgeQA', source: 'openai', is_default: true, parameters: { model: 'controlled-fixture', base_url: `${serviceURL}/v1`, api_key: 'protocol-model-secret' } } }); assert.equal(model.status, 200);
  return { app, root, origin, jar, request, json, serviceURL, tenantId: initial.body.data.tenant.id, calls: () => paidCalls, modelBodies, release: () => release?.(), async close() { release?.(); await adapter.close(); await app.close(); service.closeAllConnections(); await new Promise<void>(resolve => service.close(() => resolve())); rmSync(root, { recursive: true, force: true }); } };
}
async function waitFor(check: () => boolean) { const until = Date.now() + 3000; while (!check() && Date.now() < until) await delay(10); assert.ok(check()); }

test('real HTTP session routes stream the actual model through scoped FTS and persist references, usage and recovery', async () => {
  const f = await fixture(); try {
    const kb = await f.json('/api/v1/knowledge-bases', { method: 'POST', body: { name: '海盐资料' } }); const kbId = String(kb.body.data.id);
    const doc = f.app.database.insert('knowledges', { tenant_id: f.tenantId, knowledge_base_id: kbId, title: '预算证据', parse_status: 'completed' });
    const chunk = f.app.database.insert('chunks', { tenant_id: f.tenantId, knowledge_base_id: kbId, knowledge_id: doc.id, content: '海盐预算 468000 元', seq_id: '1152921504606846975' });
    f.app.searchIndex.indexKeyword({ tenantId: f.tenantId }, String(chunk.id));
    const created = await f.json('/api/v1/sessions', { method: 'POST', body: { title: '海盐问答', knowledge_base_id: kbId } }); assert.equal(created.status, 200);
    const id = created.body.data.id;
    assert.equal((await f.json(`/api/v1/sessions/${id}/pin`, { method: 'POST' })).body.data.is_pinned, true);
    assert.equal((await f.json('/api/v1/sessions?query=' + encodeURIComponent('海盐'))).body.data.total, 1);
    const requestId = randomUUID();
    const response = await f.request(`/api/v1/knowledge-chat/${id}`, { method: 'POST', headers: { 'X-Request-ID': requestId }, body: { query: '海盐预算', stream: true, knowledge_base_ids: [kbId] } });
    assert.equal(response.status, 200); assert.match(response.headers.get('content-type')!, /^text\/event-stream/);
    const frames = await response.text(); assert.match(frames, /event: message_start/); assert.match(frames, /468000/); assert.match(frames, /1152921504606846975/); assert.match(frames, /event: done/); assert.equal(frames.includes('protocol-model-secret'), false);
    const history = (await f.json(`/api/v1/messages/${id}/load`)).body.data.items;
    assert.equal(history.length, 2); assert.equal(history[1].is_completed, true); assert.equal(history[1].knowledge_references[0].knowledge_id, doc.id);
    assert.ok(JSON.stringify(f.modelBodies[0].messages).includes('海盐预算 468000 元'));
    const resumed = await f.request(`/api/v1/sessions/continue-stream/${id}?message_id=${history[1].id}`); assert.equal(resumed.status, 200); assert.match(await resumed.text(), /event: done/); assert.equal(f.calls(), 1);
    assert.equal((await f.json('/api/v1/models/usage')).status, 200); assert.equal(f.app.database.get('SELECT sum(total_tokens) AS n FROM model_usage')?.n, 12);
    assert.ok((await f.json(`/api/v1/sessions/${id}/events`)).body.data.items.length > 0);
    assert.equal((await f.json(`/api/v1/sessions/${id}/context-usage`)).body.data.estimated, true);
    await f.json(`/api/v1/sessions/${id}/messages`, { method: 'DELETE' }); assert.equal((await f.json(`/api/v1/messages/${id}/load`)).body.data.items.length, 0);
    assert.equal((await f.json('/api/v1/sessions/batch', { method: 'DELETE', body: { ids: [id] } })).status, 200); assert.equal((await f.json(`/api/v1/sessions/${id}`)).status, 404);
  } finally { await f.close(); }
});

test('HTTP stream disconnect preserves the job; reconnect and request-ID stop terminate the actual paid call without replay', async () => {
  const f = await fixture(); try {
    const session = await f.json('/api/v1/sessions', { method: 'POST', body: { title: '连接验收' } }); assert.equal(session.status, 200); const id = session.body.data.id;
    const early = 'before-reply'; assert.equal((await f.json(`/api/v1/sessions/${id}/stop`, { method: 'POST', body: { request_id: early } })).status, 200);
    const skipped = await f.request(`/api/v1/knowledge-chat/${id}`, { method: 'POST', headers: { 'X-Request-ID': early }, body: { query: '早停', stream: true, knowledge_base_ids: [] } }); assert.equal(skipped.status, 200); await skipped.text(); assert.equal(f.calls(), 0);
    const controller = new AbortController(), requestId = 'disconnect-stop';
    const stream = await f.request(`/api/v1/knowledge-chat/${id}`, { method: 'POST', signal: controller.signal, headers: { 'X-Request-ID': requestId }, body: { query: 'HOLD_HTTP', stream: true, knowledge_base_ids: [] } });
    assert.equal(stream.status, 200); await waitFor(() => f.calls() === 1); controller.abort(); await stream.body?.cancel().catch(() => {});
    const assistant = (await f.json(`/api/v1/messages/${id}/load`)).body.data.items.find((m: any) => m.request_id === requestId && m.role === 'assistant'); assert.equal(assistant.is_completed, false);
    const resumed = await f.request(`/api/v1/sessions/continue-stream/${id}?message_id=${assistant.id}`); assert.equal(resumed.status, 200);
    const stopped = await f.json(`/api/v1/sessions/${id}/stop`, { method: 'POST', body: { request_id: requestId } }); assert.equal(stopped.status, 200); assert.equal(stopped.body.data.stopped, true);
    assert.match(await resumed.text(), /event: done/); f.release(); assert.equal(f.calls(), 1);
    const completed = (await f.json(`/api/v1/messages/${id}/load`)).body.data.items.find((m: any) => m.id === assistant.id); assert.equal(completed.is_completed, true);
    assert.equal((await f.json(`/api/v1/sessions/${id}/stop`, { method: 'POST', body: {} })).status, 400);
  } finally { await f.close(); }
});

test('registered integration routes perform real health/search/login HTTP and expose credentials only through trusted cookies', async () => {
  const f = await fixture(); try {
    assert.equal((await f.json('/api/v1/system/config/langfuse', { method: 'PUT', body: { enabled: true, base_url: f.serviceURL, ui_project_id: 'qa-project', public_key: 'protocol-public-key', secret_key: 'protocol-integration-secret' } })).status, 200);
    const health = await f.json('/api/v1/system/config/langfuse/test', { method: 'POST' }); assert.equal(health.status, 200); assert.equal(health.body.data.state, 'connected'); assert.equal(health.body.data.project_count, 1);
    const provider = await f.json('/api/v1/web-search-providers', { method: 'POST', body: { name: '真实受控搜索', provider: 'searxng', url: `${f.serviceURL}/search`, api_key: 'protocol-search-secret' } }); const providerId = provider.body.data.id;
    const search = await f.json(`/api/v1/web-search-providers/${providerId}/test`, { method: 'POST' }); assert.equal(search.status, 200); assert.equal(search.body.data.result_count, 1);
    const credentials = await f.json(`/api/v1/web-search-providers/${providerId}/credentials`); assert.equal(credentials.status, 200); assert.equal(credentials.body.data.fields.api_key.configured, true); assert.equal(JSON.stringify(credentials.body).includes('protocol-search-secret'), false);
    assert.equal((await f.json(`/api/v1/web-search-providers/${providerId}/credentials/api_key`, { method: 'DELETE' })).status, 200);
    assert.equal((await f.json('/api/v1/system/config/local_services', { method: 'PUT', body: { auto_login: true, login_email: 'qa@local', password: 'protocol-login-secret' } })).status, 200);
    const login = await f.request('/api/v1/observability/langfuse/session', { method: 'POST', body: {} }); assert.equal(login.status, 200); const result = await login.json() as any; assert.equal(result.data.state, 'connected'); assert.equal(JSON.stringify(result).includes('protocol-session-secret'), false);
    assert.ok(login.headers.getSetCookie().some(c => c.startsWith('next-auth.session-token=protocol-session-secret') && c.includes('HttpOnly')));
    assert.equal((await f.json('/api/v1/observability/langfuse/session', { method: 'POST', body: {} })).body.data.state, 'reused');
    const clear = await f.request('/api/v1/observability/langfuse/session/clear', { method: 'POST', body: {} }); assert.equal(clear.status, 200); assert.ok(clear.headers.getSetCookie().some(c => c.startsWith('next-auth.session-token=;') && c.includes('Max-Age=0')));
    assert.equal((await f.json('/api/v1/observability/langfuse/status')).body.data.state, 'healthy');
    assert.equal((await f.json('/api/v1/neo4j/query', { method: 'POST', body: { statement: 'MATCH(n) RETURN n' } })).status, 404);
  } finally { await f.close(); }
});

test('Wiki and Agent routes preserve Chinese nested slugs, edits, catalog and cross-space privacy', async () => {
  const f = await fixture(); try {
    const kb = (await f.json('/api/v1/knowledge-bases', { method: 'POST', body: { name: 'Wiki 验收' } })).body.data;
    const root = `/api/v1/knowledge-bases/${kb.id}/wiki`, slug = 'entities/' + encodeURIComponent('海盐 项目');
    const created = await f.json(root + '/pages', { method: 'POST', body: { slug: 'entities/海盐 项目', title: '海盐项目', content: '# 海盐\n\n预算 468000 元。', page_type: 'entity' } }); assert.equal(created.status, 200);
    assert.equal((await f.json(root + '/pages/' + slug)).body.data.title, '海盐项目');
    assert.equal((await f.json(root + '/pages/' + slug, { method: 'PUT', body: { content: '# 修订\n\n预算 470000 元。' } })).status, 200);
    assert.equal((await f.json(root + '/search?q=' + encodeURIComponent('470000'))).body.data.total, 1);
    assert.equal((await f.json(root + '/stats')).status, 200);
    const agent = await f.json('/api/v1/agents', { method: 'POST', body: { name: '证据助手', knowledge_base_ids: [kb.id], allowed_tools: ['knowledge_search'] } }); assert.equal(agent.status, 200);
    assert.equal((await f.json(`/api/v1/agents/${agent.body.data.id}/copy`, { method: 'POST' })).status, 200);
    assert.equal((await f.json('/api/v1/agents/type-presets')).body.data.items[0].agent_mode, 'multi-agent');
    const outside = f.app.auth.register({ email: 'other-business@example.invalid', password: 'other-business-only-password' });
    const foreign = await f.request(root + '/pages/' + slug, { headers: { Cookie: '', Authorization: `Bearer ${outside.credentials.access}` } }); assert.equal(foreign.status, 404);
    assert.equal((await f.json(root + '/pages/' + slug, { method: 'DELETE' })).status, 200); assert.equal((await f.json(root + '/pages/' + slug)).status, 404);
  } finally { await f.close(); }
});
