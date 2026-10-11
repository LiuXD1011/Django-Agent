import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { AuthService } from '../src/auth/index.js';
import { AppError } from '../src/errors.js';
import { CoreDatabase } from '../src/storage/database.js';
import { SearchIndex } from '../src/retrieval/search-index.js';
import { JobQueue } from '../src/jobs/queue.js';
import { ModelRuntime } from '../src/models/runtime.js';

const hash = (s: string) => createHash('sha256').update(s).digest('hex');
async function fixture() {
  const module = await import('../src/knowledge/index.js').catch(() => null);
  assert.ok(module, 'KnowledgeService must preserve the approved document business behavior');
  const root = mkdtempSync(join(tmpdir(), 'marlin-knowledge-'));
  const db = new CoreDatabase(root), auth = new AuthService(db), index = new SearchIndex(db), jobs = new JobQueue(db);
  const alice = auth.register({ username: 'alice', password: 'Knowledge✓Password' });
  const bob = auth.register({ username: 'bob', password: 'Knowledge✓Password' });
  const ctx = alice.context, service = new module.KnowledgeService(db, auth, index, jobs), bases = service.knowledgeBases;
  const kb = bases.create(ctx, { name: '预算资料', indexing_strategy: { graph_enabled: false, wiki_enabled: false } });
  const doc = (patch: Record<string, unknown> = {}, base = kb) => db.insert('knowledges', { tenant_id: ctx.tenantId, knowledge_base_id: base.id, type: 'file', title: '预算原始文件', source: '预算.txt', file_name: '预算.txt', file_type: 'txt', parse_status: 'completed', ...patch });
  const chunk = (d: any, patch: Record<string, unknown> = {}) => db.insert('chunks', { tenant_id: d.tenant_id, knowledge_base_id: d.knowledge_base_id, knowledge_id: d.id, content: '预算原始内容', chunk_index: 0, ...patch });
  return { ...module, root, db, auth, index, jobs, ctx, bob, service, bases, kb, doc, chunk, close: async () => { await jobs.close(); db.close(); rmSync(root, { recursive: true, force: true }); } };
}
const denied = (work: () => unknown, status: number) => assert.throws(work, (e: any) => e.status === status);
const rejected = (work: Promise<unknown>, status: number) => assert.rejects(work, (e: any) => e.status === status);
async function embeddingFixture(db: CoreDatabase) {
  let calls = 0;
  const server = createServer(async (req, res) => {
    assert.equal(db.sqlite.inTransaction, false);
    let body = ''; for await (const part of req) body += part;
    const input = JSON.parse(body).input; calls++;
    res.setHeader('content-type', 'application/json');
    res.end(JSON.stringify({ data: input.map((_: string, index: number) => ({ index, embedding: [1, 0] })), usage: { prompt_tokens: input.length, total_tokens: input.length } }));
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address(); assert.ok(address && typeof address !== 'string');
  return { binding: { signature: 'fixture:2', dimension: 2, runtime: new ModelRuntime({ id: 'fixture', name: 'fixture', source: 'openai', type: 'embedding', parameters: { model: 'fixture', dimension: 2, base_url: `http://127.0.0.1:${address.port}/v1` } }) }, calls: () => calls, close: () => new Promise<void>(resolve => { server.closeAllConnections(); server.close(() => resolve()); }) };
}

test('KB defaults, configuration-only copy, pin and original paginated query DTO', async () => {
  const f = await fixture();
  try {
    assert.ok(new f.KnowledgeError(400, 'invalid', 'Invalid') instanceof AppError);
    assert.equal(f.kb.chunking_config.child_chunk_size, 384);
    assert.deepEqual(f.kb.capabilities, { vector: true, keyword: true, wiki: false, graph: false });
    const d = f.doc(); f.chunk(d);
    const raw = f.db.read('knowledge_bases', f.kb.id)!;
    f.db.update('knowledge_bases', f.kb.id, { cos_config: { legacy: true }, faq_config: { legacy: 'retained' }, question_generation_config: { enabled: true }, storage_provider_config: { provider: 'local', api_key: 'fixture-secret' }, chunking_config: { ...raw.chunking_config as object, opaque: 'retained' } });
    const copied = f.bases.copy(f.ctx, f.kb.id);
    assert.equal(copied.task_id, ''); assert.equal(copied.knowledge_base.name, '预算资料 copy');
    assert.equal(copied.knowledge_base.knowledge_count, 0);
    const clone = f.db.read('knowledge_bases', copied.knowledge_base.id)!;
    assert.deepEqual(clone.cos_config, { legacy: true }); assert.deepEqual(clone.faq_config, { legacy: 'retained' });
    assert.equal((clone.chunking_config as any).opaque, 'retained');
    assert.equal(JSON.stringify(copied).includes('fixture-secret'), false);
    assert.equal(f.bases.pin(f.ctx, copied.knowledge_base.id, true).is_pinned, true);
    assert.equal(f.bases.list(f.ctx, { q: '预算', page_size: 1 }).items[0].id, clone.id);
    assert.equal(f.bases.list(f.ctx, { creator: 'mine' }).total, 2);
    assert.equal(f.bases.list(f.ctx, { creator: 'others' }).total, 0);
    assert.equal(f.bases.moveTargets(f.ctx, f.kb.id).items[0].id, clone.id);
    assert.equal(f.bases.get(f.ctx, f.kb.id).chunk_count, 1);
    assert.equal(f.bases.list(f.ctx, { type: 'faq' }).total, 0);
    denied(() => f.bases.create(f.ctx, { type: 'faq' }), 400);
    denied(() => f.bases.create(f.ctx, { indexing_strategy: { vector_enabled: false, keyword_enabled: false, graph_enabled: false, wiki_enabled: false } }), 400);
  } finally { await f.close(); }
});

test('strict chunk configuration writes preserve opaque JSON and backfill historical effective settings', async () => {
  const f = await fixture();
  try {
    f.db.update('knowledge_bases', f.kb.id, { chunking_config: { chunkSize: '768', opaque: { old: true } } });
    const legacy = f.bases.get(f.ctx, f.kb.id);
    assert.equal(legacy.chunking_config.chunk_size, 768); assert.equal(legacy.needs_reindex, true);
    assert.deepEqual(f.db.read('knowledge_bases', f.kb.id)?.chunking_config, { chunkSize: '768', opaque: { old: true } });
    const d = f.doc({ metadata: { process_config: { parser_engine: 'plain', chunking_config: { chunk_size: 1024 }, graph_enabled: false, other: { keep: true } }, chunking_diagnostics: { selected_strategy: 'heading' } } });
    denied(() => f.bases.update(f.ctx, f.kb.id, { chunking_config: { chunk_size: 100 } }), 400);
    const result = f.bases.update(f.ctx, f.kb.id, { chunking_config: { chunk_size: 512 }, embedding_model_id: 'new-model' });
    assert.equal(result.needs_reindex, true);
    assert.deepEqual((f.db.read('knowledge_bases', f.kb.id)?.chunking_config as any).opaque, { old: true });
    const meta = f.db.read('knowledges', d.id)?.metadata as any;
    assert.equal(meta.effective_chunking_config.chunk_size, 1024); assert.equal(meta.process_config.other.keep, true);
    assert.equal(result.last_effective_strategy, 'heading');
  } finally { await f.close(); }
});

test('authoritative ACL, personal owner filtering and inconsistent child namespaces are enforced on every call', async () => {
  const f = await fixture();
  try {
    const other = f.bases.create(f.bob.context, { name: '私有' });
    f.db.update('users', f.ctx.userId, { is_system_admin: true, can_access_all_tenants: true });
    denied(() => f.bases.get(f.ctx, other.id), 404);
    const outside = f.db.insert('knowledges', { tenant_id: f.bob.context.tenantId, knowledge_base_id: other.id, type: 'file', title: 'private', source: 'private' });
    denied(() => f.service.get(f.ctx, outside.id), 404);
    const malformed = f.doc({}, other); denied(() => f.service.get(f.ctx, malformed.id), 404);
    const d = f.doc(); const malformedChunk = f.chunk(d, { tenant_id: f.bob.context.tenantId });
    denied(() => f.service.getChunk(f.ctx, malformedChunk.id, d.id), 404);
    assert.equal(f.service.listChunks(f.ctx, d.id).total, 0);
    f.db.run("update tenant_members set status='revoked' where user_id=?", f.ctx.userId);
    denied(() => f.bases.list(f.ctx), 401);
    await rejected(f.service.delete(f.ctx, d.id), 401);
  } finally { await f.close(); }
});

test('document filters, counts, batch aliases and stats retain API semantics without leaking metadata in lists', async () => {
  const f = await fixture();
  try {
    const tag = f.service.createTag(f.ctx, f.kb.id, { name: '合同' });
    const a = f.doc({ title: '合同', tag_id: tag.id, metadata: { content: '隐藏检索词', process_config: { parser_engine: 'plain' } }, storage_size: 7 });
    const b = f.doc({ title: '处理中', parse_status: 'finalizing', file_type: 'pdf', storage_size: 9 });
    const c = f.doc({ title: '失败', parse_status: 'failed', file_type: 'png', channel: 'mobile' });
    const p = f.service.list(f.ctx, f.kb.id, { keyword: '隐藏检索词', limit: 1, offset: 0 });
    assert.equal(p.total, 1); assert.equal(p.page, 1); assert.equal(p.page_size, 1);
    assert.equal(p.items[0].id, a.id); assert.equal('metadata' in p.items[0], false);
    assert.deepEqual(p.status_counts, { completed: 1, finalizing: 1, failed: 1 }); assert.equal(p.tag_counts[tag.id], 1);
    assert.equal(p.processing_records.length, 3);
    assert.equal(f.service.list(f.ctx, f.kb.id, { parseStatus: 'failed,finalizing', file_types: 'pdf,png' }).total, 2);
    assert.equal(f.service.list(f.ctx, undefined, { channel: 'mobile' }).items[0].id, c.id);
    assert.equal(f.service.batch(f.ctx, `${a.id},${b.id},${a.id}`).items.length, 2);
    assert.equal(f.service.stats(f.ctx, f.kb.id).storage_size, 16);
    assert.equal(f.service.stats(f.ctx, f.kb.id).processing, 1);
    assert.equal(f.service.get(f.ctx, a.id).metadata.process_config.parser_engine, 'plain');
  } finally { await f.close(); }
});

test('tag CRUD scopes uniqueness and preserves existing document tag strings after deletion', async () => {
  const f = await fixture();
  try {
    const tag = f.service.createTag(f.ctx, f.kb.id, { name: '标签', color: '#123', sort_order: 2 });
    const first = f.service.createTag(f.ctx, f.kb.id, { name: '先', sort_order: 1 });
    assert.equal(f.service.listTags(f.ctx, f.kb.id).items[0].id, first.id);
    denied(() => f.service.createTag(f.ctx, f.kb.id, { name: '标签' }), 409);
    assert.equal(f.service.updateTag(f.ctx, f.kb.id, tag.id, { name: '新标签' }).name, '新标签');
    const other = f.bases.create(f.ctx, { name: '另一个' });
    denied(() => f.service.getTag(f.ctx, other.id, tag.id), 404);
    const d = f.doc(); await rejected(f.service.update(f.ctx, d.id, { tag_id: f.service.createTag(f.ctx, other.id, { name: '外部' }).id }), 404);
    await f.service.update(f.ctx, d.id, { tag_id: tag.id });
    f.service.deleteTag(f.ctx, f.kb.id, tag.id);
    assert.equal(f.service.get(f.ctx, d.id).tag_id, tag.id);
  } finally { await f.close(); }
});

test('Unicode chunk edit synchronizes real FTS and removes all old vectors with exact 60-bit IDs', async () => {
  const f = await fixture(), endpoint = await embeddingFixture(f.db);
  try {
    const d = f.doc(), c = f.chunk(d, { seq_id: '1152921504606846975' });
    const scope = { tenantId: f.ctx.tenantId, knowledgeBaseIds: [f.kb.id] };
    await f.index.rebuild(scope, endpoint.binding);
    const state = f.index.state(scope)[0]!; const table = f.index.vectorTable(state.model_signature, state.dimension, state.generation);
    assert.equal(f.db.get(`select count(*) as n from ${table}`)?.n, 1);
    const result = await f.service.updateChunk(f.ctx, d.id, c.id, { content: '修改😀中文内容', metadata: { provenance: { page: 2 } } });
    assert.equal(result.seq_id, '1152921504606846975'); assert.equal(result.content, '修改😀中文内容');
    assert.equal(f.index.keyword(scope, '预算原始内容', 10).length, 0); assert.equal(f.index.keyword(scope, '修改', 10)[0].id, c.id);
    assert.equal(f.db.get(`select count(*) as n from ${table}`)?.n, 0); assert.equal(endpoint.calls(), 1);
    assert.equal(f.index.state(scope)[0]?.status, 'needs_rebuild');
    assert.equal(f.db.read('chunks', c.id)?.content_hash, hash('修改😀中文内容'));
    assert.equal((f.service.get(f.ctx, d.id).metadata as any).graph_status, 'needs_rebuild');
  } finally { await endpoint.close(); await f.close(); }
});

test('chunk disable/delete relinks searchable siblings, removes orphan parents, preserves media sources and read-only guards', async () => {
  const f = await fixture();
  try {
    const d = f.doc(), parent = f.chunk(d, { chunk_type: 'parent_text', is_enabled: false }), container = f.chunk(d, { chunk_type: 'image_container', is_enabled: false });
    const a = f.chunk(d, { chunk_index: 1, context_parent_id: parent.id }), b = f.chunk(d, { chunk_index: 2, context_parent_id: parent.id });
    const image = f.db.insert('knowledge_images', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb.id, knowledge_id: d.id, source_type: 'page', content_hash: hash('image'), storage_path: 'media/image.png', source_ref: 'page:3' });
    const media = f.chunk(d, { chunk_index: 3, chunk_type: 'image_ocr', media_parent_id: container.id, anchor_chunk_id: a.id, image_info: { image_id: image.id, source_ref: 'page:3' }, relation_chunks: [a.id, b.id] });
    await rejected(f.service.updateChunk(f.ctx, d.id, parent.id, { content: 'no' }), 409);
    await rejected(f.service.deleteChunk(f.ctx, d.id, container.id), 409);
    await f.service.toggleChunk(f.ctx, d.id, a.id, false);
    assert.equal(f.service.getChunk(f.ctx, media.id).anchor_chunk_id, null); assert.deepEqual(f.service.getChunk(f.ctx, media.id).relation_chunks, [b.id]);
    assert.equal(f.service.getChunk(f.ctx, b.id).next_chunk_id, media.id);
    await f.service.deleteChunk(f.ctx, d.id, b.id);
    assert.equal(f.db.read('chunks', parent.id), undefined); assert.equal(f.service.getChunk(f.ctx, a.id).context_parent_id, null);
    await f.service.toggleChunk(f.ctx, d.id, media.id, false);
    assert.equal(f.db.read('chunks', container.id), undefined); assert.equal(f.service.getChunk(f.ctx, media.id).media_parent_id, null);
    assert.deepEqual(f.service.getChunk(f.ctx, media.id).image_info, { image_id: image.id, source_ref: 'page:3' });
    assert.ok(f.db.read('knowledge_images', image.id));
  } finally { await f.close(); }
});

test('document metadata changes remove disabled/title stale index content without rewriting opaque process settings', async () => {
  const f = await fixture();
  try {
    const d = f.doc({ title: '旧标题', metadata: { content: '原始文档', process_config: { parser_engine: 'plain', chunkingConfig: { strategy: 'record' }, graph_enabled: true, extractConfig: { future: true } } } });
    const c = f.chunk(d); const scope = { tenantId: f.ctx.tenantId, knowledgeBaseIds: [f.kb.id] }; f.index.indexKeyword(scope, c.id);
    await f.service.update(f.ctx, d.id, { title: '新标题', enable_status: 'disabled' });
    assert.equal(f.index.keyword(scope, '旧标题', 10).length, 0);
    await f.service.update(f.ctx, d.id, { enable_status: 'enabled' });
    assert.equal(f.index.keyword(scope, '新标题', 10)[0]?.id, c.id);
    assert.equal((f.service.get(f.ctx, d.id).metadata as any).process_config.extractConfig.future, true);
    assert.equal((f.service.get(f.ctx, d.id).metadata as any).content, '原始文档');
    await rejected(f.service.update(f.ctx, d.id, { enable_status: 'invented' }), 400);
  } finally { await f.close(); }
});

test('deletion only clears explicitly owned hashed media, preserves shared/unowned/unsafe source files and soft-deletes metadata', async () => {
  const f = await fixture();
  try {
    mkdirSync(join(f.root, 'media')); const owned = 'media/owned.txt', shared = 'media/shared.png', imported = 'media/imported.txt';
    writeFileSync(join(f.root, owned), 'owned'); writeFileSync(join(f.root, shared), 'shared'); writeFileSync(join(f.root, imported), 'original');
    const d = f.doc({ file_path: owned, file_hash: hash('owned'), metadata: { storage_owned: true } }); f.chunk(d);
    const keep = f.doc({ file_path: imported });
    f.db.insert('knowledge_images', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb.id, knowledge_id: d.id, storage_path: shared, storage_owned: true, content_hash: hash('shared'), source_type: 'page' });
    f.db.insert('knowledge_images', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb.id, knowledge_id: keep.id, storage_path: shared, content_hash: hash('shared'), source_type: 'page' });
    const result = await f.service.delete(f.ctx, d.id);
    assert.equal(result.id, d.id); assert.equal(result.task_id, ''); assert.equal(existsSync(join(f.root, owned)), false);
    assert.equal(readFileSync(join(f.root, shared), 'utf8'), 'shared'); assert.equal(readFileSync(join(f.root, imported), 'utf8'), 'original');
    assert.ok(f.db.read('knowledges', d.id)?.deleted_at); assert.equal(f.db.get('select count(*) as n from chunks where knowledge_id=?', d.id)?.n, 0);
    await f.service.delete(f.ctx, keep.id); assert.equal(existsSync(join(f.root, imported)), true);
    writeFileSync(join(f.root, 'outside.txt'), 'outside'); symlinkSync(join(f.root, 'outside.txt'), join(f.root, 'media/link.txt'));
    const symlinkDoc = f.doc({ file_path: 'media/link.txt', file_hash: hash('outside'), metadata: { storage_owned: true } });
    const warning = await f.service.delete(f.ctx, symlinkDoc.id);
    assert.equal(readFileSync(join(f.root, 'outside.txt'), 'utf8'), 'outside'); assert.ok(warning.warnings.length);
  } finally { await f.close(); }
});

