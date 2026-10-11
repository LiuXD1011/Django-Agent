import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { AuthService } from '../src/auth/index.js';
import { CoreDatabase } from '../src/storage/database.js';
import { CredentialVault } from '../src/storage/credentials.js';
import { ModelConfigurationService } from '../src/settings/model-configuration.js';
import { CallScope } from '../src/integrations/network.js';
import { queryNeo4jHttp } from '../src/integrations/neo4j-http.js';

async function fixture() {
  const module = await import('../src/graph/index.js').catch(() => null);
  assert.ok(module, 'GraphService must generate and query the actual scoped graph with publication fences');
  const root = mkdtempSync(join(tmpdir(), 'marlin-graph-')), db = new CoreDatabase(root), auth = new AuthService(db);
  const owner = auth.register({ username: 'graphowner', password: 'GraphFixture✓Password' }), ctx = owner.context;
  const outsider = auth.register({ username: 'graphoutside', password: 'GraphFixture✓Password' }).context;
  const models = new ModelConfigurationService(db, auth, new CredentialVault(root));
  const kb = db.insert('knowledge_bases', { id: 'kb:a-b', tenant_id: ctx.tenantId, name: 'Graph资料', indexing_strategy: { graph_enabled: true } });
  const doc = (title = '文档甲', patch: any = {}) => db.insert('knowledges', { tenant_id: ctx.tenantId, knowledge_base_id: kb.id, title, enable_status: 'enabled', metadata: { source_generation: 'source-1' }, ...patch });
  const chunk = (d: any, content = 'Orca uses GraphRAG 的真实来源😀', patch: any = {}) => db.insert('chunks', { tenant_id: d.tenant_id, knowledge_base_id: d.knowledge_base_id, knowledge_id: d.id, content, chunk_index: 0, metadata: { provenance: { source_ref: 'page:1', page_index: 0 } }, ...patch });
  return { ...module, root, db, auth, ctx, outsider, models, kb, doc, chunk, owner, close: () => { db.close(); rmSync(root, { recursive: true, force: true }); } };
}
const denied = (work: () => unknown, status: number) => assert.throws(work, (e: any) => e.status === status);
async function servers(f: any, options: any = {}) {
  const nodes: any[] = [], relations: any[] = [], neoCalls: any[] = [], modelCalls: any[] = [];
  const server = createServer(async (req, res) => {
    assert.equal(f.db.sqlite.inTransaction, false);
    let raw = ''; for await (const part of req) raw += part;
    const body = JSON.parse(raw); res.setHeader('content-type', 'application/json');
    if (req.url?.includes('/query/v2')) {
      neoCalls.push(body); if (options.neoGate) await options.neoGate(body);
      const p = body.parameters, statement = body.statement;
      const belongs = (n: any) => n.namespace === p.namespace && n.tenant_id === p.tenant_id && n.knowledge_base_id === p.knowledge_base_id;
      let records: any[] = [];
      if (statement.includes('MARLIN_WRITE_GENERATION')) {
        nodes.push(...p.nodes); relations.push(...p.relations); records = [{ nodes: p.nodes.length, relations: p.relations.length }];
      } else if (statement.includes('MARLIN_DELETE_DOCUMENT')) {
        for (let i = nodes.length - 1; i >= 0; i--) if (belongs(nodes[i]) && nodes[i].knowledge_id === p.knowledge_id && (!p.generation || nodes[i].generation === p.generation)) nodes.splice(i, 1);
        for (let i = relations.length - 1; i >= 0; i--) if (belongs(relations[i]) && relations[i].knowledge_id === p.knowledge_id && (!p.generation || relations[i].generation === p.generation)) relations.splice(i, 1);
      } else if (statement.includes('MARLIN_READ_GENERATIONS')) {
        const active = (n: any) => belongs(n) && p.active.some((a: any) => a.knowledge_id === n.knowledge_id && a.generation === n.generation);
        records = [...nodes.filter(active).map(node => ({ node })), ...relations.filter(active).map(relation => ({ relation }))];
        if (options.poison) records.push({ node: { ...nodes[0], id: 'foreign', tenant_id: f.outsider.tenantId, name: 'tenant-secret' } });
        records = records.slice(p.offset, p.offset + p.limit);
      } else assert.fail('Only a fixed graph template may reach the transport');
      res.end(JSON.stringify({ data: { fields: ['record'], values: records.map(r => [r]) } })); return;
    }
    modelCalls.push(body); if (options.modelGate) await options.modelGate(body, modelCalls.length);
    const prompt = body.messages.at(-1).content;
    const value = options.modelReply ? await options.modelReply(body, modelCalls.length) : prompt.includes('GRAPH_ENTITIES') ? [{ chunk_key: 'c001', entities: [{ name: 'Orca', attributes: ['agent'] }, { name: 'GraphRAG', attributes: ['retrieval'] }] }]
      : prompt.includes('GRAPH_RELATIONS') ? [{ entity1: 'Orca', entity2: 'GraphRAG', relation: 'uses', strength: 8 }] : { node: [{ name: 'Orca' }], relation: [] };
    res.end(JSON.stringify({ choices: [{ message: { content: JSON.stringify(value) }, finish_reason: 'stop' }], usage: { prompt_tokens: 5, completion_tokens: 2, total_tokens: 7 } }));
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve)); const address = server.address(); assert.ok(address && typeof address !== 'string');
  const base = `http://127.0.0.1:${address.port}`;
  const config = f.models.create(f.ctx, { name: 'graph-model', type: 'KnowledgeQA', source: 'openai', parameters: { model: 'controlled', base_url: `${base}/v1`, api_key: 'controlled-key' } });
  f.db.update('knowledge_bases', f.kb.id, { summary_model_id: config.id });
  const transport = async (ctx: any, kbId: string, statement: string, parameters: any, opts: any = {}) => {
    f.auth.assertCan(ctx, opts.write ? 'document.write' : 'read'); assert.equal(kbId, parameters.knowledge_base_id); assert.equal(ctx.tenantId, parameters.tenant_id);
    const scope = new CallScope(opts); try { const result: any = await queryNeo4jHttp(scope, { url: base, username: 'controlled', password: 'controlled' }, statement, parameters); return { ...result, records: result.records.map((r: any) => r.record) }; } finally { scope.dispose(); }
  };
  const service = new f.GraphService(f.db, f.auth, f.models, undefined, { transport });
  return { service, nodes, relations, modelCalls, neoCalls, close: async () => { await service.close(); await new Promise<void>(resolve => { server.closeAllConnections(); server.close(() => resolve()); }); } };
}

