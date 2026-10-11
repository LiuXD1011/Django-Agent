import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { createConnection, createServer as createTcpServer } from 'node:net';
import { createHash, randomUUID } from 'node:crypto';
import { test } from 'node:test';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { SSEServerTransport } from '@modelcontextprotocol/sdk/server/sse.js';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';
import { AppError } from '../src/errors.js';
import { CoreDatabase } from '../src/storage/database.js';
import { CredentialVault } from '../src/storage/credentials.js';
import { AuthService } from '../src/auth/index.js';
import { SettingsService } from '../src/settings/index.js';
import type { JsonObject } from '../src/contracts.js';

async function fixture() {
  const module = await import('../src/integrations/index.js').catch(() => null);
  assert.ok(module, 'Independent integrations must perform actual external protocol calls');
  const root = mkdtempSync(join(tmpdir(), 'marlin-integrations-'));
  const db = new CoreDatabase(root), auth = new AuthService(db), vault = new CredentialVault(root);
  const owner = auth.register({ username: 'owner', password: 'FixturePassword✓' }).context;
  const outsider = auth.register({ username: 'outside', password: 'FixturePassword✓' }).context;
  db.update('users', owner.userId, { is_system_admin: true });
  const settings = new SettingsService(db, auth, vault);
  const integrations = new module.IntegrationService(db, auth, settings);
  return { db, auth, vault, owner, outsider, settings, integrations, async close() { await integrations.close(); db.close(); rmSync(root, { recursive: true, force: true }); } };
}
async function http(handler: (req: IncomingMessage, res: ServerResponse) => void | Promise<void>) {
  const server = createServer(handler); await new Promise<void>(r => server.listen(0, '127.0.0.1', r));
  return { url: `http://127.0.0.1:${(server.address() as { port: number }).port}`, async close() { server.closeAllConnections(); await new Promise<void>(r => server.close(() => r())); } };
}
async function body(req: IncomingMessage) { const chunks = []; for await (const chunk of req) chunks.push(chunk); return JSON.parse(Buffer.concat(chunks).toString()); }
const error = (code: string) => (e: any) => e.code === code && !e.message.includes('fixture-secret');

test('trusted scoped Neo4j validates authoritative KB namespace and write permissions before real Bolt connection', async () => {
  const f = await fixture(); let magic = '';
  const server = createTcpServer(socket => socket.once('data', bytes => { magic = bytes.subarray(0, 4).toString('hex'); socket.end(Buffer.alloc(4)); }));
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const kb = f.db.insert('knowledge_bases', { tenant_id: f.outsider.tenantId, name: 'Scoped graph' });
    const kbId = String(kb.id), parameters = { tenant_id: f.outsider.tenantId, knowledge_base_id: kbId, namespace: createHash('sha256').update(JSON.stringify([f.outsider.tenantId, kbId])).digest('hex') };
    f.settings.updateIntegration(f.owner, 'neo4j', { enabled: true, uri: `bolt://127.0.0.1:${(server.address() as { port: number }).port}`, username: 'fixture', password: 'fixture-secret' });
    await assert.rejects(f.integrations.queryScopedNeo4j(f.outsider, kbId, 'RETURN $namespace', parameters), error('integration_connection_failed')); assert.equal(magic, '6060b017');
    await assert.rejects(f.integrations.queryScopedNeo4j(f.outsider, kbId, 'RETURN $namespace', { ...parameters, namespace: 'wrong' }), error('integration_scope_mismatch'));
    await assert.rejects(f.integrations.queryScopedNeo4j(f.outsider, kbId, 'RETURN $namespace', { ...parameters, tenant_id: f.owner.tenantId }), error('integration_scope_mismatch'));
    await assert.rejects(f.integrations.queryScopedNeo4j(f.owner, kbId, 'RETURN $namespace', parameters), error('knowledge_base_not_found'));
    const tenantId = String(f.db.insert('tenants', { name: 'Shared fixture', space_type: 'legacy' }).id);
    f.db.insert('tenant_members', { tenant_id: tenantId, user_id: f.outsider.userId, role: 'viewer', status: 'active' });
    const viewer = { ...f.outsider, tenantId }, viewerKbId = String(f.db.insert('knowledge_bases', { tenant_id: tenantId, name: 'Viewer graph' }).id);
    const viewerParameters = { tenant_id: tenantId, knowledge_base_id: viewerKbId, namespace: createHash('sha256').update(JSON.stringify([tenantId, viewerKbId])).digest('hex') };
    await assert.rejects(f.integrations.queryScopedNeo4j(viewer, viewerKbId, 'RETURN $namespace', viewerParameters, { write: true }), error('action_forbidden'));
    f.db.update('knowledge_bases', kbId, { deleted_at: new Date().toISOString() });
    await assert.rejects(f.integrations.queryScopedNeo4j(f.outsider, kbId, 'RETURN $namespace', parameters), error('knowledge_base_not_found'));
  } finally { await new Promise<void>(resolve => server.close(() => resolve())); await f.close(); }
});