test('batch deletion validates every scope before mutation and KB deletion clears derived data while retaining eval evidence as stale', async () => {
  const f = await fixture();
  try {
    const a = f.doc(), other = f.bases.create(f.bob.context, { name: '外部' });
    const b = f.db.insert('knowledges', { tenant_id: f.bob.context.tenantId, knowledge_base_id: other.id, type: 'file', title: 'outside', source: 'outside' });
    await rejected(f.service.batchDelete(f.ctx, [a.id, b.id], f.kb.id), 404); assert.equal(f.db.read('knowledges', a.id)?.deleted_at, null);
    const c = f.chunk(a); f.index.indexKeyword({ tenantId: f.ctx.tenantId, knowledgeBaseIds: [f.kb.id] }, c.id);
    f.service.createTag(f.ctx, f.kb.id, { name: 'cascade' });
    f.db.insert('wiki_pages', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb.id, slug: 'page', title: 'page' });
    f.db.insert('wiki_pending_ops', { tenant_id: f.ctx.tenantId, scope_id: f.kb.id, op: 'ingest', dedup_key: a.id });
    const report = f.db.insert('generic_resources', { tenant_id: f.ctx.tenantId, resource_type: 'rag_eval_reports', data: { requested_configuration: { source: { knowledge_base_id: f.kb.id } }, metrics: { score: 0.7 } } });
    await f.bases.delete(f.ctx, f.kb.id);
    assert.ok(f.db.read('knowledge_bases', f.kb.id)?.deleted_at); assert.ok(f.db.read('knowledges', a.id)?.deleted_at);
    for (const table of ['chunks', 'knowledge_tags', 'wiki_pages']) assert.equal(f.db.get(`select count(*) as n from ${table} where knowledge_base_id=?`, f.kb.id)?.n, 0);
    assert.equal(f.db.get('select count(*) as n from wiki_pending_ops where scope_id=?', f.kb.id)?.n, 0);
    const data = f.db.read('generic_resources', report.id)?.data as any; assert.equal(data.freshness_status, 'stale'); assert.equal(data.metrics.score, 0.7);
    assert.equal(f.db.read('knowledges', b.id)?.deleted_at, null);
  } finally { await f.close(); }
});

