import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readFileSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createServer } from 'node:http';
import { test } from 'node:test';
import { CoreDatabase } from '../src/storage/database.js';
import { CredentialVault } from '../src/storage/credentials.js';
import { AuthService } from '../src/auth/index.js';
import type { JsonObject } from '../src/contracts.js';

async function fixture() {
  const module = await import('../src/settings/index.js').catch(() => null);
  assert.ok(module, 'Settings and model configuration must run in the independent core');
  const root = mkdtempSync(join(tmpdir(), 'marlin-settings-'));
  const db = new CoreDatabase(root), auth = new AuthService(db), vault = new CredentialVault(root);
  const owner = auth.register({ username: 'owner', password: 'FixturePassword✓' }).context;
  const outsider = auth.register({ username: 'outside', password: 'FixturePassword✓' }).context;
  return { db, auth, vault, owner, outsider, root, models: new module.ModelConfigurationService(db, auth, vault), settings: new module.SettingsService(db, auth, vault), close() { db.close(); rmSync(root, { recursive: true, force: true }); } };
}
const config = (type = 'chat', extra: JsonObject = {}): JsonObject => ({ name: 'fixture', type, source: 'openai', parameters: { base_url: 'http://localhost:8081/v1', api_key: 'fixture-key', model: 'fixture' }, ...extra });
const denied = (fn: () => unknown, status: number, code?: string) => assert.throws(fn, (e: any) => e.status === status && (!code || e.code === code));

test('model CRUD scopes tenant, canonicalizes four defaults, projects credentials and soft deletes', async () => {
  const f = await fixture();
  try {
    for (const [type, canonical] of [['chat', 'KnowledgeQA'], ['embedding', 'Embedding'], ['rerank', 'Rerank'], ['vision', 'VLLM']]) {
      const first = f.models.create(f.owner, config(type, { is_default: true }));
      const next = f.models.create(f.owner, config(type, { is_default: true, context_window: 8192 }));
      assert.equal(first.type, canonical); assert.equal(f.models.get(f.owner, String(first.id)).is_default, false);
      assert.equal(f.models.configuration(f.owner, canonical!).id, next.id);
      assert.equal(next.context_window, 8192); assert.equal(f.models.get(f.owner, String(first.id)).context_window, 128000);
      assert.equal(JSON.stringify(next).includes('fixture-key'), false); assert.equal((next.parameters as JsonObject).api_key, undefined);
      assert.equal(f.vault.decrypt(f.db.read('models', String(next.id))!.parameters).api_key, 'fixture-key');
      assert.match(String(f.db.read('models', String(next.id))!.parameters.api_key), /^enc:v1:/);
      denied(() => f.models.get(f.outsider, String(next.id)), 404);
      f.models.delete(f.owner, String(next.id)); assert.ok(f.db.read('models', String(next.id))!.deleted_at);
      denied(() => f.models.get(f.owner, String(next.id)), 404);
    }
    denied(() => f.models.create(f.owner, config('asr')), 400);
  } finally { f.close(); }
});

test('blank, null and mask preserve keys; ciphertext and host changes cannot reuse old secrets', async () => {
  const f = await fixture();
  try {
    const id = String(f.models.create(f.owner, config()).id);
    for (const api_key of ['', null, '******']) f.models.update(f.owner, id, { parameters: { api_key } });
    assert.equal(f.models.configuration(f.owner, id).parameters.api_key, 'fixture-key');
    denied(() => f.models.updateCredentials(f.owner, id, { api_key: 'enc:v1:injected' }), 400);
    denied(() => f.models.update(f.owner, id, { parameters: { base_url: 'http://evil.invalid/v1', api_key: '' } }), 400, 'credential_endpoint_changed');
    denied(() => f.models.update(f.owner, id, { parameters: { base_url: '', baseURL: 'http://evil.invalid/v1' } }), 400, 'credential_endpoint_changed');
    assert.equal(f.models.configuration(f.owner, id).parameters.base_url, 'http://localhost:8081/v1');
    f.models.update(f.owner, id, { parameters: { base_url: 'http://other.invalid/v1', apiKey: 'replacement-key' } });
    assert.equal(f.models.configuration(f.owner, id).parameters.api_key, 'replacement-key');
    f.models.clearCredential(f.owner, id, 'api_key');
    assert.equal(f.models.credentials(f.owner, id).fields.api_key.configured, false);
    f.models.update(f.owner, id, { parameters: { base_url: 'http://anonymous.invalid/v1' } });
  } finally { f.close(); }
});