test('scoped graph publication rechecks configuration and authorization after await (authorization boundary unit test)', async () => {
  const f = await fixture();
  try {
    const kbId = String(f.db.insert('knowledge_bases', { tenant_id: f.outsider.tenantId, name: 'Boundary' }).id);
    const parameters = { tenant_id: f.outsider.tenantId, knowledge_base_id: kbId, namespace: createHash('sha256').update(JSON.stringify([f.outsider.tenantId, kbId])).digest('hex') };
    f.settings.updateIntegration(f.owner, 'neo4j', { enabled: true, uri: 'bolt://127.0.0.1:1', username: 'fixture', password: 'fixture-secret' });
    // This seam tests publication authorization only; it is not evidence of a successful Bolt query.
    (f.integrations as any).neo4j = async () => { f.settings.updateIntegration(f.owner, 'neo4j', { enabled: false }); return { state: 'connected', records: [] }; };
    await assert.rejects(f.integrations.queryScopedNeo4j(f.outsider, kbId, 'RETURN $namespace', parameters), error('integration_configuration_changed'));
    f.settings.updateIntegration(f.owner, 'neo4j', { enabled: true });
    (f.integrations as any).neo4j = async () => { f.auth.logoutAll(f.outsider); return { state: 'connected', records: [] }; };
    await assert.rejects(f.integrations.queryScopedNeo4j(f.outsider, kbId, 'RETURN $namespace', parameters), (e: any) => e.code === 'unauthorized');
  } finally { await f.close(); }
});

test('close awaits actual pending work cleanup even after its public cancellation has settled', async () => {
  const f = await fixture(); let release!: () => void, started!: () => void, completed = false, closed = false;
  const barrier = new Promise<void>(resolve => { release = resolve; });
  const running = new Promise<void>(resolve => { started = resolve; });
  try {
    const pending = (f.integrations as any).call({}, async (scope: any) => {
      started(); try { await scope.wait(new Promise<void>(() => {})); }
      finally { await barrier; f.db.read('users', f.owner.userId); completed = true; }
    });
    const rejected = assert.rejects(pending, error('integration_closed'));
    await running;
    const closing = f.integrations.close().then(() => { closed = true; });
    await rejected; await new Promise(resolve => setImmediate(resolve));
    assert.equal(closed, false, 'Shutdown must retain DB access until actual work finally completes');
    release(); await closing; assert.equal(completed, true);
  } finally { release(); await f.close(); }
});

test('disabled and incomplete integrations are explicit; forged global flags and tenant scope fail', async () => {
  const f = await fixture();
  try {
    assert.equal((await f.integrations.testIntegration(f.owner, 'langfuse')).state, 'disabled');
    f.db.insert('integration_configs', { name: 'langfuse', parameters: { enabled: true, base_url: 'http://127.0.0.1:1' } });
    assert.equal((await f.integrations.testIntegration(f.owner, 'langfuse')).state, 'not_configured');
    await assert.rejects(f.integrations.testIntegration({ ...f.outsider, isSystemAdmin: true }, 'langfuse'), error('system_admin_required'));
    const provider = f.settings.createProvider(f.owner, 'web_search_providers', { name: 'local search', provider: 'searxng', url: 'http://127.0.0.1:1' });
    await assert.rejects(f.integrations.search(f.outsider, String(provider.id), 'fixture'), error('provider_not_found'));
  } finally { await f.close(); }
});