test('graph JSON accepts original object/fenced/bare entity and relation shapes without flattening types', async () => {
  const f = await fixture();
  try {
    const g = f.parseGraph('```json\n[{"entity":"Orca","entity_attributes":["agent"]},{"entity1":"Orca","entity2":"GraphRAG","relation":"uses","strength":8}]\n```');
    assert.deepEqual(g.node.map((n: any) => n.name), ['Orca', 'GraphRAG']); assert.equal(g.relation[0].type, 'uses');
    const object = f.parseGraph('{"nodes":[{"name":"Orca"}],"relations":[{"source":"Orca","target":"GraphRAG","type":"uses"}]}');
    assert.equal(object.relation.length, 1);
    assert.throws(() => f.parseGraph('bad-json'), (e: any) => e.code === 'model_output_invalid');
  } finally { f.close(); }
});

test('namespace hashing keeps original IDs exact and cannot collide by punctuation or numeric precision', async () => {
  const f = await fixture();
  try {
    assert.notEqual(f.graphNamespace(f.ctx.tenantId, 'kb:a-b'), f.graphNamespace(f.ctx.tenantId, 'kb:a_b'));
    assert.notEqual(f.graphNamespace('1152921504606846976', 'kb'), f.graphNamespace('1152921504606846977', 'kb'));
    assert.equal(f.graphNamespace(f.ctx.tenantId, String(f.kb.id)), createHash('sha256').update(JSON.stringify([f.ctx.tenantId, f.kb.id])).digest('hex'));
  } finally { f.close(); }
});

