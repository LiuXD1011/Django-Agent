import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { CoreApplication } from '../src/application.js';
import type { HttpMethod, JsonObject } from '../src/contracts.js';
import { createCoreHttpServer } from '../src/adapters/http.js';

test('real public channel uses scoped guest sessions, runtime usage and revocable grants without owner impersonation', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-channel-http-'));
  const app = new CoreApplication(root, { allowAutoSetup: true });
  const http = createCoreHttpServer(app, { port: 0 });
  const prompts: string[] = [], fixtureChunks: string[] = []; let agentCalls = 0, externalRequests = 0;
  const provider = createServer(async (request, response) => {
    if (request.url === '/probe') { externalRequests++; response.end('Private probe must never be contacted'); return; }
    assert.equal(app.database.sqlite.inTransaction, false);
    let body = ''; for await (const part of request) body += part;
    prompts.push(body);
    response.setHeader('content-type', 'text/event-stream');
    const decoded = JSON.parse(body) as JsonObject;
    if (Array.isArray(decoded.tools)) {
      agentCalls++;
      if (agentCalls === 1) {
        const malicious = [
          { name: 'database_query', arguments: { query_type: 'session_stats' } },
          { name: 'read_skill', arguments: { skill_name: 'private-fixture' } },
          { name: 'web_fetch', arguments: { url: `http://${request.headers.host}/probe` } },
          { name: 'mcp_unselected_private_service', arguments: { query: 'private data' } },
        ].map((item, i) => ({ index: i + 1, id: `unauthorized-${i}`, type: 'function', function: { name: item.name, arguments: JSON.stringify(item.arguments) } }));
        response.end(`data: ${JSON.stringify({ choices: [{ delta: { tool_calls: [{ index: 0, id: 'fixture-search', type: 'function', function: { name: 'knowledge_search', arguments: JSON.stringify({ query: 'budget' }) } }, ...malicious] } }] })}\n\ndata: ${JSON.stringify({ choices: [{ delta: {}, finish_reason: 'tool_calls' }], usage: { prompt_tokens: 9, completion_tokens: 3, total_tokens: 12 } })}\n\ndata: [DONE]\n\n`);
        return;
      }
    }
    response.end(`data: ${JSON.stringify({ choices: [{ delta: { content: 'Public fixture answer' } }] })}\n\ndata: ${JSON.stringify({ choices: [{ delta: {}, finish_reason: 'stop' }], usage: { prompt_tokens: 9, completion_tokens: 3, total_tokens: 12 } })}\n\ndata: [DONE]\n\n`);
  });
  try {
    const owner = app.auth.autoSetup({ password: 'channel-owned-fixture' });
    await new Promise<void>(resolve => provider.listen(0, '127.0.0.1', resolve));
    const address = provider.address(); assert.ok(address && typeof address !== 'string');
    const configuredModel = app.models.create(owner.context, { name: 'Controlled channel fixture', source: 'openai', type: 'KnowledgeQA', is_default: true, parameters: { base_url: `http://127.0.0.1:${address.port}/v1`, model: 'fixture', api_key: 'channel-fixture-only-secret' } });
    const kb = app.knowledge.knowledgeBases.create(owner.context, { name: 'Public channel fixture' });
    const privateKb = app.knowledge.knowledgeBases.create(owner.context, { name: 'Private channel fixture' });
    for (const [base, content, seq] of [[kb, 'Public budget evidence', '1'], [privateKb, 'Private budget never exposed', '2']] as const) {
      const doc = app.database.insert('knowledges', { tenant_id: owner.context.tenantId, knowledge_base_id: base.id, title: 'Budget fixture', enable_status: 'enabled', parse_status: 'completed' });
      const chunk = app.database.insert('chunks', { tenant_id: owner.context.tenantId, knowledge_base_id: base.id, knowledge_id: doc.id, content, seq_id: seq });
      app.searchIndex.indexKeyword({ tenantId: owner.context.tenantId }, String(chunk.id)); fixtureChunks.push(String(chunk.id));
    }
    const { origin } = await http.listen();
    const req = async (method: HttpMethod, path: string, body?: JsonObject, token?: string, extra: Record<string, string> = {}) => {
      const result = await fetch(origin + path, { method, headers: { origin, ...(token ? { authorization: `Bearer ${token}` } : {}), ...(body ? { 'content-type': 'application/json' } : {}), ...extra }, ...(body ? { body: JSON.stringify(body) } : {}) });
      return { status: result.status, data: (await result.json() as JsonObject).data as JsonObject };
    };
    app.database.update('models', String(configuredModel.id), { type: 'chat' }); // Actual legacy imported model role, same real runtime.
    const channel = await req('POST', '/api/v1/embed-channels', { name: 'Public scoped fixture', enabled: true, allowed_origins: [origin], knowledge_base_ids: [kb.id!], model_id: configuredModel.id! }, owner.credentials.access);
    assert.equal(channel.status, 200); const id = String(channel.data.id);
    assert.equal(channel.data.token, undefined);
    const csrf = await fetch(origin + '/api/v1/auth/csrf');
    const csrfToken = ((await csrf.json() as JsonObject).data as JsonObject).csrf_token as string;
    const exchange = () => req('POST', `/api/v1/embed/${id}/exchange`, {}, undefined, { cookie: `csrftoken=${csrfToken}`, 'x-csrftoken': csrfToken });
    const guest = await exchange(); assert.equal(guest.status, 200); assert.equal(guest.data.expires_in, 3600);
    const token = String(guest.data.token);
    const config = await req('GET', `/api/v1/embed/${id}/config`, undefined, token);
    assert.equal(config.status, 200); assert.equal(JSON.stringify(config.data).includes('channel-fixture-only-secret'), false);
    assert.equal((await req('GET', '/api/v1/auth/me', undefined, token)).status, 401);
    assert.equal((await req('GET', `/api/v1/embed/${id}/chunks/${fixtureChunks[0]}`, undefined, token)).data.content, 'Public budget evidence');
    assert.equal((await req('GET', `/api/v1/embed/${id}/chunks/${fixtureChunks[1]}`, undefined, token)).status, 404);
    app.database.update('chunks', fixtureChunks[0]!, { is_enabled: false });
    assert.equal((await req('GET', `/api/v1/embed/${id}/chunks/${fixtureChunks[0]}`, undefined, token)).status, 404);
    app.database.update('chunks', fixtureChunks[0]!, { is_enabled: true });
    const session = await req('POST', `/api/v1/embed/${id}/sessions`, {}, token);
    assert.equal(session.status, 200); const sessionId = String(session.data.id);
    const another = await exchange(); const otherToken = String(another.data.token);
    assert.equal((await req('GET', `/api/v1/embed/${id}/messages/${sessionId}/load`, undefined, otherToken)).status, 404);
    assert.equal((await req('POST', `/api/v1/embed/${id}/knowledge-chat/${sessionId}`, { query: 'budget', knowledge_base_ids: [privateKb.id!] }, token)).status, 403);
    const answer = await req('POST', `/api/v1/embed/${id}/knowledge-chat/${sessionId}`, { query: 'budget' }, token);
    assert.equal(answer.status, 200); assert.equal(answer.data.answer, 'Public fixture answer');
    assert.equal(prompts.length, 1); assert.ok(prompts[0]!.includes('Public budget evidence')); assert.equal(prompts[0]!.includes('Private budget never exposed'), false);
    assert.equal(app.database.get('SELECT count(*) AS n FROM model_usage WHERE total_tokens=12 AND success=1')?.n, 1);
    const loaded = await req('GET', `/api/v1/embed/${id}/messages/${sessionId}/load`, undefined, token);
    assert.equal(loaded.status, 200); assert.equal((loaded.data.items as JsonObject[]).length, 2);
    const agentAnswer = await req('POST', `/api/v1/embed/${id}/agent-chat/${sessionId}`, { query: 'budget via selected knowledge tool' }, token);
    assert.equal(agentAnswer.status, 200); assert.equal(agentAnswer.data.answer, 'Public fixture answer');
    assert.equal(agentCalls, 2); assert.equal(prompts.length, 3);
    const lastPrompt = JSON.parse(prompts[2]!) as { messages: Array<{ role: string; content: string }> };
    assert.ok(lastPrompt.messages.some(message => message.role === 'tool' && message.content.includes('Public budget evidence')));
    assert.equal(JSON.stringify(lastPrompt).includes('Private budget never exposed'), false);
    const forbiddenResults = lastPrompt.messages.filter(message => message.role === 'tool' && message.content.includes('PERMISSION_DENIED'));
    assert.equal(forbiddenResults.length, 4);
    assert.ok(forbiddenResults.every(message => message.content.startsWith('Tool is outside the authorized selection')));
    assert.equal(externalRequests, 0);
    assert.equal(app.database.get('SELECT count(*) AS n FROM model_usage WHERE total_tokens=12 AND success=1')?.n, 3);
    assert.equal(app.database.get("SELECT count(*) AS n FROM desktop_jobs WHERE kind='chat.maintenance'")?.n, 0);
    const events = await req('GET', `/api/v1/embed/${id}/sessions/${sessionId}/events`, undefined, token);
    assert.equal(events.status, 200); assert.ok((events.data.items as JsonObject[]).length > 5);
    const stopped = await req('POST', `/api/v1/embed/${id}/sessions/${sessionId}/stop`, { message_id: String((agentAnswer.data.message as JsonObject).id) }, token);
    assert.equal(stopped.status, 200); assert.equal(stopped.data.stopped, true);
    const stats = await req('GET', `/api/v1/embed-channels/${id}/stats`, undefined, owner.credentials.access);
    assert.equal(stats.status, 200); assert.equal(stats.data.sessions, 1); assert.equal(stats.data.messages, 4);
    assert.equal((app.chat.list(owner.context).items as JsonObject[]).some(s => s.id === sessionId), false);
    assert.equal(app.chat.stats(owner.context).total_sessions, 0);
    assert.equal(app.chat.stats(owner.context).total_messages, 0);
    const normal = app.chat.create(owner.context, { title: 'ordinary owner fixture' });
    const deleted = await app.chat.batchDelete(owner.context, { delete_all: true });
    assert.equal(deleted.deleted_count, 1);
    assert.ok(app.database.read('sessions', String(normal.id))!.deleted_at);
    assert.equal(app.database.read('sessions', sessionId)!.deleted_at, null);
    assert.equal((await req('POST', `/api/v1/embed-channels/${id}/rotate-token`, {}, owner.credentials.access)).status, 200);
    assert.equal((await req('GET', `/api/v1/embed/${id}/config`, undefined, token)).status, 401);
    assert.equal(prompts.length, 3);
  } finally {
    await http.close(); await app.close(); await new Promise<void>(resolve => { provider.closeAllConnections(); provider.close(() => resolve()); }); rmSync(root, { recursive: true, force: true });
  }
});