test('Langfuse authenticates actual projects API, validates schema and never returns credentials', async () => {
  const f = await fixture(); let mode = 'ok', observed = '';
  const server = await http((req, res) => {
    observed = String(req.headers.authorization); assert.equal(req.url, '/api/public/projects');
    res.setHeader('content-type', 'application/json');
    if (mode === 'denied') { res.statusCode = 401; res.end('fixture-secret'); }
    else res.end(JSON.stringify(mode === 'invalid' ? { status: 'ok' } : { data: [{ id: 'project', name: 'Local fixture' }] }));
  });
  try {
    f.settings.updateIntegration(f.owner, 'langfuse', { enabled: true, base_url: server.url, public_key: 'fixture-public', secret_key: 'fixture-secret' });
    const result = await f.integrations.testIntegration(f.owner, 'langfuse');
    assert.equal(result.state, 'connected'); assert.equal(result.project_count, 1);
    assert.equal(observed, `Basic ${Buffer.from('fixture-public:fixture-secret').toString('base64')}`);
    assert.equal(JSON.stringify(result).includes('fixture-secret'), false);
    mode = 'invalid'; await assert.rejects(f.integrations.testIntegration(f.owner, 'langfuse'), error('integration_invalid_response'));
    mode = 'denied'; await assert.rejects(f.integrations.testIntegration(f.owner, 'langfuse'), error('integration_connection_failed'));
  } finally { await server.close(); await f.close(); }
});

test('real configured search requests carry query and return source URLs; challenge HTML is not empty success', async () => {
  const f = await fixture(); let observed = '', mode = 'searxng';
  const server = await http((req, res) => {
    observed = req.url!;
    if (mode === 'duckduckgo') assert.equal(req.headers['user-agent'], 'Mozilla/5.0');
    if (mode === 'searxng') { res.setHeader('content-type', 'application/json'); res.end(JSON.stringify({ results: [{ title: 'Actual fixture', url: 'https://example.org/evidence', content: 'Source snippet' }] })); }
    else { res.setHeader('content-type', 'text/html'); res.end(mode === 'duckduckgo' ? '<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Freal">Actual &amp; evidence</a><span class="result__snippet">Real <b>snippet</b></span></div>' : '<html>CAPTCHA bot challenge</html>'); }
  });
  try {
    const id = String(f.settings.createProvider(f.owner, 'web_search_providers', { name: 'search', provider: 'searxng', url: `${server.url}/search` }).id);
    const result = await f.integrations.search(f.owner, id, 'unicode 😀');
    assert.equal(result.state, 'connected'); assert.equal(result.results[0].url, 'https://example.org/evidence');
    assert.equal(new URL(observed, server.url).searchParams.get('q'), 'unicode 😀');
    f.settings.updateProvider(f.owner, 'web_search_providers', id, { provider: 'duckduckgo' }); mode = 'duckduckgo';
    const duck = await f.integrations.search(f.owner, id, 'query');
    assert.equal(duck.results[0].url, 'https://example.org/real'); assert.equal(duck.results[0].title, 'Actual & evidence');
    mode = 'challenge'; await assert.rejects(f.integrations.search(f.owner, id, 'query'), error('integration_invalid_response'));
  } finally { await server.close(); await f.close(); }
});

test('bounded network abort, timeout, response size, redirects and owning service shutdown isolate calls', async () => {
  const f = await fixture(); let mode = 'hold', forwarded = 0;
  const other = await http((_req, res) => { forwarded++; res.end('{}'); });
  const server = await http((_req, res) => {
    if (mode === 'hold') return;
    if (mode === 'redirect') { res.statusCode = 307; res.setHeader('location', other.url); res.end(); return; }
    res.setHeader('content-type', 'application/json'); res.end(mode === 'large' ? 'x'.repeat(2 * 1024 * 1024) : '{"results":[]}');
  });
  try {
    const id = String(f.settings.createProvider(f.owner, 'web_search_providers', { name: 'bounded', provider: 'searxng', url: server.url, api_key: 'fixture-secret' }).id);
    const start = performance.now(); await assert.rejects(f.integrations.search(f.owner, id, 'query', { timeoutMs: 50 }), error('integration_timeout'));
    assert.ok(performance.now() - start < 1000);
    const controller = new AbortController(); const pending = f.integrations.search(f.owner, id, 'query', { signal: controller.signal }); controller.abort('fixture-secret');
    await assert.rejects(pending, error('integration_cancelled'));
    const forged = new AbortController(); forged.abort(new AppError(502, 'fixture-secret', 'fixture-secret'));
    await assert.rejects(f.integrations.search(f.owner, id, 'query', { signal: forged.signal }), error('integration_cancelled'));
    mode = 'redirect'; await assert.rejects(f.integrations.search(f.owner, id, 'query'), error('integration_redirect_rejected')); assert.equal(forwarded, 0);
    mode = 'large'; await assert.rejects(f.integrations.search(f.owner, id, 'query'), error('integration_response_too_large'));
    mode = 'ok'; assert.equal((await f.integrations.search(f.owner, id, 'query')).state, 'connected');
    mode = 'hold'; const owned = f.integrations.search(f.owner, id, 'query'); await f.integrations.close(); await assert.rejects(owned, error('integration_closed'));
  } finally { await server.close(); await other.close(); await f.close(); }
});