test('missing graph transport or model returns explicit capability and pending, never completed', async () => {
  const f = await fixture(); const service = new f.GraphService(f.db, f.auth, f.models);
  try {
    const d = f.doc(); f.chunk(d);
    assert.equal((await service.build(f.ctx, String(f.kb.id), String(d.id))).status, 'needs_configuration');
    const g = await service.overview(f.ctx, String(f.kb.id)); assert.equal(g.state, 'not_configured'); assert.deepEqual(g.nodes, []);
    assert.equal(f.db.get('select count(*) as n from model_usage')?.n, 0);
  } finally { await service.close(); f.close(); }
});

test('actual HTTP extraction and graph Query API publish safe fixed templates, provenance and truthful usage', async () => {
  const f = await fixture(), s = await servers(f, { poison: true });
  try {
    const d = f.doc(), c = f.chunk(d, undefined, { id: '1152921504606846976' });
    const built = await s.service.build(f.ctx, String(f.kb.id), String(d.id));
    assert.equal(built.status, 'completed'); assert.equal(built.output.nodes, 2); assert.equal(built.output.relations, 1);
    const g = await s.service.overview(f.ctx, String(f.kb.id), { limit: 1 });
    assert.equal(g.nodes.length, 1); assert.equal(g.meta.total, 2); assert.equal(g.meta.truncated, true); assert.equal(JSON.stringify(g).includes('tenant-secret'), false);
    const full = await s.service.overview(f.ctx, String(f.kb.id));
    assert.equal(full.edges[0].type, 'uses'); assert.deepEqual(full.nodes[0].chunks, [c.id]);
    assert.equal(full.nodes[0].source_refs[0].source_ref, 'page:1');
    assert.deepEqual((await s.service.types(f.ctx, String(f.kb.id))).relation_types, ['uses']);
    assert.equal(f.db.get('select count(*) as n from model_usage')?.n, 2);
    assert.equal(f.db.get('select sum(total_tokens) as n from model_usage')?.n, 14);
    assert.equal(s.neoCalls[0].statement.includes(String(f.kb.id)), false);
    assert.ok(s.neoCalls.every(c => c.statement.includes('namespace') && c.statement.includes('tenant_id') && c.statement.includes('knowledge_base_id')));
    const repeated = await s.service.build(f.ctx, String(f.kb.id), String(d.id)); assert.equal(repeated.output.repeated, true); assert.equal(s.modelCalls.length, 2);
  } finally { await s.close(); f.close(); }
});

test('overview/ego/type pagination preserves exact metadata and shared contributions across document cleanup', async () => {
  const f = await fixture(), s = await servers(f);
  try {
    const a = f.doc(), b = f.doc('文档乙'); f.chunk(a); f.chunk(b); await s.service.build(f.ctx, String(f.kb.id), String(a.id)); await s.service.build(f.ctx, String(f.kb.id), String(b.id));
    const g = await s.service.overview(f.ctx, String(f.kb.id)); assert.equal(g.nodes.length, 2); assert.equal(g.nodes[0].source_refs.length, 2);
    assert.equal((await s.service.ego(f.ctx, String(f.kb.id), String(g.nodes[0].id), { depth: 3 })).nodes.length, 2);
    assert.equal((await s.service.overview(f.ctx, String(f.kb.id), { types: 'Entity', offset: 1, limit: 1 })).meta.total, 2);
    await s.service.removeDocument(f.ctx, String(f.kb.id), String(a.id));
    const after = await s.service.overview(f.ctx, String(f.kb.id)); assert.equal(after.nodes.length, 2); assert.equal(after.nodes[0].source_refs.length, 1); assert.equal(after.nodes[0].source_refs[0].knowledge_id, b.id);
    await s.service.removeDocument(f.ctx, String(f.kb.id), String(b.id)); assert.equal((await s.service.overview(f.ctx, String(f.kb.id))).nodes.length, 0);
  } finally { await s.close(); f.close(); }
});

