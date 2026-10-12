import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test, type TestContext } from 'node:test';
import { AuthService } from '../src/auth/index.js';
import { AuthReader } from '../src/auth/reader.js';
import type { JsonObject } from '../src/contracts.js';
import { paginate } from '../src/knowledge/config.js';
import { KnowledgeReadDomain } from '../src/knowledge/read-domain.js';
import { KnowledgeQueries } from '../src/knowledge/read-queries.js';
import { CoreDatabase, type BindValue, type Row } from '../src/storage/database.js';
import { ReadDatabase } from '../src/storage/read-database.js';

/** Observe actual native readonly reads; never replace SQL results or DTOs. */
class ObservedReadDatabase extends ReadDatabase {
  chunkReads = 0;
  documentMetadataReads = 0;
  documentMetadataBytes = 0;
  chunkMetadataBytes = 0;
  referenceColumns: string[] = [];
  referenceCount = 0;
  afterReferences?: () => void;
  override all<T extends Row = Row>(sql: string, ...parameters: BindValue[]): T[] {
    const rows = super.all<T>(sql, ...parameters);
    if (/\bFROM chunks\b/.test(sql)) {
      this.referenceColumns = rows.length ? Object.keys(rows[0]!) : [];
      this.referenceCount = rows.length;
      const after = this.afterReferences; this.afterReferences = undefined; after?.();
    }
    return rows;
  }
  override read(name: string, id: BindValue): Row | undefined {
    const row = super.read(name, id);
    if (name === 'chunks' && row) {
      this.chunkReads++;
      this.chunkMetadataBytes += Buffer.byteLength(JSON.stringify(row.metadata));
    }
    return row;
  }
  override get<T extends Row = Row>(sql: string, ...parameters: BindValue[]): T | undefined {
    const row = super.get<T>(sql, ...parameters);
    if (row && /\bknowledges\b/.test(sql) && 'metadata' in row) {
      this.documentMetadataReads++;
      this.documentMetadataBytes += Buffer.byteLength(String(row.metadata));
    }
    return row;
  }
  reset(): void {
    this.chunkReads = this.documentMetadataReads = this.documentMetadataBytes = this.chunkMetadataBytes = 0;
    this.referenceColumns = []; this.referenceCount = 0;
  }
}

function fixture(t: TestContext, count = 67, largeMetadata = true) {
  const root = mkdtempSync(join(tmpdir(), 'marlin-chunk-pagination-'));
  const db = new CoreDatabase(root), auth = new AuthService(db);
  const issue = auth.register({ username: 'page-owner', password: 'Page fixture✓Password' });
  const other = auth.register({ username: 'page-other', password: 'Page other✓Password' });
  const kb = db.insert('knowledge_bases', { tenant_id: issue.context.tenantId, name: '当前资料' });
  const otherKb = db.insert('knowledge_bases', { tenant_id: issue.context.tenantId, name: '其他库' });
  const privateKb = db.insert('knowledge_bases', { tenant_id: other.context.tenantId, name: '其他租户库' });
  const doc = db.insert('knowledges', { tenant_id: issue.context.tenantId, knowledge_base_id: kb.id,
    title: '完整来源', enable_status: 'disabled', metadata: { content: '完整原文😀'.repeat(largeMetadata ? 65536 : 4), source_generation: 'original-generation', opaque: { preserved: true } } });
  const privateDoc = db.insert('knowledges', { tenant_id: other.context.tenantId, knowledge_base_id: privateKb.id, title: '私有来源' });
  const types = ['parent_text', 'text', 'image_container', 'image_ocr', 'image_caption'];
  const ids = Array.from({ length: count }, (_, i) => `page-chunk-${String(count - i).padStart(3, '0')}`);
  db.insertMany('chunks', ids.map((id, i) => ({ id, tenant_id: issue.context.tenantId, knowledge_base_id: kb.id, knowledge_id: doc.id,
    chunk_index: Math.floor(i / 3), chunk_type: types[i % types.length], is_enabled: i % 4 !== 0,
    seq_id: (9223372036854775700n + BigInt(i)).toString(), content: `原块${i}😀\n正文原样保留`, start_at: i, end_at: i + 10,
    context_parent_id: i > 0 ? ids[0] : null, media_parent_id: i > 2 ? ids[2] : null,
    pre_chunk_id: ids[i - 1] ?? '', next_chunk_id: ids[i + 1] ?? '', content_hash: `original-hash-${i}`,
    image_info: { image_id: `image-${i}`, source_ref: 'page:3', width: 10 }, relation_chunks: [ids[0]!],
    metadata: { source_generation: 'original-generation', source_range: { start: i, end: i + 10 }, opaque: '保留😀'.repeat(largeMetadata ? 4096 : 4), api_key: 'synthetic-never-public' } })));
  db.insert('chunks', { tenant_id: issue.context.tenantId, knowledge_base_id: kb.id, knowledge_id: doc.id, chunk_index: 0, deleted_at: '2026-01-01', content: '软删排除' });
  db.insert('chunks', { tenant_id: issue.context.tenantId, knowledge_base_id: otherKb.id, knowledge_id: doc.id, chunk_index: 0, content: '错误库排除' });
  db.insert('chunks', { tenant_id: other.context.tenantId, knowledge_base_id: kb.id, knowledge_id: doc.id, chunk_index: 0, content: '错误租户排除' });
  const reader = new ObservedReadDatabase(db.path, root), readonlyAuth = new AuthReader(reader);
  const domain = new KnowledgeReadDomain(reader, readonlyAuth), queries = new KnowledgeQueries(domain);
  const all = db.all('SELECT id FROM chunks WHERE tenant_id=? AND knowledge_base_id=? AND knowledge_id=? AND deleted_at IS NULL ORDER BY chunk_index,id', issue.context.tenantId, String(kb.id), String(doc.id))
    .map(row => domain.chunkDto(db.read('chunks', String(row.id))!));
  const read = (params: JsonObject = {}) => reader.snapshot(() => queries.listChunks(readonlyAuth.authenticateAccess(issue.credentials.access), String(doc.id), params));
  const expected = (params: JsonObject = {}) => paginate(all.filter(row => !params.chunk_type || row.chunk_type === params.chunk_type), params);
  t.after(() => { reader.close(); db.close(); rmSync(root, { recursive: true, force: true }); });
  return { root, db, auth, issue, other, kb, privateKb, doc, privateDoc, reader, readonlyAuth, domain, queries, all, read, expected };
}

