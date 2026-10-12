import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import BetterSqlite3 from 'better-sqlite3';
import { CoreDatabase, openNativeDatabase } from '../src/storage/database.js';
import { ReadDatabase, type DatabaseReader } from '../src/storage/read-database.js';

function fixture() {
  const directory = mkdtempSync(join(tmpdir(), 'marlin-read-database 中文 '));
  const writer = new CoreDatabase(directory);
  const tenant = writer.insert('tenants', { name: 'old', api_key: 'readonly-fixture-key' });
  const reader = new ReadDatabase(writer.path, directory, { timeoutMs: 250 });
  const typedWriter: DatabaseReader = writer;
  return { directory, writer, typedWriter, tenant, reader, close() { reader.close(); writer.close(); rmSync(directory, { recursive: true, force: true }); } };
}

test('native read database never creates a missing file or data directory and requires existing WAL', () => {
  const directory = mkdtempSync(join(tmpdir(), 'marlin-read-missing 中文 '));
  try {
    const missing = join(directory, 'missing');
    assert.throws(() => new ReadDatabase(join(missing, 'marlin.sqlite3'), missing));
    assert.equal(existsSync(missing), false);
    assert.throws(() => new ReadDatabase(join(directory, 'missing.sqlite3'), directory));
    assert.equal(existsSync(join(directory, 'missing.sqlite3')), false);
    const path = join(directory, 'rollback.sqlite3');
    const initialized = openNativeDatabase(path); initialized.exec('CREATE TABLE fixture(value TEXT)'); initialized.close();
    assert.throws(() => new ReadDatabase(path, directory), /WAL/);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('readonly row codec equals owner decoding for exact 64-bit IDs, JSON, booleans, null and Unicode', () => {
  const f = fixture();
  try {
    const huge = 9223372036854775806n;
    const tenant = f.writer.insert('tenants', { id: huge, name: '大整数😀', api_key: 'huge-key', agent_config: null });
    const user = f.writer.insert('users', { username: 'codec', email: 'codec@example.invalid', password_hash: 'fixture', tenant_id: tenant.id,
      is_active: false, preferences: '{"number":1152921504606846975,"items":[true,null,"😀"]}' });
    assert.deepEqual(f.reader.read('tenants', huge), f.writer.read('tenants', huge));
    assert.deepEqual(f.reader.read('users', String(user.id)), f.writer.read('users', String(user.id)));
    assert.equal(f.reader.get('SELECT id FROM tenants WHERE id=?', huge)?.id, huge.toString());
    assert.deepEqual(f.reader.all('SELECT id FROM tenants WHERE id=?', huge), [{ id: huge.toString() }]);
    assert.equal(f.reader.get('SELECT ? AS id', Number.MAX_SAFE_INTEGER)?.id, Number.MAX_SAFE_INTEGER);
    assert.equal(f.reader.get('SELECT ? AS id', -9223372036854775807n)?.id, '-9223372036854775807');
    assert.equal(f.reader.read('users', 'not-present'), undefined);
    assert.throws(() => f.reader.read('users; DROP TABLE users', 'anything'), /未知业务表/);
    assert.throws(() => f.reader.read('sqlite_master', 'anything'), /未知业务表/);
    // Real corrupted-row fixture: normal owner writes correctly reject this
    // invalid JSON via SQLite CHECK, so bypass that constraint only here.
    f.writer.sqlite.pragma('ignore_check_constraints=ON');
    try { f.writer.run('UPDATE users SET preferences=? WHERE id=?', '{broken', String(user.id)); }
    finally { f.writer.sqlite.pragma('ignore_check_constraints=OFF'); }
    assert.throws(() => f.reader.read('users', String(user.id)), SyntaxError);
  } finally { f.close(); }
});

test('deferred snapshot retains one committed version while the sole writer commits, then releases it', () => {
  const f = fixture();
  try {
    const result = f.reader.snapshot(() => {
      const first = f.reader.get('SELECT name FROM tenants WHERE id=?', f.tenant.id as number);
      f.writer.transaction(() => { f.writer.update('tenants', f.tenant.id as number, { name: 'new' }); });
      return [first, f.reader.get('SELECT name FROM tenants WHERE id=?', f.tenant.id as number)];
    });
    assert.deepEqual(result, [{ name: 'old' }, { name: 'old' }]);
    assert.equal(f.reader.snapshot(() => f.reader.get('SELECT name FROM tenants WHERE id=?', f.tenant.id as number))?.name, 'new');
    assert.equal(f.typedWriter.read('tenants', f.tenant.id as number)?.name, 'new');
  } finally { f.close(); }
});

test('readonly statements and native connection deny mutations, DDL and ATTACH without exposing a writer', () => {
  const f = fixture();
  try {
    for (const method of ['run', 'insert', 'update', 'delete', 'backup', 'sqlite', 'orm']) assert.equal(method in f.reader, false);
    assert.equal(f.reader.path, f.writer.path); assert.equal(f.reader.dataRoot, f.directory);
    for (const sql of ["UPDATE tenants SET name='forbidden' RETURNING id", 'DELETE FROM tenants RETURNING id', 'CREATE TABLE forbidden(value)', 'PRAGMA user_version=999', 'PRAGMA query_only=OFF', '/* prefix */ PRAGMA query_only=OFF', 'EXPLAIN PRAGMA query_only=OFF', "ATTACH ':memory:' AS forbidden"]) {
      assert.throws(() => f.reader.get(sql), /只读|readonly|reader|read-only/i);
    }
    assert.equal(f.writer.read('tenants', f.tenant.id as number)?.name, 'old');
    assert.equal(f.writer.get("SELECT name FROM sqlite_master WHERE name='forbidden'"), undefined);
    assert.equal(f.reader.get('PRAGMA query_only')?.query_only, 1);
    // SQLite marks PRAGMA journal_mode as possibly writing even without an
    // assignment; keep the native guard and query its read-only table form.
    assert.equal(f.reader.get('SELECT journal_mode FROM pragma_journal_mode')?.journal_mode, 'wal');
  } finally { f.close(); }
});

test('snapshot rejects async or thenable work and errors release the actual native read transaction', () => {
  const f = fixture();
  try {
    let asyncEntered = false;
    assert.throws(() => f.reader.snapshot(async () => { asyncEntered = true; }), /同步/);
    assert.equal(asyncEntered, false);
    assert.throws(() => f.reader.snapshot(() => { f.reader.get('SELECT * FROM tenants'); return { then() {} }; }), /同步/);
    assert.throws(() => f.reader.snapshot(() => { f.reader.get('SELECT * FROM tenants'); throw new Error('owned snapshot failure'); }), /owned snapshot failure/);
    f.writer.update('tenants', f.tenant.id as number, { name: 'after error' });
    assert.equal(f.reader.snapshot(() => f.reader.snapshot(() => f.reader.get('SELECT name FROM tenants')))!.name, 'after error');
    assert.equal(f.writer.get('PRAGMA wal_checkpoint(TRUNCATE)')?.busy, 0);
    f.reader.close(); f.reader.close(); assert.throws(() => f.reader.get('SELECT 1'));
  } finally { f.close(); }
});

test('opening, reading and closing with existing FTS/vec schema performs no initialization writes', () => {
  const f = fixture();
  try {
    f.writer.run('CREATE VIRTUAL TABLE read_fixture_vec USING vec0(embedding float[2])');
    f.writer.run('INSERT INTO chunks_fts(rowid,content) VALUES(?,?)', 1, 'readonly fixture');
    f.reader.close();
    const tablesBefore = f.writer.all('SELECT type,name,sql FROM sqlite_master ORDER BY type,name');
    const versionsBefore = f.writer.all('SELECT * FROM desktop_schema_versions');
    const metaBefore = f.writer.all('SELECT * FROM desktop_meta');
    const jobsBefore = f.writer.all('SELECT * FROM desktop_jobs');
    const filesBefore = readdirSync(f.directory).sort();
    const reader = new ReadDatabase(f.writer.path, f.directory);
    try {
      assert.equal(reader.get("SELECT count(*) AS n FROM chunks_fts WHERE chunks_fts MATCH 'readonly'")?.n, 1);
      assert.equal(reader.get('SELECT name FROM tenants')?.name, 'old');
      assert.equal(reader.get("SELECT name FROM sqlite_master WHERE name='read_fixture_vec'")?.name, 'read_fixture_vec');
    } finally { reader.close(); }
    assert.deepEqual(f.writer.all('SELECT type,name,sql FROM sqlite_master ORDER BY type,name'), tablesBefore);
    assert.deepEqual(f.writer.all('SELECT * FROM desktop_schema_versions'), versionsBefore);
    assert.deepEqual(f.writer.all('SELECT * FROM desktop_meta'), metaBefore);
    assert.deepEqual(f.writer.all('SELECT * FROM desktop_jobs'), jobsBefore);
    assert.deepEqual(readdirSync(f.directory).sort(), filesBefore);
  } finally { f.close(); }
});

test('ReadDatabase uses the actual native readonly handle and SQLite itself denies an INSERT', () => {
  const f = fixture(), original = BetterSqlite3.prototype.prepare;
  let readonly: boolean | undefined, nativeCode: string | undefined;
  try {
    // Observe the real native handle during one private fixture query. This
    // never substitutes a database, and the product exposes no native handle.
    BetterSqlite3.prototype.prepare = function(sql: string) {
      if (sql === 'SELECT 17 AS readonly_probe') {
        readonly = this.readonly;
        try { original.call(this, "INSERT INTO desktop_meta(key,value) VALUES('readonly-probe','forbidden')").run(); }
        catch (error) { nativeCode = (error as { code?: string }).code; }
      }
      return original.call(this, sql);
    } as typeof original;
    assert.equal(f.reader.get('SELECT 17 AS readonly_probe')?.readonly_probe, 17);
    assert.equal(readonly, true);
    assert.equal(nativeCode, 'SQLITE_READONLY');
    assert.equal(f.writer.get("SELECT value FROM desktop_meta WHERE key='readonly-probe'"), undefined);
  } finally { BetterSqlite3.prototype.prepare = original; f.close(); }
});