test('deleted/disabled/moved/edited chunks and mismatched tenant children are filtered before pagination', async () => {
  const f = await fixture(), s = await servers(f);
  try {
    const d = f.doc(), c = f.chunk(d); await s.service.build(f.ctx, String(f.kb.id), String(d.id));
    await assert.rejects(s.service.overview(f.outsider, String(f.kb.id)), (e: any) => e.status === 404);
    f.db.update('chunks', c.id, { content: 'newly edited evidence' }); assert.equal((await s.service.overview(f.ctx, String(f.kb.id))).nodes.length, 0);
    await s.service.build(f.ctx, String(f.kb.id), String(d.id)); f.db.update('knowledges', d.id, { enable_status: 'disabled' }); assert.equal((await s.service.overview(f.ctx, String(f.kb.id))).nodes.length, 0);
    assert.equal((await s.service.build(f.ctx, String(f.kb.id), String(d.id))).status, 'pending');
    denied(() => s.service.capabilities(f.outsider, String(f.kb.id)), 404);
  } finally { await s.close(); f.close(); }
});

test('source change while graph stage waits prevents publication and unreferenced remote generations never reappear', async () => {
  const f = await fixture(); let release!: () => void, reached!: () => void;
  const waiting = new Promise<void>(r => reached = r), gate = new Promise<void>(r => release = r);
  const s = await servers(f, { neoGate: async (body: any) => { if (body.statement.includes('MARLIN_WRITE_GENERATION')) { reached(); await gate; } } });
  try {
    const d = f.doc(), c = f.chunk(d); const running = s.service.build(f.ctx, String(f.kb.id), String(d.id)); await waiting;
    f.db.update('chunks', c.id, { content: 'changed while remote staged' }); release();
    await assert.rejects(running, (e: any) => e.status === 409);
    assert.ok(s.nodes.length > 0); assert.equal((await s.service.overview(f.ctx, String(f.kb.id))).nodes.length, 0);
    assert.equal(f.db.get('select count(*) as n from model_usage')?.n, 2);
  } finally { release(); await s.close(); f.close(); }
});

test('owner publication closure expires immediately for an ordinary function returning Promise', async () => {
  const f = await fixture(), s = await servers(f); let late: (() => unknown) | undefined;
  try {
    const d = f.doc(); f.chunk(d);
    await assert.rejects(s.service.build(f.ctx, String(f.kb.id), String(d.id), { publish: (commit: () => unknown) => { late = commit; commit(); return Promise.resolve({}); } }), (e: any) => e.status === 409);
    assert.throws(() => late!(), (e: any) => e.status === 409);
    assert.equal((await s.service.overview(f.ctx, String(f.kb.id))).nodes.length, 0);
  } finally { await s.close(); f.close(); }
});

test('controlled model transport cancellation settles and close prevents any queued or late publication', async () => {
  const f = await fixture(); let reached!: () => void; const waiting = new Promise<void>(r => reached = r);
  const s = await servers(f, { modelGate: async () => { reached(); await new Promise<void>(r => setTimeout(r, 100)); } });
  try {
    const d = f.doc(); f.chunk(d); const running = s.service.build(f.ctx, String(f.kb.id), String(d.id)); await waiting; await s.service.close(); await assert.rejects(running);
    assert.equal(s.neoCalls.length, 1); assert.ok(s.neoCalls[0].statement.includes('MARLIN_READ_GENERATIONS'));
    assert.equal(s.neoCalls.filter(call => call.statement.includes('MARLIN_WRITE_GENERATION')).length, 0);
    assert.equal(f.db.get('select count(*) as n from generic_resources where resource_type=?', 'graph_document')?.n, 0);
    await assert.rejects(s.service.build(f.ctx, String(f.kb.id), String(d.id)));
  } finally { await s.close(); f.close(); }
});

