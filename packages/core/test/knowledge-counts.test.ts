import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test, { type TestContext } from 'node:test';
import { AuthService } from '../src/auth/index.js';
import { defaultChunking, searchableTypes } from '../src/knowledge/config.js';
import { KnowledgeDomain } from '../src/knowledge/domain.js';
import { KnowledgeService } from '../src/knowledge/index.js';
import { SearchIndex } from '../src/retrieval/search-index.js';
import { CoreDatabase, type Row } from '../src/storage/database.js';

function fixture(t: TestContext) {
  const root = mkdtempSync(join(tmpdir(), 'marlin-knowledge-counts-'));
  const db = new CoreDatabase(root);
  t.after(() => { db.close(); rmSync(root, { recursive: true, force: true }); });
  const auth = new AuthService(db);
  const ctx = auth.register({ username: 'count-owner', password: 'CountsFixture✓Password' }).context;
  const other = auth.register({ username: 'count-other', password: 'OtherCountsFixture✓Password' }).context;
  const index = new SearchIndex(db), domain = new KnowledgeDomain(db, auth, index), service = new KnowledgeService(db, auth, index);
  const kb = db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: '统计来源', chunking_config: defaultChunking });
  const otherKb = db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: '同租户另一个库' });
  const privateKb = db.insert('knowledge_bases', { tenant_id: other.tenantId, name: '外租户库' });
  const retiredKb = db.insert('knowledge_bases', { tenant_id: ctx.tenantId, name: '已删库', deleted_at: '2026-01-01T00:00:00.000Z' });
  const doc = (base: Row = kb, patch: Record<string, unknown> = {}) => db.insert('knowledges', {
    tenant_id: base.tenant_id, knowledge_base_id: base.id, title: '计数文档', parse_status: 'completed', updated_at: '2026-01-01T00:00:00.000Z', ...patch,
  });
  const chunk = (source: Row, patch: Record<string, unknown> = {}) => db.insert('chunks', {
    tenant_id: source.tenant_id, knowledge_base_id: source.knowledge_base_id, knowledge_id: source.id,
    content: '中文😀正文只用于真实存储，统计不需要读取它。', metadata: { legacy: { provenance: ['保留元数据'] }, source_generation: 'old-chunk-generation' }, ...patch,
  });
  const current = doc(kb, { storage_size: 7, processed_at: '2026-01-09T00:00:00.000Z', metadata: {
    content: '原文保留', source_generation: 'current-generation', chunking_diagnostics: { selected_strategy: 'heading' }, effective_chunking_config: { ...defaultChunking, chunk_size: 768 },
  } });
  const disabled = doc(kb, { enable_status: 'disabled', storage_size: 9, processed_at: '2026-01-08T00:00:00.000Z', metadata: {} });
  const pending = doc(kb, { parse_status: 'pending', metadata: {} });
  const parent = chunk(current, { chunk_type: 'parent', is_enabled: false });
  const text = chunk(current, { chunk_type: 'text' });
  chunk(current, { chunk_type: 'image_ocr', is_enabled: false });
  chunk(current, { chunk_type: 'image_caption' });
  chunk(current, { chunk_type: 'table' });
  chunk(disabled, { chunk_type: 'parent', is_enabled: false });
  chunk(disabled, { chunk_type: 'text', is_enabled: false });
  chunk(disabled, { chunk_type: 'image_caption', is_enabled: false });
  chunk(disabled, { chunk_type: 'json_record', is_enabled: false });
  chunk(pending, { chunk_type: 'text' });
  chunk(current, { chunk_type: 'text', deleted_at: '2026-01-01T00:00:00.000Z' });
  chunk(doc(kb, { deleted_at: '2026-01-01T00:00:00.000Z' }));
  chunk(doc(otherKb));
  chunk(doc(privateKb));
  chunk(doc(retiredKb));
  chunk(current, { tenant_id: other.tenantId });
  chunk(current, { knowledge_base_id: otherKb.id });
  chunk(doc(privateKb), { tenant_id: ctx.tenantId, knowledge_base_id: kb.id });
  chunk(doc(kb, { tenant_id: other.tenantId }), { tenant_id: ctx.tenantId });
  const legacyChunks = domain.docs(ctx, String(kb.id)).flatMap(d => domain.chunks(ctx, d));
  assert.equal(legacyChunks.length, 10, 'The original scoped row set includes disabled records and all types');
  assert.equal(legacyChunks.filter(c => searchableTypes.has(String(c.chunk_type))).length, 6);
  return { db, auth, ctx, other, domain, service, kb, otherKb, privateKb, retiredKb, current, parent, text, doc, chunk };
}