test('move preserves document/chunk/media/Wiki provenance, switches real index namespace and declares rebuild pending', async () => {
  const f = await fixture(), endpoint = await embeddingFixture(f.db);
  try {
    const target = f.bases.create(f.ctx, { name: '目标', indexing_strategy: { wiki_enabled: true, graph_enabled: false } });
    const d = f.doc({ file_path: 'media/source.txt', metadata: { content: '原文', process_config: { parser_engine: 'plain' } } }), c = f.chunk(d, { seq_id: '1152921504606846901', image_info: { source_ref: 'page:1' } });
    const image = f.db.insert('knowledge_images', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb.id, knowledge_id: d.id, storage_path: 'media/image.png', content_hash: hash('image'), source_type: 'page' });
    f.db.insert('wiki_pages', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb.id, slug: '源页', title: '源页', source_refs: [{ knowledge_id: d.id }], chunk_refs: [c.id], page_metadata: { contributions: { [d.id]: { doc_title: d.title, chunks: [c.id], description: '保留来源' } } } });
    const scope = { tenantId: f.ctx.tenantId, knowledgeBaseIds: [f.kb.id] }; await f.index.rebuild(scope, endpoint.binding);
    const result = await f.service.move(f.ctx, [d.id], target.id, f.kb.id);
    assert.equal(result.moved, 1); assert.equal(result.target_knowledge_base_id, target.id);
    assert.ok(result.warnings.some((w: any) => w.code === 'graph_rebuild_required'));
    assert.equal(f.service.get(f.ctx, d.id).knowledge_base_id, target.id); assert.equal(f.service.get(f.ctx, d.id).file_path, 'media/source.txt');
    assert.equal(f.db.read('knowledge_images', image.id)?.knowledge_base_id, target.id);
    assert.equal(f.service.getChunk(f.ctx, c.id).seq_id, '1152921504606846901'); assert.equal((f.service.getChunk(f.ctx, c.id).image_info as any).source_ref, 'page:1');
    assert.equal(f.index.keyword(scope, '预算', 10).length, 0);
    assert.equal(f.index.keyword({ tenantId: f.ctx.tenantId, knowledgeBaseIds: [target.id] }, '预算', 10)[0]?.id, c.id);
    const op = f.db.all('select * from wiki_pending_ops where scope_id=?', target.id)[0]!;
    assert.equal(JSON.parse(op.payload).source_pages[0].page_metadata.contributions[d.id].description, '保留来源');
    assert.equal(endpoint.calls(), 1);
    const graph = f.db.all("select value from desktop_meta where key like 'knowledge.graph.pending:%'").map(row => JSON.parse(row.value as string)).find(op => op.operation === 'move');
    assert.ok(graph, 'Graph move must persist its original namespace for recovery');
    assert.equal(graph.tenant_id, f.ctx.tenantId); assert.equal(graph.knowledge_base_id, f.kb.id); assert.equal(graph.target_knowledge_base_id, target.id); assert.equal(graph.knowledge_id, d.id);
  } finally { await endpoint.close(); await f.close(); }
});