test('official Neo4j driver sends Bolt handshake, refuses incompatible server and cancels only its owned socket', async () => {
  const f = await fixture(); const sockets = new Set<import('node:net').Socket>(); let magic = '', mode = 'refuse', onHandshake: (() => void) | undefined;
  const server = createTcpServer(socket => {
    sockets.add(socket); socket.on('close', () => sockets.delete(socket));
    socket.once('data', bytes => { magic = bytes.subarray(0, 4).toString('hex'); if (magic !== '6060b017') return; if (mode === 'refuse') socket.end(Buffer.alloc(4)); else onHandshake?.(); });
  });
  await new Promise<void>(r => server.listen(0, '127.0.0.1', r));
  try {
    f.settings.updateIntegration(f.owner, 'neo4j', { enabled: true, uri: `bolt://127.0.0.1:${(server.address() as { port: number }).port}`, username: 'fixture', password: 'fixture-secret' });
    await assert.rejects(f.integrations.testIntegration(f.owner, 'neo4j'), error('integration_connection_failed')); assert.equal(magic, '6060b017');
    mode = 'hold'; const start = performance.now(); await assert.rejects(f.integrations.queryNeo4j(f.owner, 'RETURN $value AS value', { value: 1 }, { timeoutMs: 50 }), error('integration_timeout')); assert.ok(performance.now() - start < 1000);
    await new Promise(r => setTimeout(r, 80)); assert.equal(sockets.size, 0);
    const unrelated = createConnection({ port: (server.address() as { port: number }).port, host: '127.0.0.1' });
    await new Promise<void>(r => unrelated.once('connect', () => { unrelated.write('unrelated'); r(); }));
    try {
      const controller = new AbortController(); let cancelledAt = 0;
      onHandshake = () => { cancelledAt = performance.now(); controller.abort(); };
      await assert.rejects(f.integrations.queryNeo4j(f.owner, 'RETURN $value AS value', { value: 1 }, { signal: controller.signal, timeoutMs: 2000 }), error('integration_cancelled'));
      assert.ok(cancelledAt > 0 && performance.now() - cancelledAt < 500);
      await new Promise(r => setTimeout(r, 80)); assert.equal(sockets.size, 1); assert.equal(unrelated.destroyed, false);
    } finally { unrelated.destroy(); }
    await assert.rejects(f.integrations.queryNeo4j({ ...f.outsider, isSystemAdmin: true }, 'RETURN 1'), error('system_admin_required'));
  } finally { for (const socket of sockets) socket.destroy(); await new Promise<void>(r => server.close(() => r())); await f.close(); }
});

