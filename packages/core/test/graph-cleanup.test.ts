import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { createServer } from 'node:http';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { CoreApplication } from '../src/application.js';
import { GraphService, graphNamespace } from '../src/graph/index.js';
import type { JsonObject } from '../src/contracts.js';
import { CallScope } from '../src/integrations/network.js';
import { queryNeo4jHttp } from '../src/integrations/neo4j-http.js';

async function controlledGraph(f: ReturnType<typeof fixture>) {
  const calls: JsonObject[] = [], remote: JsonObject[] = [], state = { outage: false, gate: undefined as undefined | (() => Promise<void>) };
  const server = createServer(async (req, res) => {
    assert.equal(f.app.database.sqlite.inTransaction, false);
    let raw = ''; for await (const part of req) raw += part;
    const body = JSON.parse(raw); calls.push(body); await state.gate?.();
    res.setHeader('content-type', 'application/json');
    if (state.outage) { res.statusCode = 503; res.end('{}'); return; }
    const p = body.parameters;
    assert.ok(body.statement.includes('MARLIN_DELETE_'));
    for (let i = remote.length - 1; i >= 0; i--) {
      const row = remote[i]!;
      if (row.namespace === p.namespace && row.tenant_id === p.tenant_id && row.knowledge_base_id === p.knowledge_base_id && (body.statement.includes('MARLIN_DELETE_KNOWLEDGE_BASE') || row.knowledge_id === p.knowledge_id && (!p.generation || row.generation === p.generation))) remote.splice(i, 1);
    }
    res.end(JSON.stringify({ data: { fields: ['deleted'], values: [[0]] } }));
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve)); const address = server.address(); assert.ok(address && typeof address !== 'string');
  const transport = async (_ctx: any, _kb: string, statement: string, parameters: JsonObject, options: any = {}) => {
    const scope = new CallScope(options);
    try { return await queryNeo4jHttp(scope, { url: `http://127.0.0.1:${address.port}`, username: 'local', password: 'fixture' }, statement, parameters); } finally { scope.dispose(); }
  };
  return { calls, remote, state, service: () => new GraphService(f.app.database, f.app.auth, f.app.models, undefined, { transport }), close: () => new Promise<void>(resolve => { server.closeAllConnections(); server.close(() => resolve()); }) };
}

function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'marlin-graph-cleanup-'));
  const app = new CoreApplication(root, { allowAutoSetup: true });
  const issue = app.auth.autoSetup({ password: 'Independent-graph-cleanup-fixture' });
  const kb = app.knowledge.knowledgeBases.create(issue.context, { name: 'Graph cleanup', indexing_strategy: { graph_enabled: true } });
  return { root, app, issue, kb, close: async () => { await app.close(); rmSync(root, { recursive: true, force: true }); } };
}
const pending = (f: ReturnType<typeof fixture>) => f.app.database.all("SELECT key,value FROM desktop_meta WHERE key LIKE 'knowledge.graph.pending:%'").map(row => ({ key: String(row.key), value: JSON.parse(String(row.value)) }));

test('deleted knowledge base pending document cleanup retries its exact original namespace', async () => {
  const f = fixture(), calls: JsonObject[] = [];
  const graph = new GraphService(f.app.database, f.app.auth, f.app.models, undefined, { transport: async (_ctx, _kb, statement, parameters) => { calls.push({ statement, parameters }); return { state: 'connected', records: [] }; } });
  try {
    const d = f.app.database.insert('knowledges', { tenant_id: f.issue.context.tenantId, knowledge_base_id: f.kb.id, title: 'retire me' });
    await f.app.knowledge.knowledgeBases.delete(f.issue.context, String(f.kb.id));
    const result = await graph.processPending(f.issue.context, String(f.kb.id));
    assert.equal(result.processed, 1);
    assert.equal(calls.length, 1); const params = calls[0]!.parameters as JsonObject;
    assert.equal(params.knowledge_id, d.id); assert.equal(params.namespace, graphNamespace(f.issue.context.tenantId, String(f.kb.id)));
    assert.equal(pending(f)[0]!.value.status, 'completed');
    await assert.rejects(graph.overview(f.issue.context, String(f.kb.id)), (e: any) => e.status === 404);
  } finally { await graph.close(); await f.close(); }
});