test('editing and deleting a document cancel actual running jobs and fence their late business publication', async () => {
  const f = await fixture();
  try {
    for (const operation of ['edit', 'delete']) {
      const d = f.doc({ parse_status: 'processing' }); let ready!: () => void, release!: () => void, jobContext: any;
      const started = new Promise<void>(r => { ready = r; }), delayed = new Promise<void>(r => { release = r; });
      const kind = `process_knowledge_${operation}`;
      f.jobs.register(kind, async (ctx) => { jobContext = ctx; ready(); await delayed; ctx.publish(() => f.db.update('knowledges', d.id, { title: '迟到覆写' })); return {}; });
      const job = f.jobs.create({ scope: { tenantId: f.ctx.tenantId, userId: f.ctx.userId }, requestId: `request-${operation}`, kind, payload: { knowledge_id: d.id }, recoveryPolicy: 'manual' });
      const running = f.jobs.run(job.id); await started;
      if (operation === 'edit') await f.service.update(f.ctx, d.id, { title: '用户修改' }); else await f.service.delete(f.ctx, d.id);
      assert.equal(jobContext.signal.aborted, true); denied(() => jobContext.publish(() => f.db.update('knowledges', d.id, { title: 'late' })), 409);
      assert.equal(f.db.read('knowledges', d.id)?.parse_status, 'cancelled');
      release(); assert.equal((await running).status, 'cancelled'); assert.notEqual(f.db.read('knowledges', d.id)?.title, '迟到覆写');
    }
  } finally { await f.close(); }
});