test('bounded graph staging persists every node and relation before publishing the large generation', async () => {
  const f = await fixture(), s = await servers(f, { modelReply: async (_body: any, call: number) => call === 1
    ? [{ chunk_key: 'c001', entities: Array.from({ length: 70 }, (_, i) => ({ name: `Entity-${i}`, attributes: [] })) }]
    : Array.from({ length: 69 }, (_, i) => ({ entity1: `Entity-${i}`, entity2: `Entity-${i + 1}`, relation: 'uses', strength: 3 })) });
  try {
    const d = f.doc(); f.chunk(d); const built = await s.service.build(f.ctx, String(f.kb.id), String(d.id));
    assert.equal(built.output.nodes, 70); assert.equal(built.output.relations, 69); assert.equal(s.nodes.length, 70); assert.equal(s.relations.length, 69);
    const view = await s.service.overview(f.ctx, String(f.kb.id));
    assert.equal(view.nodes.length, 70); assert.equal(view.edges.length, 69); assert.equal(view.meta.total, 70);
    assert.ok(s.neoCalls.filter(call => call.statement.includes('MARLIN_READ_GENERATIONS')).some(call => call.parameters.offset === 128));
    assert.ok(s.neoCalls.every(call => JSON.stringify(call.parameters).length < 256 * 1024));
  } finally { await s.close(); f.close(); }
});

test('Neo4j disabled capability is checked before any potentially paid model extraction', async () => {
  const f = await fixture(), s = await servers(f), service = new f.GraphService(f.db, f.auth, f.models, undefined, { transport: async () => ({ state: 'disabled' }) });
  try {
    const d = f.doc(); f.chunk(d); const result = await service.build(f.ctx, String(f.kb.id), String(d.id));
    assert.equal(result.status, 'needs_configuration'); assert.equal(s.modelCalls.length, 0); assert.equal(f.db.get('select count(*) as n from model_usage')?.n, 0);
  } finally { await service.close(); await s.close(); f.close(); }
});

test('graph query is a scoped read for viewers and returns current source chunks with actual usage', async () => {
  const f = await fixture(), s = await servers(f);
  try {
    const team = f.db.insert('tenants', { name: 'team', api_key: 'fixture-team', status: 'active' });
    const membership = f.db.insert('tenant_members', { user_id: f.ctx.userId, tenant_id: team.id, role: 'owner', status: 'active' });
    const scoped = f.auth.authenticateAccess(f.owner.credentials.access, String(team.id));
    const base = f.db.insert('knowledge_bases', { tenant_id: team.id, name: 'team graph', indexing_strategy: { graph_enabled: true } });
    const config = f.models.create(scoped, { name: 'team-model', type: 'KnowledgeQA', source: 'openai', parameters: f.models.configuration(f.ctx, 'KnowledgeQA').parameters });
    f.db.update('knowledge_bases', base.id, { summary_model_id: config.id });
    const d = f.db.insert('knowledges', { tenant_id: team.id, knowledge_base_id: base.id, title: '共享资料', enable_status: 'enabled' });
    const c = f.db.insert('chunks', { tenant_id: team.id, knowledge_base_id: base.id, knowledge_id: d.id, content: 'Orca uses GraphRAG' });
    await s.service.build(scoped, String(base.id), String(d.id));
    f.db.update('tenant_members', membership.id, { role: 'viewer' });
    const result = await s.service.search(scoped, String(base.id), 'Orca 是什么？');
    assert.equal(result.items[0].chunk_id, c.id); assert.equal(result.items[0].match_type, 'graph');
    assert.equal(f.db.get('select count(*) as n from model_usage where tenant_id=?', String(team.id))?.n, 3);
    await assert.rejects(s.service.build(scoped, String(base.id), String(d.id)), (e: any) => e.status === 403);
  } finally { await s.close(); f.close(); }
});

