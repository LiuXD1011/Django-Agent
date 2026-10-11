import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { joins, records, scopeClause, searchable } from '../src/retrieval/internal.js';
import { SearchIndex } from '../src/retrieval/search-index.js';
import type { SearchScope } from '../src/retrieval/types.js';
import { CoreDatabase, type BindValue, type Row } from '../src/storage/database.js';

function fixture() {
  const directory = mkdtempSync(join(tmpdir(), 'marlin-keyword-recall-'));
  const db = new CoreDatabase(directory);
  const tenant = db.insert('tenants', { name: 'Recall fixture', api_key: 'fixture-only' });
  const kb = db.insert('knowledge_bases', { tenant_id: tenant.id, name: 'Source namespace' });
  const metadata = { content: 'canonical source😀'.repeat(8000), source_generation: 'original', parser: { version: 'fixture' } };
  const doc = db.insert('knowledges', { tenant_id: tenant.id, knowledge_base_id: kb.id, title: 'Fixture source', metadata });
  const index = new SearchIndex(db);
  const scope: SearchScope = { tenantId: String(tenant.id), knowledgeBaseIds: [String(kb.id)] };
  let sequence = 1000n;
  const chunk = (id: string, content: string, values: Record<string, unknown> = {}) => db.insert('chunks', {
    id, tenant_id: tenant.id, knowledge_base_id: kb.id, knowledge_id: doc.id,
    seq_id: sequence++, chunk_index: 0, content, ...values,
  });
  return { db, tenant, kb, doc, metadata, index, scope, chunk,
    close() { db.close(); rmSync(directory, { recursive: true, force: true }); } };
}
const ids = (rows: Array<{ chunk_id: string }>) => rows.map(row => row.chunk_id);

test('MATCH recall follows FTS candidates with indexed sequence lookups', () => {
  const f = fixture();
  try {
    const chunks = Array.from({ length: 600 }, (_, i) => f.chunk(`key-${i}`, `uniquefact${i} original revenue source`));
    f.index.indexKeywords(f.scope, chunks.map(row => String(row.id)));
    const all = f.db.all.bind(f.db); let plan: Row[] = [];
    f.db.all = ((sql: string, ...args: BindValue[]) => {
      if (sql.startsWith('SELECT c.id ') && sql.includes('chunks_fts')) plan = all('EXPLAIN QUERY PLAN ' + sql, ...args);
      return all(sql, ...args);
    }) as typeof f.db.all;
    assert.deepEqual(ids(f.index.keyword(f.scope, 'uniquefact599', 1)), ['key-599']);
    const candidate = plan.findIndex(row => /chunks_fts .*INDEX .*:M/.test(String(row.detail)));
    const sequence = plan.findIndex(row => /SEARCH c .*\(seq_id=\?\)/.test(String(row.detail)));
    assert.ok(candidate >= 0 && sequence > candidate,
      'MATCH must evaluate FTS candidates once and fetch each source through its exact sequence index');
  } finally { f.close(); }
});

test('keyword limit=1 hydrates only its selected chunk and reads complete source metadata once', () => {
  const f = fixture();
  try {
    const provenance = { source_generation: 'original', provenance: { page: 8, bbox: [1, 2, 3, 4] } };
    const chunks = Array.from({ length: 200 }, (_, i) => f.chunk(`source-${i}`, `uniquefact${i} original source`, { metadata: provenance }));
    f.index.indexKeywords(f.scope, chunks.map(row => String(row.id)));
    const all = f.db.all.bind(f.db), get = f.db.get.bind(f.db); let hydrated = 0, sourceReads = 0;
    f.db.all = ((sql: string, ...args: BindValue[]) => { const rows = all(sql, ...args); hydrated += rows.filter(row => 'knowledge_title' in row).length; return rows; }) as typeof f.db.all;
    f.db.get = ((sql: string, ...args: BindValue[]) => { if (/SELECT d.metadata/.test(sql)) sourceReads++; return get(sql, ...args); }) as typeof f.db.get;
    const result = f.index.keyword(f.scope, 'uniquefact199', 1);
    assert.deepEqual(ids(result), ['source-199']); assert.equal(hydrated, 1); assert.equal(sourceReads, 1);
    assert.deepEqual(result[0]?.metadata, provenance);
    assert.equal(result[0]?.knowledge_title, 'Fixture source');
    assert.deepEqual(f.db.read('knowledges', String(f.doc.id))?.metadata, f.metadata);
    assert.deepEqual(f.index.keyword(f.scope, 'nonexistentuniquefact', 1), []);
    assert.equal(hydrated, 1); assert.equal(sourceReads, 1, 'No-hit queries must not copy the unrelated canonical source');
  } finally { f.close(); }
});

