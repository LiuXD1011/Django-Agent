import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { CoreDatabase, openNativeDatabase } from '../src/storage/database.js';
import { CredentialVault } from '../src/storage/credentials.js';
import { JobQueue } from '../src/jobs/index.js';
import { AuthService, hashPassword } from '../src/auth/index.js';
import { ModelConfigurationService } from '../src/settings/index.js';
import { DocumentParser } from '../src/documents/parser.js';
import { DocumentWorkflow } from '../src/documents/workflow.js';
import { resolve } from 'node:path';

async function implementation() {
  const module = await import('../src/storage/legacy.js').catch(() => null);
  assert.ok(module, 'Legacy importer and verified backup must exist without Django');
  return module;
}

function fixture(root: string) {
  const source = join(root, '旧资料 空格');
  const db = new CoreDatabase(source);
  const vault = new CredentialVault(source);
  const tenant = db.insert('tenants', { name: '旧空间', api_key: 'test-legacy-api-key' });
  const user = db.insert('users', { username: 'migration-qa', email: 'migration@example.invalid', password_hash: 'pbkdf2_sha256$260000$unchanged$encoded', tenant_id: tenant.id });
  const kb = db.insert('knowledge_bases', { tenant_id: tenant.id, name: '沧澜计划', creator_id: user.id });
  const mediaPath = join(source, 'media', '原始文档', '中文 资料.md');
  mkdirSync(join(source, 'media', '原始文档'), { recursive: true });
  writeFileSync(mediaPath, '# 沧澜计划\n预算46.8万元。🪸\n');
  const hash = createHash('sha256').update(readFileSync(mediaPath)).digest('hex');
  const doc = db.insert('knowledges', { tenant_id: tenant.id, knowledge_base_id: kb.id, type: 'file', title: '中文 资料.md', source: 'upload', file_name: '中文 资料.md', file_path: mediaPath, file_hash: hash, parse_status: 'completed' });
  const chunk = db.insert('chunks', { tenant_id: tenant.id, knowledge_base_id: kb.id, knowledge_id: doc.id, content: '预算46.8万元。🪸', chunk_index: 0, seq_id: '1152921504606846975', metadata: { nested: ['保留', null], legacy_seq_id: '1152921504606846975' } });
  // A Python JSON writer stored the large ID as an unquoted integer.
  db.run('update chunks set metadata=? where id=?', '{"nested":["保留",null],"legacy_seq_id":1152921504606846975}', String(chunk.id));
  const model = db.insert('models', { id: 'migration-test-model', tenant_id: tenant.id, name: 'fixture', type: 'KnowledgeQA', source: 'custom', parameters: vault.encrypt({ base_url: 'https://example.invalid/v1', api_key: 'test-only-import-secret' }) });
  db.insert('generic_resources', { tenant_id: tenant.id, resource_type: 'opaque-business-config', data: { enabled: true, values: [1, null, '中文'] } });
  db.insert('wiki_pages', { tenant_id: tenant.id, knowledge_base_id: kb.id, slug: '沧澜/预算', title: '预算', content: '|金额|\n|---|\n|46.8|', source_refs: [{ knowledge_id: doc.id, chunk_id: chunk.id }] });
  db.insert('task_records', { task_type: 'evaluation', status: 'running', payload: { tenant_id: tenant.id, user_id: user.id }, result: { partial: true, paid_call_result_unknown: true } });
  db.run('create table django_migrations(id integer primary key, app text, name text, applied text)');
  db.run('insert into django_migrations(app,name,applied) values(?,?,?)', 'personal_knowledge_base', '0026_personal_spaces', '2026-10-01');
  db.close();
  renameSync(join(source, 'marlin.sqlite3'), join(source, 'db.sqlite3'));
  return { source, tenant, user, kb, doc, chunk, model, mediaPath, hash };
}

