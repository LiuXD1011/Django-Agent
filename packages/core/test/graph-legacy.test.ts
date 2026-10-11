import assert from 'node:assert/strict';
import { chmodSync, mkdtempSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { execFile } from 'node:child_process';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { promisify } from 'node:util';
import test from 'node:test';
import { AuthService } from '../src/auth/index.js';
import { CoreDatabase } from '../src/storage/database.js';
import { CredentialVault } from '../src/storage/credentials.js';
import { importLegacy } from '../src/storage/legacy.js';
import { ModelConfigurationService } from '../src/settings/model-configuration.js';
import { SettingsService } from '../src/settings/settings.js';
import { IntegrationService } from '../src/integrations/index.js';
import { GraphService } from '../src/graph/index.js';
import { KnowledgeService } from '../src/knowledge/index.js';
import { CallScope } from '../src/integrations/network.js';
import { queryNeo4jHttp } from '../src/integrations/neo4j-http.js';

async function fixture(options: { secondDocument?: boolean } = {}) {
  const module = await import('../src/storage/graph-legacy.js').catch(() => null);
  assert.ok(module, 'Legacy graph migration must preserve the actual read-only ENTITY namespace without a paid rebuild');
  const root = mkdtempSync(join(tmpdir(), 'marlin-legacy-graph-')), sourceRoot = join(root, 'source'), target = join(root, 'target');
  const source = new CoreDatabase(sourceRoot), sourceAuth = new AuthService(source);
  const password = 'GraphLegacyFixture✓Password', owner = sourceAuth.register({ username: 'graph-migration-owner', password });
  source.update('tenants', owner.context.tenantId, { space_type: 'legacy', personal_owner_id: null });
  sourceAuth.register({ username: 'graph-migration-outsider', password });
  const kb = source.insert('knowledge_bases', { id: 'kb:a-b', tenant_id: owner.context.tenantId, name: '旧图知识库', indexing_strategy: { graph_enabled: true } });
  const doc = source.insert('knowledges', { id: 'doc:exact-id', tenant_id: owner.context.tenantId, knowledge_base_id: kb.id, title: '文档😀', enable_status: 'enabled' });
  const first = source.insert('chunks', { id: '1152921504606846976', tenant_id: owner.context.tenantId, knowledge_base_id: kb.id, knowledge_id: doc.id, content: 'Orca 使用 GraphRAG 😀', chunk_index: 0, metadata: { source_refs: [{ source_ref: 'page:2', page_index: 1, canonical_start: 10, canonical_end: 12 }] }, relation_chunks: ['1152921504606846977'] });
  const second = source.insert('chunks', { id: '1152921504606846977', tenant_id: owner.context.tenantId, knowledge_base_id: kb.id, knowledge_id: doc.id, content: 'GraphRAG 与实体关系', chunk_index: 1 });
  const hidden = source.insert('chunks', { id: 'disabled-chunk', tenant_id: owner.context.tenantId, knowledge_base_id: kb.id, knowledge_id: doc.id, content: 'DISABLED_SECRET', is_enabled: false });
  if (options.secondDocument) {
    source.insert('knowledges', { ...doc, id: 'z-second-source' });
    source.insert('chunks', { ...first, id: 'second-source-chunk', knowledge_id: 'z-second-source' });
  }
  source.insert('integration_configs', { name: 'neo4j', parameters: new CredentialVault(sourceRoot).encrypt({ enabled: true, uri: 'bolt://127.0.0.1:7687', username: 'fixture', password: 'fixture' }) });
  source.run('CREATE TABLE django_migrations(id INTEGER PRIMARY KEY,app TEXT,name TEXT)');
  source.run('INSERT INTO django_migrations(app,name) VALUES(?,?)', 'personal_knowledge_base', '0026_personal_tenants');
  source.close();
  renameSync(join(sourceRoot, 'marlin.sqlite3'), join(sourceRoot, 'db.sqlite3'));
  await importLegacy({ sourceRoot, targetRoot: target });
  const db = new CoreDatabase(target), auth = new AuthService(db), ctx = auth.login({ login: 'graph-migration-owner', password }).context;
  const outside = auth.login({ login: 'graph-migration-outsider', password }).context;
  const models = new ModelConfigurationService(db, auth, new CredentialVault(target));
  const integrations = new IntegrationService(db, auth, new SettingsService(db, auth, new CredentialVault(target)));
  const records: any[] = [
    { kind: 'node', key: 'n:1', labels: ['ENTITYkb_a_b', 'ENTITYdoc_exact_id'], properties: { name: 'Orca', kg: doc.id, attributes: ['实际代理😀'], chunks: [first.id, hidden.id, 'foreign-chunk'], custom_original: 'preserve-private-export' } },
    { kind: 'node', key: 'n:2', labels: ['ENTITYkb_a_b', 'ENTITYdoc_exact_id'], properties: { name: 'GraphRAG', kg: doc.id, attributes: ['知识检索'], chunks: [second.id] } },
    { kind: 'relation', key: 'r:1', source: 'n:1', target: 'n:2', relation_type: 'uses', properties: { strength: 8, weight: 7.5, combined_degree: 4, chunks: [first.id, second.id], custom_original: 42 } },
  ];
  const calls: any[] = [], modelCalls: any[] = []; let gate: ((body: any) => Promise<void>) | undefined;
  const server = createServer(async (req, res) => {
    let raw = ''; for await (const part of req) raw += part;
    const body = JSON.parse(raw);
    if (req.url === '/v1/chat/completions') {
      modelCalls.push(body); res.setHeader('content-type', 'application/json');
      res.end(JSON.stringify({ choices: [{ message: { content: JSON.stringify({ node: [{ name: 'Orca' }, { name: 'GraphRAG' }], relation: [] }) }, finish_reason: 'stop' }], usage: { prompt_tokens: 3, completion_tokens: 2, total_tokens: 5 } })); return;
    }
    calls.push(body);
    assert.equal(db.sqlite.inTransaction, false, 'No transaction may be held across the external read');
    if (gate) await gate(body);
    assert.match(body.statement, /MARLIN_LEGACY_READ_(NODES|RELATIONS)/);
    assert.doesNotMatch(body.statement, /\b(MERGE|CREATE|SET|DELETE|REMOVE|CALL)\b/u);
    const p = body.parameters, selected = p.knowledge_id === doc.id ? records.filter(r => r.kind === p.phase && r.key > p.cursor).slice(0, p.limit) : [];
    res.setHeader('content-type', 'application/json'); res.end(JSON.stringify({ data: { fields: ['record'], values: selected.map(record => [record]) } }));
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve)); const address = server.address(); assert.ok(address && typeof address !== 'string');
  const transport = async (actor: any, ticket: any, page: any, options: any) => {
    const query = module.legacyGraphReadQuery(db, auth, actor, ticket, page);
    const scope = new CallScope(options);
    try { const result: any = await queryNeo4jHttp(scope, { url: `http://127.0.0.1:${address.port}`, username: 'fixture', password: 'fixture' }, query.statement, query.parameters); return { ...result, records: result.records.map((r: any) => r.record) }; }
    finally { scope.dispose(); }
  };
  const migration = new module.LegacyGraphMigration(db, auth, integrations, { transport, pageSize: 1 });
  const graph = new GraphService(db, auth, models);
  const service = auth.authenticateApiKey(String(db.read('tenants', ctx.tenantId)!.api_key), ctx.tenantId);
  return { ...module, root, target, db, auth, ctx, outside, service, kb, doc, first, second, hidden, records, calls, modelCalls, models, modelBase: `http://127.0.0.1:${address.port}/v1`, migration, graph, integrations, gate: (value: typeof gate) => { gate = value; },
    close: async () => { await graph.close(); await integrations.close(); await new Promise<void>(resolve => { server.closeAllConnections(); server.close(() => resolve()); }); db.close(); rmSync(root, { recursive: true, force: true }); } };
}

test('legacy export uses exact imported labels/kg, hashes every paginated property and publishes local source evidence without network writes or model calls', async () => {
  const f = await fixture();
  try {
    const inspected = await f.migration.inspect(f.ctx);
    assert.equal(inspected.nodes, 2); assert.equal(inspected.relations, 1); assert.equal(inspected.published_documents, 0);
    assert.equal(f.db.get("SELECT count(*) AS n FROM generic_resources WHERE resource_type='graph_document'")?.n, 0);
    const result = await f.migration.import(f.ctx);
    assert.equal(result.nodes, 2); assert.equal(result.relations, 1); assert.equal(result.published_documents, 1); assert.equal(result.repeated, false);
    assert.match(result.export_sha256, /^[a-f0-9]{64}$/); assert.match(result.conversion_sha256, /^[a-f0-9]{64}$/); assert.match(result.publication_sha256, /^[a-f0-9]{64}$/);
    const archive = JSON.parse(readFileSync(join(f.target, result.archive_path), 'utf8'));
    assert.equal(archive.documents[0].records[0].properties.custom_original, 'preserve-private-export');
    assert.equal(archive.documents[0].records[2].properties.custom_original, 42);
    assert.ok(f.calls.every(c => c.parameters.knowledge_id === f.doc.id && c.statement.includes(':ENTITYkb_a_b:ENTITYdoc_exact_id')));
    const view = await f.graph.overview(f.ctx, String(f.kb.id));
    assert.equal(view.state, 'connected'); assert.deepEqual(view.nodes.map(n => n.name).sort(), ['GraphRAG', 'Orca']); assert.equal(view.edges[0].weight, 7.5); assert.equal(view.edges[0].strength, 8);
    const orca = view.nodes.find(n => n.name === 'Orca')!; assert.deepEqual(orca.chunks, [f.first.id]); assert.equal(orca.source_refs[0].page_index, 1); assert.equal(orca.source_refs[0].canonical_end, 12);
    assert.deepEqual(f.db.read('chunks', f.first.id)?.relation_chunks, [f.second.id], 'Original weighted relation order must not be replaced during import');
    assert.deepEqual((await f.graph.types(f.ctx, String(f.kb.id))).relation_types, ['uses']); assert.equal((await f.graph.ego(f.ctx, String(f.kb.id), String(orca.id))).nodes.length, 2);
    assert.equal(f.graph.capabilities(f.ctx, String(f.kb.id)).legacy_namespace_status, 'imported');
    assert.equal(f.db.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
    const repeated = await f.migration.import(f.ctx); assert.equal(repeated.repeated, true); assert.equal(repeated.publication_sha256, result.publication_sha256);
  } finally { await f.close(); }
});

test('legacy migration tickets cannot be forged or used by another tenant; edited sources never revive from the external graph', async () => {
  const f = await fixture();
  try {
    await assert.rejects(f.integrations.readLegacyGraph(f.ctx, {} as any, { phase: 'node', cursor: '', limit: 1 }), (e: any) => e.status === 403);
    await assert.rejects(f.migration.import(f.outside), (e: any) => e.code === 'legacy_graph_no_sources');
    await f.migration.import(f.ctx);
    await assert.rejects(f.graph.overview(f.outside, String(f.kb.id)), (e: any) => e.status === 404);
    f.db.update('chunks', f.first.id, { content: 'new edited content' });
    assert.equal((await f.graph.overview(f.ctx, String(f.kb.id))).nodes.length, 0);
    await assert.rejects(f.migration.import(f.ctx), (e: any) => e.status === 409 && e.code === 'legacy_graph_source_changed');
    f.db.update('knowledges', f.doc.id, { enable_status: 'disabled' }); assert.equal((await f.graph.overview(f.ctx, String(f.kb.id))).nodes.length, 0);
  } finally { await f.close(); }
});

test('normal chunk metadata edits cannot revive the archived graph against changed source evidence', async t => {
  for (const kind of ['provenance', 'parser_position']) await t.test(kind, async () => {
    const f = await fixture();
    try {
      await f.migration.import(f.ctx);
      assert.equal((await f.graph.overview(f.ctx, String(f.kb.id))).nodes.length, 2);
      const knowledge = new KnowledgeService(f.db, f.auth);
      const metadata = { ...f.db.read('chunks', f.first.id)!.metadata as Record<string, any> };
      if (kind === 'provenance') metadata.source_refs = [{ source_ref: 'edited-page:99', page_index: 98 }];
      else metadata.canonical_start = 99;
      await knowledge.updateChunk(f.ctx, String(f.doc.id), String(f.first.id), { metadata });
      assert.equal(f.db.read('chunks', f.first.id)!.content, f.first.content);
      assert.equal((await f.graph.overview(f.ctx, String(f.kb.id))).nodes.length, 0);
      const publications = f.db.all("SELECT * FROM generic_resources WHERE resource_type='graph_document'"), reads = f.calls.length;
      await assert.rejects(f.migration.import(f.ctx), (e: any) => e.status === 409 && e.code === 'legacy_graph_source_changed');
      assert.equal(f.calls.length, reads, 'Changed source evidence must be rejected before reading the old graph');
      assert.deepEqual(f.db.all("SELECT * FROM generic_resources WHERE resource_type='graph_document'"), publications);
      assert.equal((await f.graph.overview(f.ctx, String(f.kb.id))).nodes.length, 0);
      assert.equal(f.db.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
    } finally { await f.close(); }
  });
});

test('derived graph associations do not prevent an unchanged source from being imported again', async () => {
  const f = await fixture();
  try {
    const first = await f.migration.import(f.ctx);
    const metadata = f.db.read('chunks', f.first.id)!.metadata as Record<string, any>;
    f.db.update('chunks', f.first.id, { metadata: { ...metadata, graph_relation_chunks: [f.second.id], graph_indirect_relation_chunks: [f.second.id] } });
    const repeated = await f.migration.import(f.ctx);
    assert.equal(repeated.repeated, true); assert.equal(repeated.publication_sha256, first.publication_sha256);
    const view = await f.graph.overview(f.ctx, String(f.kb.id));
    assert.equal(view.nodes.length, 2); assert.equal(view.nodes.find(n => n.name === 'Orca')!.source_refs[0].source_ref, 'page:2');
    assert.equal(f.db.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
  } finally { await f.close(); }
});

test('external export mutation, cancellation and source changes during read reject atomically without any publication', async () => {
  const f = await fixture();
  try {
    let pages = 0; f.gate(async () => { if (++pages === 4) f.records[0].properties.attributes = ['changed external graph']; });
    await assert.rejects(f.migration.import(f.ctx), (e: any) => e.code === 'legacy_graph_external_changed');
    assert.equal(f.db.get("SELECT count(*) AS n FROM generic_resources WHERE resource_type='graph_document'")?.n, 0);
    const controller = new AbortController(); f.gate(async () => { controller.abort(); });
    await assert.rejects(f.migration.import(f.ctx, { signal: controller.signal }));
    assert.equal(f.db.get("SELECT count(*) AS n FROM generic_resources WHERE resource_type='graph_document'")?.n, 0);
    f.gate(async () => { f.db.update('chunks', f.first.id, { content: 'changed local source' }); });
    await assert.rejects(f.migration.import(f.ctx), (e: any) => e.code === 'legacy_graph_source_changed');
    assert.equal(f.db.get("SELECT count(*) AS n FROM generic_resources WHERE resource_type='graph_document'")?.n, 0);
  } finally { await f.close(); }
});

test('missing old relation weights are explicit derived values; empty graph is verified empty, never a successful reconstruction', async () => {
  const f = await fixture();
  try {
    f.records[2].properties = {};
    const result = await f.migration.import(f.ctx); assert.ok(result.warnings.includes('legacy_relationship_weight_not_stored'));
    const view = await f.graph.overview(f.ctx, String(f.kb.id)); assert.ok(view.edges[0].weight >= 1); assert.ok(view.edges[0].source_refs.length > 0);
    f.records.splice(0); const empty = await f.migration.inspect(f.ctx); assert.equal(empty.nodes, 0); assert.equal(empty.relations, 0); assert.equal(empty.state, 'verified_empty');
  } finally { await f.close(); }
});

test('the original tenant API credential permits a read-only inventory but cannot publish or mint a user migration identity', async () => {
  const f = await fixture();
  try {
    assert.equal(f.service.userId, '');
    const inspected = await f.migration.inspect(f.service); assert.equal(inspected.nodes, 2); assert.equal(inspected.relations, 1);
    await assert.rejects(f.migration.import(f.service), (e: any) => e.status === 403);
    assert.equal(f.db.get("SELECT count(*) AS n FROM generic_resources WHERE resource_type='graph_document'")?.n, 0);
    assert.equal(f.db.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
  } finally { await f.close(); }
});

test('legacy local query uses one real model query invocation and excludes seen chunks before its independent top K without contacting old graph storage', async () => {
  const f = await fixture();
  try {
    await f.migration.import(f.ctx); const reads = f.calls.length;
    f.models.create(f.ctx, { name: 'Controlled legacy graph query', type: 'KnowledgeQA', source: 'openai', parameters: { model: 'controlled', base_url: f.modelBase, api_key: 'fixture-only' } });
    const result = await f.graph.search(f.ctx, String(f.kb.id), 'Orca and GraphRAG', { limit: 1, seenChunkIds: [String(f.first.id)] });
    assert.deepEqual(result.items.map((i: any) => i.chunk_id), [f.second.id]); assert.equal(result.items[0].match_type, 'graph');
    assert.equal(f.calls.length, reads); assert.equal(f.modelCalls.length, 1); assert.equal(f.db.get("SELECT count(*) AS n FROM model_usage WHERE scenario='graph_query_extract'")?.n, 1);
  } finally { await f.close(); }
});

test('the actual CLI uses private real credentials and rejects API-key publication without leaking inputs or claiming success', async () => {
  const f = await fixture();
  try {
    const privatePath = join(f.root, 'private-auth.json'), key = String(f.db.read('tenants', f.ctx.tenantId)!.api_key);
    writeFileSync(privatePath, JSON.stringify({ mode: 'api_key', credential: key, tenant_id: f.ctx.tenantId }), { mode: 0o600 });
    const invoke = () => promisify(execFile)(process.execPath, ['--import', 'tsx', 'src/tools/migrate-graph.ts', 'import', '--data-root', f.target, '--auth-file', privatePath], { cwd: process.cwd(), timeout: 15000 });
    await assert.rejects(invoke(), (e: any) => { assert.match(e.stderr, /action_forbidden/); assert.equal(e.stderr.includes(key), false); assert.equal(e.stdout, ''); return true; });
    if (process.platform !== 'win32') {
      chmodSync(privatePath, 0o644);
      await assert.rejects(invoke(), (e: any) => { assert.match(e.stderr, /private_auth_file_required/); assert.equal(e.stderr.includes(key), false); return true; });
    }
    assert.equal(f.calls.length, 0); assert.equal(f.db.get("SELECT count(*) AS n FROM generic_resources WHERE resource_type='graph_document'")?.n, 0);
  } finally { await f.close(); }
});

test('a conflict in the second document rolls back the first publication and never overwrites a modern graph', async () => {
  const f = await fixture({ secondDocument: true });
  try {
    const id = `graph:${(await import('../src/wiki/internal.js')).hash([f.ctx.tenantId, f.kb.id, 'z-second-source'])}`;
    const preserved = { knowledge_base_id: f.kb.id, knowledge_id: 'z-second-source', storage: 'neo4j', nodes: [], relations: [] };
    f.db.insert('generic_resources', { id, tenant_id: f.ctx.tenantId, resource_type: 'graph_document', data: preserved });
    await assert.rejects(f.migration.import(f.ctx), (e: any) => e.code === 'legacy_graph_publication_conflict');
    assert.equal(f.db.get("SELECT count(*) AS n FROM generic_resources WHERE resource_type='graph_document'")?.n, 1);
    assert.deepEqual(f.db.read('generic_resources', id)!.data, preserved);
  } finally { await f.close(); }
});

test('removing a preserved graph retires only its local publication and clears its recorded old graph associations without writing the original Neo4j', async () => {
  const f = await fixture();
  try {
    await f.migration.import(f.ctx); const reads = f.calls.length;
    const removed = await f.graph.removeDocument(f.ctx, String(f.kb.id), String(f.doc.id));
    assert.equal(removed.status, 'completed'); assert.equal(removed.output.remote_cleanup, 'not_required');
    assert.equal(f.calls.length, reads); assert.deepEqual(f.db.read('chunks', f.first.id)!.relation_chunks, []);
    assert.equal((await f.graph.overview(f.ctx, String(f.kb.id))).nodes.length, 0);
    assert.equal(f.db.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
  } finally { await f.close(); }
});
