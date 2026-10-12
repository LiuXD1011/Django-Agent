// Root-executed only: installed native validation of the newly owned clone.
// All output is counts/hashes; no auth, HTTP, models or original source DB.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, lstatSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join, normalize } from 'node:path';
import { pathToFileURL } from 'node:url';

export const canonical = value => typeof value === 'bigint' ? JSON.stringify(value.toString()) : Array.isArray(value)
  ? `[${value.map(canonical).join(',')}]` : value && typeof value === 'object'
    ? `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(',')}}` : JSON.stringify(value);
const hash = value => createHash('sha256').update(value).digest('hex');
const digest = value => hash(canonical(value));
const fail = code => { throw new Error(code); };
const expect = (condition, code) => { if (!condition) fail(code); };
export function portable(name) {
  expect(typeof name === 'string' && name && !/[\\:\x00-\x1f<>"|?*]/.test(name) && !name.startsWith('/'), 'unsafe_relative_path');
  for (const part of name.split('/')) expect(part && part !== '.' && part !== '..' && !/[. ]$/.test(part)
    && !/^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(part), 'nonportable_path');
  return name;
}

async function main() {
  const [root, data, backup, output, mode] = process.argv.slice(2);
  const owned = 'C:\\Users\\lxd\\AppData\\Local\\Temp\\Marlin 安装验收 20261010';
  expect(process.platform === 'win32' && process.arch === 'x64' && process.version === 'v22.23.2', 'bundled_windows_node_required');
  expect(normalize(root) === join(owned, '应用', 'resources', 'runtime') && normalize(data) === join(owned, '浏览器资料副本 20261012 第1轮')
    && normalize(backup) === join(owned, '.offline-clone-launch-20261012-1', '已冻结备份') && ['exact', 'after-gui'].includes(mode), 'fixed_owned_scope_required');
  expect(['after-restore', 'before-hidden-smoke', 'after-hidden-smoke', 'before-visible-clone', 'after-visible-clone']
    .some(label => normalize(output) === join(owned, '.offline-clone-launch-20261012-1', label, 'audit.json')), 'owned_audit_output_required');
  expect(normalize(process.execPath) === join(root, 'node', 'node.exe') && process.env.PATH === 'C:\\Windows\\System32', 'system_runtime_refused');
  expect(!existsSync(output), 'audit_output_exists');
  const core = join(root, 'core'), requireCore = createRequire(join(core, 'package.json'));
  for (const name of ['better-sqlite3', 'sqlite-vec']) expect(requireCore.resolve(name).startsWith(join(core, 'node_modules') + '\\'), 'foreign_native_module_refused');
  const { CoreDatabase, openNativeDatabase } = await import(pathToFileURL(join(core, 'dist/storage/database.js')).href);
  const { fileHash, safeDataPath } = await import(pathToFileURL(join(core, 'dist/storage/files.js')).href);
  const { tableDefinitions } = await import(pathToFileURL(join(core, 'dist/storage/schema-manifest.js')).href);
  const { CredentialVault } = await import(pathToFileURL(join(core, 'dist/storage/credentials.js')).href);
  const manifest = JSON.parse(readFileSync(join(backup, 'backup-manifest.json'), 'utf8'));
  const fileHashes = {};
  for (const item of manifest.files.filter(file => file.path !== 'marlin.sqlite3')) {
    portable(item.path); const path = safeDataPath(data, item.path);
    expect(lstatSync(path).isFile() && lstatSync(path).size === item.size && fileHash(path) === item.sha256, 'cloned_managed_file_changed');
    fileHashes[item.path] = item.sha256;
  }
  const managedNames = [];
  const visit = relative => {
    const path = safeDataPath(data, portable(relative)), info = lstatSync(path);
    expect(!info.isSymbolicLink(), 'clone_managed_symlink_refused');
    if (info.isDirectory()) for (const name of readdirSync(path)) visit(relative + '/' + name);
    else { expect(info.isFile(), 'clone_managed_special_file_refused'); managedNames.push(relative); }
  };
  for (const scope of ['media', '.settings', '.secrets', '.cache', 'archives']) if (existsSync(join(data, scope))) visit(scope);
  expect(digest(managedNames.sort()) === digest(Object.keys(fileHashes).sort()), 'clone_managed_file_set_changed');
  expect(lstatSync(join(data, '.secrets', 'credentials.key')).size === 32, 'cloned_credential_key_invalid');
  const mutableAuth = new Set(['device_sessions', 'device_refresh_tokens', 'auth_tokens', 'desktop_meta']);
  const checked = new Set([...tableDefinitions.map(table => table.name), 'desktop_meta', 'desktop_imports', 'desktop_jobs', 'desktop_job_steps', 'desktop_job_events', 'desktop_schema_versions', 'search_index_meta']);
  const db = new CoreDatabase(data); let state;
  try {
    expect(db.sqlite.pragma('integrity_check').length === 1 && db.sqlite.pragma('integrity_check')[0].integrity_check === 'ok', 'clone_integrity_failed');
    expect(db.sqlite.pragma('foreign_key_check').length === 0, 'clone_foreign_keys_failed');
    const tables = {}, protectedTables = {}, names = db.all("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name");
    expect(digest(names.map(row => row.name).sort()) === digest(Object.keys(manifest.tables).sort()), 'clone_table_set_changed');
    for (const { name } of names) {
      expect(/^[A-Za-z_][A-Za-z_0-9]*$/.test(name), 'invalid_table_name');
      const count = Number(db.get(`SELECT count(*) AS n FROM "${name}"`).n); expect(Number.isSafeInteger(count), 'unsafe_table_count');
      tables[name] = { count };
      if (mode === 'exact' || !mutableAuth.has(name)) expect(count === manifest.tables[name].count, 'clone_table_count_changed');
      if (checked.has(name)) {
        // Stream native raw values; no full vec-shadow BLOB hydration here.
        // Formal restore already checked every table's complete canonical digest.
        const hashes = [];
        for (const row of db.sqlite.prepare(`SELECT * FROM "${name}"`).iterate()) hashes.push(digest(row));
        const table = { count, digest: digest(hashes.sort()) };
        if (mode === 'exact' || !mutableAuth.has(name)) expect(digest(table) === digest(manifest.tables[name]), 'clone_business_table_changed');
        if (!mutableAuth.has(name)) protectedTables[name] = table;
      }
    }
    for (const [table, states] of [['desktop_jobs', ['queued', 'running']], ['task_records', ['pending', 'running']], ['agent_actors', ['queued', 'running', 'pending']]])
      expect(Number(db.get(`SELECT count(*) AS n FROM "${table}" WHERE status IN (${states.map(() => '?').join(',')})`, ...states).n) === 0, 'clone_active_work_refused');
    expect(!db.get("SELECT 1 AS n FROM desktop_meta WHERE key='ipc.receipts'"), 'clone_pending_auth_receipts_refused');
    expect(!db.get("SELECT 1 AS n FROM generic_resources WHERE json_extract(data,'$.generation.status')='running' LIMIT 1"), 'clone_active_generation_refused');
    const metaHashes = [...db.sqlite.prepare("SELECT * FROM desktop_meta WHERE key NOT IN ('ipc.session','ipc.receipts')").iterate()].map(digest).sort();
    let decryptedFields = 0;
    const vault = new CredentialVault(data);
    for (const table of tableDefinitions) for (const column of table.columns.filter(item => item.encrypted)) {
      for (const row of db.all(`SELECT "${column.name}" FROM "${table.name}" WHERE "${column.name}" IS NOT NULL`)) {
        expect(typeof row[column.name] === 'string', 'clone_encrypted_field_invalid');
        vault.decrypt(JSON.parse(row[column.name])); decryptedFields++;
      }
    }
    const files = new Map(manifest.files.map(file => [file.path, file])); let media = 0, external = 0;
    const verify = (name, expected) => {
      if (/^(https?:|data:)/i.test(name)) { external++; return; }
      portable(name); const file = files.get(name);
      expect(file && typeof expected === 'string' && /^[a-f0-9]{64}$/i.test(expected) && file.sha256 === expected.toLowerCase(), 'clone_media_reference_invalid'); media++;
    };
    for (const row of db.all("SELECT file_path,file_hash FROM knowledges WHERE type='file' AND deleted_at IS NULL AND file_path<>''")) verify(row.file_path, row.file_hash);
    for (const row of db.all("SELECT storage_path,content_hash FROM knowledge_images WHERE deleted_at IS NULL AND storage_path<>''")) verify(row.storage_path, row.content_hash);
    state = { tables, protected_tables: protectedTables, managed_files_sha256: fileHashes, credential_fields_authenticated: decryptedFields,
      protected_desktop_meta_sha256: digest(metaHashes), active_work: 0, pending_auth_receipts: 0, verified_media: media, external_references_not_verified: external,
      all_table_digest_verified_at_formal_restore: true, extension_shadow_digest_repeated: false };
  } finally { db.close(); }
  const native = openNativeDatabase(':memory:'); let nativeResult;
  try {
    native.defaultSafeIntegers(); requireCore('sqlite-vec').load(native);
    native.exec('CREATE VIRTUAL TABLE f USING fts5(content); CREATE VIRTUAL TABLE v USING vec0(embedding float[2])');
    const id = (1n << 60n) + 321n;
    native.prepare('INSERT INTO f(rowid,content) VALUES(?,?)').run(id, 'native offline clone verification');
    native.prepare('INSERT INTO v(rowid,embedding) VALUES(?,?)').run(id, new Float32Array([0.25, 0.75]));
    assert.equal(native.prepare("SELECT rowid FROM f WHERE f MATCH 'clone'").get().rowid, id);
    const vector = native.prepare('SELECT rowid,distance FROM v WHERE embedding MATCH ? AND k=1').get(new Float32Array([0.25, 0.75]));
    assert.equal(vector.rowid, id); assert.equal(vector.distance, 0);
    nativeResult = { sqlite_version: native.prepare('SELECT sqlite_version() AS version').get().version, vec_version: native.prepare('SELECT vec_version() AS version').get().version, exact_native_id: id.toString() };
  } finally { native.close(); }
  writeFileSync(output, JSON.stringify({ ok: true, mode, ...state, native: nativeResult, original_source_database_opened: false, auth_or_model_requests: 0 }, null, 2) + '\n', { flag: 'wx' });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main().catch(() => {
  process.stderr.write('clone_audit_refused\n'); process.exitCode = 1;
});