test('existing Langfuse local login performs CSRF, account/project verification, cookie reuse and clear with real HTTP', async () => {
  const f = await fixture(); let requests = 0, observedPassword = '', mismatch = false;
  const server = await http(async (req, res) => {
    requests++; res.setHeader('content-type', 'application/json');
    if (req.url === '/api/auth/csrf') { res.setHeader('set-cookie', 'next-auth.csrf-token=fixture-csrf; Path=/; HttpOnly'); res.end('{"csrfToken":"csrf"}'); }
    else if (req.url === '/api/auth/callback/credentials') {
      let data = ''; for await (const chunk of req) data += chunk;
      const form = new URLSearchParams(data); observedPassword = form.get('password')!;
      assert.equal(form.get('csrfToken'), 'csrf'); assert.ok(String(req.headers.cookie).includes('next-auth.csrf-token=fixture-csrf'));
      res.setHeader('set-cookie', 'next-auth.session-token=fixture-session-secret; Path=/; HttpOnly'); res.end('{}');
    } else if (req.url === '/api/auth/session') res.end(JSON.stringify({ user: { email: mismatch ? 'other@local' : 'fixture@local', organizations: [{ projects: [{ id: 'project' }] }] } }));
    else if (req.url === '/api/public/health') res.end('{"status":"OK"}');
    else { res.statusCode = 404; res.end('{}'); }
  });
  try {
    f.settings.updateIntegration(f.owner, 'langfuse', { base_url: server.url, ui_project_id: 'project' });
    const options = { requestOrigin: server.url, remoteAddress: '127.0.0.1' };
    await assert.rejects(f.integrations.langfuseSession(f.owner, options), error('auto_login_disabled'));
    f.settings.updateIntegration(f.owner, 'local_services', { auto_login: true, login_email: 'fixture@local', password: 'fixture-secret' });
    const result = await f.integrations.langfuseSession(f.owner, options);
    assert.equal(result.result.state, 'connected'); assert.equal(observedPassword, 'fixture-secret'); assert.equal(requests, 3);
    assert.equal(JSON.stringify(result.result).includes('fixture-session-secret'), false);
    assert.equal(result.cookies[0].name, 'next-auth.session-token'); assert.equal(result.cookies[0].value, 'fixture-session-secret');
    assert.equal((await f.integrations.langfuseSession(f.owner, { ...options, existingCookies: { 'next-auth.session-token': 'fixture-session-secret' } })).result.state, 'reused'); assert.equal(requests, 4);
    mismatch = true; await assert.rejects(f.integrations.langfuseSession(f.owner, { ...options, existingCookies: { 'next-auth.session-token': 'wrong-account' } }), error('account_conflict'));
    await assert.rejects(f.integrations.langfuseSession(f.owner, { ...options, requestOrigin: 'http://evil.invalid' }), error('local_host_required'));
    const clear = f.integrations.clearLangfuseSession(f.owner, { ...options, existingCookies: { 'next-auth.session-token': 'fixture-session-secret', unrelated: 'keep' } });
    assert.equal(clear.result.state, 'cleared'); assert.deepEqual(clear.cookies.map((cookie: any) => [cookie.name, cookie.maxAge]), [['next-auth.session-token', 0]]);
    assert.equal((await f.integrations.langfuseStatus(f.owner)).state, 'healthy');
  } finally { await server.close(); await f.close(); }
});

test('Langfuse actual OTLP metadata spans preserve timing, filter private fields, honor sampling and validate partial rejection', async () => {
  const f = await fixture(); let payload: any, requests = 0, partial = false;
  const server = await http(async (req, res) => {
    assert.equal(req.url, '/api/public/otel/v1/traces'); assert.equal(req.headers['x-langfuse-ingestion-version'], '4');
    assert.equal(req.headers.authorization, `Basic ${Buffer.from('fixture-public:fixture-secret').toString('base64')}`);
    payload = await body(req); requests++; res.setHeader('content-type', 'application/json'); res.end(JSON.stringify(partial ? { partialSuccess: { rejectedSpans: '1', errorMessage: 'fixture-secret' } } : {}));
  });
  try {
    f.settings.updateIntegration(f.owner, 'langfuse', { enabled: true, base_url: server.url, public_key: 'fixture-public', secret_key: 'fixture-secret', sample_rate: 1 });
    const event = { name: 'chat.turn', traceId: '123456789abcdef0123456789abcdef0', spanId: '123456789abcdef0', startedAt: 1000, endedAt: 1250, success: true, input: 'private-body api_key=unrelated-secret Bearer token-secret', output: { answer: 'visible answer', api_key: 'unrelated-secret' }, metadata: { request_id: 'safe-id', query: 'private content', api_key: 'fixture-secret', arbitrary: 'secret' } };
    const result = await f.integrations.recordTrace(f.owner, event);
    assert.equal(result.state, 'accepted');
    const span = payload.resourceSpans[0].scopeSpans[0].spans[0];
    assert.equal(span.startTimeUnixNano, '1000000000'); assert.equal(span.endTimeUnixNano, '1250000000');
    const attributes = JSON.stringify(span.attributes); assert.ok(attributes.includes('safe-id')); assert.equal(attributes.includes('private content') || attributes.includes('fixture-secret') || attributes.includes('arbitrary'), false);
    assert.equal(attributes.includes('private-body') || attributes.includes('visible answer'), false);
    partial = true; await assert.rejects(f.integrations.recordTrace(f.owner, event), error('integration_trace_rejected'));
    f.settings.updateIntegration(f.owner, 'langfuse', { sample_rate: 0 });
    assert.equal((await f.integrations.recordTrace(f.owner, event)).state, 'sampled_out'); assert.equal(requests, 2);
    f.settings.updateIntegration(f.owner, 'langfuse', { sample_rate: 1, orphan_mode: 'skip' });
    assert.equal((await f.integrations.recordTrace(f.owner, { ...event, type: 'generation' })).state, 'orphan_skipped'); assert.equal(requests, 2);
    partial = false; f.settings.updateIntegration(f.owner, 'langfuse', { log_content: true });
    await f.integrations.recordTrace(f.owner, { ...event, usage: { prompt_tokens: 100, completion_tokens: 30, cached_tokens: 20, reasoning_tokens: 10, total_tokens: 130 } });
    const uploaded = payload.resourceSpans[0].scopeSpans[0].spans[0].attributes;
    assert.ok(JSON.stringify(uploaded).includes('private-body') && JSON.stringify(uploaded).includes('visible answer'));
    assert.equal(JSON.stringify(uploaded).includes('unrelated-secret') || JSON.stringify(uploaded).includes('token-secret'), false);
    assert.deepEqual(JSON.parse(uploaded.find((a: any) => a.key === 'langfuse.observation.usage_details').value.stringValue), { input: 80, output: 20, input_cached_tokens: 20, output_reasoning_tokens: 10, total: 130 });
  } finally { await server.close(); await f.close(); }
});

