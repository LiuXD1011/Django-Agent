import { createHash, randomUUID } from 'node:crypto';
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, renameSync, rmSync } from 'node:fs';
import { basename, dirname, join, resolve } from 'node:path';
import type BetterSqlite3 from 'better-sqlite3';
import * as sqliteVec from 'sqlite-vec';
import type { Json, JsonObject } from '../contracts.js';
import { CredentialVault } from './credentials.js';
import { CoreDatabase, openNativeDatabase } from './database.js';
import { assertSeparateRoots, copyDataFiles, copyVerifiedFiles, fileHash, listFiles, records, safeDataPath, StagedDirectory, verifyFiles, writePrivateJson, type FileRecord } from './files.js';
import { parseStoredJson } from './json.js';
import { tableDefinitions } from './schema-manifest.js';
import type { ColumnDefinition } from './schema-types.js';

interface TableRecord {
  count: number;
  source_digest: string;
  target_digest: string;
  defaulted_columns: string[];
  archived_columns: string[];
  verified_rows: number;
}

export interface ImportManifest {
  protocol: 1;
  source_version: string;
  fingerprint: string;
  tables: Record<string, TableRecord>;
  files: FileRecord[];
  indexes: { status: 'needs_rebuild'; legacy_index_archived: boolean };
  interrupted_tasks: number;
  warnings: string[];
}

interface BackupManifest { protocol: 1; kind: 'marlin-backup'; created_at: string; files: FileRecord[]; tables: Record<string, { count: number; digest: string }> }

