import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { AuthService } from '../src/auth/index.js';
import { CoreDatabase, openNativeDatabase } from '../src/storage/database.js';
import { KnowledgeService } from '../src/knowledge/index.js';
import { KnowledgeReadDomain } from '../src/knowledge/read-domain.js';
import { KnowledgeQueries } from '../src/knowledge/read-queries.js';
import { AuthReader } from '../src/auth/reader.js';
import { ReadDatabase } from '../src/storage/read-database.js';
import { readIndexState } from '../src/retrieval/index-state.js';
import { registerKnowledgeReadRoutes, type ReadRouteContext, type ReadRouteRegistrar } from '../src/knowledge/read-routes.js';
import { readDocumentStages, registerDocumentReadRoutes } from '../src/documents/stages-query.js';
import type { Json, JsonObject } from '../src/contracts.js';
import type { Row } from '../src/storage/database.js';
import type { TestContext } from 'node:test';

test('knowledge page queries preserve DTOs on native readonly SQLite without constructor DDL', () => {
  const root = mkdtempSync(join(tmpdir(), 'marlin-knowledge-read-extraction-'));
  const db = new CoreDatabase(root), auth = new AuthService(db);
  try {
    const issue = auth.register({ username: 'readonly-owner', password: 'Readonly✓Password' });
    const owner = new KnowledgeService(db, auth), kb = owner.knowledgeBases.create(issue.context, { name: '只读测试', indexing_strategy: { graph_enabled: false, wiki_enabled: false } });
    const doc = db.insert('knowledges', { tenant_id: issue.context.tenantId, knowledge_base_id: kb.id, type: 'file', title: '保持正文', parse_status: 'completed', metadata: { content: '正文😀逐字保留', workflow_status: 'failed', opaque: { keep: true } } });
    db.insert('chunks', { tenant_id: issue.context.tenantId, knowledge_base_id: kb.id, knowledge_id: doc.id, chunk_type: 'parent', content: '父块😀', seq_id: '9223372036854775806' });
    const expected = { base: owner.knowledgeBases.get(issue.context, String(kb.id)), doc: owner.get(issue.context, String(doc.id)), stats: owner.stats(issue.context, String(kb.id)), chunks: owner.listChunks(issue.context, String(doc.id)) };
    db.close();
    const sqlite = openNativeDatabase(db.path, { readonly: true, fileMustExist: true });
    sqlite.defaultSafeIntegers();
    // Retain the actual CoreDatabase codec/cache implementation; this real native
    // readonly backend exposes current constructor DDL without a fake CoreDatabase.
    Object.defineProperty(db, 'sqlite', { value: sqlite });
    const ddl: string[] = [], exec = sqlite.exec.bind(sqlite);
    sqlite.exec = sql => { ddl.push(sql); return exec(sql); };
    const queries = new KnowledgeQueries(new KnowledgeReadDomain(db, auth));
    const actual = { base: queries.knowledgeBases.get(issue.context, String(kb.id)), doc: queries.get(issue.context, String(doc.id)), stats: queries.stats(issue.context, String(kb.id)), chunks: queries.listChunks(issue.context, String(doc.id)) };
    assert.deepEqual(actual, expected);
    assert.equal(actual.doc.workflow_status, 'failed');
    assert.equal(actual.stats.completed, 0);
    assert.equal(actual.stats.failed, 1);
    assert.equal(actual.stats.chunk_count, 1);
    assert.equal(actual.chunks.items[0]!.seq_id, '9223372036854775806');
    assert.deepEqual(ddl, [], 'A readonly page constructor must not even issue IF NOT EXISTS DDL');
  } finally { db.close(); rmSync(root, { recursive: true, force: true }); }
});