test('MCP SDK performs real initialize, pagination, tools/call and session termination without REST mocks', async () => {
  const f = await fixture(); const sessions = new Map<string, { server: Server; transport: StreamableHTTPServerTransport }>();
  const methods: string[] = []; let auth = '', deleted = 0;
  const endpoint = await http(async (req, res) => {
    auth = String(req.headers.authorization);
    const payload = req.method === 'POST' ? await body(req) : undefined;
    if (payload?.method) methods.push(payload.method);
    let session = sessions.get(String(req.headers['mcp-session-id']));
    if (!session && payload?.method === 'initialize') {
      const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: randomUUID, enableJsonResponse: true });
      const server = new Server({ name: 'actual-local-mcp', version: '1.0.0' }, { capabilities: { tools: {} } });
      server.setRequestHandler(ListToolsRequestSchema, request => ({ tools: request.params?.cursor ? [{ name: 'second', inputSchema: { type: 'object' } }] : [{ name: 'echo', description: 'Untrusted tool', inputSchema: { type: 'object', properties: { value: { type: 'string' } } } }], ...(request.params?.cursor ? {} : { nextCursor: 'next' }) }));
      server.setRequestHandler(CallToolRequestSchema, request => ({ content: [{ type: 'text', text: request.params.arguments?.value === 'reflect' ? 'Bearer fixture-secret' : `echo:${request.params.arguments?.value}` }] }));
      await server.connect(transport); session = { server, transport };
    }
    if (!session) { res.statusCode = 404; res.end(); return; }
    await session.transport.handleRequest(req, res, payload);
    if (session.transport.sessionId) sessions.set(session.transport.sessionId, session);
    if (req.method === 'DELETE') deleted++;
  });
  try {
    const id = String(f.settings.createProvider(f.owner, 'mcp_services', { name: 'mcp', url: `${endpoint.url}/mcp`, api_key: 'fixture-secret' }).id);
    const tools = await f.integrations.listMcpTools(f.owner, id);
    assert.deepEqual(tools.tools.map((v: any) => v.name), ['echo', 'second']);
    const result = await f.integrations.callMcpTool(f.owner, id, 'echo', { value: 'actual protocol' });
    assert.equal(result.content[0].text, 'echo:actual protocol'); assert.equal(result.untrusted, true);
    assert.ok(methods.includes('initialize') && methods.includes('notifications/initialized') && methods.includes('tools/list') && methods.includes('tools/call'));
    assert.equal(auth, 'Bearer fixture-secret'); assert.equal(deleted, 2);
    assert.equal(JSON.stringify(await f.integrations.callMcpTool(f.owner, id, 'echo', { value: 'reflect' })).includes('fixture-secret'), false);
    await assert.rejects(f.integrations.listMcpTools(f.outsider, id), error('provider_not_found'));
  } finally { for (const session of sessions.values()) await session.server.close(); await endpoint.close(); await f.close(); }
});