test('a native readonly 20-item chunk page hydrates only its page and never reads canonical document metadata', t => {
  const f = fixture(t), before = f.db.get('SELECT total_changes() AS n')!.n;
  f.reader.reset();
  const actual = f.read({ page: 2, page_size: 20 });
  assert.deepEqual(actual, f.expected({ page: 2, page_size: 20 }));
  assert.equal(actual.total, 67); assert.equal(actual.items.length, 20);
  t.diagnostic(JSON.stringify({ returned_items: actual.items.length, total: actual.total, chunk_reads: f.reader.chunkReads,
    chunk_metadata_bytes: f.reader.chunkMetadataBytes, document_metadata_reads: f.reader.documentMetadataReads, document_metadata_bytes: f.reader.documentMetadataBytes }));
  assert.equal(f.reader.chunkReads, 20, 'Page-only hydration must not read complete off-page chunks');
  assert.equal(f.reader.documentMetadataReads, 0, 'Scope authorization needs no canonical body/parser metadata');
  assert.deepEqual(f.reader.referenceColumns, ['id', 'chunk_type']); assert.equal(f.reader.referenceCount, 67);
  assert.equal(f.db.get('SELECT total_changes() AS n')!.n, before);
});

test('native chunk pages retain exact ordering, strict type comparison and original pagination normalization', t => {
  const f = fixture(t, 19, false), before = f.db.get('SELECT total_changes() AS n')!.n;
  const params: JsonObject[] = [
    {}, { page: 2, page_size: 4 }, { offset: 3, limit: 4 }, { offset: 5, page: 2, page_size: 4 },
    { page: 1.9, page_size: 4.9 }, { page: -2, page_size: 0 }, { page: 'invalid', limit: 'invalid' },
    { offset: -100, page_size: 3 }, { offset: 1.8, page_size: 2 }, { page_size: 1000 },
    { page: null, offset: 100, page_size: 3 }, { page_size: 'Infinity', page: 'Infinity' },
    { page: 100, page_size: 4 }, { offset: 19, limit: 4 },
    ...['text', 'parent_text', 'image_container', 'image_ocr', 'image_caption', 'unknown', 1, true, ['text'], { type: 'text' }, '', 0, false, null]
      .map(chunk_type => ({ chunk_type, page_size: 3 })),
  ];
  for (const q of params) {
    f.reader.reset(); const actual = f.read(q);
    assert.deepEqual(actual, f.expected(q), JSON.stringify(q));
    assert.equal(f.reader.chunkReads, actual.items.length, JSON.stringify(q));
    assert.equal(f.reader.documentMetadataReads, 0);
  }
  assert.equal(f.db.get('SELECT total_changes() AS n')!.n, before);
});