test('KB DELETE route keeps a durable namespace ticket even with no document rows and disabled Neo4j', async () => {
  const f = fixture();
  try {
    const response = await f.app.dispatch({ protocol: 1, id: randomUUID(), method: 'DELETE', path: `/api/v1/knowledge-bases/${f.kb.id}` }, { transport: 'ipc', access: f.issue.credentials.access });
    assert.equal(response.response.status, 200);
    assert.ok(f.app.database.read('knowledge_bases', String(f.kb.id))?.deleted_at);
    assert.equal(pending(f).filter(item => item.value.operation === 'delete_knowledge_base').length, 1);
    const cleanup = await f.app.dispatch({ protocol: 1, id: randomUUID(), method: 'POST', path: `/api/v1/knowledge-bases/${f.kb.id}/graph/cleanup`, body: {} }, { transport: 'ipc', access: f.issue.credentials.access });
    assert.equal(cleanup.response.status, 200);
    assert.equal(pending(f)[0]!.value.status, 'pending');
  } finally { await f.close(); }
});

test('graph capabilities report disabled or incomplete Neo4j independently of an extraction model', async () => {
  const f = fixture();
  try {
    f.app.models.create(f.issue.context, { name: 'unused controlled model', type: 'KnowledgeQA', source: 'openai', parameters: { base_url: 'http://127.0.0.1:9/v1', model: 'fixture', api_key: 'fixture-secret' } });
    const disabled = f.app.graph.capabilities(f.issue.context, String(f.kb.id));
    assert.equal(disabled.state, 'disabled'); assert.equal(disabled.transport_available, false);
    // Imported old configuration may be incomplete; current Settings correctly refuses enabling it.
    f.app.database.insert('integration_configs', { name: 'neo4j', parameters: { enabled: true, uri: 'bolt://127.0.0.1:9', username: 'fixture' } });
    const incomplete = f.app.graph.capabilities(f.issue.context, String(f.kb.id));
    assert.equal(incomplete.state, 'not_configured'); assert.equal(incomplete.transport_available, false);
    assert.equal(JSON.stringify(incomplete).includes('fixture-secret'), false);
    assert.equal(f.app.database.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
  } finally { await f.close(); }
});

test('deleted-scope Integration cleanup is ticket-only while ordinary graph queries stay forbidden', async () => {
  const f = fixture();
  try {
    f.app.database.insert('knowledges', { tenant_id: f.issue.context.tenantId, knowledge_base_id: f.kb.id, title: 'retired document' });
    await f.app.knowledge.knowledgeBases.delete(f.issue.context, String(f.kb.id));
    const item = pending(f)[0]!;
    const service = f.app.integrations as any;
    assert.equal(typeof service.cleanupScopedNeo4j, 'function');
    assert.equal((await service.cleanupScopedNeo4j(f.issue.context, String(f.kb.id), item.key)).state, 'disabled');
    await assert.rejects(service.cleanupScopedNeo4j(f.issue.context, String(f.kb.id), 'knowledge.graph.pending:missing'), (e: any) => e.status === 404);
    await assert.rejects(service.queryScopedNeo4j(f.issue.context, String(f.kb.id), 'RETURN 1', { namespace: graphNamespace(f.issue.context.tenantId, String(f.kb.id)), tenant_id: f.issue.context.tenantId, knowledge_base_id: f.kb.id }), (e: any) => e.status === 404);
  } finally { await f.close(); }
});

test('cleanup result exposes remaining durable work when the bounded batch stops early', async () => {
  const f = fixture(); const graph = new GraphService(f.app.database, f.app.auth, f.app.models, undefined, { transport: async () => ({ state: 'connected', records: [] }) });
  try {
    for (let i = 0; i < 2; i++) f.app.database.insert('knowledges', { tenant_id: f.issue.context.tenantId, knowledge_base_id: f.kb.id, title: `doc ${i}` });
    await f.app.knowledge.knowledgeBases.delete(f.issue.context, String(f.kb.id));
    assert.equal((await graph.processPending(f.issue.context, String(f.kb.id), { limit: 1 })).remaining, 1);
  } finally { await graph.close(); await f.close(); }
});

test('controlled HTTP graph outage preserves local KB deletion and restart retry removes only its namespace', async () => {
  const f = fixture(), http = await controlledGraph(f); const originalGraph = f.app.graph;
  let graph = http.service(); (f.app as any).graph = graph;
  try {
    const namespace = graphNamespace(f.issue.context.tenantId, String(f.kb.id));
    http.remote.push({ namespace, tenant_id: f.issue.context.tenantId, knowledge_base_id: f.kb.id!, knowledge_id: 'orphan-staging' }, { namespace: 'foreign', tenant_id: 'other', knowledge_base_id: f.kb.id! });
    http.state.outage = true;
    const response = await f.app.dispatch({ protocol: 1, id: randomUUID(), method: 'DELETE', path: `/api/v1/knowledge-bases/${f.kb.id}` }, { transport: 'ipc', access: f.issue.credentials.access });
    assert.equal(response.response.status, 200); assert.ok(f.app.database.read('knowledge_bases', String(f.kb.id))?.deleted_at);
    const removed = (response.response.body as JsonObject).data as JsonObject;
    assert.ok((removed.warnings as JsonObject[]).some(w => w.code === 'graph_cleanup_pending'));
    assert.equal(pending(f)[0]!.value.status, 'pending');
    await f.app.close();
    f.app = new CoreApplication(f.root);
    f.app.auth.authenticateAccess(f.issue.credentials.access);
    graph = http.service(); (f.app as any).graph = graph;
    http.state.outage = false;
    const result = await graph.processPending(f.issue.context, String(f.kb.id));
    assert.equal((result.results as JsonObject[])[0]!.status, 'completed');
    assert.deepEqual(http.remote, [{ namespace: 'foreign', tenant_id: 'other', knowledge_base_id: f.kb.id! }]);
    assert.equal(pending(f)[0]!.value.status, 'completed');
  } finally { await originalGraph.close(); await graph.close(); await http.close(); await f.app.close(); await f.close(); }
});

test('document edit cleanup pins the previous generation and preserves a newly published graph', async () => {
  const f = fixture(), http = await controlledGraph(f), graph = http.service();
  try {
    const d = f.app.database.insert('knowledges', { tenant_id: f.issue.context.tenantId, knowledge_base_id: f.kb.id, title: 'old title' });
    const namespace = graphNamespace(f.issue.context.tenantId, String(f.kb.id)), id = `graph:${createHash('sha256').update(JSON.stringify([f.issue.context.tenantId, f.kb.id, d.id])).digest('hex')}`;
    const data = { namespace, knowledge_base_id: f.kb.id!, knowledge_id: d.id!, generation: 'old-generation', published_at: new Date().toISOString() };
    f.app.database.insert('generic_resources', { id, tenant_id: f.issue.context.tenantId, resource_type: 'graph_document', data, status: 'active' });
    await f.app.knowledge.update(f.issue.context, String(d.id), { title: 'new title' });
    assert.equal(pending(f)[0]!.value.generation, 'old-generation');
    f.app.database.update('generic_resources', id, { data: { ...data, generation: 'new-generation' }, status: 'active' });
    for (const generation of ['old-generation', 'new-generation']) http.remote.push({ ...data, tenant_id: f.issue.context.tenantId, generation });
    await graph.processPending(f.issue.context, String(f.kb.id));
    assert.equal(http.remote.length, 1); assert.equal(http.remote[0]!.generation, 'new-generation');
    assert.equal(f.app.database.read('generic_resources', id)!.status, 'active');
  } finally { await graph.close(); await http.close(); await f.close(); }
});

test('cleanup rejects foreign tickets and permission revocation after the actual remote response', async () => {
  const f = fixture(), http = await controlledGraph(f), graph = http.service();
  let release!: () => void, reached!: () => void; const gate = new Promise<void>(resolve => release = resolve), waiting = new Promise<void>(resolve => reached = resolve);
  try {
    const key = graph.queueKnowledgeBaseCleanup(f.issue.context, String(f.kb.id));
    await f.app.knowledge.knowledgeBases.delete(f.issue.context, String(f.kb.id));
    const other = f.app.auth.register({ email: 'graph-foreign@example.invalid', password: 'Independent-foreign-fixture' });
    await assert.rejects(graph.processPending(other.context, String(f.kb.id)), (e: any) => e.status === 404);
    await assert.rejects(f.app.integrations.cleanupScopedNeo4j(other.context, String(f.kb.id), key), (e: any) => e.status === 404);
    assert.equal(http.calls.length, 0);
    http.state.gate = async () => { reached(); await gate; };
    const work = graph.processPending(f.issue.context, String(f.kb.id)); void work.catch(() => {}); await waiting;
    f.app.database.run("UPDATE tenant_members SET status='revoked' WHERE tenant_id=? AND user_id=?", f.issue.context.tenantId, f.issue.context.userId!);
    release(); await assert.rejects(work, (e: any) => [401, 403].includes(e.status));
    assert.equal(pending(f)[0]!.value.status, 'pending');
  } finally { release?.(); await graph.close(); await http.close(); await f.close(); }
});

test('ordinary viewers read truthful graph readiness without administrator settings permission or secrets', async () => {
  const f = fixture();
  try {
    f.app.settings.updateIntegration(f.issue.context, 'neo4j', { enabled: true, uri: 'bolt://127.0.0.1:9', username: 'fixture', password: 'private-graph-fixture' });
    const team = f.app.database.insert('tenants', { name: 'graph-readiness-team', api_key: 'graph-readiness-fixture', status: 'active' });
    const viewer = f.app.auth.register({ email: 'graph-viewer@example.invalid', password: 'Independent-viewer-fixture' });
    f.app.database.insert('tenant_members', { user_id: viewer.context.userId, tenant_id: team.id, role: 'viewer', status: 'active' });
    const scoped = f.app.auth.authenticateAccess(viewer.credentials.access, String(team.id));
    const kb = f.app.database.insert('knowledge_bases', { tenant_id: team.id, name: 'viewer graph', indexing_strategy: { graph_enabled: true } });
    const result = f.app.graph.capabilities(scoped, String(kb.id));
    assert.equal(result.transport_available, true); assert.equal(result.state, 'model_not_configured');
    assert.deepEqual(result.neo4j, { state: 'configured', enabled: true, configured: true, connection_verified: false });
    assert.equal(JSON.stringify(result).includes('private-graph-fixture'), false);
    assert.throws(() => f.app.settings.getIntegration(scoped, 'neo4j'), (e: any) => e.status === 403);
    await assert.rejects(f.app.graph.processPending(scoped, String(kb.id)), (e: any) => e.status === 403);
  } finally { await f.close(); }
});

test('namespace cleanup cannot run before tombstone and close cancels its actual owned request', async () => {
  const f = fixture(), http = await controlledGraph(f), graph = http.service();
  let reached!: () => void; const waiting = new Promise<void>(resolve => reached = resolve); let settled = false;
  try {
    const key = graph.queueKnowledgeBaseCleanup(f.issue.context, String(f.kb.id));
    await assert.rejects(f.app.integrations.cleanupScopedNeo4j(f.issue.context, String(f.kb.id), key), (e: any) => e.code === 'graph_cleanup_source_active');
    assert.equal(http.calls.length, 0);
    await f.app.knowledge.knowledgeBases.delete(f.issue.context, String(f.kb.id));
    http.state.gate = async () => { reached(); await new Promise<void>(resolve => setTimeout(resolve, 100)); };
    const work = graph.processPending(f.issue.context, String(f.kb.id)).finally(() => settled = true); void work.catch(() => {}); await waiting;
    await graph.close(); assert.equal(settled, true); await assert.rejects(work, (e: any) => e.code === 'operation_cancelled');
    assert.equal(pending(f)[0]!.value.status, 'pending');
  } finally { await graph.close(); await http.close(); await f.close(); }
});

test('legacy unpinned active-source cleanup never guesses a new generation from equal wall-clock timestamps', async () => {
  const f = fixture(), http = await controlledGraph(f), graph = http.service();
  try {
    const d = f.app.database.insert('knowledges', { tenant_id: f.issue.context.tenantId, knowledge_base_id: f.kb.id, title: 'retained source' });
    const created = new Date().toISOString(), namespace = graphNamespace(f.issue.context.tenantId, String(f.kb.id));
    const id = `graph:${createHash('sha256').update(JSON.stringify([f.issue.context.tenantId, f.kb.id, d.id])).digest('hex')}`;
    f.app.database.insert('generic_resources', { id, tenant_id: f.issue.context.tenantId, resource_type: 'graph_document', status: 'active', data: { namespace, knowledge_base_id: f.kb.id!, knowledge_id: d.id!, generation: 'new-publication', published_at: created } });
    f.app.database.run('INSERT INTO desktop_meta(key,value) VALUES(?,?)', `knowledge.graph.pending:${randomUUID()}`, JSON.stringify({ schema_version: 1, tenant_id: f.issue.context.tenantId, knowledge_base_id: f.kb.id, knowledge_id: d.id, operation: 'update', status: 'pending', created_at: created }));
    const result = await graph.processPending(f.issue.context, String(f.kb.id));
    assert.equal(result.remaining, 1); assert.equal(http.calls.length, 0);
    assert.equal(f.app.database.read('generic_resources', id)!.status, 'active');
    assert.equal((result.results as JsonObject[])[0]!.reason, 'graph_cleanup_generation_missing');
  } finally { await graph.close(); await http.close(); await f.close(); }
});

test('invalid imported Neo4j endpoint remains a pending warning after successful local deletion', async () => {
  const f = fixture();
  try {
    f.app.database.insert('integration_configs', { name: 'neo4j', parameters: { enabled: true, uri: 'https://invalid.example.invalid', username: 'fixture', password: 'fixture' } });
    const response = await f.app.dispatch({ protocol: 1, id: randomUUID(), method: 'DELETE', path: `/api/v1/knowledge-bases/${f.kb.id}` }, { transport: 'ipc', access: f.issue.credentials.access });
    assert.equal(response.response.status, 200);
    assert.ok(f.app.database.read('knowledge_bases', String(f.kb.id))!.deleted_at);
    assert.equal(pending(f)[0]!.value.status, 'pending');
    const data = (response.response.body as JsonObject).data as JsonObject;
    assert.ok((data.warnings as JsonObject[]).some(w => w.code === 'graph_cleanup_pending'));
  } finally { await f.close(); }
});