test('SSE MCP uses official SDK, sends saved authorization and rejects external endpoint announcements', async () => {
  const f = await fixture(); let mode = 'ok', auth = '', calls = 0;
  const sessions = new Map<string, { server: Server; transport: SSEServerTransport }>();
  const endpoint = await http(async (req, res) => {
    auth = String(req.headers.authorization);
    if (req.method === 'GET') {
      if (mode === 'external') { res.setHeader('content-type', 'text/event-stream'); res.write('event: endpoint\ndata: http://evil.invalid/messages\n\n'); return; }
      const transport = new SSEServerTransport('/messages', res);
      const server = new Server({ name: 'actual-sse', version: '1.0.0' }, { capabilities: { tools: {} } });
      server.setRequestHandler(ListToolsRequestSchema, () => ({ tools: [{ name: 'echo', inputSchema: { type: 'object' } }] }));
      server.setRequestHandler(CallToolRequestSchema, () => { calls++; return { content: [{ type: 'text', text: 'sse reply' }] }; });
      sessions.set(transport.sessionId, { server, transport }); await server.connect(transport); return;
    }
    const session = sessions.get(new URL(req.url!, 'http://localhost').searchParams.get('sessionId')!);
    if (!session) { res.statusCode = 404; res.end(); return; }
    await session.transport.handlePostMessage(req, res, await body(req));
  });
  try {
    const id = String(f.settings.createProvider(f.owner, 'mcp_services', { name: 'sse', url: `${endpoint.url}/sse`, transport: 'sse', api_key: 'fixture-secret' }).id);
    assert.equal((await f.integrations.listMcpTools(f.owner, id)).tools[0].name, 'echo');
    assert.equal((await f.integrations.callMcpTool(f.owner, id, 'echo', {})).content[0].text, 'sse reply');
    assert.equal(auth, 'Bearer fixture-secret'); assert.equal(calls, 1);
    mode = 'external'; await assert.rejects(f.integrations.listMcpTools(f.owner, id), error('integration_connection_failed'));
  } finally { for (const session of sessions.values()) await session.server.close(); await endpoint.close(); await f.close(); }
});

test('MCP handshake revalidates session authorization and saved configuration before an external side effect', async () => {
  const f = await fixture(); let revoke = true, calls = 0;
  const transports: StreamableHTTPServerTransport[] = [];
  const endpoint = await http(async (req, res) => {
    const payload = req.method === 'POST' ? await body(req) : undefined;
    let transport = transports.find(t => t.sessionId === req.headers['mcp-session-id']);
    if (!transport && payload?.method === 'initialize') {
      transport = new StreamableHTTPServerTransport({ sessionIdGenerator: randomUUID, enableJsonResponse: true }); transports.push(transport);
      const server = new Server({ name: 'guarded', version: '1.0.0' }, { capabilities: { tools: {} } });
      server.setRequestHandler(CallToolRequestSchema, () => { calls++; return { content: [] }; });
      await server.connect(transport);
    }
    if (!transport) { res.statusCode = 404; res.end(); return; }
    if (payload?.method === 'initialize') {
      if (revoke) f.db.run('update device_sessions set revoked_at=? where id=?', new Date().toISOString(), f.owner.deviceId);
      else { const row = f.db.all('select id from generic_resources where resource_type=?', 'mcp_services')[0]!; f.settings.updateProvider(f.owner, 'mcp_services', String(row.id), { enabled: false }); }
    }
    await transport.handleRequest(req, res, payload);
  });
  try {
    const id = String(f.settings.createProvider(f.owner, 'mcp_services', { name: 'guarded', url: endpoint.url }).id);
    await assert.rejects(f.integrations.callMcpTool(f.owner, id, 'danger', {}), (e: any) => e.code === 'unauthorized' && e.status === 401); assert.equal(calls, 0);
    f.db.run('update device_sessions set revoked_at=null where id=?', f.owner.deviceId); revoke = false;
    await assert.rejects(f.integrations.callMcpTool(f.owner, id, 'danger', {}), error('integration_configuration_changed')); assert.equal(calls, 0);
  } finally { for (const transport of transports) await transport.close(); await endpoint.close(); await f.close(); }
});