test('delegated grant revalidates TTL, origin, source, sponsor and isolates account/owner history', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-channel-authority-'));
  const { CoreDatabase } = await import('../src/storage/database.js');
  const { AuthService } = await import('../src/auth/index.js');
  const { CredentialVault } = await import('../src/storage/credentials.js');
  const { ModelConfigurationService } = await import('../src/settings/model-configuration.js');
  const { ChatService } = await import('../src/chat/index.js');
  const { ChannelService } = await import('../src/legacy/index.js');
  const db = new CoreDatabase(root), auth = new AuthService(db, { allowAutoSetup: true }), vault = new CredentialVault(root);
  const models = new ModelConfigurationService(db, auth, vault), chat = new ChatService(db, auth, { models });
  let currentTime = Date.now(); const channels = new ChannelService(db, auth, vault, chat, { now: () => currentTime });
  try {
    const sponsor = auth.autoSetup({ password: 'authority-fixture-only' });
    const kb = db.insert('knowledge_bases', { tenant_id: sponsor.context.tenantId, name: 'Frozen public scope' });
    const channel = channels.create(sponsor.context, 'embed_channels', { allowed_origins: ['http://localhost:9191'], knowledge_base_ids: [kb.id!] });
    const id = String(channel.id), issued = channels.exchange(id, 'http://localhost:9191');
    const ctx = channels.authenticate(id, String(issued.token), 'http://localhost:9191');
    assert.equal(ctx.role, 'channel'); assert.equal(ctx.isSystemAdmin, false); assert.equal(ctx.userId, sponsor.context.userId);
    assert.throws(() => auth.me(ctx), { status: 401 });
    assert.throws(() => auth.listDevices(ctx), { status: 401 });
    assert.throws(() => auth.changePassword(ctx, 'authority-fixture-only', 'replacement-fixture'), { status: 401 });
    assert.throws(() => auth.updatePreferences(ctx, { enable_memory: true }), { status: 401 });
    assert.throws(() => auth.logoutAll(ctx), { status: 401 });
    assert.throws(() => auth.assertCan(ctx, 'credentials.manage'), { status: 403 });
    assert.throws(() => auth.assertCan(ctx, 'read', '999'), { status: 403 });
    assert.throws(() => channels.authenticate(id, String(issued.token), 'http://localhost:9192'), { status: 401 });
    assert.throws(() => channels.exchange(id, 'http://localhost:9192'), { status: 403 });
    const forged = { ...ctx, channel: { ...ctx.channel!, knowledgeBaseIds: ['forged-kb'] }, isSystemAdmin: true };
    assert.throws(() => auth.assertCan(forged, 'read'), { status: 401 });
    const session = channels.createSession(ctx); assert.equal(session.user_id, undefined); assert.equal(session.tenant_id, undefined);
    const stored = db.read('sessions', String(session.id))!;
    assert.equal(stored.user_id, sponsor.context.userId); assert.equal((stored.agent_config as JsonObject).enable_memory, false);
    assert.deepEqual((stored.agent_config as JsonObject).allowed_tools, ['actor', 'thinking', 'knowledge_search', 'list_knowledge_docs', 'get_document_info', 'grep_chunks', 'wiki_search', 'wiki_read_page']);
    assert.throws(() => chat.get(sponsor.context, String(session.id)), { status: 404 });
    const rawGrant = db.get('SELECT value FROM desktop_meta WHERE key=?', `channel.grant:${ctx.channel!.grantId}`)!;
    assert.equal(String(rawGrant.value).includes(String(issued.token)), false);
    currentTime += 3600001;
    assert.throws(() => channels.authenticate(id, String(issued.token), 'http://localhost:9191'), { status: 401 });
    assert.throws(() => chat.get(ctx, String(session.id)), { status: 401 });
    const renewed = channels.exchange(id, 'http://localhost:9191');
    const fresh = channels.authenticate(id, String(renewed.token), 'http://localhost:9191');
    db.update('knowledge_bases', String(kb.id), { deleted_at: new Date().toISOString() });
    assert.throws(() => auth.assertCan(fresh, 'read'), { status: 401 });
    db.update('knowledge_bases', String(kb.id), { deleted_at: null });
    const next = channels.exchange(id, 'http://localhost:9191'); const nextCtx = channels.authenticate(id, String(next.token), 'http://localhost:9191');
    db.update('tenant_members', String(db.get('SELECT id FROM tenant_members WHERE tenant_id=? AND user_id=?', sponsor.context.tenantId, sponsor.context.userId)!.id), { status: 'revoked' });
    assert.throws(() => auth.assertCan(nextCtx, 'read'), { status: 401 });
    assert.equal(db.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
  } finally { await channels.close(); await chat.close(); db.close(); rmSync(root, { recursive: true, force: true }); }
});