test('selected record sets batch exact keys, preserve source/provenance and read each document once', () => {
  const f = fixture();
  try {
    const chunks = Array.from({ length: 150 }, (_, i) => f.chunk(`selected-${i}`, `budget source ${i}`, {
      metadata: { source_generation: 'original', page: i }, start_at: i * 10, end_at: i * 10 + 5,
      image_info: { page: i, mime_type: 'image/png' },
    }));
    const selected = chunks.slice(0, 70).map(row => String(row.id));
    const scope = { ...f.scope, knowledgeBaseIds: [String(f.kb.id), ...Array.from({ length: 899 }, (_, i) => `absent-${i}`)] };
    const all = f.db.all.bind(f.db), get = f.db.get.bind(f.db); let sourceReads = 0, hydrated = 0, largestParameters = 0;
    const plans: Row[][] = [];
    f.db.all = ((sql: string, ...args: BindValue[]) => {
      largestParameters = Math.max(largestParameters, args.length);
      const rows = all(sql, ...args); hydrated += rows.length; plans.push(all('EXPLAIN QUERY PLAN ' + sql, ...args)); return rows;
    }) as typeof f.db.all;
    f.db.get = ((sql: string, ...args: BindValue[]) => { if (/SELECT d.metadata/.test(sql)) sourceReads++; return get(sql, ...args); }) as typeof f.db.get;
    const result = records(f.db, scope, false, [...selected, selected[0]!, 'missing']);
    assert.equal(result.length, 70); assert.equal(hydrated, 70); assert.equal(sourceReads, 1); assert.equal(largestParameters, 965);
    assert.equal(plans.length, 2); assert.ok(plans.every(plan => plan.some(row => /SEARCH c .*\(id=\?\)/.test(String(row.detail)))));
    for (const row of result) {
      const original = chunks.find(chunk => chunk.id === row.id)!;
      assert.deepEqual(row.metadata, original.metadata); assert.deepEqual(row.image_info, original.image_info);
      assert.equal(row.start_at, original.start_at); assert.equal(row.end_at, original.end_at);
      assert.deepEqual(row.knowledge_metadata, f.metadata);
    }
    assert.deepEqual(records(f.db, f.scope, false, []), []);
  } finally { f.close(); }
});

test('MATCH BM25 and literal short-query order match the prior scoped SQL including stable ties', () => {
  const f = fixture();
  try {
    for (const [id, content, position] of [
      ['z-tie', 'budget costs 预算%_\\😀。', 2], ['a-tie', 'budget costs 预算%_\\😀。', 2],
      ['first-position', 'budget budget costs 预算%_\\😀。', 1], ['longer', 'budget with many unrelated words and costs', 3],
    ] as const) f.chunk(id, content, { chunk_index: position });
    f.index.indexKeywords(f.scope, ['z-tie', 'a-tie', 'first-position', 'longer']);
    const clause = scopeClause(f.scope);
    for (const [query, condition, value, order] of [
      ['budget costs', 'chunks_fts MATCH ?', '"budget" OR "costs"', 'bm25(chunks_fts),c.id'],
      ['预算', "chunks_fts.content LIKE ? ESCAPE '\\'", '%预算%', 'c.chunk_index,c.id'],
      ['%', "chunks_fts.content LIKE ? ESCAPE '\\'", '%\\%%', 'c.chunk_index,c.id'],
      ['_', "chunks_fts.content LIKE ? ESCAPE '\\'", '%\\_%', 'c.chunk_index,c.id'],
      ['\\', "chunks_fts.content LIKE ? ESCAPE '\\'", '%\\\\%', 'c.chunk_index,c.id'],
      ['😀', "chunks_fts.content LIKE ? ESCAPE '\\'", '%😀%', 'c.chunk_index,c.id'],
      ['。', "chunks_fts.content LIKE ? ESCAPE '\\'", '%。%', 'c.chunk_index,c.id'],
    ] as const) for (const limit of [1, 3, 10]) {
      const reference = f.db.all(`SELECT c.id ${joins} JOIN chunks_fts ON chunks_fts.rowid=c.seq_id
        WHERE ${clause.sql} AND c.seq_id IS NOT NULL AND ${searchable} AND ${condition} ORDER BY ${order} LIMIT ?`, ...clause.binds, value, limit);
      assert.deepEqual(ids(f.index.keyword(f.scope, query, limit)), reference.map(row => String(row.id)), query);
    }
    assert.deepEqual(ids(f.index.keyword(f.scope, '%', 10)), ['first-position', 'a-tie', 'z-tie']);
  } finally { f.close(); }
});