function canonical(value: unknown): string {
  if (typeof value === 'bigint') return JSON.stringify(value.toString());
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(',')}}`;
  return JSON.stringify(value);
}

function digest(value: unknown): string { return createHash('sha256').update(canonical(value)).digest('hex'); }

function tableExists(database: BetterSqlite3.Database, name: string): boolean {
  return Boolean(database.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?").get(name));
}

function verifyDatabase(database: BetterSqlite3.Database): void {
  const integrity = database.pragma('integrity_check') as Array<{ integrity_check: string }>;
  if (integrity.length !== 1 || integrity[0]?.integrity_check !== 'ok') throw new Error('数据库完整性校验失败。');
  if ((database.pragma('foreign_key_check') as unknown[]).length) throw new Error('数据库关联完整性校验失败。');
}

function verifyOwnership(db: CoreDatabase): void {
  const known = new Map(tableDefinitions.map((table) => [table.name, new Set(table.columns.map((column) => column.name))]));
  const parents: Record<string, string> = { knowledge_base_id: 'knowledge_bases', knowledge_id: 'knowledges', session_id: 'sessions' };
  for (const table of tableDefinitions) {
    const columns = known.get(table.name)!;
    if (!columns.has('tenant_id')) continue;
    for (const [reference, parent] of Object.entries(parents)) {
      if (!columns.has(reference)) continue;
      const parentColumns = known.get(parent)!;
      const mismatch = ['tenant_id', 'knowledge_base_id', 'knowledge_id'].filter((column) => column !== reference && columns.has(column) && parentColumns.has(column)).map((column) => `child."${column}" IS NOT parent."${column}"`);
      if (mismatch.length && db.get(`SELECT 1 AS invalid FROM "${table.name}" child JOIN "${parent}" parent ON child."${reference}"=parent.id WHERE ${mismatch.join(' OR ')} LIMIT 1`)) throw new Error(`表 ${table.name} 存在跨空间或文档的归属错误。`);
    }
  }
  for (const column of ['context_parent_id', 'media_parent_id']) {
    if (db.get(`SELECT 1 AS invalid FROM chunks child JOIN chunks parent ON child."${column}"=parent.id WHERE child.tenant_id IS NOT parent.tenant_id OR child.knowledge_base_id IS NOT parent.knowledge_base_id OR child.knowledge_id IS NOT parent.knowledge_id LIMIT 1`)) throw new Error('分块父子归属不一致。');
  }
}

function sourceVersion(database: BetterSqlite3.Database): string {
  if (!tableExists(database, 'django_migrations')) throw new Error('旧数据库缺少版本记录，不能安全导入。');
  const rows = database.prepare("SELECT name FROM django_migrations WHERE app='personal_knowledge_base' ORDER BY name").all() as Array<{ name: string }>;
  if (!rows.length || rows.some((row) => !/^\d{4}_/.test(row.name) || Number(row.name.slice(0, 4)) > 26)) throw new Error('旧数据库版本不受当前导入工具支持。');
  for (const name of ['tenants', 'users', 'knowledge_bases', 'knowledges']) if (!tableExists(database, name)) throw new Error(`旧数据库缺少业务表 ${name}。`);
  return rows.at(-1)!.name;
}

function tableRows(database: BetterSqlite3.Database, table: string, primary: string): Record<string, unknown>[] {
  return database.prepare(`SELECT * FROM "${table}" ORDER BY "${primary}"`).all() as Record<string, unknown>[];
}

function decode(column: ColumnDefinition, value: unknown): unknown {
  if (value === null) return null;
  if (column.type === 'json') {
    if (typeof value !== 'string') throw new Error(`旧表 JSON 字段 ${column.name} 格式无效。`);
    try { return parseStoredJson(value); } catch { throw new Error(`旧表 JSON 字段 ${column.name} 校验失败。`); }
  }
  if (column.type === 'boolean') {
    if (value !== 0 && value !== 1 && value !== 0n && value !== 1n) throw new Error(`旧表布尔字段 ${column.name} 格式无效。`);
    return value === 1 || value === 1n;
  }
  return value;
}

/** Resolve only files already copied from the selected data root, never arbitrary absolute paths. */
function mediaMapper(files: FileRecord[]): (name: string, required?: boolean) => string {
  const names = new Set(files.map((file) => file.path));
  return (name, required = false) => {
    if (!name || /^(https?:|data:|s3:|cos:)/i.test(name)) return name;
    const clean = name.replaceAll('\\', '/');
    const marker = clean.lastIndexOf('/media/');
    const candidate = clean.startsWith('media/') ? clean : marker >= 0 ? clean.slice(marker + 1) : `media/${clean.replace(/^\/+/, '')}`;
    if (names.has(candidate)) return candidate;
    if (required) throw new Error('原始文档或媒体文件缺失，请恢复完整媒体目录后导入。');
    return name;
  };
}

function rewritePaths(value: Json, mapper: ReturnType<typeof mediaMapper>): Json {
  if (Array.isArray(value)) return value.map((item) => rewritePaths(item, mapper));
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(Object.entries(value).map(([name, item]) => [name, typeof item === 'string' && /^(file_path|storage_path|image_path|local_path|artifact_path|image_url)$/.test(name) ? mapper(item) : rewritePaths(item, mapper)]));
}

function verifyCredentials(db: CoreDatabase, vault: CredentialVault): void {
  for (const table of tableDefinitions) for (const column of table.columns.filter((item) => item.encrypted)) {
    for (const row of db.all(`SELECT "${column.name}" FROM "${table.name}" WHERE "${column.name}" IS NOT NULL`)) {
      const value = row[column.name];
      if (typeof value !== 'string') throw new Error('凭据格式校验失败。');
      vault.decrypt(JSON.parse(value) as Json);
    }
  }
}

function snapshotTables(db: CoreDatabase): BackupManifest['tables'] {
  const tables = db.all("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name");
  return Object.fromEntries(tables.map((table) => {
    const name = String(table.name);
    if (!/^[A-Za-z_][A-Za-z_0-9]*$/.test(name)) throw new Error('数据库包含无法安全校验的表名。');
    // Cover desktop job/event state, index metadata and extension shadow tables too.
    const rows = db.sqlite.prepare(`SELECT * FROM "${name}"`).all();
    const hashes = rows.map((row) => digest(row)).sort();
    return [name, { count: rows.length, digest: digest(hashes) }];
  }));
}

function repeatedImport(target: string, fingerprint: string): ImportManifest | undefined {
  if (!existsSync(target) || !readdirSync(target).length) return undefined;
  if (!existsSync(join(target, 'marlin.sqlite3'))) throw new Error('目标数据目录已有内容，请选择新的空目录。');
  const db = openNativeDatabase(join(target, 'marlin.sqlite3'), { readonly: true, fileMustExist: true });
  try {
    if (tableExists(db, 'desktop_imports')) {
      const row = db.prepare('SELECT manifest FROM desktop_imports WHERE fingerprint=?').get(fingerprint) as { manifest: string } | undefined;
      if (row) return JSON.parse(row.manifest) as ImportManifest;
    }
    throw new Error('目标已有不同的数据，不能覆盖；请使用新的空目录。');
  } finally { db.close(); }
}

/** One-time isolated import. The historical SQLite file is archived; no Django code runs. */
export async function importLegacy(options: { sourceRoot: string; targetRoot: string }): Promise<{ repeated: boolean; manifest: ImportManifest }> {
  const source = resolve(options.sourceRoot);
  const target = resolve(options.targetRoot);
  assertSeparateRoots(source, target);
  if (existsSync(target) && readdirSync(target).length && !existsSync(join(target, 'marlin.sqlite3'))) throw new Error('目标数据目录已有内容，请选择新的空目录。');
  const sourcePath = safeDataPath(source, 'db.sqlite3');
  if (!existsSync(sourcePath)) throw new Error('旧数据库文件不存在。');
  mkdirSync(dirname(target), { recursive: true, mode: 0o700 });
  const snapshot = mkdtempSync(join(dirname(target), `.${basename(target)}.import-snapshot-`));
  let stage: StagedDirectory | undefined;
  let legacy: BetterSqlite3.Database | undefined;
  let db: CoreDatabase | undefined;
  try {
    const snapshotDatabase = join(snapshot, 'legacy-source.sqlite3');
    const sourceDb = openNativeDatabase(sourcePath, { readonly: true, fileMustExist: true });
    try { await sourceDb.backup(snapshotDatabase); } finally { sourceDb.close(); }
    const copied = await copyDataFiles(source, snapshot);
    legacy = openNativeDatabase(snapshotDatabase, { readonly: true, fileMustExist: true });
    legacy.defaultSafeIntegers(); sqliteVec.load(legacy);
    verifyDatabase(legacy);
    const version = sourceVersion(legacy);
    const fingerprint = digest({ version, database: fileHash(snapshotDatabase), files: copied });
    const repeated = repeatedImport(target, fingerprint);
    if (repeated) return { repeated: true, manifest: repeated };
    stage = new StagedDirectory(target, source);
    await copyDataFiles(snapshot, stage.path);
    const archive = join(stage.path, 'archives', `legacy-import-${fingerprint.slice(0, 16)}`);
    if (existsSync(archive)) throw new Error('旧数据库归档名称发生冲突。');
    mkdirSync(archive, { recursive: true, mode: 0o700 });
    copyFileSync(snapshotDatabase, join(archive, 'db.sqlite3'));
    const originalFiles = records(stage.path, listFiles(stage.path));
    const copiedFiles = new Map(originalFiles.map(file => [file.path, file]));
    const mapper = mediaMapper(originalFiles);
    const sourceVault = new CredentialVault(source);
    const vault = new CredentialVault(stage.path);
    db = new CoreDatabase(stage.path);
    const core = db;
    const tables: Record<string, TableRecord> = {};
    const warnings: string[] = ['向量和全文索引需重建；旧索引原样保存在归档中。', 'Neo4j完整图数据需要独立导出；chunk关系和来源已保留。'];
    let interrupted = 0;
    core.transaction(() => {
      core.run('PRAGMA defer_foreign_keys=ON');
      for (const table of tableDefinitions) {
        const primary = table.columns.find((column) => column.primary)!.name;
        const rows = tableExists(legacy!, table.name) ? tableRows(legacy!, table.name, primary) : [];
        const sourceColumns = tableExists(legacy!, table.name) ? (legacy!.pragma(`table_info("${table.name}")`) as Array<{ name: string }>).map((column) => column.name) : [];
        const known = new Set(table.columns.map((column) => column.name));
        const defaulted = table.columns.filter((column) => !sourceColumns.includes(column.name)).map((column) => column.name);
        const archived = sourceColumns.filter((name) => !known.has(name));
        if (archived.length) warnings.push(`表 ${table.name} 的额外字段保留在原始数据库归档中。`);
        for (const original of rows) {
          const values: Record<string, unknown> = {};
          for (const column of table.columns) {
            if (!(column.name in original)) continue;
            let value = decode(column, original[column.name]);
            if (column.type === 'json' && value !== null) {
              value = rewritePaths(value as Json, mapper);
              if (column.encrypted) { sourceVault.decrypt(value as Json); value = vault.encrypt(value as Json); }
            }
            if (table.name === 'knowledges' && column.name === 'file_path' && typeof value === 'string' && value) value = mapper(value, original.type === 'file');
            if (table.name === 'knowledge_images' && column.name === 'storage_path' && typeof value === 'string') value = mapper(value, original.storage_owned === 1n || original.storage_owned === 1);
            values[column.name] = value;
          }
          if (table.name === 'knowledges' && values.type === 'file' && typeof values.file_path === 'string' && values.file_path.startsWith('media/')) {
            const copied = copiedFiles.get(values.file_path);
            if (!copied || fileHash(safeDataPath(stage!.path, values.file_path)) !== copied.sha256) throw new Error('原始文档文件哈希校验失败，请恢复匹配的原始文件。');
            if (values.file_hash && (typeof values.file_hash !== 'string' || copied.sha256 !== values.file_hash.toLowerCase())) throw new Error('原始文档文件哈希校验失败，请恢复匹配的原始文件。');
            const metadata = values.metadata ?? {};
            if (typeof metadata !== 'object' || Array.isArray(metadata)) throw new Error('原始文档元数据必须是对象。');
            // Ownership is established only after this import copied and verified
            // the selected root's file. No renderer path or unverified legacy flag
            // can authorize workflow reads or later managed-file cleanup.
            values.file_hash = copied.sha256;
            values.file_size = copied.size;
            values.metadata = { ...metadata, storage_owned: true };
          }
          if (table.name === 'knowledge_images' && values.storage_owned && typeof values.storage_path === 'string' && values.storage_path.startsWith('media/') && typeof values.content_hash === 'string' && values.content_hash) {
            if (fileHash(safeDataPath(stage!.path, values.storage_path)) !== values.content_hash.toLowerCase()) throw new Error('图片文件哈希校验失败。');
          }
          const written = core.insert(table.name, values);
          for (const column of table.columns) {
            if (!(column.name in values)) continue;
            let expected = values[column.name];
            if (column.type === 'integer' && expected !== null) {
              const integer = BigInt(expected as string | number | bigint);
              expected = integer >= BigInt(Number.MIN_SAFE_INTEGER) && integer <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(integer) : integer.toString();
            }
            if (canonical(expected) !== canonical(written[column.name])) throw new Error(`表 ${table.name} 字段 ${column.name} 导入后内容不一致。`);
          }
        }
        const targetRows = tableRows(core.sqlite, table.name, primary);
        if (rows.length !== targetRows.length) throw new Error(`表 ${table.name} 记录数校验失败。`);
        tables[table.name] = { count: rows.length, source_digest: digest(rows), target_digest: digest(targetRows), defaulted_columns: defaulted, archived_columns: archived, verified_rows: rows.length };
      }
      for (const task of core.all("SELECT * FROM task_records WHERE status IN ('pending','running')")) {
        const payload = parseStoredJson(String(task.payload)) as JsonObject;
        const tenant = payload.tenant_id ?? payload.tenantId ?? null;
        const user = payload.user_id ?? payload.userId ?? null;
        const now = new Date().toISOString();
        core.run("INSERT INTO desktop_jobs(id,tenant_id,user_id,request_id,kind,status,payload,result,error,recovery_policy,created_at,updated_at,finished_at) VALUES(?,?,?,?,?,'interrupted',?,?,?,'manual',?,?,?)", String(task.id), typeof tenant === 'number' || typeof tenant === 'string' ? tenant : null, typeof user === 'string' ? user : null, `legacy:${task.id}`, `legacy:${task.task_type}`, JSON.stringify({ input: payload, claim: null }), task.result === null ? null : String(task.result), '旧任务已中断；确认前不得重放未知付费请求。', now, now, now);
        interrupted++;
      }
      verifyDatabase(core.sqlite);
      verifyOwnership(core);
      verifyCredentials(core, vault);
    });
    for (const path of listFiles(stage.path, ['.settings']).filter((name) => name.endsWith('.json'))) {
      const absolute = safeDataPath(stage.path, path);
      let value: Json;
      try { value = parseStoredJson(readFileSync(absolute, 'utf8')); } catch { throw new Error('旧设置文件不是有效 JSON。'); }
      sourceVault.decrypt(value);
      const sealed = vault.encrypt(value);
      const replacement = `${absolute}.new-${randomUUID()}`;
      writePrivateJson(replacement, sealed);
      renameSync(replacement, absolute);
    }
    const manifest: ImportManifest = { protocol: 1, source_version: version, fingerprint, tables, files: records(stage.path, listFiles(stage.path)), indexes: { status: 'needs_rebuild', legacy_index_archived: true }, interrupted_tasks: interrupted, warnings };
    core.run('INSERT INTO desktop_imports(fingerprint,imported_at,source_version,manifest) VALUES(?,?,?,?)', fingerprint, new Date().toISOString(), version, JSON.stringify(manifest));
    core.run('INSERT INTO desktop_meta(key,value) VALUES(?,?)', 'legacy-import', JSON.stringify({ fingerprint, index_status: 'needs_rebuild', source_version: version }));
    writePrivateJson(join(stage.path, 'migration-manifest.json'), manifest);
    db.close(); db = undefined;
    verifyFiles(stage.path, manifest.files);
    stage.publish();
    return { repeated: false, manifest };
  } finally {
    db?.close(); legacy?.close(); stage?.finish(); rmSync(snapshot, { recursive: true, force: true });
  }
}

export async function createBackup(db: CoreDatabase, destination: string): Promise<BackupManifest> {
  const stage = new StagedDirectory(destination, db.dataRoot);
  let check: CoreDatabase | undefined;
  try {
    await db.backup(join(stage.path, 'marlin.sqlite3'));
    await copyDataFiles(db.dataRoot, stage.path);
    check = new CoreDatabase(stage.path);
    verifyDatabase(check.sqlite); verifyOwnership(check); verifyCredentials(check, new CredentialVault(stage.path));
    const tables = snapshotTables(check);
    check.close(); check = undefined;
    const files = records(stage.path, ['marlin.sqlite3', ...listFiles(stage.path)]);
    const manifest: BackupManifest = { protocol: 1, kind: 'marlin-backup', created_at: new Date().toISOString(), files, tables };
    writePrivateJson(join(stage.path, 'backup-manifest.json'), manifest);
    stage.publish(); return manifest;
  } finally { check?.close(); stage.finish(); }
}

/** Restore into a separate empty directory; the live application's DB is never overwritten. */
export async function restoreBackup(source: string, target: string): Promise<BackupManifest> {
  let manifest: BackupManifest;
  try { manifest = JSON.parse(readFileSync(safeDataPath(source, 'backup-manifest.json'), 'utf8')) as BackupManifest; }
  catch { throw new Error('备份清单缺失或无法读取。'); }
  if (manifest.protocol !== 1 || manifest.kind !== 'marlin-backup' || !Array.isArray(manifest.files) || !manifest.files.some((file) => file.path === 'marlin.sqlite3')) throw new Error('备份格式校验失败。');
  verifyFiles(source, manifest.files);
  const stage = new StagedDirectory(target, source);
  let db: CoreDatabase | undefined;
  try {
    copyVerifiedFiles(source, stage.path, manifest.files);
    db = new CoreDatabase(stage.path);
    verifyDatabase(db.sqlite); verifyOwnership(db); verifyCredentials(db, new CredentialVault(stage.path));
    if (canonical(snapshotTables(db)) !== canonical(manifest.tables)) throw new Error('备份记录数量或内容校验失败。');
    db.close(); db = undefined;
    stage.publish(); return manifest;
  } finally { db?.close(); stage.finish(); }
}
