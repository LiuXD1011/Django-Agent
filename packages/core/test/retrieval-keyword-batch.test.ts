import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { RetrievalError } from '../src/retrieval/internal.js';
import { SearchIndex } from '../src/retrieval/search-index.js';
import { CoreDatabase, type BindValue, type Row } from '../src/storage/database.js';

function fixture() {
  const directory = mkdtempSync(join(tmpdir(), 'marlin-keyword-batch-'));
  const db = new CoreDatabase(directory);
  const tenant = db.insert('tenants', { name: 'Keyword batch fixture', api_key: 'fixture-only' });
  const kb = db.insert('knowledge_bases', { tenant_id: tenant.id, name: 'Sources' });
  const metadata = { content: 'source😀'.repeat(12000), source_generation: 'stable' };
  const doc = db.insert('knowledges', { tenant_id: tenant.id, knowledge_base_id: kb.id, title: 'Revenue report', metadata });
  const index = new SearchIndex(db);
  const scope = { tenantId: String(tenant.id), knowledgeBaseIds: [String(kb.id)] };
  const chunk = (id: string, values: Record<string, unknown> = {}) => db.insert('chunks', {
    id, tenant_id: tenant.id, knowledge_base_id: kb.id, knowledge_id: doc.id,
    content: `revenue original source ${id}`, context_header: 'Original heading', ...values,
  });
  return { db, tenant, kb, doc, metadata, index, scope, chunk,
    close() { db.close(); rmSync(directory, { recursive: true, force: true }); } };
}

test('single keyword publication transfers no unrelated chunk or canonical-source JSON', () => {
  const f = fixture();
  try {
    const metadata = { provenance: { note: 'large existing provenance😀'.repeat(8000) }, source_generation: 'stable' };
    f.chunk('precise', { seq_id: 9223372036854775807n, metadata });
    const get = f.db.get.bind(f.db), all = f.db.all.bind(f.db); let jsonCharacters = 0;
    const observe = (row?: Row) => { if (typeof row?.metadata === 'string') jsonCharacters += row.metadata.length; };
    f.db.get = ((sql: string, ...args: BindValue[]) => { const row = get(sql, ...args); observe(row); return row; }) as typeof f.db.get;
    f.db.all = ((sql: string, ...args: BindValue[]) => { const rows = all(sql, ...args); rows.forEach(observe); return rows; }) as typeof f.db.all;
    f.index.indexKeyword(f.scope, 'precise');
    assert.equal(jsonCharacters, 0, 'FTS needs only the scoped title, heading, content and exact sequence');
    assert.equal(get('SELECT rowid FROM retrieval_chunk_ids WHERE chunk_id=?', 'precise')?.rowid, '9223372036854775807');
    assert.deepEqual(f.db.read('chunks', 'precise')?.metadata, metadata);
    assert.deepEqual(f.db.read('knowledges', String(f.doc.id))?.metadata, f.metadata);
  } finally { f.close(); }
});

test('130 keyword sources use one transaction, bounded scoped reads and batched FTS writes', () => {
  const f = fixture();
  try {
    const ids = Array.from({ length: 130 }, (_, i) => `batch-${String(i).padStart(3, '0')}`);
    f.db.transaction(() => ids.forEach((id, i) => f.chunk(id, { seq_id: 1152921504606846976n + BigInt(i) })));
    const transaction = f.db.transaction.bind(f.db), all = f.db.all.bind(f.db), run = f.db.run.bind(f.db);
    let transactions = 0, reads = 0, inserts = 0, deletes = 0;
    f.db.transaction = work => { transactions++; return transaction(work); };
    f.db.all = ((sql: string, ...args: BindValue[]) => { if (/\b(?:FROM|JOIN) chunks c/i.test(sql)) reads++; return all(sql, ...args); }) as typeof f.db.all;
    f.db.run = (sql, ...args) => { if (/^INSERT INTO chunks_fts/i.test(sql)) inserts++; if (/^DELETE FROM chunks_fts/i.test(sql)) deletes++; return run(sql, ...args); };
    f.index.indexKeywords(f.scope, [...ids, ids[0]!]);
    assert.equal(transactions, 1); assert.equal(reads, 3); assert.equal(inserts, 3); assert.equal(deletes, 3);
    assert.equal(f.db.get('SELECT count(*) AS n FROM chunks_fts')?.n, ids.length);
    assert.equal(f.db.get('SELECT content FROM chunks_fts WHERE rowid=?', 1152921504606847105n)?.content,
      'Revenue report\n\nOriginal heading\n\nrevenue original source batch-129');
    assert.equal(f.index.keyword(f.scope, 'batch-129', 1)[0]?.chunk_id, ids.at(-1));
  } finally { f.close(); }
});

