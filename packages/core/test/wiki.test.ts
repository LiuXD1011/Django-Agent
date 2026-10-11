import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { AuthService } from '../src/auth/index.js';
import { CoreDatabase } from '../src/storage/database.js';
import { CredentialVault } from '../src/storage/credentials.js';
import { ModelConfigurationService } from '../src/settings/model-configuration.js';

async function fixture() {
  const module = await import('../src/wiki/index.js').catch(() => null);
  assert.ok(module, 'WikiService must retain scoped CRUD, source contributions and actual generation');
  const root = mkdtempSync(join(tmpdir(), 'marlin-wiki-'));
  const db = new CoreDatabase(root), auth = new AuthService(db);
  const ctx = auth.register({ username: 'wikiowner', password: 'WikiFixture✓Password' }).context;
  const outsider = auth.register({ username: 'wikioutside', password: 'WikiFixture✓Password' }).context;
  const models = new ModelConfigurationService(db, auth, new CredentialVault(root));
  const kb = db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: 'Wiki资料', indexing_strategy: { wiki_enabled: true }, wiki_config: { extraction_granularity: 'standard' } });
  const service = new module.WikiService(db, auth, models);
  const doc = (title = '文档甲', patch: any = {}) => db.insert('knowledges', { tenant_id: ctx.tenantId, knowledge_base_id: kb.id, title, enable_status: 'enabled', metadata: { source_generation: 'source-1' }, ...patch });
  const chunk = (d: any, content = 'Orca 与 GraphRAG 的真实知识内容😀', patch: any = {}) => db.insert('chunks', { tenant_id: d.tenant_id, knowledge_base_id: d.knowledge_base_id, knowledge_id: d.id, content, chunk_index: 0, metadata: { provenance: { source_ref: 'page:1', page_index: 0 } }, ...patch });
  return { ...module, root, db, auth, ctx, outsider, models, kb, service, doc, chunk, close: async () => { await service.close(); db.close(); rmSync(root, { recursive: true, force: true }); } };
}
const denied = (work: () => unknown, status: number) => assert.throws(work, (e: any) => e.status === status);
async function model(f: any, reply?: (body: any, call: number) => any | Promise<any>) {
  const bodies: any[] = [];
  const server = createServer(async (req, res) => {
    assert.equal(f.db.sqlite.inTransaction, false);
    let raw = ''; for await (const part of req) raw += part;
    const body = JSON.parse(raw); bodies.push(body);
    const prompt = body.messages.at(-1).content;
    const value = reply ? await reply(body, bodies.length) : prompt.includes('WIKI_CANDIDATES') ? { entities: [{ name: 'Orca', aliases: ['Orca Agent'], description: '抽取说明' }], concepts: [] }
      : prompt.includes('WIKI_PAGES') ? { pages: [{ slug: 'entity/orca', summary: '生成摘要', content: '# Orca\n\n实际生成内容与 [[summary/example]]', referenced_chunks: [] }] }
      : '实际文档摘要';
    res.setHeader('content-type', 'application/json'); res.end(JSON.stringify({ choices: [{ message: { content: typeof value === 'string' ? value : JSON.stringify(value) }, finish_reason: 'stop' }], usage: { prompt_tokens: 7, completion_tokens: 3, total_tokens: 10 } }));
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address(); assert.ok(address && typeof address !== 'string');
  const cfg = f.models.create(f.ctx, { name: 'wiki-model', source: 'openai', type: 'KnowledgeQA', parameters: { model: 'controlled', base_url: `http://127.0.0.1:${address.port}/v1`, api_key: 'controlled-fixture-key' } });
  f.db.update('knowledge_bases', f.kb.id, { summary_model_id: cfg.id });
  return { bodies, cfg, close: () => new Promise<void>(resolve => { server.closeAllConnections(); server.close(() => resolve()); }) };
}

test('page CRUD preserves DTOs, Unicode paths, metadata and symmetric backlinks including later targets', async () => {
  const f = await fixture();
  try {
    const a = f.service.create(f.ctx, String(f.kb.id), { slug: 'entity/资料😀', title: '资料😀', content: '[[concept/预算|预算]] and [[missing]]', aliases: ['资料'] });
    const b = f.service.create(f.ctx, String(f.kb.id), { slug: 'concept/预算', title: '预算', content: '[[entity/资料😀]]', page_type: 'concept' });
    assert.deepEqual(f.service.get(f.ctx, String(f.kb.id), 'concept/预算').in_links, [a.slug]);
    assert.deepEqual(f.service.get(f.ctx, String(f.kb.id), String(a.slug)).in_links, [b.slug]);
    assert.deepEqual(a.metadata, a.page_metadata);
    assert.ok(a.folder_id); assert.equal(a.version, 1);
    const changed = f.service.update(f.ctx, String(f.kb.id), String(a.slug), { content: 'changed' });
    assert.equal(changed.version, 2); assert.deepEqual(f.service.get(f.ctx, String(f.kb.id), String(b.slug)).in_links, []);
    f.service.delete(f.ctx, String(f.kb.id), String(a.slug));
    denied(() => f.service.get(f.ctx, String(f.kb.id), String(a.slug)), 404);
    assert.equal(f.service.get(f.ctx, String(f.kb.id), String(b.slug)).content, 'entity/资料😀');
    assert.equal(f.service.list(f.ctx, String(f.kb.id)).items.length, 1);
  } finally { await f.close(); }
});

test('every collection, child row and folder reference is tenant and KB scoped', async () => {
  const f = await fixture();
  try {
    const other = f.db.insert('knowledge_bases', { tenant_id: f.ctx.tenantId, name: 'other' });
    const foreign = f.db.insert('wiki_folders', { tenant_id: f.ctx.tenantId, knowledge_base_id: other.id, name: 'other' });
    f.db.insert('wiki_pages', { tenant_id: f.outsider.tenantId, knowledge_base_id: f.kb.id, slug: 'poison', title: 'secret' });
    for (const work of [() => f.service.list(f.outsider, String(f.kb.id)), () => f.service.create(f.outsider, String(f.kb.id), { title: 'bad' })]) denied(work, 404);
    denied(() => f.service.create(f.ctx, String(f.kb.id), { title: 'bad', folder_id: foreign.id }), 404);
    const local = f.service.create(f.ctx, String(f.kb.id), { title: 'local', content: 'local' });
    denied(() => f.service.get(f.ctx, String(f.kb.id), 'poison'), 404);
    assert.equal(f.service.search(f.ctx, String(f.kb.id), { q: 'secret' }).items.length, 0);
    assert.equal(f.service.graph(f.ctx, String(f.kb.id)).nodes.length, 1);
    denied(() => f.service.update(f.ctx, String(f.kb.id), String(local.slug), { source_refs: [{ knowledge_id: 'foreign' }] }), 400);
    f.db.update('device_sessions', f.ctx.deviceId, { revoked_at: new Date().toISOString() });
    denied(() => f.service.list(f.ctx, String(f.kb.id)), 401);
  } finally { await f.close(); }
});

test('folders retain hierarchy, reject cycles, and deletion reparents local children only', async () => {
  const f = await fixture();
  try {
    const a = f.service.createFolder(f.ctx, String(f.kb.id), { name: 'A' });
    const b = f.service.createFolder(f.ctx, String(f.kb.id), { name: 'B', parent_id: a.id });
    const p = f.service.create(f.ctx, String(f.kb.id), { title: 'p', folder_id: b.id });
    assert.equal(b.path, 'A/B'); assert.equal(b.depth, 1);
    denied(() => f.service.updateFolder(f.ctx, String(f.kb.id), String(a.id), { parent_id: b.id }), 409);
    f.service.updateFolder(f.ctx, String(f.kb.id), String(a.id), { name: 'new' });
    assert.equal(f.service.getFolder(f.ctx, String(f.kb.id), String(b.id)).path, 'new/B');
    f.service.deleteFolder(f.ctx, String(f.kb.id), String(b.id));
    assert.equal(f.service.get(f.ctx, String(f.kb.id), String(p.slug)).folder_id, a.id);
  } finally { await f.close(); }
});

test('index/search pagination, overview/ego/type filters report exact totals and truncation', async () => {
  const f = await fixture();
  try {
    f.service.create(f.ctx, String(f.kb.id), { slug: 'a', title: '甲', content: '[[b]] [[c]]', page_type: 'entity' });
    f.service.create(f.ctx, String(f.kb.id), { slug: 'b', title: '乙', content: '预算中文', page_type: 'concept' });
    f.service.create(f.ctx, String(f.kb.id), { slug: 'c', title: '丙', page_type: 'summary' });
    f.service.create(f.ctx, String(f.kb.id), { slug: 'index', title: 'Hidden', page_type: 'index' });
    assert.equal(f.service.list(f.ctx, String(f.kb.id), { page_size: 1, page: 2 }).total, 3);
    assert.equal(f.service.index(f.ctx, String(f.kb.id)).groups.length, 3);
    assert.equal(f.service.search(f.ctx, String(f.kb.id), { query: '预算' }).pages.length, 1);
    const g = f.service.graph(f.ctx, String(f.kb.id), { mode: 'overview', limit: 1 });
    assert.equal(g.nodes[0].id, 'a'); assert.equal(g.meta.total, 3); assert.equal(g.meta.truncated, true);
    const ego = f.service.graph(f.ctx, String(f.kb.id), { mode: 'ego', center: 'a', types: 'concept', depth: 3 });
    assert.deepEqual(ego.nodes.map((n: any) => n.id).sort(), ['a', 'b']); assert.equal(ego.edges.length, 1);
    assert.equal(f.service.graph(f.ctx, String(f.kb.id), { mode: 'ego', center: 'missing' }).nodes.length, 0);
    denied(() => f.service.graph(f.ctx, String(f.kb.id), { mode: 'unknown' }), 400);
    denied(() => f.service.graph(f.ctx, String(f.kb.id), { mode: 'ego' }), 400);
    assert.equal(f.service.stats(f.ctx, String(f.kb.id)).total_links, 2);
    assert.ok(f.service.lint(f.ctx, String(f.kb.id)).issues.length === 0);
  } finally { await f.close(); }
});

test('unconfigured generation stays pending with local chunks and existing pages intact', async () => {
  const f = await fixture();
  try {
    const d = f.doc(); f.chunk(d); const p = f.service.create(f.ctx, String(f.kb.id), { title: 'manual', content: 'kept' });
    const r = await f.service.ingest(f.ctx, String(f.kb.id), String(d.id));
    assert.equal(r.status, 'needs_configuration'); assert.ok(r.warnings.length);
    assert.equal(f.service.get(f.ctx, String(f.kb.id), String(p.slug)).content, 'kept');
    assert.equal(f.db.get('select count(*) as n from wiki_pending_ops')?.n, 1);
    assert.equal(f.db.get('select count(*) as n from model_usage')?.n, 0);
  } finally { await f.close(); }
});

test('actual model mapping/generation/summary audit once, shared contributions survive removal and repeats', async () => {
  const f = await fixture(), m = await model(f);
  try {
    const a = f.doc('文档甲'), b = f.doc('文档乙'), ca = f.chunk(a), cb = f.chunk(b, 'Orca 的另外证据');
    assert.equal((await f.service.ingest(f.ctx, String(f.kb.id), String(a.id))).status, 'completed');
    assert.equal((await f.service.ingest(f.ctx, String(f.kb.id), String(b.id))).status, 'completed');
    let p = f.service.get(f.ctx, String(f.kb.id), 'entity/orca');
    assert.deepEqual(p.source_refs.map((s: any) => s.knowledge_id).sort(), [a.id, b.id].sort());
    assert.deepEqual(p.chunk_refs.sort(), [ca.id, cb.id].sort());
    assert.ok(p.content.includes('实际生成内容')); assert.equal(f.db.get('select count(*) as n from model_usage')?.n, 6);
    assert.ok(m.bodies[4].messages.at(-1).content.includes('文档甲'));
    const again = await f.service.ingest(f.ctx, String(f.kb.id), String(b.id));
    assert.equal(again.output.repeated, true); assert.equal(m.bodies.length, 6);
    f.service.removeDocument(f.ctx, String(f.kb.id), String(a.id));
    p = f.service.get(f.ctx, String(f.kb.id), 'entity/orca');
    assert.deepEqual(p.source_refs.map((s: any) => s.knowledge_id), [b.id]); assert.deepEqual(p.chunk_refs, [cb.id]);
    assert.equal(JSON.stringify(p).includes(String(ca.id)), false);
    f.service.removeDocument(f.ctx, String(f.kb.id), String(b.id));
    denied(() => f.service.get(f.ctx, String(f.kb.id), 'entity/orca'), 404);
    assert.ok(f.service.log(f.ctx, String(f.kb.id)).items.length >= 4);
    assert.equal(f.db.sqlite.pragma('foreign_key_check').length, 0);
  } finally { await m.close(); await f.close(); }
});

test('manual edits made while generation awaits HTTP fence publication without losing actual usage', async () => {
  const f = await fixture(); let release!: () => void, reached!: () => void;
  const waiting = new Promise<void>(r => reached = r), gate = new Promise<void>(r => release = r);
  const m = await model(f, async (_body, call) => { if (call === 1) { reached(); await gate; } return call === 1 ? { entities: [{ name: 'Orca' }] } : call === 2 ? { pages: [{ slug: 'entity/orca', content: 'late-content' }] } : 'summary'; });
  try {
    const d = f.doc(); f.chunk(d); f.service.create(f.ctx, String(f.kb.id), { slug: 'entity/orca', title: 'Orca', content: 'original' });
    const running = f.service.ingest(f.ctx, String(f.kb.id), String(d.id)); await waiting;
    f.service.update(f.ctx, String(f.kb.id), 'entity/orca', { content: 'user edit' }); release();
    await assert.rejects(running, (e: any) => e.status === 409);
    assert.equal(f.service.get(f.ctx, String(f.kb.id), 'entity/orca').content, 'user edit');
    assert.equal(f.db.get('select count(*) as n from model_usage')?.n, 3);
  } finally { release(); await m.close(); await f.close(); }
});

test('source generation, scoped citation IDs, disabled source and cancellation prevent late or foreign publication', async () => {
  const f = await fixture(); let release!: () => void, reached!: () => void;
  const waiting = new Promise<void>(r => reached = r), gate = new Promise<void>(r => release = r);
  const m = await model(f, async (_body, call) => { if (call === 1) { reached(); await gate; } return call === 1 ? { entities: [{ name: 'Orca' }] } : call === 2 ? { pages: [{ slug: 'entity/orca', content: 'bad citations', referenced_chunks: ['foreign', '1152921504606846977'] }] } : 'summary'; });
  try {
    const d = f.doc(); f.chunk(d, undefined, { id: '1152921504606846976' });
    const running = f.service.ingest(f.ctx, String(f.kb.id), String(d.id)); await waiting;
    f.db.update('knowledges', d.id, { metadata: { source_generation: 'source-2' } }); release();
    await assert.rejects(running, (e: any) => e.status === 409);
    assert.equal(f.service.list(f.ctx, String(f.kb.id)).items.length, 0);
    f.db.update('knowledges', d.id, { enable_status: 'disabled' });
    assert.equal((await f.service.ingest(f.ctx, String(f.kb.id), String(d.id))).status, 'pending');
    const controller = new AbortController(); controller.abort();
    await assert.rejects(f.service.ingest(f.ctx, String(f.kb.id), String(d.id), { signal: controller.signal }));
  } finally { release(); await m.close(); await f.close(); }
});

test('cross links protect fenced code, inline code, Markdown links, images and longer aliases', async () => {
  const f = await fixture();
  try {
    const text = '# Orca Agent\nOrca Agent and Orca\n`Orca` [Orca](https://example.test) ![Orca](x.png)\n~~~\nOrca\n~~~';
    const linked = f.linkify(text, [{ slug: 'a', title: 'Orca Agent', aliases: [] }, { slug: 'b', title: 'Orca', aliases: [] }], 'current');
    assert.ok(linked.includes('[[a|Orca Agent]]')); assert.ok(linked.includes('[[b|Orca]]'));
    assert.ok(linked.includes('# Orca Agent')); assert.ok(linked.includes('`Orca` [Orca](https://example.test) ![Orca](x.png)'));
    assert.ok(linked.endsWith('~~~\nOrca\n~~~')); assert.equal(linked.includes('[[a|[[b|'), false);
  } finally { await f.close(); }
});

test('retracting a shared document removes its merged prose from both content and contribution metadata', async () => {
  const f = await fixture(), m = await model(f, async (_body, call) => call % 3 === 1 ? { entities: [{ name: 'Orca', description: call === 1 ? '甲文档贡献' : '乙文档贡献' }] }
    : call % 3 === 2 ? { pages: [{ slug: 'entity/orca', summary: '共享摘要', content: '# Orca\nSECRET_FROM_RETRACTED_DOCUMENT_A 与当前乙文档内容' }] } : '文档摘要');
  try {
    const a = f.doc('甲'), b = f.doc('乙'); f.chunk(a, 'Orca SECRET_FROM_RETRACTED_DOCUMENT_A'); f.chunk(b, 'Orca 当前乙文档内容');
    await f.service.ingest(f.ctx, String(f.kb.id), String(a.id)); await f.service.ingest(f.ctx, String(f.kb.id), String(b.id));
    f.service.removeDocument(f.ctx, String(f.kb.id), String(a.id));
    const page = f.service.get(f.ctx, String(f.kb.id), 'entity/orca');
    assert.equal(JSON.stringify(page).includes('SECRET_FROM_RETRACTED_DOCUMENT_A'), false);
    assert.ok(String(page.content).includes('当前乙文档内容')); assert.ok(String(page.content).includes('乙文档贡献'));
  } finally { await m.close(); await f.close(); }
});

test('Wiki owner publication rejects delayed Promise commits and rolls back synchronous writes', async () => {
  const f = await fixture(), m = await model(f); let late!: () => unknown;
  try {
    const d = f.doc(); f.chunk(d);
    await assert.rejects(f.service.ingest(f.ctx, String(f.kb.id), String(d.id), { publish: (commit: () => unknown) => { late = commit; commit(); return Promise.resolve({}); } }), (e: any) => e.status === 409);
    assert.throws(() => late(), (e: any) => e.status === 409); assert.equal(f.service.list(f.ctx, String(f.kb.id)).items.length, 0);
    assert.equal(f.db.get('select count(*) as n from model_usage')?.n, 3);
  } finally { await m.close(); await f.close(); }
});

test('unknown model outcome remains a manual pending operation and is not replayed by processPending', async () => {
  const f = await fixture(), m = await model(f, async () => { await new Promise<void>(resolve => setTimeout(resolve, 100)); return { entities: [] }; });
  try {
    f.models.update(f.ctx, String(m.cfg.id), { parameters: { timeoutMs: 20 } });
    const d = f.doc(); f.chunk(d);
    await assert.rejects(f.service.ingest(f.ctx, String(f.kb.id), String(d.id)), (e: any) => e.resultUnknown === true);
    const calls = m.bodies.length; const result = await f.service.processPending(f.ctx, String(f.kb.id));
    assert.equal(m.bodies.length, calls); assert.equal(result.results[0].status, 'manual_required');
    assert.equal(f.db.get('select count(*) as n from model_usage')?.n, 1);
  } finally { await m.close(); await f.close(); }
});

test('original page collection returns all pages, explicit pagination and stats count beyond graph display caps', async () => {
  const f = await fixture();
  try {
    f.db.transaction(() => { for (let i = 0; i < 2150; i++) f.db.insert('wiki_pages', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb.id, slug: `large-${i}`, title: `Page ${i}`, content: i === 0 ? '[[large-2149]]' : '', out_links: i === 0 ? ['large-2149'] : [], in_links: i === 2149 ? ['large-0'] : [] }); });
    assert.equal(f.service.list(f.ctx, String(f.kb.id)).items.length, 2150);
    const second = f.service.list(f.ctx, String(f.kb.id), { page: 2 });
    assert.equal(second.items.length, 50); assert.equal(second.page, 2); assert.equal(second.page_size, 50);
    assert.equal(f.service.list(f.ctx, String(f.kb.id), { page_size: 200, page: 2 }).items.length, 200);
    assert.equal(f.service.stats(f.ctx, String(f.kb.id)).total_links, 1); assert.equal(f.service.stats(f.ctx, String(f.kb.id)).orphan_count, 2148);
    const g = f.service.graph(f.ctx, String(f.kb.id), { limit: 1 }); assert.equal(g.meta.total, 2150); assert.equal(g.meta.truncated, true);
  } finally { await f.close(); }
});

test('dropping the owner commit cannot report a completed Wiki generation', async () => {
  const f = await fixture(), m = await model(f);
  try {
    const d = f.doc(); f.chunk(d);
    await assert.rejects(f.service.ingest(f.ctx, String(f.kb.id), String(d.id), { publish: () => ({ status: 'completed' }) }), (e: any) => e.status === 409);
    assert.equal(f.service.list(f.ctx, String(f.kb.id)).items.length, 0);
  } finally { await m.close(); await f.close(); }
});

test('Wiki receipt includes model and generation configuration and explicit workflow enablement', async () => {
  const f = await fixture(), m = await model(f);
  try {
    const d = f.doc(); f.chunk(d);
    assert.equal((await f.service.ingest(f.ctx, String(f.kb.id), String(d.id))).status, 'completed');
    assert.equal(m.bodies.length, 3);
    f.models.update(f.ctx, String(m.cfg.id), { parameters: { model: 'changed-controlled' } });
    const rebuilt = await f.service.ingest(f.ctx, String(f.kb.id), String(d.id));
    assert.equal(rebuilt.output.repeated, false); assert.equal(m.bodies.length, 6);
    f.db.update('knowledge_bases', f.kb.id, { indexing_strategy: { wiki_enabled: false } });
    f.db.update('chunks', f.db.get('SELECT id FROM chunks WHERE knowledge_id=?', d.id)!.id, { content: '更新后的文档内容' });
    const enabled = await f.service.ingest(f.ctx, String(f.kb.id), String(d.id), { processConfig: { wiki_enabled: 'yes' } });
    assert.equal(enabled.status, 'completed'); assert.equal(m.bodies.length, 9);
  } finally { await m.close(); await f.close(); }
});

test('folder explicit path and depth survive CRUD while affected descendants and pages remain consistent', async () => {
  const f = await fixture();
  try {
    const a = f.service.createFolder(f.ctx, String(f.kb.id), { name: 'A', path: '文库/专题', depth: 2 });
    assert.equal(a.path, '文库/专题'); assert.equal(a.depth, 2);
    const b = f.service.createFolder(f.ctx, String(f.kb.id), { name: 'B', parent_id: a.id });
    const p = f.service.create(f.ctx, String(f.kb.id), { title: 'p', folder_id: b.id });
    const changed = f.service.updateFolder(f.ctx, String(f.kb.id), String(a.id), { path: '文库/改名', depth: 3 });
    assert.equal(changed.path, '文库/改名'); assert.equal(changed.depth, 3);
    const reordered = f.service.updateFolder(f.ctx, String(f.kb.id), String(a.id), { sort_order: 2 });
    assert.equal(reordered.path, '文库/改名'); assert.equal(reordered.depth, 3);
    assert.equal(f.service.getFolder(f.ctx, String(f.kb.id), String(b.id)).path, '文库/改名/B');
    assert.equal(f.service.get(f.ctx, String(f.kb.id), String(p.slug)).depth, 5);
  } finally { await f.close(); }
});

test('Wiki preserves actual pipeline source_refs across multiple parser blocks', async () => {
  const f = await fixture(), m = await model(f);
  try {
    const d = f.doc(), refs = [{ block_index: 2, source_ref: 'page:2', page_index: 1, canonical_start: 10, canonical_end: 20 }, { block_index: 4, source_ref: 'page:3', page_index: 2, canonical_start: 22, canonical_end: 30 }];
    f.chunk(d, undefined, { metadata: { source_refs: refs } });
    await f.service.ingest(f.ctx, String(f.kb.id), String(d.id));
    const page = f.service.get(f.ctx, String(f.kb.id), 'entity/orca');
    assert.deepEqual((page.page_metadata as any).contributions[String(d.id)].source_refs, refs);
  } finally { await m.close(); await f.close(); }
});

test('Wiki log returns valid JSON fields and preserves original audit details', async () => {
  const f = await fixture();
  try {
    f.db.insert('wiki_log_entries', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb.id, action: 'ingest', details: { source_generation: 'fixture-generation' } });
    const item = f.service.log(f.ctx, String(f.kb.id)).items[0];
    assert.ok(Object.values(item).every(value => value !== undefined));
    assert.deepEqual(item.details, { source_generation: 'fixture-generation' });
  } finally { await f.close(); }
});
