import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { AuthService } from '../src/auth/index.js';
import { GraphService } from '../src/graph/index.js';
import { IntegrationService } from '../src/integrations/index.js';
import { SearchIndex } from '../src/retrieval/search-index.js';
import { ModelConfigurationService } from '../src/settings/model-configuration.js';
import { SettingsService } from '../src/settings/settings.js';
import { CredentialVault } from '../src/storage/credentials.js';
import { CoreDatabase } from '../src/storage/database.js';
import { createApplicationAgentHooks } from '../src/agents/application-hooks.js';

async function adapters(dependencies: any): Promise<any> {
  return createApplicationAgentHooks(dependencies);
}
function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'marlin-agent-hooks-')), db = new CoreDatabase(root), auth = new AuthService(db);
  const ctx = auth.register({ username: 'hooks-fixture', password: 'Hooks fixture password 2026' }).context;
  const vault = new CredentialVault(root), settings = new SettingsService(db, auth, vault), models = new ModelConfigurationService(db, auth, vault), integrations = new IntegrationService(db, auth, settings), index = new SearchIndex(db);
  return { root, db, auth, ctx, settings, models, integrations, index, close: async () => { await integrations.close(); db.close(); rmSync(root, { recursive: true, force: true }); } };
}
test('application graph hook executes real GraphService extraction and current scoped source/relationship citations', async () => {
  const f = fixture(), nodes: any[] = []; let calls = 0;
  const server = createServer(async (req, res) => {
    let raw = ''; for await (const part of req) raw += part; const body = JSON.parse(raw); calls++;
    assert.equal(f.db.sqlite.inTransaction, false);
    const content = body.messages.at(-1).content.includes('GRAPH_ENTITIES') ? [{ chunk_key: 'c001', entities: [{ name: 'Orca' }] }] : { node: [{ name: 'Orca' }], relation: [] };
    res.setHeader('content-type', 'application/json'); res.end(JSON.stringify({ choices: [{ message: { content: JSON.stringify(content) }, finish_reason: 'stop' }], usage: { prompt_tokens: 4, completion_tokens: 2, total_tokens: 6 } }));
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve)); const address = server.address(); assert.ok(address && typeof address !== 'string');
  const graph = new GraphService(f.db, f.auth, f.models, undefined, { transport: async (ctx, id, statement, params) => {
    f.auth.assertCan(ctx, 'read'); assert.equal(params.knowledge_base_id, id); assert.equal(params.tenant_id, ctx.tenantId);
    if (statement.includes('MARLIN_WRITE_GENERATION')) { nodes.push(...params.nodes as any[]); return { state: 'connected', records: [{ nodes: (params.nodes as any[]).length, relations: 0 }] }; }
    assert.ok(statement.includes('MARLIN_READ_GENERATIONS')); const active = params.active as any[];
    return { state: 'connected', records: nodes.filter(n => active.some(a => a.knowledge_id === n.knowledge_id && a.generation === n.generation)).map(node => ({ node })) };
  } }); let factory: any;
  try {
    f.models.create(f.ctx, { name: 'local hook model', type: 'KnowledgeQA', source: 'openai', is_default: true, parameters: { model: 'fixture', base_url: `http://127.0.0.1:${address.port}/v1` } });
    const kb = f.db.insert('knowledge_bases', { tenant_id: f.ctx.tenantId, name: 'Graph hook', indexing_strategy: { graph_enabled: true } }), doc = f.db.insert('knowledges', { tenant_id: f.ctx.tenantId, knowledge_base_id: kb.id, title: 'Graph source' });
    const source = f.db.insert('chunks', { tenant_id: f.ctx.tenantId, knowledge_base_id: kb.id, knowledge_id: doc.id, content: 'Orca 原文😀', seq_id: '1152921504606846975', image_info: { source_ref: '真实来源' } });
    const other = f.db.insert('knowledge_bases', { tenant_id: f.ctx.tenantId, name: 'Unselected' }), otherDoc = f.db.insert('knowledges', { tenant_id: f.ctx.tenantId, knowledge_base_id: other.id, title: 'NEVER_FOREIGN' }), foreign = f.db.insert('chunks', { tenant_id: f.ctx.tenantId, knowledge_base_id: other.id, knowledge_id: otherDoc.id, content: 'NEVER_UNSELECTED_SOURCE' });
    assert.equal((await graph.build(f.ctx, String(kb.id), String(doc.id))).status, 'completed');
    f.db.update('chunks', String(source.id), { relation_chunks: [foreign.id] });
    factory = await adapters({ ...f, graph }); const result = factory.hooks.graph ? await factory.hooks.graph(f.ctx, [String(kb.id)], 'Orca', { signal: new AbortController().signal }) : { output: '', error_type: 'NOT_CONFIGURED' };
    assert.equal(result.error_type, undefined); assert.equal(result.references?.length, 1); assert.equal(result.references[0].chunk_id, source.id);
    assert.equal(result.references[0].seq_id, '1152921504606846975'); assert.equal(result.references[0].image_info.source_ref, '真实来源'); assert.equal(result.output.includes('NEVER_'), false);
    assert.equal(calls, 2); assert.equal(f.db.all('SELECT id FROM model_usage').length, 2);
    f.db.update('knowledges', String(doc.id), { enable_status: 'disabled' }); const disabled = await factory.hooks.graph(f.ctx, [String(kb.id)], 'Orca', { signal: new AbortController().signal }); assert.deepEqual(disabled.references, []);
    const before = calls; assert.deepEqual((await factory.hooks.graph(f.ctx, [], 'Orca', { signal: new AbortController().signal })).references, []); assert.equal(calls, before);
  } finally { await factory?.close(); await graph.close(); await new Promise<void>(resolve => { server.closeAllConnections(); server.close(() => resolve()); }); await f.close(); }
});
test('application web fetch performs bounded real HTTP, Unicode text conversion and rejects redirects, private targets and cancellation', async () => {
  const f = fixture(); let requests = 0, pending: (() => void) | undefined;
  const server = createServer((req, res) => {
    requests++; assert.equal(req.headers.authorization, undefined); assert.equal(req.headers.cookie, undefined);
    if (req.url === '/redirect') { res.writeHead(302, { location: 'http://127.0.0.1:1/private' }); res.end(); }
    else if (req.url === '/unterminated') { res.setHeader('content-type', 'text/html'); res.end('<script>NEVER_SCRIPT' + '<script>'.repeat(2000)); }
    else if (req.url === '/large') { res.setHeader('content-length', 1048577); res.end('x'); }
    else if (req.url === '/wait') { res.writeHead(200, { 'content-type': 'text/plain' }); res.write('waiting'); pending?.(); }
    else { res.setHeader('content-type', 'text/html; charset=utf-8'); res.end('<script>NEVER_SCRIPT</script><style>NEVER_STYLE</style><p>中文😀 &amp; 本文</p>'); }
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve)); const address = server.address(); assert.ok(address && typeof address !== 'string'); const origin = `http://127.0.0.1:${address.port}`;
  const graph = new GraphService(f.db, f.auth, f.models), factory = await adapters({ ...f, graph, webFetch: { allowedOrigins: [origin], timeoutMs: 1000 } });
  try {
    const fetch = factory.hooks.webFetch; assert.equal(typeof fetch, 'function');
    const result = await fetch(f.ctx, origin, { signal: new AbortController().signal, maxChars: 4 }); assert.equal(result.output, '中文😀 '); assert.equal(result.error, undefined);
    assert.equal((await fetch(f.ctx, origin + '/unterminated', { signal: new AbortController().signal, maxChars: 100 })).output, '', 'unclosed script contents remain excluded');
    await assert.rejects(fetch(f.ctx, origin + '/redirect', { signal: new AbortController().signal, maxChars: 30 }), (e: any) => e.code === 'web_fetch_redirect_rejected');
    await assert.rejects(fetch(f.ctx, origin + '/large', { signal: new AbortController().signal, maxChars: 30 }), (e: any) => e.code === 'web_fetch_response_too_large');
    const before = requests;
    for (const url of ['http://127.0.0.1:1/private', 'http://[::1]/', 'http://169.254.169.254/', 'http://user:password@example.test/', 'file:///etc/passwd']) await assert.rejects(fetch(f.ctx, url, { signal: new AbortController().signal, maxChars: 30 }));
    assert.equal(requests, before);
    const controller = new AbortController(), entered = new Promise<void>(resolve => { pending = resolve; }); const work = fetch(f.ctx, origin + '/wait', { signal: controller.signal, maxChars: 30 }); await entered; controller.abort(); await assert.rejects(work);
    const closing = fetch(f.ctx, origin + '/wait', { signal: new AbortController().signal, maxChars: 30 }); await factory.close(); await assert.rejects(closing);
    assert.equal(f.db.all('SELECT id FROM model_usage').length, 0);
  } finally { await factory.close(); await graph.close(); await new Promise<void>(resolve => { server.closeAllConnections(); server.close(() => resolve()); }); await f.close(); }
});
test('application skill hook reads only its actual trusted business catalog and excludes path/symlink escape with real auth', async () => {
  const f = fixture(), skillsRoot = join(f.root, 'skills'); mkdirSync(join(skillsRoot, 'source-reader'), { recursive: true });
  writeFileSync(join(skillsRoot, 'source-reader', 'SKILL.md'), '---\nname: source-reader\ndescription: Read actual evidence\n---\nAlways check the actual source.\n');
  const outside = join(f.root, 'outside'); mkdirSync(outside); writeFileSync(join(outside, 'SKILL.md'), 'NEVER_PRIVATE_FILE'); symlinkSync(outside, join(skillsRoot, 'escaped'), 'dir');
  const graph = new GraphService(f.db, f.auth, f.models), factory = await adapters({ ...f, graph, skillsRoot });
  try {
    assert.equal(typeof factory.hooks.readSkill, 'function'); const result = await factory.hooks.readSkill(f.ctx, 'source-reader'); assert.equal(result.output, 'Always check the actual source.');
    for (const name of ['../outside', 'escaped', '/etc/passwd', 'missing']) { const result = await factory.hooks.readSkill(f.ctx, name); assert.equal(result.error_type, 'NOT_FOUND'); assert.equal(result.output.includes('NEVER_PRIVATE'), false); }
    f.auth.logout(f.ctx); await assert.rejects(factory.hooks.readSkill(f.ctx, 'source-reader'));
  } finally { await factory.close(); await graph.close(); await f.close(); }
});
