import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { RetrievalError } from '../src/retrieval/internal.js';
import { SearchIndex } from '../src/retrieval/search-index.js';
import { CoreDatabase, type BindValue, type Row } from '../src/storage/database.js';

const maximum = 9223372036854775807n;
function fixture() {
  const directory = mkdtempSync(join(tmpdir(), 'marlin-keyword-id-publication-'));
  const db = new CoreDatabase(directory);
  const tenant = db.insert('tenants', { name: 'Sequence publication', api_key: 'fixture-only' });
  const kb = db.insert('knowledge_bases', { tenant_id: tenant.id, name: 'Original sources' });
  const parts = Array.from({ length: 130 }, (_, i) => `预算😀原文 ${String(i).padStart(3, '0')} revenue100\n`);
  const content = parts.join('');
  const metadata = { content, source_generation: 'original', exact_id: maximum.toString(),
    nested_provenance: { source_ref: '真实来源😀', amount: '9007199254740993' } };
  const doc = db.insert('knowledges', { tenant_id: tenant.id, knowledge_base_id: kb.id, title: 'Original title', metadata });
  const scope = { tenantId: String(tenant.id), knowledgeBaseIds: [String(kb.id)] };
  const chunk = (id: string, values: Record<string, unknown> = {}) => db.insert('chunks', {
    id, tenant_id: tenant.id, knowledge_base_id: kb.id, knowledge_id: doc.id,
    content: parts[0], context_header: 'Original heading', start_at: 0, end_at: Array.from(parts[0]!).length,
    metadata: { source_generation: 'original', provenance: { exact_id: maximum.toString() } }, ...values,
  });
  return { db, tenant, kb, doc, scope, parts, metadata, chunk, index: new SearchIndex(db),
    close() { db.close(); rmSync(directory, { recursive: true, force: true }); } };
}

test('130 precise keyword IDs read global association once each without decoding source JSON', context => {
  const f = fixture();
  try {
    const ids = f.parts.map((_, i) => `id-${String(i).padStart(3, '0')}`);
    let start = 0;
    f.db.transaction(() => ids.forEach((id, i) => {
      const content = f.parts[i]!, end = start + Array.from(content).length;
      f.chunk(id, { seq_id: i === 0 ? null : maximum - BigInt(i), chunk_index: i, content, start_at: start, end_at: end });
      start = end;
    }));
    const get = f.db.get.bind(f.db), all = f.db.all.bind(f.db), parse = JSON.parse;
    let associations = 0, sourceJsonCharacters = 0, decodes = 0, largestAssociationBinds = 0;
    const coreCalls = { get: 0, all: 0, run: 0, normalized_top_level_rows: 0 };
    const associationQueries = new Map<string, BindValue[]>();
    const observe = (row?: Row) => { if (typeof row?.metadata === 'string') sourceJsonCharacters += row.metadata.length; };
    context.mock.method(f.db, 'get', (sql: string, ...parameters: BindValue[]) => {
      coreCalls.get++;
      if (/FROM chunks WHERE seq_id=|FROM retrieval_chunk_ids WHERE (?:rowid|chunk_id)=/.test(sql)) {
        associations++; largestAssociationBinds = Math.max(largestAssociationBinds, parameters.length);
        if (!associationQueries.has(sql)) associationQueries.set(sql, parameters);
      }
      const row = get(sql, ...parameters); if (row) coreCalls.normalized_top_level_rows++; observe(row); return row;
    });
    context.mock.method(f.db, 'all', (sql: string, ...parameters: BindValue[]) => {
      coreCalls.all++;
      const rows = all(sql, ...parameters); coreCalls.normalized_top_level_rows += rows.length; rows.forEach(observe); return rows;
    });
    const run = f.db.run.bind(f.db);
    context.mock.method(f.db, 'run', (sql: string, ...parameters: BindValue[]) => { coreCalls.run++; return run(sql, ...parameters); });
    context.mock.method(JSON, 'parse', (value: string, reviver?: (key: string, value: unknown) => unknown) => {
      decodes++; return parse(value, reviver);
    });
    f.index.indexKeywords(f.scope, ids);
    const publicationCalls = { ...coreCalls };
    const plans = [...associationQueries].map(([sql, parameters]) => ({ sql, plan: all('EXPLAIN QUERY PLAN ' + sql, ...parameters) }));
    context.diagnostic(JSON.stringify({ chunks: ids.length, association_reads: associations,
      source_json_characters: sourceJsonCharacters, json_decodes: decodes, largest_association_binds: largestAssociationBinds,
      core_database_calls: publicationCalls, plans }));
    assert.equal(sourceJsonCharacters, 0); assert.equal(decodes, 0);
    assert.equal(associations, ids.length, 'Global sequence checks should cross the database boundary once per selected chunk');
    assert.equal(largestAssociationBinds, 4);
    assert.equal(plans.length, 1);
    const details = plans[0]!.plan.map(row => String(row.detail));
    assert.ok(details.some(detail => /SEARCH chunks .*\(seq_id=\?\)/.test(detail)));
    assert.ok(details.some(detail => /SEARCH retrieval_chunk_ids .*\(rowid=\?\)/.test(detail)));
    assert.ok(details.some(detail => /SEARCH retrieval_chunk_ids .*\(chunk_id=\?\)/.test(detail)));
    assert.ok(!details.some(detail => /^SCAN (?:chunks|retrieval_chunk_ids)/.test(detail)));
    assert.equal(get('SELECT count(*) AS n FROM chunks_fts')?.n, ids.length);
    assert.equal(get('SELECT rowid FROM retrieval_chunk_ids WHERE chunk_id=?', ids[1]!)?.rowid, (maximum - 1n).toString());
    assert.equal(get('SELECT content FROM chunks_fts WHERE rowid=?', maximum - 1n)?.content,
      'Original title\n\nOriginal heading\n\n' + f.parts[1]);
    assert.deepEqual(f.db.read('knowledges', String(f.doc.id))?.metadata, f.metadata);
    assert.deepEqual(f.db.read('chunks', ids[1]!)?.metadata,
      { source_generation: 'original', provenance: { exact_id: maximum.toString() } });
  } finally { f.close(); }
});