test('embedding configuration invalidates affected indexes while preserving chunks and unrelated tenants', async () => {
  const f = await fixture();
  try {
    const model = f.models.create(f.owner, config('Embedding', { is_default: true }));
    const kb = f.db.insert('knowledge_bases', { tenant_id: f.owner.tenantId, name: 'affected', embedding_model_id: model.id });
    const other = f.db.insert('knowledge_bases', { tenant_id: f.outsider.tenantId, name: 'other' });
    const knowledge = f.db.insert('knowledges', { tenant_id: f.owner.tenantId, knowledge_base_id: kb.id, title: 'retained' });
    const chunk = f.db.insert('chunks', { tenant_id: f.owner.tenantId, knowledge_base_id: kb.id, knowledge_id: knowledge.id, content: 'retained business text' });
    for (const [id, tenant, library] of [['one', f.owner.tenantId, kb.id], ['two', f.outsider.tenantId, other.id]]) f.db.run('insert into search_index_meta values(?,?,?,?,?,?,?,?)', String(id), String(tenant), String(library), 'old', 2, 'generation', 'ready', new Date().toISOString());
    f.models.update(f.owner, String(model.id), { parameters: { dimension: 4 } });
    assert.equal(f.db.get('select status from search_index_meta where id=?', 'one')?.status, 'needs_rebuild');
    assert.equal(f.db.get('select status from search_index_meta where id=?', 'two')?.status, 'ready');
    assert.equal(f.db.read('knowledge_bases', String(kb.id))!.deleted_at, null);
    assert.equal(f.db.read('chunks', String(chunk.id))!.content, 'retained business text');
  } finally { f.close(); }
});

test('embedding fallback changes without an explicit default invalidate fallback libraries', async () => {
  const f = await fixture();
  try {
    const model = f.models.create(f.owner, config('embedding'));
    const kb = f.db.insert('knowledge_bases', { tenant_id: f.owner.tenantId, name: 'fallback' });
    f.db.run('insert into search_index_meta values(?,?,?,?,?,?,?,?)', 'fallback', f.owner.tenantId, String(kb.id), 'old', 2, 'retained-generation', 'ready', new Date().toISOString());
    f.models.update(f.owner, String(model.id), { parameters: { model: 'new-embedding' } });
    assert.equal(f.db.get('select status from search_index_meta where id=?', 'fallback')!.status, 'needs_rebuild');
    assert.equal(f.db.get('select generation from search_index_meta where id=?', 'fallback')!.generation, 'retained-generation');
  } finally { f.close(); }
});