function fixture(t: TestContext) {
  const root = mkdtempSync(join(tmpdir(), 'marlin-knowledge-read-scope-'));
  const db = new CoreDatabase(root), auth = new AuthService(db);
  const issue = auth.register({ username: 'query-owner', password: 'Readonly✓Password' });
  const other = auth.register({ username: 'query-other', password: 'Readonly✓OtherPassword' });
  const owner = new KnowledgeService(db, auth);
  const kb = owner.knowledgeBases.create(issue.context, { name: '原始资料', indexing_strategy: { graph_enabled: false, wiki_enabled: false } });
  const target = owner.knowledgeBases.create(issue.context, { name: '目标资料', indexing_strategy: { graph_enabled: false, wiki_enabled: false } });
  const privateKb = owner.knowledgeBases.create(other.context, { name: '另一个用户资料', indexing_strategy: { graph_enabled: false, wiki_enabled: false } });
  const reader = new ReadDatabase(db.path, root), readonlyAuth = new AuthReader(reader);
  const domain = new KnowledgeReadDomain(reader, readonlyAuth), queries = new KnowledgeQueries(domain);
  t.after(() => { reader.close(); db.close(); rmSync(root, { recursive: true, force: true }); });
  const doc = (patch: Record<string, unknown> = {}, base: JsonObject = kb) => db.insert('knowledges', {
    tenant_id: issue.context.tenantId, knowledge_base_id: base.id, type: 'file', title: '完整来源', file_name: '来源.md', file_type: 'md', source: '来源.md', parse_status: 'completed', created_at: '2026-01-01T00:00:00.000Z', updated_at: '2026-01-01T00:00:00.000Z', metadata: { content: '前😀后\n完整来源文本', source_generation: 'source-generation', opaque: { keep: true } }, ...patch,
  });
  const chunk = (source: Row, patch: Record<string, unknown> = {}) => db.insert('chunks', {
    tenant_id: source.tenant_id, knowledge_base_id: source.knowledge_base_id, knowledge_id: source.id,
    chunk_type: 'text', content: '前😀后', start_at: 0, end_at: 3, metadata: { source_range: { start: 0, end: 3 }, opaque: ['保留'] }, ...patch,
  });
  const read = <T>(work: (ctx: ReturnType<AuthReader['authenticateAccess']>) => T) => reader.snapshot(() => work(readonlyAuth.authenticateAccess(issue.credentials.access)));
  return { root, db, auth, issue, other, owner, kb, target, privateKb, reader, readonlyAuth, domain, queries, doc, chunk, read };
}