test('nested channel credentials require real admin authority and IPC rotation never returns secrets', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-channel-management-'));
  const app = new CoreApplication(root, { allowAutoSetup: true });
  const { CoreIpcAdapter } = await import('../src/adapters/ipc.js');
  const { randomUUID } = await import('node:crypto');
  try {
    const ipc = new CoreIpcAdapter(app);
    const setup = await ipc.invoke({ protocol: 1, id: randomUUID(), method: 'POST', path: '/api/v1/auth/auto-setup', body: { password: 'channel-ipc-only-fixture' } });
    assert.equal(setup.status, 200);
    const call = (method: HttpMethod, path: string, body?: JsonObject) => ipc.invoke({ protocol: 1, id: randomUUID(), method, path, ...(body ? { body } : {}) });
    const created = await call('POST', '/api/v1/tenants', { name: 'Shared scoped channels' });
    const tenantId = String(((created.body as JsonObject).data as JsonObject).id);
    const member = app.auth.register({ email: 'channel-editor@example.invalid', password: 'editor-fixture' });
    assert.equal((await call('POST', `/api/v1/tenants/${tenantId}/members`, { user_id: member.context.userId, role: 'editor' })).status, 200);
    const denied = await app.dispatch({ protocol: 1, id: randomUUID(), method: 'POST', path: '/api/v1/im-channels', body: { name: 'Nested secret', credentials: { api_key: 'nested-fixture-only' } } }, { transport: 'http', access: member.credentials.access, selectedTenant: tenantId });
    assert.equal(denied.response.status, 403);
    const channel = await call('POST', '/api/v1/embed-channels', { name: 'Native managed public fixture' });
    assert.equal(channel.status, 200); const id = String(((channel.body as JsonObject).data as JsonObject).id);
    const stored = app.database.read('generic_resources', id)!.data as JsonObject;
    assert.ok(String(stored.token).startsWith('enc:v1:'));
    const oldToken = app.vault.decrypt(stored).token as string;
    const rotated = await call('POST', `/api/v1/embed-channels/${id}/rotate-token`, { transport: 'http', revealKey: true });
    assert.equal(rotated.status, 200); const result = (rotated.body as JsonObject).data as JsonObject;
    assert.equal(result.rotated, true); assert.equal(result.token, undefined);
    const newToken = app.vault.decrypt(app.database.read('generic_resources', id)!.data as JsonObject).token as string;
    assert.notEqual(oldToken, newToken); assert.equal(JSON.stringify(rotated).includes(oldToken), false); assert.equal(JSON.stringify(rotated).includes(newToken), false);
    assert.equal((await call('PATCH', `/api/v1/embed-channels/${id}`, { token: '******', name: 'Renamed' })).status, 200);
    assert.equal(app.vault.decrypt(app.database.read('generic_resources', id)!.data as JsonObject).token, newToken);
    assert.equal((await call('PATCH', `/api/v1/embed-channels/${id}`, { token: stored.token! })).status, 400);
    assert.equal((await call('GET', `/api/v1/embed/${id}/config`)).status, 404);
    const im = await call('POST', '/api/v1/im-channels', { name: 'IM toggle actual configuration' });
    const imId = String(((im.body as JsonObject).data as JsonObject).id);
    const toggle = await call('POST', `/api/v1/im-channels/${imId}/toggle`, {});
    assert.equal(toggle.status, 200); assert.equal(((toggle.body as JsonObject).data as JsonObject).enabled, true);
    assert.equal((await call('DELETE', `/api/v1/im-channels/${imId}`)).status, 200);
    assert.ok(app.database.read('generic_resources', imId)!.deleted_at);
    assert.equal(app.database.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
  } finally { await app.close(); rmSync(root, { recursive: true, force: true }); }
});