test('actual upstream failure, timeout and cancellation record sanitized failures once and permit the next call', async () => {
  const f = await fixture(); let state = 'error', requests = 0;
  const server = createServer(async (req, res) => {
    for await (const _ of req) { /* Drain request. */ }
    requests++;
    if (state === 'hold') return;
    res.setHeader('content-type', 'application/json');
    if (state === 'error') { res.statusCode = 401; res.end(JSON.stringify({ error: { message: 'secret=fixture-key endpoint=private' } })); }
    else res.end(JSON.stringify({ choices: [{ message: { content: 'OK' }, finish_reason: 'stop' }] }));
  });
  await new Promise<void>(r => server.listen(0, '127.0.0.1', r));
  try {
    const address = server.address() as { port: number };
    const id = String(f.models.create(f.owner, config('chat', { parameters: { base_url: `http://127.0.0.1:${address.port}/v1`, api_key: 'fixture-key' } })).id);
    await assert.rejects(f.models.test(f.owner, id), (e: any) => !e.message.includes('fixture-key') && e.status === 502);
    state = 'hold'; await assert.rejects(f.models.test(f.owner, id, { timeoutMs: 50 }), (e: any) => e.code === 'model_timeout');
    const controller = new AbortController(); const pending = f.models.test(f.owner, id, { signal: controller.signal });
    const timer = setTimeout(() => controller.abort('private cancellation reason'), 30);
    try { await assert.rejects(pending, (e: any) => e.code === 'model_cancelled' && !e.message.includes('private')); } finally { clearTimeout(timer); }
    state = 'ok'; assert.equal((await f.models.test(f.owner, id)).status, 'ok');
    const rows = f.db.all('select * from model_usage order by created_at,id');
    assert.equal(requests, 4); assert.equal(rows.length, 4); assert.equal(rows.filter(r => r.success === 0).length, 3);
    assert.ok(rows.every(r => r.total_tokens === 0 && !String(r.error_message).includes('fixture-key')));
  } finally { server.closeAllConnections(); await new Promise<void>(r => server.close(() => r())); f.close(); }
});

test('credential aliases from imported models are projected, preserved and explicitly cleared', async () => {
  const f = await fixture();
  try {
    const row = f.db.insert('models', { id: 'legacy-model', tenant_id: f.owner.tenantId, name: 'legacy', type: 'chat', source: 'openai', parameters: f.vault.encrypt({ baseURL: 'http://localhost:8081/v1', apiKey: 'legacy-key' }) });
    const id = String(row.id);
    assert.equal(f.models.credentials(f.owner, id).fields.api_key.configured, true);
    assert.equal(JSON.stringify(f.models.get(f.owner, id)).includes('legacy-key'), false);
    f.models.update(f.owner, id, { parameters: { apiKey: '******', model: 'updated' } });
    assert.equal(f.models.configuration(f.owner, id).parameters.api_key, 'legacy-key');
    f.models.clearCredential(f.owner, id, 'api_key'); assert.equal(f.models.credentials(f.owner, id).fields.api_key.configured, false);
  } finally { f.close(); }
});

test('model and tenant settings enforce authoritative admin roles and sessions', async () => {
  const f = await fixture();
  try {
    const tenant = f.db.insert('tenants', { name: 'shared', api_key: 'service' });
    const member = f.db.insert('tenant_members', { tenant_id: tenant.id, user_id: f.owner.userId, role: 'viewer', status: 'active' });
    const ctx = f.auth.authenticateAccess(f.auth.login({ login: 'owner', password: 'FixturePassword✓' }).credentials.access, String(tenant.id));
    const forged = { ...ctx, role: 'owner', isSystemAdmin: true };
    denied(() => f.models.create(forged, config()), 403);
    denied(() => f.settings.setKV(forged, 'retrieval-config', { rerank_enabled: true }), 403);
    denied(() => f.settings.getIntegration(forged, 'neo4j'), 403);
    f.db.update('tenant_members', member.id as number, { role: 'admin' });
    assert.ok(f.models.create(ctx, config()).id);
    f.auth.logout(ctx); denied(() => f.models.list(ctx), 401);
  } finally { f.close(); }
});

test('thinking updates use revision CAS, dedicated path and verified endpoint capabilities', async () => {
  const f = await fixture();
  try {
    const id = String(f.models.create(f.owner, config('chat', { parameters: { base_url: 'https://api.deepseek.com/v1', model: 'deepseek-v4-flash', api_key: 'key' } })).id);
    denied(() => f.models.update(f.owner, id, { parameters: { thinking: { mode: 'on' } } }), 400);
    const before = f.models.thinking(f.owner, id);
    const result = f.models.updateThinking(f.owner, id, { revision: before.revision, role: 'model', policy: { mode: 'on', effort: 'max' } });
    assert.equal(result.revision, Number(before.revision) + 1);
    assert.equal(f.models.configuration(f.owner, id).parameters.thinking.mode, 'on');
    denied(() => f.models.updateThinking(f.owner, id, { revision: before.revision, role: 'model', policy: { mode: 'off' } }), 409);
    assert.equal(f.models.configuration(f.owner, id).parameters.api_key, 'key');
  } finally { f.close(); }
});