test('viewer/editor/service permissions use persisted roles rather than caller role flags', async () => {
  const f = await fixture();
  try {
    const tenant = f.db.insert('tenants', { name: '协作', api_key: 'ephemeral-fixture-key' });
    const member = f.db.insert('tenant_members', { tenant_id: tenant.id, user_id: f.ctx.userId, role: 'viewer', status: 'active' });
    const ctx = { ...f.ctx, tenantId: String(tenant.id), role: 'owner' };
    const kb = f.db.insert('knowledge_bases', { tenant_id: tenant.id, name: '协作库' });
    assert.equal(f.bases.get(ctx, kb.id).name, '协作库'); denied(() => f.bases.update(ctx, kb.id, { name: '越权' }), 403);
    f.db.update('tenant_members', member.id as number, { role: 'editor' });
    assert.equal(f.bases.update(ctx, kb.id, { name: '编辑' }).name, '编辑'); await rejected(f.bases.delete(ctx, kb.id), 403);
    const service = f.auth.authenticateApiKey('ephemeral-fixture-key'); assert.equal(f.bases.get(service, kb.id).name, '编辑');
    denied(() => f.service.createTag(service, kb.id, { name: '越权' }), 403);
  } finally { await f.close(); }
});

test('shared Wiki retraction removes only the deleted source and moving preserves only the moved contribution', async () => {
  const f = await fixture();
  try {
    const a = f.doc({ title: '甲文档' }), b = f.doc({ title: '乙文档' }), ca = f.chunk(a, { content: '甲秘密证据' }), cb = f.chunk(b, { content: '乙保留证据' });
    const page = f.db.insert('wiki_pages', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb.id, slug: 'shared', title: '共享页', content: '甲乙混合旧内容', source_refs: [{ knowledge_id: a.id }, { knowledge_id: b.id }], chunk_refs: [ca.id, cb.id], page_metadata: { contributions: { [a.id]: { doc_title: a.title, description: '甲摘要', chunks: [ca.id] }, [b.id]: { doc_title: b.title, description: '乙摘要', chunks: [cb.id] } } } });
    const target = f.bases.create(f.ctx, { name: 'target', indexing_strategy: { wiki_enabled: true, graph_enabled: false } });
    await f.service.move(f.ctx, [a.id], target.id, f.kb.id);
    const remaining = f.db.read('wiki_pages', page.id)!;
    assert.deepEqual(Object.keys((remaining.page_metadata as any).contributions), [b.id]); assert.equal(String(remaining.content).includes('甲秘密'), false); assert.equal(String(remaining.content).includes('乙保留'), true);
    const pending = JSON.parse(f.db.all('select payload from wiki_pending_ops where scope_id=?', target.id)[0]!.payload as string);
    assert.deepEqual(Object.keys(pending.source_pages[0].page_metadata.contributions), [a.id]);
    assert.deepEqual(pending.source_pages[0].source_refs, [{ knowledge_id: a.id }]); assert.deepEqual(pending.source_pages[0].chunk_refs, [ca.id]);
    await f.service.delete(f.ctx, b.id); assert.equal(f.db.read('wiki_pages', page.id), undefined);
  } finally { await f.close(); }
});