test('channel shutdown aborts its in-flight real HTTP model call and leaves no running worker or memory job', async () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-channel-close-'));
  const app = new CoreApplication(root, { allowAutoSetup: true }), http = createCoreHttpServer(app, { port: 0 });
  let entered!: () => void; const sent = new Promise<void>(resolve => { entered = resolve; });
  let ownedClosed = false;
  const provider = createServer(async (request, response) => {
    assert.equal(app.database.sqlite.inTransaction, false);
    for await (const _ of request) { /* Only consume controlled fixture input. */ }
    response.on('close', () => { ownedClosed = true; });
    response.writeHead(200, { 'content-type': 'text/event-stream' });
    response.write('data: {"choices":[{"delta":{}}]}\n\n'); entered();
  });
  let closed = false;
  try {
    const owner = app.auth.autoSetup({ password: 'close-fixture-only' });
    await new Promise<void>(resolve => provider.listen(0, '127.0.0.1', resolve));
    const addr = provider.address(); assert.ok(addr && typeof addr !== 'string');
    app.models.create(owner.context, { name: 'Slow controlled fixture', type: 'KnowledgeQA', source: 'openai', is_default: true, parameters: { api_key: 'close-local-fixture', base_url: `http://127.0.0.1:${addr.port}/v1`, model: 'fixture' } });
    const { origin } = await http.listen();
    const { randomUUID } = await import('node:crypto');
    const managed = await app.dispatch({ protocol: 1, id: randomUUID(), method: 'POST', path: '/api/v1/embed-channels', body: { allowed_origins: [origin] } }, { transport: 'http', access: owner.credentials.access });
    assert.equal(managed.response.status, 200); const id = String(((managed.response.body as JsonObject).data as JsonObject).id);
    const csrfResponse = await fetch(origin + '/api/v1/auth/csrf'); const csrf = ((await csrfResponse.json() as JsonObject).data as JsonObject).csrf_token as string;
    const exchanged = await fetch(origin + `/api/v1/embed/${id}/exchange`, { method: 'POST', headers: { origin, cookie: `csrftoken=${csrf}`, 'x-csrftoken': csrf, 'content-type': 'application/json' }, body: '{}' });
    assert.equal(exchanged.status, 200); const grant = ((await exchanged.json() as JsonObject).data as JsonObject).token as string;
    const headers = { origin, authorization: `Bearer ${grant}`, 'content-type': 'application/json' };
    const sessionResponse = await fetch(origin + `/api/v1/embed/${id}/sessions`, { method: 'POST', headers, body: '{}' });
    const sessionId = String(((await sessionResponse.json() as JsonObject).data as JsonObject).id);
    const pending = fetch(origin + `/api/v1/embed/${id}/knowledge-chat/${sessionId}`, { method: 'POST', headers, body: JSON.stringify({ query: 'Controlled pending fixture' }) });
    await Promise.race([sent, new Promise((_, reject) => setTimeout(() => reject(new Error('Fixture provider was not reached')), 3000))]);
    const job = app.database.get("SELECT status FROM desktop_jobs WHERE kind='chat.turn'"); assert.equal(job?.status, 'running');
    assert.equal(app.database.get("SELECT count(*) AS n FROM desktop_jobs WHERE kind='chat.maintenance'")?.n, 0);
    const start = Date.now(); await app.close(); closed = true;
    assert.ok(Date.now() - start < 2000, 'owned work must settle before close returns');
    const result = await pending; assert.ok(result.status >= 400);
    await new Promise(resolve => setTimeout(resolve, 50)); assert.equal(ownedClosed, true);
    const { CoreDatabase } = await import('../src/storage/database.js'); const check = new CoreDatabase(root);
    try {
      assert.equal(check.get("SELECT count(*) AS n FROM desktop_jobs WHERE status IN ('running','queued')")?.n, 0);
      assert.equal(check.get("SELECT count(*) AS n FROM desktop_jobs WHERE kind='chat.maintenance'")?.n, 0);
      assert.equal(check.read('messages', String(check.get("SELECT id FROM messages WHERE role='assistant'")!.id))!.content, '');
    } finally { check.close(); }
  } finally { await http.close(); if (!closed) await app.close(); await new Promise<void>(resolve => { provider.closeAllConnections(); provider.close(() => resolve()); }); rmSync(root, { recursive: true, force: true }); }
});
