import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { JobError } from '../src/jobs/common.js';
import { SearchIndex } from '../src/retrieval/search-index.js';
import { CoreDatabase } from '../src/storage/database.js';

function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'marlin-publication-checkpoints-')), db = new CoreDatabase(root);
  const tenant = db.insert('tenants', { name: 'Checkpoint', api_key: 'checkpoint-fixture-only' });
  const kb = db.insert('knowledge_bases', { tenant_id: tenant.id, name: 'Checkpoint sources' });
  const doc = db.insert('knowledges', { tenant_id: tenant.id, knowledge_base_id: kb.id, title: 'Original context😀' });
  const common = { tenant_id: tenant.id, knowledge_base_id: kb.id, knowledge_id: doc.id };
  const scope = { tenantId: String(tenant.id), knowledgeBaseIds: [String(kb.id)] }, index = new SearchIndex(db);
  return { db, common, scope, index, close: () => { db.close(); rmSync(root, { recursive: true, force: true }); } };
}

test('insert checkpoint runs before and after real bounded batches and rolls back previously inserted rows', () => {
  const f = fixture();
  try {
    const previous = f.db.insert('chunks', { ...f.common, content: 'previous source' });
    const counts: number[] = [];
    assert.throws(() => f.db.insertMany('chunks', Array.from({ length: 75 }, (_, i) => ({ ...f.common, content: `new-${i}😀` })), () => {
      assert.equal(f.db.sqlite.inTransaction, true);
      counts.push(Number(f.db.get('SELECT count(*) AS n FROM chunks')?.n));
      if (counts.length === 2) throw new JobError(409, 'job_cancelled', 'Actual first batch checkpoint');
    }), (error: any) => error.code === 'job_cancelled');
    assert.equal(counts[0], 1); assert.ok(counts[1]! > 1 && counts[1]! < 76);
    assert.deepEqual(f.db.all('SELECT id,content FROM chunks'), [{ id: previous.id!, content: 'previous source' }]);
    assert.equal(f.db.sqlite.inTransaction, false); assert.deepEqual(f.db.all('PRAGMA foreign_key_check'), []);
  } finally { f.close(); }
});

test('FTS checkpoint after the actual 64-ID insert rolls back precise sequence registry and keyword generation', () => {
  const f = fixture();
  try {
    f.db.insertMany('chunks', Array.from({ length: 130 }, (_, i) => ({ ...f.common, id: `source-${i}`, seq_id: 9223372036854775677n + BigInt(i), content: `source-fact-${i}😀` })));
    const ids = f.db.all('SELECT id FROM chunks ORDER BY id').map(row => String(row.id)), counts: number[] = [];
    assert.throws(() => f.index.indexKeywords(f.scope, ids, undefined, () => {
      assert.equal(f.db.sqlite.inTransaction, true); counts.push(Number(f.db.get('SELECT count(*) AS n FROM chunks_fts')?.n));
      if (counts.length === 2) throw new JobError(409, 'job_cancelled', 'Actual first FTS insert checkpoint');
    }), (error: any) => error.code === 'job_cancelled');
    assert.deepEqual(counts, [0, 64]);
    assert.equal(f.db.get('SELECT count(*) AS n FROM chunks_fts')?.n, 0);
    assert.equal(f.db.get('SELECT count(*) AS n FROM retrieval_chunk_ids')?.n, 0);
    assert.equal(f.db.read('chunks', 'source-129')?.seq_id, '9223372036854775806');
    f.index.indexKeywords(f.scope, ids);
    assert.equal(f.index.keyword(f.scope, 'source-fact-129', 1)[0]?.chunk_id, 'source-129');
    assert.equal(f.db.get('SELECT rowid FROM retrieval_chunk_ids WHERE chunk_id=?', 'source-129')?.rowid, '9223372036854775806');
  } finally { f.close(); }
});

test('checkpoint callbacks reject async/thenable values and keep transaction and FTS sources atomic', async () => {
  const f = fixture();
  try {
    const rows = [{ ...f.common, id: 'actual-source', content: 'Source without async transaction' }];
    for (const callback of [async () => {}, () => Promise.reject(new Error('Controlled thenable'))]) {
      assert.throws(() => f.db.insertMany('chunks', rows, callback), /检查点必须同步/);
      assert.equal(f.db.get('SELECT count(*) AS n FROM chunks')?.n, 0);
      f.db.insertMany('chunks', rows);
      assert.throws(() => f.index.indexKeywords(f.scope, ['actual-source'], undefined, callback), (error: any) => error.code === 'invalid_checkpoint');
      assert.equal(f.db.get('SELECT count(*) AS n FROM chunks_fts')?.n, 0);
      assert.equal(f.db.get('SELECT count(*) AS n FROM retrieval_chunk_ids')?.n, 0);
      f.db.run('DELETE FROM chunks');
    }
    await Promise.resolve(); assert.equal(f.db.sqlite.inTransaction, false);
  } finally { f.close(); }
});
