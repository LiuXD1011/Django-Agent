import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { CoreDatabase, type BindValue } from '../src/storage/database.js';
import { tableDefinitions } from '../src/storage/schema-manifest.js';

function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'marlin-bulk-insert-'));
  const db = new CoreDatabase(root);
  const tenant = db.insert('tenants', { name: 'bulk fixture', api_key: 'bulk-fixture-only' });
  const kb = db.insert('knowledge_bases', { tenant_id: tenant.id, name: 'bulk' });
  const doc = db.insert('knowledges', { tenant_id: tenant.id, knowledge_base_id: kb.id, title: 'bulk' });
  const common = { tenant_id: tenant.id, knowledge_base_id: kb.id, knowledge_id: doc.id };
  return { db, tenant, kb, doc, common, close: () => { db.close(); rmSync(root, { recursive: true, force: true }); } };
}

test('bulk inserts validate and bind bounded batches without per-row reads, retaining defaults and exact integers', t => {
  const f = fixture();
  try {
    const columns = tableDefinitions.find(table => table.name === 'chunks')!.columns.length;
    const rows = Array.from({ length: 125 }, (_, i) => ({ ...f.common, content: `bulk-${i}😀`, chunk_index: i,
      seq_id: (1152921504606846975n + BigInt(i)).toString(), metadata: { nested: [i, true, null, '😀'] }, is_enabled: i % 2 === 0 }));
    const run = f.db.run.bind(f.db), get = f.db.get.bind(f.db);
    const inserts: number[] = []; let reads = 0;
    f.db.run = ((sql: string, ...args: BindValue[]) => { if (sql.startsWith('INSERT INTO "chunks"')) inserts.push(args.length); return run(sql, ...args); }) as typeof f.db.run;
    f.db.get = ((sql: string, ...args: BindValue[]) => { if (/SELECT \* FROM "chunks"/.test(sql)) reads++; return get(sql, ...args); }) as typeof f.db.get;
    assert.equal(f.db.insertMany('chunks', rows), undefined);
    assert.equal(reads, 0, 'No generated row needs to be rehydrated for this void API');
    assert.equal(inserts.length, Math.ceil(rows.length / Math.floor(900 / columns)));
    assert.ok(inserts.every(size => size <= 900));
    const bulkReads = reads, bulkInserts = inserts.slice();
    const stored = f.db.all('SELECT id FROM chunks ORDER BY chunk_index').map(row => f.db.read('chunks', row.id!)!);
    assert.equal(stored.length, rows.length);
    for (let i = 0; i < stored.length; i++) {
      assert.match(String(stored[i]!.id), /^[a-f0-9-]{36}$/);
      assert.equal(stored[i]!.seq_id, rows[i]!.seq_id);
      assert.equal(stored[i]!.is_enabled, rows[i]!.is_enabled);
      assert.deepEqual(stored[i]!.metadata, rows[i]!.metadata);
      assert.equal(stored[i]!.pre_chunk_id, ''); assert.equal(stored[i]!.context_parent_id, null);
      assert.equal(stored[i]!.flags, 1); assert.ok(Number.isFinite(Date.parse(String(stored[i]!.created_at))));
    }
    const returned = f.db.insert('chunks', { ...f.common, content: 'legacy return', metadata: { keep: true } });
    assert.equal(returned.is_enabled, true); assert.deepEqual(returned.metadata, { keep: true });
    t.diagnostic(JSON.stringify({ rows: rows.length, columns, insert_statements: bulkInserts.length,
      batch_parameters: bulkInserts, insert_reads: bulkReads }));
  } finally { f.close(); }
});

test('mixed explicit and generated auto primary keys preserve input order and precision', () => {
  const f = fixture();
  try {
    f.db.insertMany('tenants', [
      { name: 'auto before', api_key: 'bulk-before' },
      { id: '1152921504606846975', name: 'explicit', api_key: 'bulk-explicit' },
      { name: 'auto after', api_key: 'bulk-after' },
    ]);
    assert.equal(f.db.get("SELECT id FROM tenants WHERE name='auto before'")?.id, 2);
    assert.equal(f.db.get("SELECT id FROM tenants WHERE name='explicit'")?.id, '1152921504606846975');
    assert.equal(f.db.get("SELECT id FROM tenants WHERE name='auto after'")?.id, '1152921504606846976');
  } finally { f.close(); }
});