test('old unregistered FTS rows are physically removed without deleting another namespace', async () => {
  const f = await fixture();
  try {
    const a = f.doc(), b = f.doc(), ca = f.chunk(a, { seq_id: '1152921504606846902' }), cb = f.chunk(b, { seq_id: '1152921504606846903' });
    f.db.run('insert into chunks_fts(rowid,content) values(?,?)', ca.seq_id as string, '旧未注册索引'); f.db.run('insert into chunks_fts(rowid,content) values(?,?)', cb.seq_id as string, '另一个未注册索引');
    await f.service.delete(f.ctx, a.id);
    assert.equal(f.db.get('select count(*) as n from chunks_fts where rowid=?', ca.seq_id as string)?.n, 0);
    assert.equal(f.db.get('select count(*) as n from chunks_fts where rowid=?', cb.seq_id as string)?.n, 1);
  } finally { await f.close(); }
});

test('KB cascade includes already retired document artifacts and scoped running tasks', async () => {
  const f = await fixture();
  try {
    const d = f.doc(), c = f.chunk(d), scope = { tenantId: f.ctx.tenantId, knowledgeBaseIds: [f.kb.id] }; f.index.indexKeyword(scope, c.id);
    f.db.update('knowledges', d.id, { deleted_at: new Date().toISOString() });
    const job = f.jobs.create({ scope: { tenantId: f.ctx.tenantId, userId: f.ctx.userId }, kind: 'process_knowledge', requestId: 'retired-task', payload: { knowledge_id: d.id }, recoveryPolicy: 'safe' });
    f.db.insert('knowledge_images', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb.id, knowledge_id: d.id, storage_path: '', content_hash: hash('image'), source_type: 'page' });
    await f.bases.delete(f.ctx, f.kb.id);
    assert.equal(f.db.get('select count(*) as n from chunks where knowledge_id=?', d.id)?.n, 0);
    assert.equal(f.db.get('select count(*) as n from knowledge_images where knowledge_id=?', d.id)?.n, 0);
    assert.equal(f.db.get('select count(*) as n from chunks_fts')?.n, 0);
    assert.equal(f.jobs.get(job.id, job.scope).status, 'cancelled');
  } finally { await f.close(); }
});

test('move batch duplicate conflicts are explicit and atomic rather than hidden SQLite failures', async () => {
  const f = await fixture();
  try {
    const second = f.bases.create(f.ctx, { name: 'second' }), target = f.bases.create(f.ctx, { name: 'target' });
    const a = f.doc({ file_hash: hash('same'), file_name: 'same.txt' }), b = f.doc({ file_hash: hash('same'), file_name: 'same.txt' }, second);
    await rejected(f.service.move(f.ctx, [a.id, b.id], target.id), 409);
    assert.equal(f.service.get(f.ctx, a.id).knowledge_base_id, f.kb.id); assert.equal(f.service.get(f.ctx, b.id).knowledge_base_id, second.id);
  } finally { await f.close(); }
});