test('four model tests send real local HTTP requests and persist actual usage; missing credentials fail', async () => {
  const f = await fixture(); let requests = 0;
  const server = createServer(async (req, res) => {
    let body = ''; for await (const part of req) body += part;
    const data = JSON.parse(body); requests++; assert.equal(req.headers.authorization, 'Bearer fixture-key');
    const usage = { prompt_tokens: 4, completion_tokens: 2, total_tokens: 6, prompt_tokens_details: { cached_tokens: 1 } };
    res.setHeader('content-type', 'application/json');
    if (req.url?.endsWith('/embeddings')) res.end(JSON.stringify({ data: data.input.map((_: string, index: number) => ({ index, embedding: [1, 2] })), usage }));
    else if (req.url?.endsWith('/rerank')) res.end(JSON.stringify({ results: data.documents.map((_: string, index: number) => ({ index, relevance_score: 1 / (index + 1) })), usage }));
    else res.end(JSON.stringify({ choices: [{ message: { content: 'fixture actual response' }, finish_reason: 'stop' }], usage }));
  });
  await new Promise<void>(r => server.listen(0, '127.0.0.1', r));
  try {
    const address = server.address() as { port: number };
    for (const type of ['KnowledgeQA', 'Embedding', 'Rerank', 'VLLM']) {
      const id = String(f.models.create(f.owner, config(type, { parameters: { base_url: `http://127.0.0.1:${address.port}/v1`, api_key: 'fixture-key', dimension: 2 } })).id);
      const result = await f.models.test(f.owner, id); assert.equal(result.status, 'ok');
    }
    assert.equal(requests, 4); const rows = f.db.all('select * from model_usage'); assert.equal(rows.length, 4);
    assert.ok(rows.every(row => row.success === 1 && row.total_tokens === 6 && row.cached_tokens === 1));
    const noKey = String(f.models.create(f.owner, config('chat', { parameters: { base_url: `http://127.0.0.1:${address.port}/v1` } })).id);
    await assert.rejects(f.models.test(f.owner, noKey), (e: any) => e.code === 'model_not_configured'); assert.equal(requests, 4);
    const usage = f.models.usage(f.owner, { range: 7, granularity: '15m' });
    assert.equal(usage.total.calls, 5); assert.equal(usage.total.failed, 1); assert.equal(usage.total.total_tokens, 24);
    assert.equal(usage.cache_series.models.length, 4); assert.equal(usage.cache_series.granularity, '15m');
    assert.equal(f.models.usage(f.outsider, {}).total.calls, 0);
  } finally { await new Promise<void>(r => server.close(() => r())); f.close(); }
});

test('tenant KV and provider storage encrypt secrets, preserve blank edits, return configured flags and isolate tenants', async () => {
  const f = await fixture();
  try {
    f.settings.setKV(f.owner, 'web-search-config', { enabled: true, api_key: 'search-secret', nested: { token: 'nested-secret' } });
    const view = f.settings.getKV(f.owner, 'web-search-config');
    assert.equal(JSON.stringify(view).includes('search-secret'), false); assert.equal(view.configured, true);
    assert.match(String(f.db.read('tenants', f.owner.tenantId)!.web_search_config.api_key), /^enc:v1:/);
    f.settings.setKV(f.owner, 'web-search-config', { api_key: '' });
    assert.equal(f.settings.getKV(f.outsider, 'web-search-config').configured, false);
    denied(() => f.settings.setKV(f.owner, 'model-thinking-config', { revision: 9 }), 400);
    denied(() => f.settings.setKV(f.owner, 'made-up', {}), 404);
    const mcp = f.settings.createProvider(f.owner, 'mcp_services', { name: 'local', url: 'http://localhost:8080/mcp', api_key: 'mcp-secret', enabled: true });
    assert.equal(JSON.stringify(mcp).includes('mcp-secret'), false);
    denied(() => f.settings.updateProvider(f.owner, 'mcp_services', String(mcp.id), { url: 'http://elsewhere.invalid/mcp' }), 400);
    assert.equal(f.settings.listProviders(f.outsider, 'mcp_services').items.length, 0);
    denied(() => f.settings.testProvider(f.owner, 'mcp_services', String(mcp.id)), 501);
    f.settings.deleteProvider(f.owner, 'mcp_services', String(mcp.id));
    assert.ok(f.db.read('generic_resources', String(mcp.id))!.deleted_at);
    assert.equal(readFileSync(f.db.path).includes(Buffer.from('mcp-secret')), false);
  } finally { f.close(); }
});