test('close cancels and awaits actual graph read transport before allowing database shutdown', async () => {
  const f = await fixture(), options: any = {}, s = await servers(f, options); let reached!: () => void;
  const waiting = new Promise<void>(resolve => reached = resolve); let settled = false;
  try {
    const d = f.doc(); f.chunk(d); await s.service.build(f.ctx, String(f.kb.id), String(d.id));
    options.neoGate = async () => { reached(); await new Promise<void>(resolve => setTimeout(resolve, 100)); };
    const read = s.service.overview(f.ctx, String(f.kb.id)).finally(() => settled = true); void read.catch(() => {}); await waiting;
    await s.service.close(); assert.equal(settled, true); await assert.rejects(read);
  } finally { await s.close(); f.close(); }
});

test('dropping the owner commit cannot report a completed graph generation', async () => {
  const f = await fixture(), s = await servers(f);
  try {
    const d = f.doc(); f.chunk(d);
    await assert.rejects(s.service.build(f.ctx, String(f.kb.id), String(d.id), { publish: () => ({ status: 'completed' }) }), (e: any) => e.status === 409);
    assert.equal((await s.service.overview(f.ctx, String(f.kb.id))).nodes.length, 0);
  } finally { await s.close(); f.close(); }
});

test('Graph returns actual pipeline source_refs for every referenced text block', async () => {
  const f = await fixture(), s = await servers(f);
  try {
    const d = f.doc(), refs = [{ block_index: 2, source_ref: 'page:2', page_index: 1, canonical_start: 10, canonical_end: 20 }, { block_index: 4, source_ref: 'page:3', page_index: 2, canonical_start: 22, canonical_end: 30 }];
    const c = f.chunk(d, undefined, { metadata: { source_refs: refs } });
    await s.service.build(f.ctx, String(f.kb.id), String(d.id));
    const view = await s.service.overview(f.ctx, String(f.kb.id));
    assert.deepEqual(view.nodes[0].source_refs.map((r: any) => [r.source_ref, r.page_index, r.block_index, r.canonical_start, r.canonical_end, r.chunk_id]), refs.map(r => [r.source_ref, r.page_index, r.block_index, r.canonical_start, r.canonical_end, c.id]));
  } finally { await s.close(); f.close(); }
});

test('disabled graph query capability prevents potentially paid query entity extraction', async () => {
  const f = await fixture(), s = await servers(f), service = new f.GraphService(f.db, f.auth, f.models, undefined, { transport: async () => ({ state: 'disabled' }) });
  try {
    const result = await service.search(f.ctx, String(f.kb.id), 'Orca 是什么？');
    assert.equal(result.state, 'pending'); assert.deepEqual(result.items, []); assert.ok(result.warnings.length);
    assert.equal(s.modelCalls.length, 0); assert.equal(f.db.get('SELECT count(*) AS n FROM model_usage')?.n, 0);
  } finally { await service.close(); await s.close(); f.close(); }
});

test('Graph workflow enablement retains the original string boolean configuration contract', async () => {
  const f = await fixture(), s = await servers(f);
  try {
    const d = f.doc(); f.chunk(d); f.db.update('knowledge_bases', f.kb.id, { indexing_strategy: { graph_enabled: false } });
    const result = await s.service.build(f.ctx, String(f.kb.id), String(d.id), { processConfig: { graph_enabled: 'yes' } });
    assert.equal(result.status, 'completed'); assert.equal(s.modelCalls.length, 2);
  } finally { await s.close(); f.close(); }
});
