import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { CoreDatabase } from '../src/storage/database.js';

function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'marlin-statement-reuse-'));
  const db = new CoreDatabase(root);
  const prepare = db.sqlite.prepare.bind(db.sqlite);
  const prepared: string[] = [];
  db.sqlite.prepare = ((sql: string) => {
    prepared.push(sql);
    return prepare(sql);
  }) as typeof db.sqlite.prepare;
  return { db, prepared, close: () => { db.close(); rmSync(root, { recursive: true, force: true }); } };
}

test('repeated parameter queries compile once while every get and all binds its current input', () => {
  const f = fixture();
  try {
    for (let i = 0; i < 300; i++) {
      assert.equal(f.db.get('SELECT ? AS value', i)?.value, i);
      assert.deepEqual(f.db.all('SELECT ? AS value', `scope-${i}`), [{ value: `scope-${i}` }]);
    }
    assert.equal(f.prepared.filter(sql => sql === 'SELECT ? AS value').length, 1,
      'The large-document loop must not compile identical SQL for every chunk');
  } finally { f.close(); }
});

test('statement retention is bounded and recent queries survive a stream of distinct SQL', () => {
  const f = fixture();
  try {
    f.db.get('SELECT 42 AS first');
    for (let i = 0; i < 300; i++) f.db.get(`SELECT ${i} AS evictable`);
    f.db.get('SELECT 42 AS first');
    f.db.get('SELECT 42 AS first');
    assert.equal(f.prepared.filter(sql => sql === 'SELECT 42 AS first').length, 2);
  } finally { f.close(); }
});

test('reused statements observe schema changes and transaction rollback without retaining row data', () => {
  const f = fixture();
  try {
    f.db.run('CREATE TABLE statement_fixture(value TEXT)');
    f.db.run('INSERT INTO statement_fixture(value) VALUES(?)', 'original');
    assert.deepEqual(f.db.all('SELECT * FROM statement_fixture'), [{ value: 'original' }]);
    f.db.sqlite.exec('ALTER TABLE statement_fixture ADD COLUMN revision INTEGER DEFAULT 2');
    assert.deepEqual(f.db.all('SELECT * FROM statement_fixture'), [{ value: 'original', revision: 2 }]);
    assert.throws(() => f.db.transaction(() => {
      f.db.run('INSERT INTO statement_fixture(value) VALUES(?)', 'rolled-back');
      throw new Error('intentional rollback');
    }), /intentional rollback/);
    f.db.run('INSERT INTO statement_fixture(value) VALUES(?)', 'committed');
    assert.deepEqual(f.db.all('SELECT value FROM statement_fixture ORDER BY rowid'), [{ value: 'original' }, { value: 'committed' }]);
    assert.equal(f.prepared.filter(sql => sql === 'INSERT INTO statement_fixture(value) VALUES(?)').length, 1);
  } finally { f.close(); }
});