test('global integration settings require real system admin, validate fields, protect endpoint credentials and clear disables', async () => {
  const f = await fixture();
  try {
    denied(() => f.settings.updateIntegration({ ...f.owner, isSystemAdmin: true }, 'neo4j', { enabled: true }), 403);
    f.db.update('users', f.owner.userId, { is_system_admin: true });
    const result = f.settings.updateIntegration(f.owner, 'langfuse', { enabled: true, base_url: 'http://localhost:3000', public_key: 'public-secret', secret_key: 'private-secret' });
    assert.equal(result.fields.secret_key.configured, true); assert.equal(JSON.stringify(result).includes('private-secret'), false);
    assert.match(String(f.db.read('integration_configs', 'langfuse')!.parameters.secret_key), /^enc:v1:/);
    f.settings.updateIntegration(f.owner, 'langfuse', { secret_key: null, public_key: '******' });
    denied(() => f.settings.updateIntegration(f.owner, 'langfuse', { base_url: 'http://other.invalid:3000' }), 400);
    denied(() => f.settings.updateIntegration(f.owner, 'langfuse', { sample_rate: 2 }), 400);
    denied(() => f.settings.updateIntegration(f.owner, 'neo4j', { enabled: true }), 400);
    const cleared = f.settings.clearIntegrationCredential(f.owner, 'langfuse', 'secret_key');
    assert.equal(cleared.values.enabled, false); assert.equal(cleared.fields.secret_key.configured, false);
    denied(() => f.settings.testIntegration(f.owner, 'langfuse'), 501);
  } finally { f.close(); }
});

test('nested provider authorization is configured without disclosure and cannot follow a new host', async () => {
  const f = await fixture();
  try {
    const row = f.settings.createProvider(f.owner, 'mcp_services', { name: 'headers', url: 'http://localhost:8080/mcp', headers: { Authorization: 'Bearer nested-auth' } });
    assert.equal(JSON.stringify(row).includes('nested-auth'), false);
    denied(() => f.settings.updateProvider(f.owner, 'mcp_services', String(row.id), { url: 'http://elsewhere.invalid/mcp', headers: { Authorization: '' } }), 400, 'credential_endpoint_changed');
    assert.equal(row.credential_fields['headers.Authorization']?.configured, true);
    f.settings.updateProvider(f.owner, 'mcp_services', String(row.id), { url: 'http://elsewhere.invalid/mcp', headers: { Authorization: 'Bearer explicit-new' } });
  } finally { f.close(); }
});

test('unsupported imported model rows remain readable and do not block four-role model management', async () => {
  const f = await fixture();
  try {
    f.db.insert('models', { id: 'old-asr', tenant_id: f.owner.tenantId, name: 'retained old row', type: 'ASR', source: 'openai' });
    assert.equal(f.models.list(f.owner).total, 1);
    assert.equal(f.models.get(f.owner, 'old-asr').raw_type, 'ASR');
    assert.ok(f.models.create(f.owner, config('Embedding')).id);
    assert.equal(f.db.read('models', 'old-asr')!.deleted_at, null);
  } finally { f.close(); }
});