test('bulk and returning insert share all field validation and late validation rolls back prior batches', () => {
  const f = fixture();
  try {
    const cycle: Record<string, unknown> = {}; cycle.self = cycle;
    const invalid = [{ unknown_field: 'x' }, { is_enabled: 'true' }, { seq_id: Number.MAX_SAFE_INTEGER + 1 },
      { content: 42 }, { content: null }, { metadata: '{broken' }, { metadata: { nested: Infinity } },
      { metadata: new Date() }, { metadata: cycle }];
    for (const fields of invalid) {
      const row = { ...f.common, content: 'bad', ...fields };
      let original = '';
      assert.throws(() => f.db.insert('chunks', row), error => { original = (error as Error).message; return true; });
      assert.throws(() => f.db.insertMany('chunks', [...Array.from({ length: 40 }, (_, i) => ({ ...f.common, content: `valid-${i}` })), row]),
        error => (error as Error).message === original);
      assert.equal(f.db.get('SELECT count(*) AS n FROM chunks')?.n, 0);
    }
    for (const percentile of [NaN, Infinity, '0.5']) {
      let original = '';
      assert.throws(() => f.db.insert('semantic_chunk_cache', { percentile }), error => { original = (error as Error).message; return true; });
      assert.throws(() => f.db.insertMany('semantic_chunk_cache', [{ percentile }]), error => (error as Error).message === original);
      assert.equal(f.db.get('SELECT count(*) AS n FROM semantic_chunk_cache')?.n, 0);
    }
    assert.throws(() => f.db.insertMany('tenants', [{ name: 'real', api_key: 'real', storage_used: 0.5 }]), /精度/);
    assert.throws(() => f.db.insertMany('users; DROP TABLE chunks', []), /未知业务表/);
    assert.equal(f.db.insertMany('chunks', []), undefined);
    assert.equal(f.db.sqlite.inTransaction, false);
  } finally { f.close(); }
});

test('multi-value statement constraints retain row ordering and late foreign key failures are atomic', () => {
  const f = fixture();
  try {
    f.db.sqlite.exec('CREATE TABLE bulk_seen(position INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT); CREATE TRIGGER bulk_order AFTER INSERT ON chunks BEGIN INSERT INTO bulk_seen(content) VALUES(NEW.content); END');
    f.db.insertMany('chunks', Array.from({ length: 70 }, (_, i) => ({ ...f.common, content: `ordered-${i}` })));
    assert.deepEqual(f.db.all('SELECT content FROM bulk_seen ORDER BY position').map(row => row.content), Array.from({ length: 70 }, (_, i) => `ordered-${i}`));
    assert.throws(() => f.db.insertMany('chunks', [...Array.from({ length: 40 }, (_, i) => ({ ...f.common, content: `discard-${i}` })),
      { ...f.common, knowledge_id: 'missing-document', content: 'invalid foreign key' }]), /FOREIGN KEY/);
    assert.equal(f.db.get('SELECT count(*) AS n FROM chunks')?.n, 70);
    assert.equal(f.db.get('SELECT count(*) AS n FROM bulk_seen')?.n, 70, 'Trigger side effects share rollback');
  } finally { f.close(); }
});

test('a real later-batch SQLite trigger abort rolls back every bulk row and retains previous data', () => {
  const f = fixture();
  try {
    const previous = f.db.insert('chunks', { ...f.common, content: 'previous', chunk_index: -1 });
    f.db.sqlite.exec("CREATE TRIGGER bulk_fault BEFORE INSERT ON chunks WHEN NEW.chunk_index=45 BEGIN SELECT RAISE(ABORT,'bulk_late_failure'); END");
    assert.throws(() => f.db.insertMany('chunks', Array.from({ length: 90 }, (_, i) => ({ ...f.common, content: `new-${i}`, chunk_index: i }))), /bulk_late_failure/);
    assert.deepEqual(f.db.all('SELECT id,content FROM chunks'), [{ id: previous.id!, content: 'previous' }]);
    assert.equal(f.db.sqlite.inTransaction, false);
    assert.deepEqual(f.db.all('PRAGMA foreign_key_check'), []);
  } finally { f.close(); }
});

test('nested bulk insertion never commits its caller and an actual deferred commit fault rolls everything back', () => {
  const f = fixture();
  try {
    assert.throws(() => f.db.transaction(() => {
      f.db.sqlite.pragma('defer_foreign_keys=ON');
      f.db.update('knowledges', f.doc.id!, { description: 'must roll back' });
      f.db.insertMany('chunks', [{ ...f.common, content: 'valid' }, { ...f.common, knowledge_base_id: 'missing', content: 'deferred invalid' }]);
      assert.equal(f.db.get('SELECT count(*) AS n FROM chunks')?.n, 2);
      assert.equal(f.db.sqlite.inTransaction, true);
    }), /FOREIGN KEY/);
    assert.equal(f.db.get('SELECT count(*) AS n FROM chunks')?.n, 0);
    assert.equal(f.db.read('knowledges', f.doc.id!)?.description, '');
    assert.deepEqual(f.db.all('PRAGMA foreign_key_check'), []);
    f.db.transaction(() => {
      f.db.update('knowledges', f.doc.id!, { description: 'outer continues' });
      assert.throws(() => f.db.insertMany('chunks', [{ ...f.common, content: 'discard' }, { ...f.common, content: null }]), /不允许为空/);
      assert.equal(f.db.sqlite.inTransaction, true);
    });
    assert.equal(f.db.read('knowledges', f.doc.id!)?.description, 'outer continues');
    assert.equal(f.db.get('SELECT count(*) AS n FROM chunks')?.n, 0);
  } finally { f.close(); }
});