test('batch scope rejects foreign sources and supports the maximum 900-KB parameter range', () => {
  const f = fixture();
  try {
    f.chunk('owned', { seq_id: 10 });
    const other = f.db.insert('tenants', { name: 'Other', api_key: 'other-fixture-only' });
    const foreignKb = f.db.insert('knowledge_bases', { tenant_id: other.id, name: 'Foreign' });
    const foreignDoc = f.db.insert('knowledges', { tenant_id: other.id, knowledge_base_id: foreignKb.id, title: 'Foreign title' });
    f.chunk('foreign', { tenant_id: other.id, knowledge_base_id: foreignKb.id, knowledge_id: foreignDoc.id, seq_id: 11 });
    f.chunk('inconsistent', { knowledge_id: foreignDoc.id, seq_id: 12 });
    const additional = Array.from({ length: 63 }, (_, i) => `owned-${i}`);
    f.db.transaction(() => additional.forEach((id, i) => f.chunk(id, { seq_id: 500 + i })));
    const scope = { ...f.scope, knowledgeBaseIds: [String(f.kb.id), ...Array.from({ length: 899 }, (_, i) => `absent-${i}`)] };
    const all = f.db.all.bind(f.db); let largestParameterCount = 0;
    f.db.all = ((sql: string, ...args: BindValue[]) => { largestParameterCount = Math.max(largestParameterCount, args.length); return all(sql, ...args); }) as typeof f.db.all;
    f.index.indexKeywords(scope, ['owned', ...additional, 'foreign', 'inconsistent', 'missing']);
    assert.equal(largestParameterCount, 965);
    assert.equal(f.db.get('SELECT count(*) AS n FROM chunks_fts')?.n, 64);
    assert.equal(f.db.get('SELECT chunk_id FROM retrieval_chunk_ids WHERE rowid=?', 10)?.chunk_id, 'owned');
    assert.equal(f.db.get('SELECT chunk_id FROM retrieval_chunk_ids WHERE rowid=?', 11), undefined);
    f.index.indexKeywords({ ...f.scope, knowledgeBaseIds: [] }, ['foreign', 'owned']);
    assert.equal(f.db.get('SELECT count(*) AS n FROM chunks_fts')?.n, 64);
  } finally { f.close(); }
});

test('batch reads use a precise chunk key lookup instead of scanning the scoped KB for every batch', () => {
  const f = fixture();
  try {
    const ids = Array.from({ length: 64 }, (_, i) => `key-${i}`);
    f.db.transaction(() => { for (let i = 0; i < 600; i++) f.chunk(`key-${i}`, { seq_id: 1000 + i }); });
    const all = f.db.all.bind(f.db); let plan: Row[] = [];
    f.db.all = ((sql: string, ...args: BindValue[]) => {
      if (/\bSELECT c.id,c.seq_id/.test(sql)) plan = all('EXPLAIN QUERY PLAN ' + sql, ...args);
      return all(sql, ...args);
    }) as typeof f.db.all;
    f.index.indexKeywords(f.scope, ids);
    assert.ok(plan.some(row => /SEARCH c .*\(id=\?\)/.test(String(row.detail))),
      'Each requested chunk must use its exact primary key, independently of scoped corpus size');
    assert.equal(f.db.get('SELECT count(*) AS n FROM chunks_fts')?.n, ids.length);
  } finally { f.close(); }
});

test('every inactive source condition removes existing keyword and vector rows without deleting provenance', () => {
  for (const change of [
    (f: ReturnType<typeof fixture>) => f.db.update('chunks', 'target', { is_enabled: false }),
    (f: ReturnType<typeof fixture>) => f.db.update('chunks', 'target', { chunk_type: 'parent_text' }),
    (f: ReturnType<typeof fixture>) => f.db.update('chunks', 'target', { deleted_at: new Date().toISOString() }),
    (f: ReturnType<typeof fixture>) => f.db.update('knowledges', String(f.doc.id), { enable_status: 'disabled' }),
    (f: ReturnType<typeof fixture>) => f.db.update('knowledges', String(f.doc.id), { deleted_at: new Date().toISOString() }),
    (f: ReturnType<typeof fixture>) => f.db.update('knowledge_bases', String(f.kb.id), { deleted_at: new Date().toISOString() }),
    (f: ReturnType<typeof fixture>) => f.db.update('tenants', f.tenant.id!, { status: 'inactive' }),
  ]) {
    const f = fixture();
    try {
      f.chunk('target', { seq_id: 40, metadata: { original: true } });
      f.index.indexKeywords(f.scope, ['target']);
      const table = f.index.vectorTable('fixture-space', 2, randomUUID());
      f.db.sqlite.exec(`CREATE VIRTUAL TABLE ${table} USING vec0(embedding float[2])`);
      f.db.run(`INSERT INTO ${table}(rowid,embedding) VALUES(?,?)`, 40n, Buffer.from(new Float32Array([1, 0]).buffer));
      f.db.run('INSERT INTO retrieval_vector_entries(table_name,rowid,chunk_id,tenant_id,knowledge_base_id,knowledge_id,fingerprint) VALUES(?,?,?,?,?,?,?)',
        table, 40, 'target', String(f.tenant.id), String(f.kb.id), String(f.doc.id), 'fixture');
      change(f); f.index.indexKeywords(f.scope, ['target']);
      assert.equal(f.db.get('SELECT count(*) AS n FROM chunks_fts')?.n, 0);
      assert.equal(f.db.get(`SELECT count(*) AS n FROM ${table}`)?.n, 0);
      assert.equal(f.db.get('SELECT count(*) AS n FROM retrieval_vector_entries')?.n, 0);
      assert.deepEqual(f.db.read('chunks', 'target')?.metadata, { original: true });
    } finally { f.close(); }
  }
});