test('startup configuration writes a real independent file, applies busy timeout, bounds workers, logs safely and distinguishes legacy fields', async () => {
  const f = await fixture();
  try {
    denied(() => f.settings.getIntegration({ ...f.owner, isSystemAdmin: true }, 'startup'), 403);
    f.db.update('users', f.owner.userId, { is_system_admin: true });
    const result = f.settings.updateIntegration(f.owner, 'startup', { task_workers: 2, sqlite_timeout: 3, model_timeout: 1, log_level: 'WARNING', allowed_hosts: ['old.example.invalid'] });
    const path = join(f.root, '.settings', 'startup.json');
    assert.equal(JSON.parse(readFileSync(path, 'utf8')).task_workers, 2);
    assert.equal(result.restart_required, true); assert.equal(result.active.task_workers, 4);
    assert.equal(result.field_support.allowed_hosts.applied, false);
    if (process.platform !== 'win32') assert.equal(statSync(path).mode & 0o777, 0o600);
    const { StartupConfiguration } = await import('../src/settings/index.js');
    const startup = new StartupConfiguration(f.root, { environ: {} }); startup.applyDatabase(f.db);
    assert.equal(f.db.sqlite.pragma('busy_timeout', { simple: true }), 3000n);
    let running = 0, peak = 0;
    const run = () => startup.runTask(async () => { running++; peak = Math.max(peak, running); await new Promise(r => setTimeout(r, 20)); running--; return 7; });
    assert.deepEqual(await Promise.all([run(), run(), run(), run()]), [7, 7, 7, 7]); assert.equal(peak, 2);
    startup.log('INFO', 'settings.saved'); assert.equal(existsSync(join(f.root, '.logs', 'core.jsonl')), false);
    startup.log('ERROR', 'worker.failed'); assert.match(readFileSync(join(f.root, '.logs', 'core.jsonl'), 'utf8'), /worker.failed/);
    denied(() => startup.log('ERROR', 'raw secret: fixture-key'), 400);
    denied(() => f.settings.updateIntegration(f.owner, 'startup', { proxy_url: 'http://user:secret@example.invalid' }), 400);
    denied(() => f.settings.updateIntegration(f.owner, 'startup', { model_timeout: 1.5 }), 400);
    denied(() => f.settings.clearIntegrationCredential(f.owner, 'startup', 'password'), 405);
  } finally { f.close(); }
});

test('saved startup timeout affects real model calls after recreation and preserves per-model timeout overrides', async () => {
  const f = await fixture();
  const server = createServer(async (req, _res) => { for await (const _ of req) { /* hold the actual request */ } });
  await new Promise<void>(r => server.listen(0, '127.0.0.1', r));
  try {
    f.db.update('users', f.owner.userId, { is_system_admin: true });
    f.settings.updateIntegration(f.owner, 'startup', { model_timeout: 1 });
    const { ModelConfigurationService } = await import('../src/settings/index.js');
    const models = new ModelConfigurationService(f.db, f.auth, f.vault);
    const address = server.address() as { port: number };
    const id = String(models.create(f.owner, config('chat', { parameters: { base_url: `http://127.0.0.1:${address.port}/v1`, api_key: 'fixture-key' } })).id);
    assert.equal(models.configuration(f.owner, id).parameters.timeoutMs, 1000);
    const started = Date.now(); await assert.rejects(models.test(f.owner, id), (e: any) => e.code === 'model_timeout');
    assert.ok(Date.now() - started >= 900 && Date.now() - started < 2000);
    models.update(f.owner, id, { parameters: { timeout: 7 } });
    assert.equal(models.configuration(f.owner, id).parameters.timeoutMs, undefined);
    assert.equal(models.configuration(f.owner, id).parameters.timeout, 7);
  } finally { server.closeAllConnections(); await new Promise<void>(r => server.close(() => r())); f.close(); }
});

test('default role selection preserves creation-order fallback and auxiliary role mapping', async () => {
  const f = await fixture();
  try {
    const older = f.models.create(f.owner, config('chat', { fallback_priority: 100 }));
    f.db.update('models', String(older.id), { created_at: '2026-01-01T00:00:00.000Z' });
    f.models.create(f.owner, config('chat', { fallback_priority: 0 }));
    for (const role of ['chat', 'summary', 'title', 'question', 'extract']) assert.equal(f.models.configuration(f.owner, role).id, older.id);
  } finally { f.close(); }
});