test('cleanup recovery retains modified source bytes and safely retries the persisted manifest after restoration', async () => {
  const f = await fixture();
  try {
    mkdirSync(join(f.root, 'media')); const path = 'media/changed.txt'; writeFileSync(join(f.root, path), 'changed-after-plan');
    const d = f.doc({ file_path: path, file_hash: hash('original'), metadata: { storage_owned: true } });
    const result = await f.service.delete(f.ctx, d.id); assert.ok(result.warnings.some((w: any) => w.code === 'artifact_cleanup_pending'));
    assert.equal(readFileSync(join(f.root, path), 'utf8'), 'changed-after-plan');
    assert.equal(f.db.get("select count(*) as n from desktop_meta where key like 'knowledge.cleanup:%'")?.n, 1);
    f.service.recoverCleanup(f.ctx); assert.equal(readFileSync(join(f.root, path), 'utf8'), 'changed-after-plan');
    writeFileSync(join(f.root, path), 'original'); f.service.recoverCleanup(f.ctx);
    assert.equal(existsSync(join(f.root, path)), false); assert.equal(f.db.get("select count(*) as n from desktop_meta where key like 'knowledge.cleanup:%'")?.n, 0);
  } finally { await f.close(); }
});

test('backfill storage failure rolls the KB update back rather than hiding incomplete history', async () => {
  const f = await fixture();
  try {
    f.doc({ metadata: { chunking_diagnostics: { selected_strategy: 'heading' } } });
    f.db.run("CREATE TRIGGER block_backfill BEFORE UPDATE OF metadata ON knowledges BEGIN SELECT RAISE(ABORT,'fixture backfill failure'); END");
    assert.throws(() => f.bases.update(f.ctx, f.kb.id, { chunking_config: { chunk_size: 1024 } }), /fixture backfill failure/);
    assert.equal(f.bases.get(f.ctx, f.kb.id).chunking_config.chunk_size, 512);
  } finally { await f.close(); }
});

test('historical default indexing strategy still schedules real persistent Wiki pending work', async () => {
  const f = await fixture();
  try {
    f.db.update('knowledge_bases', f.kb.id, { indexing_strategy: {} }); const d = f.doc(), c = f.chunk(d);
    assert.equal(f.bases.get(f.ctx, f.kb.id).capabilities.wiki, true);
    await f.service.updateChunk(f.ctx, d.id, c.id, { content: '更新内容' });
    assert.equal(f.db.get('select count(*) as n from wiki_pending_ops where scope_id=? and dedup_key=?', f.kb.id, d.id)?.n, 1);
  } finally { await f.close(); }
});

test('clearing the document collection preserves the knowledge base and tags while retiring every document and Wiki page', async () => {
  const f = await fixture();
  try {
    const d = f.doc(); f.chunk(d); const tag = f.service.createTag(f.ctx, f.kb.id, { name: '保留标签' });
    const retired = f.doc(), retiredChunk = f.chunk(retired); f.index.indexKeyword({ tenantId: f.ctx.tenantId, knowledgeBaseIds: [f.kb.id] }, retiredChunk.id);
    f.db.update('knowledges', retired.id, { deleted_at: new Date().toISOString() });
    f.db.insert('wiki_pages', { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb.id, slug: 'manual', title: 'manual', page_type: 'manual' });
    assert.equal(typeof f.service.clear, 'function', 'The original collection DELETE must remain distinct from deleting a knowledge base');
    await f.service.clear(f.ctx, f.kb.id);
    assert.equal(f.bases.get(f.ctx, f.kb.id).knowledge_count, 0); assert.equal(f.service.listTags(f.ctx, f.kb.id).items[0].id, tag.id);
    assert.ok(f.db.read('knowledges', d.id)?.deleted_at); assert.equal(f.db.get('select count(*) as n from wiki_pages where knowledge_base_id=?', f.kb.id)?.n, 0);
    assert.equal(f.db.get('select count(*) as n from chunks where knowledge_base_id=?', f.kb.id)?.n, 0); assert.equal(f.db.get('select count(*) as n from chunks_fts')?.n, 0);
  } finally { await f.close(); }
});

test('a document changed after a cleanup plan is committed prevents the old manifest deleting its source', async () => {
  const f = await fixture();
  try {
    mkdirSync(join(f.root, 'media')); const path = 'media/replaced.txt'; writeFileSync(join(f.root, path), 'changed');
    const d = f.doc({ file_path: path, file_hash: hash('original'), metadata: { storage_owned: true } }); await f.service.delete(f.ctx, d.id);
    f.db.update('knowledges', d.id, { metadata: { storage_owned: true, version: 'new-document' } }); writeFileSync(join(f.root, path), 'original');
    f.service.recoverCleanup(f.ctx); assert.equal(readFileSync(join(f.root, path), 'utf8'), 'original');
    assert.equal(f.db.get("select count(*) as n from desktop_meta where key like 'knowledge.cleanup:%'")?.n, 1);
  } finally { await f.close(); }
});