test('legacy import preserves all identities, JSON, 60-bit refs, passwords, ciphertext and media; repeated import is inert', async () => {
  const { importLegacy } = await implementation();
  const root = mkdtempSync(join(tmpdir(), 'marlin-import-'));
  let db;
  try {
    const f = fixture(root);
    const originalDb = readFileSync(join(f.source, 'db.sqlite3'));
    const originalKey = readFileSync(join(f.source, '.secrets', 'credentials.key'));
    const target = join(root, '新桌面 空格');
    const result = await importLegacy({ sourceRoot: f.source, targetRoot: target });
    assert.equal(result.repeated, false);
    assert.equal(Object.keys(result.manifest.tables).length, 31);
    assert.equal(result.manifest.tables.chunks?.count, 1);
    assert.equal(result.manifest.indexes.status, 'needs_rebuild');
    db = new CoreDatabase(target);
    assert.equal(db.read('users', String(f.user.id))?.password_hash, f.user.password_hash);
    assert.equal(db.read('chunks', String(f.chunk.id))?.seq_id, f.chunk.seq_id);
    assert.deepEqual(db.read('chunks', String(f.chunk.id))?.metadata, f.chunk.metadata);
    assert.deepEqual(db.read('models', String(f.model.id))?.parameters, f.model.parameters);
    assert.equal(new CredentialVault(target).decrypt(db.read('models', String(f.model.id))!.parameters as { api_key: string }).api_key, 'test-only-import-secret');
    assert.equal(db.read('knowledges', String(f.doc.id))?.file_path, 'media/原始文档/中文 资料.md');
    assert.equal(createHash('sha256').update(readFileSync(join(target, 'media', '原始文档', '中文 资料.md'))).digest('hex'), f.hash);
    assert.equal(db.get('select status from desktop_jobs')?.status, 'interrupted', 'unknown paid calls cannot resume automatically');
    const jobs = new JobQueue(db);
    const interrupted = jobs.list({ tenantId: String(f.tenant.id), userId: String(f.user.id) });
    assert.equal(interrupted.length, 1);
    assert.deepEqual(interrupted[0]?.payload, { tenant_id: f.tenant.id, user_id: f.user.id }, 'migration preserves retry inputs through the actual queue envelope');
    assert.equal(db.get('select status from task_records')?.status, 'running', 'historical record is preserved for the migration report');
    assert.deepEqual(db.all('pragma foreign_key_check'), []);
    db.close(); db = undefined;
    const repeated = await importLegacy({ sourceRoot: f.source, targetRoot: target });
    assert.equal(repeated.repeated, true);
    db = new CoreDatabase(target);
    assert.equal(db.get('select count(*) as count from chunks')?.count, 1);
    assert.deepEqual(readFileSync(join(f.source, 'db.sqlite3')), originalDb);
    assert.deepEqual(readFileSync(join(f.source, '.secrets', 'credentials.key')), originalKey);
    assert.deepEqual(readFileSync(join(target, '.secrets', 'credentials.key')), originalKey);
  } finally { db?.close(); rmSync(root, { recursive: true, force: true }); }
});

test('only copied and verified legacy originals become workflow-owned and retain safe source bytes', async () => {
  const { importLegacy } = await implementation();
  const root = mkdtempSync(join(tmpdir(), 'marlin-import-workflow-'));
  let db: CoreDatabase | undefined, workflow: DocumentWorkflow | undefined, jobs: JobQueue | undefined;
  try {
    const f = fixture(root);
    const source = openNativeDatabase(join(f.source, 'db.sqlite3'));
    source.prepare('UPDATE users SET password_hash=? WHERE id=?').run(hashPassword('import-workflow-test-password'),String(f.user.id));
    source.close();
    const target=join(root,'new');
    await importLegacy({sourceRoot:f.source,targetRoot:target});
    db=new CoreDatabase(target);
    const doc=db.read('knowledges',String(f.doc.id))!;
    assert.equal((doc.metadata as any).storage_owned,true);
    assert.equal(doc.file_hash,f.hash);
    assert.equal(doc.file_size,readFileSync(f.mediaPath).length);
    const auth=new AuthService(db), issue=auth.login({login:'migration@example.invalid',password:'import-workflow-test-password'});
    jobs=new JobQueue(db);
    const models=new ModelConfigurationService(db,auth,new CredentialVault(target));
    workflow=new DocumentWorkflow(db,auth,jobs,models,undefined,{parser:new DocumentParser({pythonExecutable:process.env.MARLIN_PARSER_PYTHON??'/tmp/marlin-parser-isolation-20261010/bin/python',workerPath:resolve('../../workers/document/worker.py')}),scheduler:()=>{}});
    const file=await workflow.readOwnedSource(issue.context,String(f.doc.id));
    assert.deepEqual(file.bytes,readFileSync(f.mediaPath));
    const reparsed=await workflow.reparse(issue.context,String(f.doc.id),{});
    assert.equal(reparsed.knowledge.id,f.doc.id);
    assert.equal(jobs.get(reparsed.task_id,{tenantId:issue.context.tenantId,userId:issue.context.userId}).status,'queued');
  } finally { await Promise.allSettled([workflow?.close(),jobs?.close()]);db?.close();rmSync(root,{recursive:true,force:true}); }
});