test('paged DTOs retain disabled, parent/media, bigint and complete content without leaking private fields', t => {
  const f = fixture(t, 19, false), storedDocument = f.db.read('knowledges', String(f.doc.id));
  const actual = f.read({ page_size: 100 });
  assert.deepEqual(actual, f.expected({ page_size: 100 }));
  assert.ok(actual.items.some(row => row.chunk_type === 'parent_text'));
  assert.ok(actual.items.some(row => row.chunk_type === 'image_container'));
  assert.ok(actual.items.some(row => row.is_enabled === false));
  for (const row of actual.items) {
    const stored = f.db.read('chunks', String(row.id))!;
    assert.equal(row.content, stored.content); assert.equal(row.seq_id, String(stored.seq_id));
    assert.ok(BigInt(String(row.seq_id)) > BigInt(Number.MAX_SAFE_INTEGER));
    for (const key of ['context_parent_id', 'media_parent_id', 'pre_chunk_id', 'next_chunk_id', 'relation_chunks', 'start_at', 'end_at', 'image_info']) assert.deepEqual(row[key], stored[key]);
    assert.equal('content_hash' in row, false); assert.equal('deleted_at' in row, false);
    const metadata = row.metadata as JsonObject;
    assert.equal(metadata.api_key, undefined); assert.deepEqual(metadata.source_range, (stored.metadata as JsonObject).source_range);
    assert.equal(metadata.opaque, (stored.metadata as JsonObject).opaque);
  }
  assert.deepEqual(f.db.read('knowledges', String(f.doc.id)), storedDocument);
  // Existing non-paginated callers still receive the complete original rows.
  const allRows = f.reader.snapshot(() => f.domain.chunks(f.issue.context, f.doc));
  assert.equal(allRows.length, 19); assert.equal(allRows[0]!.content_hash, f.db.read('chunks', String(allRows[0]!.id))!.content_hash);
});

test('empty pages and empty documents perform no complete chunk or canonical metadata hydration', t => {
  const f = fixture(t, 0, false);
  for (const q of [{}, { page: 100, page_size: 20 }, { chunk_type: 'text' }]) {
    f.reader.reset(); assert.deepEqual(f.read(q), f.expected(q));
    assert.equal(f.reader.chunkReads, 0); assert.equal(f.reader.documentMetadataReads, 0);
  }
});

test('native pages preserve payload, document/KB scope errors and recheck revoked membership before hydration', t => {
  const f = fixture(t, 6, false), current = f.readonlyAuth.authenticateAccess(f.issue.credentials.access);
  const query = (id: string, params: unknown = {}) => f.reader.snapshot(() => f.queries.listChunks(current, id, params as JsonObject));
  for (const params of [null, [], 'text', 3]) assert.throws(() => query(String(f.doc.id), params), { status: 400, code: 'invalid_payload' });
  for (const id of ['missing-document', String(f.privateDoc.id)]) assert.throws(() => query(id), { status: 404, code: 'knowledge_not_found' });
  // Authentication/document errors retain priority over invalid query payloads.
  assert.throws(() => query('missing-document', null), { status: 404, code: 'knowledge_not_found' });
  f.db.update('knowledges', String(f.doc.id), { deleted_at: '2026-01-01' });
  assert.throws(() => query(String(f.doc.id)), { status: 404, code: 'knowledge_not_found' });
  f.db.update('knowledges', String(f.doc.id), { deleted_at: null });
  f.db.update('knowledge_bases', String(f.kb.id), { deleted_at: '2026-01-01' });
  assert.throws(() => query(String(f.doc.id)), { status: 404, code: 'knowledge_base_not_found' });
  f.db.update('knowledge_bases', String(f.kb.id), { deleted_at: null });
  f.reader.reset(); assert.equal(query(String(f.doc.id)).total, 6);
  f.db.run("UPDATE tenant_members SET status='revoked' WHERE tenant_id=? AND user_id=?", f.issue.context.tenantId, f.issue.context.userId);
  f.reader.reset();
  assert.throws(() => query(String(f.doc.id), null), { status: 401, code: 'unauthorized' });
  assert.equal(f.reader.chunkReads, 0); assert.equal(f.reader.referenceCount, 0);
});

test('native WAL snapshot keeps exact count and page DTOs from one generation while the writer commits between projection and hydration', t => {
  const f = fixture(t, 6, false), q = { page_size: 3 }, original = f.expected(q);
  const firstId = String(original.items[0]!.id), secondId = String(original.items[1]!.id);
  f.reader.afterReferences = () => f.db.transaction(() => {
    f.db.update('chunks', firstId, { content: '新一代正文', metadata: { source_generation: 'new-generation' } });
    f.db.update('chunks', secondId, { deleted_at: '2026-01-01' });
    f.db.insert('chunks', { id: 'new-leading-chunk', tenant_id: f.issue.context.tenantId, knowledge_base_id: f.kb.id, knowledge_id: f.doc.id, chunk_index: -1, content: '新一代新增块' });
  });
  f.reader.reset();
  assert.deepEqual(f.read(q), original);
  assert.equal(f.reader.chunkReads, 3); assert.equal(f.reader.documentMetadataReads, 0);
  assert.equal(f.db.read('chunks', firstId)!.content, '新一代正文');
  const fresh = f.db.all('SELECT id FROM chunks WHERE tenant_id=? AND knowledge_base_id=? AND knowledge_id=? AND deleted_at IS NULL ORDER BY chunk_index,id', f.issue.context.tenantId, String(f.kb.id), String(f.doc.id))
    .map(row => f.domain.chunkDto(f.db.read('chunks', String(row.id))!));
  f.reader.reset(); assert.deepEqual(f.read(q), paginate(fresh, q)); assert.equal(f.reader.chunkReads, 3);
  assert.equal(f.read(q).items[0]!.id, 'new-leading-chunk');
});