test('real readonly capabilities preserve knowledge pages, secret projection, parent and disabled counts', t => {
  const f = fixture(t);
  const tag = f.owner.createTag(f.issue.context, String(f.kb.id), { name: '标签', color: 'blue' });
  const source = f.doc({ tag_id: tag.id, storage_size: '9007199254740993', metadata: { content: '前😀后\n完整来源文本', source_generation: 'current-source', process_config: { opaque: '保留', api_key: 'fixture-secret' }, chunking_diagnostics: { selected_strategy: 'heading' } } });
  const disabled = f.doc({ title: '已停用', enable_status: 'disabled', storage_size: 2 });
  const parent = f.chunk(source, { chunk_type: 'parent', is_enabled: false, seq_id: '9223372036854775806' });
  const child = f.chunk(source, { context_parent_id: parent.id, seq_id: '9007199254740993', is_enabled: false });
  f.chunk(source, { chunk_type: 'image_ocr', seq_id: 3 });
  f.chunk(disabled, { chunk_type: 'image_caption', seq_id: 4 });
  const compare = (ctx: ReturnType<AuthReader['authenticateAccess']>) => ({
    bases: f.queries.knowledgeBases.list(ctx), base: f.queries.knowledgeBases.get(ctx, String(f.kb.id)),
    targets: f.queries.knowledgeBases.moveTargets(ctx, String(f.kb.id)),
    detail: f.queries.get(ctx, String(source.id)), batch: f.queries.batch(ctx, [String(source.id), String(disabled.id), String(source.id)]),
    list: f.queries.list(ctx, String(f.kb.id), { keyword: '完整来源', page_size: 1 }),
    global: f.queries.list(ctx, undefined, { q: '前😀后' }),
    stats: f.queries.stats(ctx, String(f.kb.id)), chunks: f.queries.listChunks(ctx, String(source.id)),
    child: f.queries.getChunk(ctx, String(child.id), String(source.id)), tags: f.queries.listTags(ctx, String(f.kb.id)), tag: f.queries.getTag(ctx, String(f.kb.id), String(tag.id)),
  });
  const before = f.db.get('SELECT total_changes() AS n')!.n, schema = f.db.all('SELECT type,name,sql FROM sqlite_schema ORDER BY type,name');
  const actual = f.read(compare);
  const expected = {
    bases: f.owner.knowledgeBases.list(f.issue.context), base: f.owner.knowledgeBases.get(f.issue.context, String(f.kb.id)),
    targets: f.owner.knowledgeBases.moveTargets(f.issue.context, String(f.kb.id)),
    detail: f.owner.get(f.issue.context, String(source.id)), batch: f.owner.batch(f.issue.context, [String(source.id), String(disabled.id), String(source.id)]),
    list: f.owner.list(f.issue.context, String(f.kb.id), { keyword: '完整来源', page_size: 1 }),
    global: f.owner.list(f.issue.context, undefined, { q: '前😀后' }),
    stats: f.owner.stats(f.issue.context, String(f.kb.id)), chunks: f.owner.listChunks(f.issue.context, String(source.id)),
    child: f.owner.getChunk(f.issue.context, String(child.id), String(source.id)), tags: f.owner.listTags(f.issue.context, String(f.kb.id)), tag: f.owner.getTag(f.issue.context, String(f.kb.id), String(tag.id)),
  };
  assert.deepEqual(actual, expected);
  assert.equal(actual.base.total_chunk_count, 4);
  assert.equal(actual.base.chunk_count, 3, 'disabled text/OCR/caption still count by existing type semantics');
  assert.equal(actual.stats.storage_size, '9007199254740995');
  assert.equal(actual.child.seq_id, '9007199254740993');
  assert.equal(actual.child.context_parent_id, parent.id);
  assert.equal(actual.child.start_at, 0); assert.equal(actual.child.end_at, 3);
  assert.equal((actual.detail.metadata as JsonObject).content, '前😀后\n完整来源文本');
  assert.equal(JSON.stringify(actual).includes('fixture-secret'), false);
  assert.equal(f.db.get('SELECT total_changes() AS n')!.n, before);
  assert.deepEqual(f.db.all('SELECT type,name,sql FROM sqlite_schema ORDER BY type,name'), schema);
});

test('readonly document filters retain current workflow state and metadata-free processing records', t => {
  const f = fixture(t);
  const failed = f.doc({ title: '当前失败', metadata: { content: '查询词', workflow_status: 'failed', source_generation: 'old-published', processing_warnings: [{ code: 'stage_failed' }, { code: 'stage_failed' }] } });
  f.doc({ title: '已中断', metadata: { workflow_status: 'interrupted' }, file_type: 'png' });
  f.doc({ title: '已取消', metadata: { workflow_status: 'cancelled' }, file_type: 'pdf' });
  f.doc({ title: '新处理中', parse_status: 'processing', metadata: { workflow_status: 'processing' }, channel: 'mobile', created_at: '2026-01-02T00:00:00.000Z' });
  const result = f.read(ctx => f.queries.list(ctx, String(f.kb.id), { parseStatus: 'failed', keyword: '查询词', limit: 1, offset: 0 }));
  assert.equal(result.total, 1); assert.equal(result.items[0]!.id, failed.id);
  assert.equal('metadata' in result.items[0]!, false);
  assert.equal(result.items[0]!.workflow_status, 'failed');
  assert.equal(result.items[0]!.source_generation, 'old-published');
  assert.deepEqual(result.items[0]!.processing_warning_codes, ['stage_failed']);
  assert.deepEqual(result.status_counts, { failed: 2, cancelled: 1, processing: 1 });
  assert.equal((result.processing_records as Json[]).length, 4);
  assert.equal(f.read(ctx => f.queries.list(ctx, String(f.kb.id), { parse_status: 'failed', file_types: 'png' })).total, 1);
  assert.equal(f.read(ctx => f.queries.list(ctx, undefined, { channel: 'mobile', startTime: '2026-01-02', endTime: '2026-01-03' })).total, 1);
  assert.throws(() => f.read(ctx => f.queries.list(ctx, String(f.kb.id), { start_time: 'invalid' })), { status: 400, code: 'invalid_time_filter' });
  assert.throws(() => f.read(ctx => f.queries.batch(ctx, Array.from({ length: 901 }, (_, i) => String(i)))), { status: 400, code: 'invalid_ids' });
  assert.deepEqual(f.read(ctx => f.queries.stats(ctx, String(f.kb.id))).status_counts, { pending: 0, processing: 1, finalizing: 0, completed: 0, failed: 2, cancelled: 1 });
});