test('a sequence collision in a later batch rolls back all earlier keyword writes and assigned IDs', () => {
  const f = fixture();
  try {
    f.chunk('published', { seq_id: 17 }); f.index.indexKeyword(f.scope, 'published');
    const original = f.db.all('SELECT rowid,content FROM chunks_fts');
    const ids = Array.from({ length: 65 }, (_, i) => `new-${i}`);
    f.db.transaction(() => ids.forEach(id => f.chunk(id)));
    f.db.update('chunks', 'new-64', { seq_id: 17 });
    assert.throws(() => f.index.indexKeywords(f.scope, ids), error => error instanceof RetrievalError && error.code === 'seq_id_collision');
    assert.deepEqual(f.db.all('SELECT rowid,content FROM chunks_fts'), original);
    assert.equal(f.db.get('SELECT count(*) AS n FROM retrieval_chunk_ids')?.n, 1);
    assert.equal(f.db.get("SELECT count(*) AS n FROM chunks WHERE id LIKE 'new-%' AND seq_id IS NOT NULL")?.n, 1);
  } finally { f.close(); }
});

test('registered rowid collisions and changed precise sequences cannot overwrite another keyword source', () => {
  const f = fixture();
  try {
    f.chunk('first', { seq_id: 1152921504606846976n });
    f.index.indexKeywords(f.scope, ['first']);
    f.db.update('chunks', 'first', { seq_id: 1152921504606846977n });
    f.chunk('second', { seq_id: 1152921504606846976n });
    assert.throws(() => f.index.indexKeywords(f.scope, ['second']), /collision/i);
    f.index.indexKeywords(f.scope, ['first', 'second']);
    assert.equal(f.db.get('SELECT chunk_id FROM retrieval_chunk_ids WHERE rowid=?', 1152921504606846976n)?.chunk_id, 'second');
    assert.equal(f.db.get('SELECT chunk_id FROM retrieval_chunk_ids WHERE rowid=?', 1152921504606846977n)?.chunk_id, 'first');
    assert.equal(f.db.get('SELECT count(*) AS n FROM chunks_fts')?.n, 2);
  } finally { f.close(); }
});

test('owner cancellation or a publisher failure rolls back an entire keyword batch', () => {
  const f = fixture();
  try {
    for (const id of ['a', 'b']) f.chunk(id);
    let publications = 0;
    assert.throws(() => f.index.indexKeywords(f.scope, ['a', 'b'], write => {
      publications++; write(); throw new Error('owned attempt cancelled');
    }), /owned attempt cancelled/);
    assert.equal(publications, 1); assert.equal(f.db.sqlite.inTransaction, false);
    assert.equal(f.db.get('SELECT count(*) AS n FROM chunks_fts')?.n, 0);
    assert.equal(f.db.get('SELECT count(*) AS n FROM retrieval_chunk_ids')?.n, 0);
    assert.equal(f.db.get('SELECT count(*) AS n FROM chunks WHERE seq_id IS NOT NULL')?.n, 0);
  } finally { f.close(); }
});

test('batch publication rejects asynchronous commits and preserves numeric source-range validation', async () => {
  const f = fixture();
  try {
    f.chunk('a'); let late!: Promise<void>;
    assert.throws(() => f.index.indexKeywords(f.scope, ['a'], write => {
      late = Promise.resolve().then(write); return late;
    }), /synchronous/i);
    await assert.rejects(late, /publication|commit/i);
    f.db.run('UPDATE chunks SET start_at=? WHERE id=?', 9007199254740992n, 'a');
    assert.throws(() => f.index.indexKeywords(f.scope, ['a']), error => error instanceof RetrievalError && error.code === 'invalid_offset');
    assert.equal(f.db.get('SELECT count(*) AS n FROM chunks_fts')?.n, 0);
  } finally { f.close(); }
});
