import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { records } from '../src/retrieval/internal.js';
import { SearchIndex } from '../src/retrieval/search-index.js';
import type { BindValue, Row } from '../src/storage/database.js';
import { CoreDatabase } from '../src/storage/database.js';

function fixture() {
  const directory = mkdtempSync(join(tmpdir(), 'marlin-retrieval-source-scaling-'));
  const db = new CoreDatabase(directory);
  const tenant = db.insert('tenants', { name: 'Source scaling fixture', api_key: 'unit-fixture' });
  const kb = db.insert('knowledge_bases', { tenant_id: tenant.id, name: 'Large source' });
  const source = 'large canonical source😀\n'.repeat(40000);
  const metadata = { content: source, source_generation: 'generation-1', chunking_diagnostics: { selected_strategy: 'layout' } };
  const doc = db.insert('knowledges', { tenant_id: tenant.id, knowledge_base_id: kb.id, title: 'Revenue', metadata });
  const children = Array.from({ length: 12 }, (_, i) => db.insert('chunks', {
    tenant_id: tenant.id, knowledge_base_id: kb.id, knowledge_id: doc.id, content: `Q1 revenue 100 fixture ${i}`,
    chunk_index: i, start_at: i * 20, end_at: i * 20 + 20, is_enabled: true,
  }));
  const scope = { tenantId: String(tenant.id), knowledgeBaseIds: [String(kb.id)] };
  return { db, source, metadata, children, scope, index: new SearchIndex(db), close() { db.close(); rmSync(directory, { recursive: true, force: true }); } };
}

function observeLargeValues(db: CoreDatabase) {
  const all = db.all.bind(db), get = db.get.bind(db);
  let characters = 0;
  const observe = (row?: Row) => {
    for (const value of Object.values(row ?? {}))
      if (typeof value === 'string' && value.length > 10000) characters += value.length;
  };
  db.all = ((sql: string, ...parameters: BindValue[]) => {
    const rows = all(sql, ...parameters); rows.forEach(observe); return rows;
  }) as typeof db.all;
  db.get = ((sql: string, ...parameters: BindValue[]) => {
    const row = get(sql, ...parameters); observe(row); return row;
  }) as typeof db.get;
  return () => characters;
}

test('keyword publication never transfers the large canonical source for each child', () => {
  const f = fixture();
  try {
    const transferred = observeLargeValues(f.db);
    for (const child of f.children) f.index.indexKeyword(f.scope, String(child.id));
    assert.equal(transferred(), 0, 'Keyword indexing needs the title and chunk, not the full parser document');
    assert.equal(f.db.get('SELECT count(*) AS n FROM chunks_fts')?.n, f.children.length);
    assert.equal(f.index.keyword(f.scope, 'revenue', 1).length, 1);
  } finally { f.close(); }
});

test('scoped hydration reads each document source once while preserving complete metadata', () => {
  const f = fixture();
  try {
    const transferred = observeLargeValues(f.db);
    const rows = records(f.db, f.scope);
    assert.equal(rows.length, f.children.length);
    assert.ok(transferred() <= JSON.stringify(f.metadata).length,
      'One source document must not be returned by SQLite once per matching child');
    for (const row of rows) assert.deepEqual(row.knowledge_metadata, f.metadata);
    assert.deepEqual(records(f.db, { ...f.scope, knowledgeBaseIds: [] }), []);
  } finally { f.close(); }
});

test('sequence collision checks use an indexed lookup while still rejecting actual duplicate IDs', () => {
  const f = fixture();
  try {
    const plan = f.db.all('EXPLAIN QUERY PLAN SELECT id FROM chunks WHERE seq_id=? AND id<>? LIMIT 1', 12345, 'fixture');
    assert.ok(plan.some(row => /SEARCH chunks .*\(seq_id=\?\)/.test(String(row.detail))),
      'Publishing every child must not scan the growing chunks table for its sequence ID');
    const first = f.children[0]!, second = f.children[1]!;
    f.db.update('chunks', String(first.id), { seq_id: 12345 });
    f.db.update('chunks', String(second.id), { seq_id: 12345 });
    assert.throws(() => f.index.indexKeyword(f.scope, String(first.id)), /collision/i);
    assert.equal(f.db.get('SELECT count(*) AS n FROM chunks_fts')?.n, 0);
  } finally { f.close(); }
});