test('wrong credentials or missing original media fail before publish and never alter source or occupied target', async () => {
  const { importLegacy } = await implementation();
  const root = mkdtempSync(join(tmpdir(), 'marlin-import-failure-'));
  try {
    const f = fixture(root);
    const key = join(f.source, '.secrets', 'credentials.key');
    writeFileSync(key, Buffer.alloc(32, 42));
    const target = join(root, 'new');
    await assert.rejects(importLegacy({ sourceRoot: f.source, targetRoot: target }), /解密|密钥/);
    assert.equal(existsSync(target), false);
    assert.deepEqual(readFileSync(key), Buffer.alloc(32, 42));
    assert.equal(readdirSync(root).some((name) => name.includes('.import-')), false);
    const occupied = join(root, 'occupied');
    mkdirSync(occupied); writeFileSync(join(occupied, 'keep.txt'), 'unrelated');
    await assert.rejects(importLegacy({ sourceRoot: f.source, targetRoot: occupied }), /非空|已有|占用/);
    assert.equal(readFileSync(join(occupied, 'keep.txt'), 'utf8'), 'unrelated');
  } finally { rmSync(root, { recursive: true, force: true }); }
  const second = mkdtempSync(join(tmpdir(), 'marlin-import-missing-'));
  try {
    const f = fixture(second); rmSync(f.mediaPath);
    await assert.rejects(importLegacy({ sourceRoot: f.source, targetRoot: join(second, 'new') }), /文件|媒体/);
    assert.equal(existsSync(join(second, 'new')), false);
  } finally { rmSync(second, { recursive: true, force: true }); }
  const third = mkdtempSync(join(tmpdir(), 'marlin-import-hash-'));
  try {
    const f = fixture(third); writeFileSync(f.mediaPath, '内容被替换');
    await assert.rejects(importLegacy({ sourceRoot: f.source, targetRoot: join(third, 'new') }), /哈希|hash|校验/);
    assert.equal(existsSync(join(third, 'new')), false);
  } finally { rmSync(third, { recursive: true, force: true }); }
});

