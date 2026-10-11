import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

async function implementation() {
  const implementation = await import('../src/storage/database.js').catch(() => null);
  assert.ok(implementation, 'TypeScript database and migrations must exist');
  return implementation;
}

test('fresh real SQLite creates all business tables, actual FTS5/vec extensions and durable defaults', async () => {
  const { CoreDatabase } = await implementation();
  const root = mkdtempSync(join(tmpdir(), 'marlin-db-'));
  let db;
  try {
    db = new CoreDatabase(root);
    assert.equal(db.all("select name from sqlite_master where type='table' and name='users'").length, 1);
    assert.equal(db.all("select name from sqlite_master where type='table' and name='integration_configs'").length, 1);
    assert.equal(db.get('select vec_version() as version')?.version, 'v0.1.9');
    db.run('insert into chunks_fts(rowid,content) values (?,?)', 1, '沧澜计划预算46.8万元');
    // SQLite's trigram tokenizer indexes at least three code points. Short Chinese
    // queries belong to the scoped LIKE fallback covered by retrieval.test.ts.
    assert.equal(db.all("select rowid from chunks_fts where chunks_fts match '沧澜计'").length, 1);
    const tenant = db.insert('tenants', { name: '验收空间', api_key: 'test-space-key' });
    const user = db.insert('users', { username: 'qa', email: 'qa@example.invalid', password_hash: 'test-hash', tenant_id: tenant.id });
    assert.equal(user.is_active, true);
    assert.deepEqual(user.preferences, {});
    db.close();
    db = new CoreDatabase(root);
    assert.equal(db.get('select username from users where id=?', user.id)?.username, 'qa');
    assert.equal(db.all('select version from desktop_schema_versions').length, 1);
  } finally { db?.close(); rmSync(root, { recursive: true, force: true }); }
});

test('relationships cascade, invalid foreign keys fail, rollback is complete and indexes keep 60-bit IDs precise', async () => {
  const { CoreDatabase } = await implementation();
  const root = mkdtempSync(join(tmpdir(), 'marlin-db-integrity-'));
  const db = new CoreDatabase(root);
  try {
    const tenant = db.insert('tenants', { name: '验收空间', api_key: 'test-space-key' });
    const kb = db.insert('knowledge_bases', { tenant_id: tenant.id, name: '验收库' });
    const doc = db.insert('knowledges', { tenant_id: tenant.id, knowledge_base_id: kb.id, type: 'file', title: '测试.md', source: 'upload' });
    const preciseId = 1152921504606846975n;
    const chunk = db.insert('chunks', { tenant_id: tenant.id, knowledge_base_id: kb.id, knowledge_id: doc.id, content: '精确ID', chunk_index: 0, seq_id: preciseId.toString() });
    assert.equal(chunk.seq_id, preciseId.toString());
    assert.equal(db.get('select seq_id from chunks where id=?', chunk.id)?.seq_id, preciseId.toString());
    assert.throws(() => db.insert('knowledges', { tenant_id: tenant.id, knowledge_base_id: 'missing-kb', type: 'file', title: '坏关联', source: 'upload' }), /FOREIGN KEY/);
    assert.throws(() => db.transaction(() => {
      db.insert('knowledge_bases', { tenant_id: tenant.id, name: '应回滚' });
      throw new Error('planned failure');
    }), /planned failure/);
    assert.equal(db.get('select count(*) as count from knowledge_bases')?.count, 1);
    assert.throws(() => db.transaction(async () => 1), /同步|synchronous/i);
    db.run('delete from knowledge_bases where id=?', kb.id);
    assert.equal(db.get('select count(*) as count from knowledges')?.count, 0);
    assert.equal(db.get('select count(*) as count from chunks')?.count, 0);
    assert.deepEqual(db.all('pragma foreign_key_check'), []);
  } finally { db.close(); rmSync(root, { recursive: true, force: true }); }
});

test('table/column names are closed, invalid JSON/inexact integers cannot silently corrupt data', async () => {
  const { CoreDatabase } = await implementation();
  const root = mkdtempSync(join(tmpdir(), 'marlin-db-validation-'));
  const db = new CoreDatabase(root);
  try {
    assert.throws(() => db.insert('users; drop table users', {}), /表|table/i);
    assert.throws(() => db.insert('users', { unknown_column: 'x' }), /字段|column/i);
    assert.throws(() => db.insert('tenants', { name: 'bad', api_key: 'qa', storage_quota: Number.MAX_SAFE_INTEGER + 1 }), /精度|safe|integer/i);
    assert.throws(() => db.insert('tenants', { name: 'bad', api_key: 'qa', retriever_engines: 'not-valid-json' }), /JSON/i);
    for (const invalid of [{ nested: NaN }, { nested: Infinity }, { nested: undefined }, [undefined], new Date()]) {
      assert.throws(() => db.insert('tenants', { name: 'bad', api_key: 'qa', retriever_engines: invalid }), /JSON/i);
    }
    assert.throws(() => db.insert('tenants', { id: null, name: 'bad', api_key: 'qa' }), /空|必填/i);
    assert.equal(db.get('select count(*) as count from tenants')?.count, 0);
  } finally { db.close(); rmSync(root, { recursive: true, force: true }); }
});