test('provider and tenant credential endpoints report state, encrypt edits and clear individual secrets without deleting configuration', async () => {
  const f = await fixture();
  try {
    assert.equal(typeof f.settings.clearProviderCredential, 'function');
    const row = f.settings.createProvider(f.owner, 'mcp_services', { name: 'clear', url: 'http://localhost:8080/mcp', api_key: 'first' });
    const id = String(row.id);
    f.settings.updateProviderCredentials(f.owner, 'mcp_services', id, { api_key: 'replaced' });
    assert.equal(f.settings.providerCredentials(f.owner, 'mcp_services', id).fields.api_key.configured, true);
    f.settings.clearProviderCredential(f.owner, 'mcp_services', id, 'api_key');
    assert.equal(f.settings.providerCredentials(f.owner, 'mcp_services', id).fields.api_key.configured, false);
    assert.equal(f.settings.getProvider(f.owner, 'mcp_services', id).url, 'http://localhost:8080/mcp');
    denied(() => f.settings.updateProviderCredentials(f.owner, 'mcp_services', id, { url: 'http://elsewhere.invalid' }), 400);
    denied(() => f.settings.clearProviderCredential(f.outsider, 'mcp_services', id, 'api_key'), 404);
    f.settings.setKV(f.owner, 'web-search-config', { base_url: 'http://localhost:8080', api_key: 'search', enabled: true });
    f.settings.clearKVCredential(f.owner, 'web-search-config', 'api_key');
    assert.equal(f.settings.getKV(f.owner, 'web-search-config').fields.api_key.configured, false);
    assert.equal(f.settings.getKV(f.owner, 'web-search-config').value.enabled, true);
  } finally { f.close(); }
});

test('trusted usage auditing survives revocation, validates actual counters, removes secrets and uses invocation UUID idempotency', async () => {
  const f = await fixture();
  try {
    assert.equal(typeof f.models.recordUsage, 'function');
    const id = String(f.models.create(f.owner, config()).id), cfg = f.models.configuration(f.owner, id);
    f.auth.assertCan(f.owner, 'admin'); f.auth.logout(f.owner);
    const usage = { prompt_tokens: 3, completion_tokens: 2, total_tokens: 5, cached_tokens: 1, reasoning_tokens: 1 };
    const outcome = { scenario: 'document.embedding', success: true, durationMs: 20, invocationId: '11111111-2222-4333-8444-555555555555', metadata: { operation: 'embedding', job_id: 'job-fixture', api_key: 'private-secret', prompt: 'private prompt' } };
    const first = f.models.recordUsage(f.owner, cfg, usage, outcome);
    assert.equal(first.id, outcome.invocationId); assert.equal(first.total_tokens, 5);
    assert.equal(JSON.stringify(first).includes('fixture-key'), false);
    assert.equal(JSON.stringify(first).includes('private-secret'), false);
    assert.equal(f.models.recordUsage(f.owner, cfg, usage, outcome).id, first.id);
    assert.equal(f.db.get('select count(*) as n from model_usage')!.n, 1);
    denied(() => f.models.recordUsage(f.owner, cfg, { ...usage, total_tokens: 6 }, outcome), 409, 'usage_conflict');
    denied(() => f.models.recordUsage(f.owner, cfg, { ...usage, prompt_tokens: Infinity }, { ...outcome, invocationId: undefined }), 400);
    denied(() => f.models.recordUsage(f.owner, cfg, usage, { ...outcome, invocationId: undefined, errorCode: 'secret=private-secret' }), 400);
    denied(() => f.models.recordUsage(f.outsider, cfg, usage, { ...outcome, invocationId: undefined }), 404);
    assert.equal(f.db.get('select count(*) as n from model_usage')!.n, 1);
  } finally { f.close(); }
});