test('readonly calls recheck authoritative membership and reject tenant, KB, child and tag scope mismatches', t => {
  const f = fixture(t), source = f.doc(), elsewhere = f.doc({}, f.target);
  const outside = f.doc({ tenant_id: f.other.context.tenantId }, f.privateKb);
  const wrongChild = f.chunk(source, { knowledge_base_id: f.target.id });
  const wrongTenant = f.chunk(source, { tenant_id: f.other.context.tenantId });
  const wrongTag = f.owner.createTag(f.issue.context, String(f.target.id), { name: '其他库标签' });
  for (const work of [
    () => f.queries.get(f.issue.context, String(outside.id)),
    () => f.queries.getChunk(f.issue.context, String(wrongChild.id), String(source.id)),
    () => f.queries.getChunk(f.issue.context, String(wrongTenant.id)),
    () => f.queries.getTag(f.issue.context, String(f.kb.id), String(wrongTag.id)),
    () => f.queries.knowledgeBases.get(f.issue.context, String(f.privateKb.id)),
  ]) assert.throws(() => f.reader.snapshot(work), { status: 404 });
  assert.equal(f.read(ctx => f.queries.listChunks(ctx, String(source.id))).total, 0);
  const valid = f.chunk(source);
  assert.throws(() => f.read(ctx => f.queries.getChunk(ctx, String(valid.id), String(elsewhere.id))), { status: 404 });
  const stale = f.readonlyAuth.authenticateAccess(f.issue.credentials.access);
  f.db.run("UPDATE tenant_members SET status='revoked' WHERE tenant_id=? AND user_id=?", f.issue.context.tenantId, f.issue.context.userId);
  assert.throws(() => f.reader.snapshot(() => f.queries.get(stale, String(source.id))), { status: 401 });
  assert.throws(() => f.read(ctx => f.queries.knowledgeBases.list(ctx)), { status: 401 });
});

test('pure index-state reader retains active tenant/KB namespace and empty/invalid scope semantics', t => {
  const f = fixture(t);
  const state = (id: string, tenant: string, kb: Json, status = 'ready') => f.db.run('INSERT INTO search_index_meta(id,tenant_id,knowledge_base_id,model_signature,dimension,generation,status,updated_at) VALUES(?,?,?,?,?,?,?,?)', id, tenant, String(kb), 'model-space', 1024, 'generation', status, '2026-01-01T00:00:00.000Z');
  state('active:own', f.issue.context.tenantId, f.kb.id!);
  state('building:own', f.issue.context.tenantId, f.kb.id!);
  state('active:wrong-namespace', f.issue.context.tenantId, f.privateKb.id!);
  state('active:private', f.other.context.tenantId, f.privateKb.id!);
  assert.deepEqual(f.reader.snapshot(() => readIndexState(f.reader, { tenantId: f.issue.context.tenantId })), [
    { id: 'active:own', tenant_id: f.issue.context.tenantId, knowledge_base_id: String(f.kb.id), model_signature: 'model-space', dimension: 1024, generation: 'generation', status: 'ready' },
  ]);
  assert.deepEqual(readIndexState(f.reader, { tenantId: f.issue.context.tenantId, knowledgeBaseIds: [] }), []);
  assert.throws(() => readIndexState(f.reader, { tenantId: 1.5 }), { code: 'unsafe_id' });
  assert.throws(() => readIndexState(f.reader, { tenantId: f.issue.context.tenantId, knowledgeBaseIds: Array.from({ length: 901 }, (_, i) => String(i)) }), { code: 'invalid_scope' });
  f.db.update('knowledge_bases', String(f.kb.id), { deleted_at: '2026-01-01T00:00:00.000Z' });
  assert.deepEqual(readIndexState(f.reader, { tenantId: f.issue.context.tenantId }), []);
  f.db.update('tenants', f.other.context.tenantId, { status: 'disabled' });
  assert.deepEqual(readIndexState(f.reader, { tenantId: f.other.context.tenantId }), []);
});