test('foreign namespaces and stale inactive FTS rows cannot crowd out an authorized result before LIMIT', () => {
  const f = fixture();
  try {
    const other = f.db.insert('tenants', { name: 'Other fixture', api_key: 'other-fixture-only' });
    const otherKb = f.db.insert('knowledge_bases', { tenant_id: other.id, name: 'Foreign namespace' });
    const otherDoc = f.db.insert('knowledges', { tenant_id: other.id, knowledge_base_id: otherKb.id, title: 'Foreign fixture' });
    const localKb = f.db.insert('knowledge_bases', { tenant_id: f.tenant.id, name: 'Excluded local namespace' });
    const localDoc = f.db.insert('knowledges', { tenant_id: f.tenant.id, knowledge_base_id: localKb.id, title: 'Excluded fixture' });
    const foreign: string[] = [], local: string[] = [];
    for (let i = 0; i < 70; i++) {
      foreign.push(String(f.chunk(`foreign-${i}`, 'budget '.repeat(10) + '预算%_\\', { tenant_id: other.id, knowledge_base_id: otherKb.id, knowledge_id: otherDoc.id }).id));
      local.push(String(f.chunk(`excluded-${i}`, 'budget '.repeat(10) + '预算%_\\', { knowledge_base_id: localKb.id, knowledge_id: localDoc.id }).id));
    }
    f.index.indexKeywords({ tenantId: String(other.id) }, foreign); f.index.indexKeywords({ tenantId: String(f.tenant.id) }, local);
    f.chunk('healthy', 'budget original 预算%_\\', { seq_id: 9223372036854775807n, chunk_index: 100 });
    f.chunk('disabled', 'budget '.repeat(10) + '预算%_\\', { chunk_index: 0 });
    f.chunk('deleted', 'budget '.repeat(10) + '预算%_\\', { chunk_index: 0 });
    f.chunk('parent', 'budget '.repeat(10) + '预算%_\\', { chunk_index: 0 });
    f.chunk('mismatched-doc', 'budget '.repeat(10) + '预算%_\\', { chunk_index: 0 });
    f.index.indexKeywords(f.scope, ['healthy', 'disabled', 'deleted', 'parent', 'mismatched-doc']);
    f.db.update('chunks', 'disabled', { is_enabled: false });
    f.db.update('chunks', 'deleted', { deleted_at: new Date().toISOString() });
    f.db.update('chunks', 'parent', { chunk_type: 'parent_text' });
    f.db.update('chunks', 'mismatched-doc', { knowledge_id: otherDoc.id });
    for (const query of ['budget', '预算', '%', '_', '\\']) {
      const result = f.index.keyword(f.scope, query, 1);
      assert.deepEqual(ids(result), ['healthy']); assert.equal(result[0]?.seq_id, '9223372036854775807');
      assert.deepEqual(f.index.keyword({ ...f.scope, knowledgeBaseIds: [] }, query, 1), []);
    }
    for (const [table, id, value] of [
      ['knowledges', f.doc.id!, { enable_status: 'disabled' }], ['knowledges', f.doc.id!, { deleted_at: new Date().toISOString() }],
      ['knowledge_bases', f.kb.id!, { deleted_at: new Date().toISOString() }], ['tenants', f.tenant.id!, { status: 'inactive' }],
    ] as const) {
      const previous = f.db.read(table, id)!; f.db.update(table, id, value);
      assert.deepEqual(f.index.keyword(f.scope, 'budget', 1), []); assert.deepEqual(f.index.keyword(f.scope, '%', 1), []);
      f.db.update(table, id, Object.fromEntries(Object.keys(value).map(key => [key, previous[key]])));
    }
  } finally { f.close(); }
});

test('selected hydration reapplies scope, active state and document namespace before decoding', () => {
  const f = fixture();
  try {
    f.chunk('active', 'budget original'); f.chunk('inactive', 'budget disabled', { is_enabled: false });
    const other = f.db.insert('tenants', { name: 'Other', api_key: 'other-fixture-only' });
    const kb = f.db.insert('knowledge_bases', { tenant_id: other.id, name: 'Other' });
    const doc = f.db.insert('knowledges', { tenant_id: other.id, knowledge_base_id: kb.id, title: 'Other' });
    f.chunk('foreign', 'budget foreign', { tenant_id: other.id, knowledge_base_id: kb.id, knowledge_id: doc.id });
    f.chunk('inconsistent', 'budget inconsistent', { knowledge_id: doc.id });
    assert.deepEqual(records(f.db, f.scope, false, ['foreign', 'inactive', 'inconsistent', 'active']).map(row => row.id), ['active']);
    assert.deepEqual(records(f.db, f.scope, false, 'active').map(row => row.id), ['active']);
    assert.deepEqual(records(f.db, { ...f.scope, knowledgeBaseIds: [] }, false, ['active']), []);
  } finally { f.close(); }
});