test('older missing columns get explicit defaults; unknown future versions and corrupt foreign keys fail closed', async () => {
  const { importLegacy } = await implementation();
  const root = mkdtempSync(join(tmpdir(), 'marlin-import-version-'));
  try {
    const source = join(root, 'old'); mkdirSync(source);
    const sql = openNativeDatabase(join(source, 'db.sqlite3'));
    sql.exec("create table django_migrations(id integer primary key,app text,name text,applied text); insert into django_migrations values(1,'personal_knowledge_base','0001_initial','2020-01-01'); create table tenants(id integer primary key,name text,api_key text); insert into tenants values(7,'历史空间','test-key'); create table users(id text primary key,username text,email text,password_hash text,tenant_id integer); insert into users values('old-user','old','old@example.invalid','preserved-hash',7); create table knowledge_bases(id text primary key,tenant_id integer,name text); create table knowledges(id text primary key,tenant_id integer,knowledge_base_id text,type text,title text,source text);");
    sql.close();
    const result = await importLegacy({ sourceRoot: source, targetRoot: join(root, 'new') });
    assert.ok(result.manifest.tables.tenants?.defaulted_columns.includes('space_type'));
    const db = new CoreDatabase(join(root, 'new'));
    assert.equal(db.read('tenants', 7)?.space_type, 'legacy');
    assert.equal(db.read('users', 'old-user')?.password_hash, 'preserved-hash'); db.close();
    const future = openNativeDatabase(join(source, 'db.sqlite3'));
    future.exec("update django_migrations set name='0099_future'"); future.close();
    await assert.rejects(importLegacy({ sourceRoot: source, targetRoot: join(root, 'future') }), /版本/);
    assert.equal(existsSync(join(root, 'future')), false);
    const broken = openNativeDatabase(join(source, 'db.sqlite3'));
    broken.exec("update django_migrations set name='0001_initial'; insert into knowledges values('orphan',7,'does-not-exist','file','broken','upload')"); broken.close();
    await assert.rejects(importLegacy({ sourceRoot: source, targetRoot: join(root, 'orphan') }), /关联|FOREIGN KEY/);
    assert.equal(existsSync(join(root, 'orphan')), false);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('legacy import refuses cross-space document ownership even when individual foreign keys are valid', async () => {
  const { importLegacy } = await implementation();
  const root = mkdtempSync(join(tmpdir(), 'marlin-import-ownership-'));
  try {
    const f = fixture(root);
    renameSync(join(f.source, 'db.sqlite3'), join(f.source, 'marlin.sqlite3'));
    const db = new CoreDatabase(f.source);
    const other = db.insert('tenants', { name: '另一空间', api_key: 'different-test-key' });
    db.update('knowledges', String(f.doc.id), { tenant_id: other.id }); db.close();
    renameSync(join(f.source, 'marlin.sqlite3'), join(f.source, 'db.sqlite3'));
    await assert.rejects(importLegacy({ sourceRoot: f.source, targetRoot: join(root, 'new') }), /归属|空间|关联/);
    assert.equal(existsSync(join(root, 'new')), false);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('overlapping target is rejected before creating a snapshot anywhere inside original media', async () => {
  const { importLegacy } = await implementation();
  const root = mkdtempSync(join(tmpdir(), 'marlin-import-overlap-'));
  try {
    const f = fixture(root);
    const before = readdirSync(join(f.source, 'media'));
    await assert.rejects(importLegacy({ sourceRoot: f.source, targetRoot: join(f.source, 'media', 'new') }), /重叠/);
    assert.deepEqual(readdirSync(join(f.source, 'media')), before);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('backup/restore validates database, file hashes, relationships and secret key; corrupt backups never publish', async () => {
  const { importLegacy, createBackup, restoreBackup } = await implementation();
  const root = mkdtempSync(join(tmpdir(), 'marlin-backup-'));
  let db;
  try {
    const f = fixture(root);
    const target = join(root, 'new');
    await importLegacy({ sourceRoot: f.source, targetRoot: target });
    db = new CoreDatabase(target);
    const backup = join(root, 'backup');
    await createBackup(db, backup);
    writeFileSync(join(backup, 'media', 'unlisted.txt'), 'not-part-of-backup');
    db.update('knowledge_bases', String(f.kb.id), { name: 'changed-after-backup' });
    db.close(); db = undefined;
    const restored = join(root, 'restored');
    await restoreBackup(backup, restored);
    assert.equal(existsSync(join(restored, 'media', 'unlisted.txt')), false, 'only validated manifest files may be restored');
    db = new CoreDatabase(restored);
    assert.equal(db.read('knowledge_bases', String(f.kb.id))?.name, '沧澜计划');
    assert.equal(new CredentialVault(restored).decrypt(db.read('models', String(f.model.id))!.parameters as { api_key: string }).api_key, 'test-only-import-secret');
    assert.deepEqual(db.all('pragma foreign_key_check'), []);
    writeFileSync(join(backup, 'media', '原始文档', '中文 资料.md'), 'tampered');
    await assert.rejects(restoreBackup(backup, join(root, 'corrupt-restore')), /哈希|完整|校验/);
    assert.equal(existsSync(join(root, 'corrupt-restore')), false);
  } finally { db?.close(); rmSync(root, { recursive: true, force: true }); }
});