test('shared GET registry is exact, synchronous, and stage projection preserves history and parser gating', t => {
  const f = fixture(t), source = f.doc();
  const child = f.chunk(source);
  const tag = f.owner.createTag(f.issue.context, String(f.kb.id), { name: '轨迹标签' });
  f.db.insert('knowledge_processing_spans', { knowledge_id: source.id, span_id: 'attempt-2', attempt: 2, parent_span_id: 'root-2', name: 'publish_local', status: 'completed', input_data: { source: 'new' }, output_data: { count: 1 }, metadata: { keep: true }, started_at: '2026-01-02T00:00:00.000Z', finished_at: '2026-01-02T00:00:01.000Z', duration_ms: 1000 });
  f.db.insert('knowledge_processing_spans', { knowledge_id: source.id, span_id: 'attempt-1', attempt: 1, parent_span_id: 'root-1', name: 'reader', status: 'failed', error_code: 'stage_failed', error_message: 'stage_failed', started_at: '2026-01-01T00:00:00.000Z' });
  const rows: Array<{ method: 'GET'; path: string; handle: (ctx: ReadRouteContext) => Json }> = [];
  const registrar: ReadRouteRegistrar = { route: (method, path, handle) => { rows.push({ method, path, handle }); } };
  registerKnowledgeReadRoutes(registrar, f.queries);
  registerDocumentReadRoutes(registrar, f.domain, { parserEnabled: true });
  assert.deepEqual(rows.map(row => row.path), [
    '/api/v1/knowledge-bases', '/api/v1/knowledge-bases/:id', '/api/v1/knowledge-bases/:id/move-targets',
    '/api/v1/knowledge-bases/:id/knowledge', '/api/v1/knowledge-bases/:id/knowledge/stats',
    '/api/v1/knowledge/batch', '/api/v1/knowledge/search', '/api/v1/knowledge/:id',
    '/api/v1/chunks/by-id/:chunk', '/api/v1/chunks/:id', '/api/v1/chunks/:id/:chunk',
    '/api/v1/knowledge-bases/:id/tags', '/api/v1/knowledge-bases/:id/tags/:tag', '/api/v1/knowledge/:id/stages',
  ]);
  const paramsFor = (path: string) => ({ id: path.startsWith('/api/v1/knowledge-bases') ? String(f.kb.id) : String(source.id), chunk: String(child.id), tag: String(tag.id) });
  for (const row of rows) {
    assert.equal(row.method, 'GET');
    const result = f.read(auth => row.handle({ auth, params: paramsFor(row.path), query: new URLSearchParams({ ids: String(source.id) }) }));
    assert.equal(typeof (result as JsonObject)?.then, 'undefined', row.path);
  }
  const stageRoute = rows.at(-1)!;
  const result = f.read(auth => stageRoute.handle({ auth, params: { id: String(source.id) }, query: new URLSearchParams() })) as JsonObject;
  const spans = result.spans as JsonObject[];
  assert.equal(result.items, result.spans);
  assert.deepEqual(spans.map(span => span.id), ['attempt-1', 'attempt-2']);
  assert.equal(spans[0]!.error_code, 'stage_failed');
  assert.equal(spans[1]!.duration_ms, 1000);
  assert.deepEqual(readDocumentStages(f.reader, String(source.id)), { knowledge_id: source.id, spans });
  const disabled: typeof rows = [];
  registerDocumentReadRoutes({ route: (method, path, handle) => { disabled.push({ method, path, handle }); } }, f.domain, { parserEnabled: false });
  assert.throws(() => f.read(auth => disabled[0]!.handle({ auth, params: { id: String(source.id) }, query: new URLSearchParams() })), { status: 503, code: 'parser_not_configured' });
});