test('global maximum-integer sequence conflicts in another KB or tenant cannot be hidden by scope', () => {
  for (const crossTenant of [false, true]) {
    const f = fixture();
    try {
      const tenant = crossTenant ? f.db.insert('tenants', { name: 'Foreign tenant', api_key: 'foreign-fixture-only' }) : f.tenant;
      const kb = f.db.insert('knowledge_bases', { tenant_id: tenant.id, name: 'Foreign KB' });
      const doc = f.db.insert('knowledges', { tenant_id: tenant.id, knowledge_base_id: kb.id, title: 'Foreign source' });
      f.chunk('foreign', { tenant_id: tenant.id, knowledge_base_id: kb.id, knowledge_id: doc.id, seq_id: maximum });
      f.chunk('owned', { seq_id: maximum });
      assert.throws(() => f.index.indexKeywords(f.scope, ['owned']), error => error instanceof RetrievalError && error.code === 'seq_id_collision');
      assert.equal(f.db.get('SELECT count(*) AS n FROM chunks_fts')?.n, 0);
      assert.equal(f.db.get('SELECT count(*) AS n FROM retrieval_chunk_ids')?.n, 0);
      assert.deepEqual(f.db.read('knowledges', String(f.doc.id))?.metadata, f.metadata);
    } finally { f.close(); }
  }
});

test('changing a precise sequence removes its old keyword and vector association before publishing the new rowid', () => {
  const f = fixture();
  try {
    f.chunk('moving', { seq_id: maximum }); f.index.indexKeyword(f.scope, 'moving');
    const table = f.index.vectorTable('fixture-space', 2, randomUUID());
    f.db.sqlite.exec(`CREATE VIRTUAL TABLE ${table} USING vec0(embedding float[2])`);
    f.db.run(`INSERT INTO ${table}(rowid,embedding) VALUES(?,?)`, maximum, Buffer.from(new Float32Array([1, 0]).buffer));
    f.db.run('INSERT INTO retrieval_vector_entries(table_name,rowid,chunk_id,tenant_id,knowledge_base_id,knowledge_id,fingerprint) VALUES(?,?,?,?,?,?,?)',
      table, maximum, 'moving', String(f.tenant.id), String(f.kb.id), String(f.doc.id), 'original');
    f.db.update('chunks', 'moving', { seq_id: maximum - 1n }); f.index.indexKeyword(f.scope, 'moving');
    assert.equal(f.db.get('SELECT content FROM chunks_fts WHERE rowid=?', maximum), undefined);
    assert.equal(f.db.get('SELECT rowid FROM retrieval_chunk_ids WHERE chunk_id=?', 'moving')?.rowid, (maximum - 1n).toString());
    assert.equal(f.db.get('SELECT count(*) AS n FROM retrieval_vector_entries')?.n, 0);
    assert.equal(f.db.get(`SELECT count(*) AS n FROM ${table}`)?.n, 0);
    assert.equal(f.db.get('SELECT content FROM chunks_fts WHERE rowid=?', maximum - 1n)?.content,
      'Original title\n\nOriginal heading\n\n' + f.parts[0]);
  } finally { f.close(); }
});

test('per-chunk reads retain ordered release of an old registered sequence and rollback reversed input', () => {
  const f = fixture();
  try {
    f.chunk('first', { seq_id: maximum }); f.index.indexKeyword(f.scope, 'first');
    f.db.update('chunks', 'first', { seq_id: maximum - 1n }); f.chunk('second', { seq_id: maximum });
    const previous = f.db.all('SELECT rowid,content FROM chunks_fts');
    assert.throws(() => f.index.indexKeywords(f.scope, ['second', 'first']), /collision/i);
    assert.deepEqual(f.db.all('SELECT rowid,content FROM chunks_fts'), previous);
    f.index.indexKeywords(f.scope, ['first', 'second']);
    assert.equal(f.db.get('SELECT chunk_id FROM retrieval_chunk_ids WHERE rowid=?', maximum)?.chunk_id, 'second');
    assert.equal(f.db.get('SELECT chunk_id FROM retrieval_chunk_ids WHERE rowid=?', maximum - 1n)?.chunk_id, 'first');
  } finally { f.close(); }
});

test('every new publication rereads current document title and active state without caching sources', () => {
  const f = fixture();
  try {
    f.chunk('latest', { seq_id: maximum }); f.index.indexKeyword(f.scope, 'latest');
    f.db.update('knowledges', String(f.doc.id), { title: 'Latest source title' }); f.index.indexKeyword(f.scope, 'latest');
    assert.equal(f.db.get('SELECT content FROM chunks_fts WHERE rowid=?', maximum)?.content,
      'Latest source title\n\nOriginal heading\n\n' + f.parts[0]);
    f.db.update('knowledges', String(f.doc.id), { enable_status: 'disabled' }); f.index.indexKeyword(f.scope, 'latest');
    assert.equal(f.db.get('SELECT count(*) AS n FROM chunks_fts')?.n, 0);
    assert.deepEqual(f.db.read('knowledges', String(f.doc.id))?.metadata, f.metadata);
  } finally { f.close(); }
});