test('MCP hung handshake honors timeout/cancel, closes its resources, and permits a later actual SDK connection', async () => {
  const f = await fixture(); let held = 0, mode = 'hold';
  const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: randomUUID, enableJsonResponse: true });
  const sdk = new Server({ name: 'recovery', version: '1.0.0' }, { capabilities: { tools: {} } });
  sdk.setRequestHandler(ListToolsRequestSchema, () => ({ tools: [{ name: 'recovered', inputSchema: { type: 'object' } }] }));
  await sdk.connect(transport);
  const endpoint = await http(async (req, res) => {
    const payload = req.method === 'POST' ? await body(req) : undefined;
    if (mode === 'hold') { held++; return; }
    await transport.handleRequest(req, res, payload);
  });
  try {
    const id = String(f.settings.createProvider(f.owner, 'mcp_services', { name: 'held', url: endpoint.url }).id);
    const start = performance.now(); await assert.rejects(f.integrations.listMcpTools(f.owner, id, { timeoutMs: 50 }), error('integration_timeout')); assert.ok(performance.now() - start < 500);
    const controller = new AbortController(); const pending = f.integrations.callMcpTool(f.owner, id, 'echo', {}, { signal: controller.signal });
    const timer = setTimeout(() => controller.abort('fixture-secret'), 30);
    try { await assert.rejects(pending, error('integration_cancelled')); } finally { clearTimeout(timer); }
    assert.ok(held >= 2);
    mode = 'ok'; assert.equal((await f.integrations.listMcpTools(f.owner, id)).tools[0].name, 'recovered'); mode = 'hold';
    const owned = f.integrations.listMcpTools(f.owner, id); await f.integrations.close(); await assert.rejects(owned, error('integration_closed'));
  } finally { await sdk.close(); await endpoint.close(); await f.close(); }
});

test('explicit Neo4j Query API HTTP fixture validates parameterization and 202 query errors without claiming Bolt success', async () => {
  const module = await import('../src/integrations/neo4j-http.js').catch(() => null);
  assert.ok(module, 'Explicit Query API adapter must use the real HTTP protocol');
  const { CallScope } = await import('../src/integrations/network.js'); let mode = 'ok', observed: any;
  const server = await http(async (req, res) => {
    assert.equal(req.url, '/db/neo4j/query/v2'); assert.equal(req.headers.authorization, `Basic ${Buffer.from('fixture:fixture-secret').toString('base64')}`);
    observed = await body(req); res.statusCode = 202; res.setHeader('content-type', 'application/json');
    res.end(JSON.stringify(mode === 'ok' ? { data: { fields: ['value'], values: [[observed.parameters.value]] } } : { errors: [{ code: 'Neo.ClientError.Statement.SyntaxError', message: 'fixture-secret' }] }));
  });
  const scope = new CallScope();
  try {
    const result = await module.queryNeo4jHttp(scope, { url: server.url, username: 'fixture', password: 'fixture-secret' }, 'RETURN $value AS value', { value: 'actual HTTP parameter' });
    assert.equal(observed.statement, 'RETURN $value AS value'); assert.equal(result.records[0].value, 'actual HTTP parameter'); assert.equal(result.transport, 'query_api_http');
    mode = 'error'; await assert.rejects(module.queryNeo4jHttp(scope, { url: server.url, username: 'fixture', password: 'fixture-secret' }, 'RETURN invalid', {}), error('integration_query_failed'));
  } finally { scope.dispose(); await server.close(); }
});

test('Google and configured Bing-compatible APIs send real protocol credentials without reflecting them into sources', async () => {
  const f = await fixture(); let provider = 'google', observed = '';
  const server = await http((req, res) => {
    observed = req.url!; res.setHeader('content-type', 'application/json');
    if (provider === 'google') { assert.equal(new URL(req.url!, 'http://local').searchParams.get('key'), 'fixture-secret'); res.end('{"items":[{"title":"fixture-secret evidence","link":"https://example.org/one","snippet":"Source"}]}'); }
    else { assert.equal(req.headers['ocp-apim-subscription-key'], 'fixture-secret'); res.end('{"webPages":{"value":[{"name":"Bing compatible","url":"https://example.org/two","snippet":"Source"}]}}'); }
  });
  try {
    const id = String(f.settings.createProvider(f.owner, 'web_search_providers', { name: 'google', url: `${server.url}/search`, provider: 'google', api_key: 'fixture-secret', cx: 'fixture-engine' }).id);
    const google = await f.integrations.search(f.owner, id, 'query'); assert.equal(google.results[0].url, 'https://example.org/one'); assert.equal(JSON.stringify(google).includes('fixture-secret'), false);
    assert.equal(new URL(observed, server.url).searchParams.get('cx'), 'fixture-engine');
    provider = 'bing'; f.settings.updateProvider(f.owner, 'web_search_providers', id, { provider: 'bing' });
    assert.equal((await f.integrations.search(f.owner, id, 'query')).results[0].url, 'https://example.org/two');
    const unconfigured = String(f.settings.createProvider(f.owner, 'web_search_providers', { name: 'legacy Bing', provider: 'bing', api_key: 'fixture-secret' }).id);
    assert.equal((await f.integrations.search(f.owner, unconfigured, 'query')).state, 'not_configured');
  } finally { await server.close(); await f.close(); }
});