test('KB processing statistics keep polling after local content completes until its actual workflow finishes', async () => {
  const f = await fixture();
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  try {
    const d = f.doc({ pending_subtasks_count: 1, summary_status: 'running', metadata: { content: '已完成本地正文' } });
    const c = f.chunk(d, { content: '已完成本地正文' });
    f.index.indexKeyword({ tenantId: f.ctx.tenantId, knowledgeBaseIds: [f.kb.id] }, c.id);
    let ready!: () => void;
    const started = new Promise<void>(resolve => { ready = resolve; });
    f.jobs.register('process_knowledge', async ctx => {
      ctx.publish(() => f.db.update('knowledges', d.id, { metadata: { content: '已完成本地正文', workflow_job_id: ctx.jobId, workflow_status: 'processing' } }));
      ready(); await held;
      ctx.publish(() => f.db.update('knowledges', d.id, { pending_subtasks_count: 0, summary_status: 'completed', metadata: { content: '已完成本地正文', workflow_job_id: ctx.jobId, workflow_status: 'completed' } }));
      return {};
    });
    const job = f.jobs.create({ scope: { tenantId: f.ctx.tenantId, userId: f.ctx.userId }, requestId: 'kb-local-completed-auxiliary-workflow', kind: 'process_knowledge', recoveryPolicy: 'manual', payload: { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb.id, knowledge_id: d.id } });
    f.db.update('knowledges', d.id, { metadata: { content: '已完成本地正文', workflow_job_id: job.id, workflow_status: 'pending' } });
    assert.equal(f.bases.get(f.ctx, f.kb.id).processing_count, 1, 'queued reparse with usable local content still needs polling');
    assert.equal(f.bases.list(f.ctx).items[0].is_processing, true);
    const running = f.jobs.run(job.id); await started;
    assert.equal(f.bases.get(f.ctx, f.kb.id).processing_count, 1, 'summary/Wiki may still run after parse_status completed');
    const stats = f.service.stats(f.ctx, f.kb.id);
    assert.equal(stats.processing, 1); assert.equal(stats.is_processing, true);
    assert.equal(stats.completed, 0); assert.equal(stats.status_counts.completed, 0);
    assert.equal(stats.status_counts.processing, 1, 'The displayed workflow state determines the mutually exclusive sidebar category');
    assert.equal(f.service.get(f.ctx, d.id).parse_status, 'completed');
    assert.equal(f.index.keyword({ tenantId: f.ctx.tenantId, knowledgeBaseIds: [f.kb.id] }, '已完成本地正文', 10)[0]?.id, c.id);
    release(); assert.equal((await running).status, 'completed');
    assert.equal(f.bases.get(f.ctx, f.kb.id).processing_count, 0);
    assert.equal(f.service.stats(f.ctx, f.kb.id).is_processing, false);
    assert.equal(f.service.stats(f.ctx, f.kb.id).completed, 1);
    assert.equal(f.service.stats(f.ctx, f.kb.id).status_counts.processing, 0);
    assert.equal(f.service.get(f.ctx, d.id).summary_status, 'completed');
  } finally { release(); await f.close(); }
});

test('KB polling ignores stale pending counters, terminal or expired workflows and mismatched current job scopes', async () => {
  const f = await fixture();
  try {
    const stale = f.doc({ pending_subtasks_count: 1, summary_status: 'needs_configuration', metadata: { workflow_status: 'processing' } });
    const linked = (request: string, patch: Record<string, unknown> = {}) => {
      const d = f.doc({ pending_subtasks_count: 1 });
      const job = f.jobs.create({ scope: { tenantId: f.ctx.tenantId, userId: f.ctx.userId }, requestId: request, kind: 'process_knowledge', recoveryPolicy: 'manual', payload: { tenant_id: f.ctx.tenantId, knowledge_base_id: f.kb.id, knowledge_id: d.id } });
      f.db.update('knowledges', d.id, { metadata: { workflow_job_id: job.id, workflow_status: 'processing' } });
      if (Object.keys(patch).length) f.db.run('UPDATE desktop_jobs SET payload=? WHERE id=?', JSON.stringify({ input: { ...job.payload, ...patch }, claim: null }), job.id);
      return { d, job };
    };
    const cancelled = linked('kb-cancelled'); f.jobs.cancelByRequest(cancelled.job.requestId, cancelled.job.scope);
    for (const status of ['completed', 'failed', 'interrupted']) {
      const item = linked(`kb-${status}`); f.db.run('UPDATE desktop_jobs SET status=? WHERE id=?', status, item.job.id);
    }
    linked('kb-wrong-doc', { knowledge_id: stale.id });
    linked('kb-wrong-kb', { knowledge_base_id: 'unrelated-base' });
    linked('kb-wrong-tenant', { tenant_id: f.bob.context.tenantId });
    const wrongTenant = linked('kb-wrong-job-tenant'); f.db.run('UPDATE desktop_jobs SET tenant_id=? WHERE id=?', f.bob.context.tenantId, wrongTenant.job.id);
    const wrongKind = linked('kb-wrong-kind'); f.db.run("UPDATE desktop_jobs SET kind='chat.reply' WHERE id=?", wrongKind.job.id);
    const old = linked('kb-superseded'); f.db.update('knowledges', old.d.id, { metadata: { workflow_job_id: 'replaced-workflow' } });
    const fenced = linked('kb-document-cancelled'); f.db.update('knowledges', fenced.d.id, { metadata: { workflow_job_id: fenced.job.id, workflow_status: 'cancelled' } });
    const expired = linked('kb-expired'); f.db.run("UPDATE desktop_jobs SET status='running',attempt=1,payload=? WHERE id=?", JSON.stringify({ input: expired.job.payload, claim: { ownerToken: 'expired-owner', leaseUntil: Date.now() - 1000 } }), expired.job.id);
    assert.equal(f.bases.get(f.ctx, f.kb.id).processing_count, 0);
    assert.equal(f.service.stats(f.ctx, f.kb.id).processing, 0);
    assert.equal(f.service.get(f.ctx, stale.id).pending_subtasks_count, 1, 'reads do not rewrite legacy counters');
    assert.equal(f.service.get(f.ctx, stale.id).summary_status, 'needs_configuration');
  } finally { await f.close(); }
});