function observeChunkHydration(t: TestContext, db: CoreDatabase) {
  const original = db.read.bind(db);
  let rows = 0;
  t.mock.method(db, 'read', (name: string, id: Parameters<CoreDatabase['read']>[1]) => {
    const row = original(name, id);
    if (name === 'chunks' && row) rows++;
    return row;
  });
  return () => rows;
}

test('knowledge-base counters preserve all legacy rows without hydrating chunk正文 or metadata', t => {
  const f = fixture(t), reads = observeChunkHydration(t, f.db);
  const result = f.service.knowledgeBases.get(f.ctx, String(f.kb.id));
  assert.equal(result.chunk_count, 6);
  assert.equal(result.total_chunk_count, 10);
  assert.equal(result.knowledge_count, 3);
  assert.equal(result.processing_count, 1);
  assert.equal(result.is_processing, true);
  assert.equal(result.needs_reindex, true);
  assert.equal(result.last_effective_strategy, 'heading');
  assert.deepEqual(result.chunking_config, defaultChunking);
  assert.equal(reads(), 0, 'Counter-only KB reads must not load complete chunks.content/metadata');
});

test('document statistics count parent and nonsearchable types without hydrating chunk正文 or metadata', t => {
  const f = fixture(t), reads = observeChunkHydration(t, f.db);
  const result = f.service.stats(f.ctx, String(f.kb.id));
  assert.equal(result.chunk_count, 10, 'stats.chunk_count is the legacy total, not enabled or searchable-only count');
  assert.equal(result.document_count, 3);
  assert.equal(result.storage_size, 16);
  assert.equal(result.completed, 2);
  assert.equal(result.pending, 1);
  assert.equal(result.processing, 1);
  assert.deepEqual(result.status_counts, { pending: 1, processing: 0, finalizing: 0, completed: 2, failed: 0, cancelled: 0 });
  assert.equal(reads(), 0, 'Counter-only stats reads must not load complete chunks.content/metadata');
});

test('empty and separately scoped knowledge bases keep exact zero/own-row counts', t => {
  const f = fixture(t), empty = f.db.insert('knowledge_bases', { tenant_id: f.ctx.tenantId, name: '空库' });
  const result = f.service.knowledgeBases.get(f.ctx, String(empty.id));
  assert.equal(result.chunk_count, 0); assert.equal(result.total_chunk_count, 0);
  assert.equal(f.service.stats(f.ctx, String(empty.id)).chunk_count, 0);
  assert.equal(f.service.knowledgeBases.get(f.ctx, String(f.otherKb.id)).total_chunk_count, 1);
  assert.equal(f.service.stats(f.other, String(f.privateKb.id)).chunk_count, 1);
});

test('counter reads reflect soft deletes and new rows while disabled flags preserve legacy totals', t => {
  const f = fixture(t), id = String(f.kb.id);
  f.db.update('chunks', String(f.text.id), { is_enabled: false });
  assert.equal(f.service.knowledgeBases.get(f.ctx, id).chunk_count, 6);
  f.db.update('chunks', String(f.parent.id), { deleted_at: '2026-01-01T00:00:00.000Z' });
  assert.equal(f.service.knowledgeBases.get(f.ctx, id).total_chunk_count, 9);
  assert.equal(f.service.knowledgeBases.get(f.ctx, id).chunk_count, 6);
  f.chunk(f.current, { chunk_type: 'text', is_enabled: false });
  assert.equal(f.service.stats(f.ctx, id).chunk_count, 10);
  assert.equal(f.service.knowledgeBases.get(f.ctx, id).chunk_count, 7);
  f.db.update('knowledges', String(f.current.id), { deleted_at: '2026-01-01T00:00:00.000Z' });
  assert.equal(f.service.stats(f.ctx, id).chunk_count, 5);
  assert.equal(f.service.knowledgeBases.get(f.ctx, id).chunk_count, 3);
});

test('counting retains current KB/tenant and persisted membership authorization', t => {
  const f = fixture(t);
  for (const read of [() => f.service.knowledgeBases.get(f.ctx, String(f.privateKb.id)), () => f.service.stats(f.ctx, String(f.privateKb.id)),
    () => f.service.knowledgeBases.get(f.ctx, String(f.retiredKb.id)), () => f.service.stats(f.ctx, String(f.retiredKb.id))]) {
    assert.throws(read, (error: any) => error.status === 404);
  }
  f.db.run("UPDATE tenant_members SET status='revoked' WHERE user_id=? AND tenant_id=?", f.ctx.userId, f.ctx.tenantId);
  const forged = { ...f.ctx, role: 'owner', isSystemAdmin: true };
  assert.throws(() => f.service.knowledgeBases.get(forged, String(f.kb.id)), (error: any) => error.status === 401);
  assert.throws(() => f.service.stats(forged, String(f.kb.id)), (error: any) => error.status === 401);
});
