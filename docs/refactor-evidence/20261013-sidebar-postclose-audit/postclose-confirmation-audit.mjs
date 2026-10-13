// Read only an owned byte snapshot; never opens the original clone database.
import { createHash } from 'node:crypto';
import { existsSync, lstatSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join, normalize } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
export const typed = v => typeof v === 'bigint' ? ['integer',v.toString()] : Buffer.isBuffer(v) ? ['blob',v.toString('base64')]
  : v === null ? ['null'] : typeof v === 'number' ? ['real',Object.is(v,-0)?'-0':v.toString()] : typeof v === 'string' ? ['text',v]
  : Object.fromEntries(Object.keys(v).sort().map(k=>[k,typed(v[k])]));
export const digest = v => createHash('sha256').update(JSON.stringify(typed(v))).digest('hex');
const fail = code => { throw new Error(code); };
const need = (v,c) => { if (!v) fail(c); };
const sha = p => createHash('sha256').update(readFileSync(p)).digest('hex');
async function main() {
  const [runtime,snapshot,source,output] = process.argv.slice(2);
  const owned='C:\\Users\\lxd\\AppData\\Local\\Temp\\Marlin 安装验收 20261010';
  need(process.platform==='win32' && process.version==='v22.23.2' && process.arch==='x64','bundled_native_required');
  need(normalize(runtime)===join(owned,'应用/resources/runtime') && normalize(source)===join(owned,'浏览器资料副本 20261012 第1轮'),'fixed_scope_required');
  need(normalize(snapshot)===join(owned,'.sidebar-clone-postclose-20261013-1','confirmation-1','snapshot') && normalize(output)===join(owned,'.sidebar-clone-postclose-20261013-1','confirmation-1','audit.json'),'owned_snapshot_scope_required');
  need(normalize(process.execPath)===join(runtime,'node/node.exe') && process.env.PATH==='C:\\Windows\\System32' && !existsSync(output),'fixed_runtime_or_output_required');
  const core=join(runtime,'core'), req=createRequire(join(core,'package.json'));
  const {openNativeDatabase}=await import(pathToFileURL(join(core,'dist/storage/database.js')).href);
  const {CredentialVault}=await import(pathToFileURL(join(core,'dist/storage/credentials.js')).href);
  const {tableDefinitions}=await import(pathToFileURL(join(core,'dist/storage/schema-manifest.js')).href);
  const database=join(snapshot,'marlin.sqlite3'), dbBefore=sha(database);
  const db=openNativeDatabase(database,{readonly:true,fileMustExist:true});
  const oldAudit=join(dirname(dirname(fileURLToPath(import.meta.url))),'20261012-offline-windows-restore-launch','clone-audit.mjs');
  const {canonical:legacy}=await import(pathToFileURL(oldAudit).href);
  const oldDigest=v=>createHash('sha256').update(legacy(v)).digest('hex');
  const tables={},protectedTables={},legacyProtected={},managed={};let fields=0,media=0,report;
  try {
    db.defaultSafeIntegers();req('sqlite-vec').load(db);db.pragma('query_only=ON');
    need(db.pragma('integrity_check').length===1 && db.pragma('integrity_check')[0].integrity_check==='ok','integrity_failed');
    need(db.pragma('foreign_key_check').length===0,'foreign_keys_failed');
    const mutable=new Set(['device_sessions','device_refresh_tokens','auth_tokens','desktop_meta']);
    const checked=new Set([...tableDefinitions.map(x=>x.name),'desktop_imports','desktop_jobs','desktop_job_steps','desktop_job_events','desktop_schema_versions','search_index_meta']);
    const names=db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").all();
    need(names.length===72,'current_table_set_changed');
    for(const {name} of names) {
      need(/^[a-zA-Z_][a-zA-Z_0-9]*$/.test(name),'unsafe_table_name');
      const hashes=[],oldHashes=[];for(const row of db.prepare(`SELECT * FROM "${name}"`).iterate()){
        hashes.push(digest(row));if(checked.has(name)&&!mutable.has(name))oldHashes.push(oldDigest(row));
      }
      tables[name]={count:hashes.length,digest:digest({rows:hashes.sort().join(',')})};
      if(!mutable.has(name))protectedTables[name]=tables[name];
      if(checked.has(name)&&!mutable.has(name))legacyProtected[name]={count:hashes.length,digest:oldDigest(oldHashes.sort())};
    }
    for(const [name,states] of [['desktop_jobs',['queued','running']],['task_records',['pending','running']],['agent_actors',['queued','running','pending']]])
      need(db.prepare(`SELECT count(*) AS n FROM "${name}" WHERE status IN (${states.map(()=>'?').join(',')})`).get(...states).n===0n,'active_work_refused');
    need(!db.prepare("SELECT 1 FROM desktop_meta WHERE key='ipc.receipts'").get(),'pending_auth_refused');
    need(!db.prepare("SELECT 1 FROM generic_resources WHERE json_extract(data,'$.generation.status')='running' LIMIT 1").get(),'active_generation_refused');
    const vault=new CredentialVault(snapshot);
    for(const table of tableDefinitions)for(const col of table.columns.filter(x=>x.encrypted))
      for(const row of db.prepare(`SELECT "${col.name}" AS value FROM "${table.name}" WHERE "${col.name}" IS NOT NULL`).iterate()){
        need(typeof row.value==='string','encrypted_field_invalid');vault.decrypt(JSON.parse(row.value));fields++;
      }
    need(fields>0,'credential_authentication_required');
    const visit=relative=>{
      const p=join(source,relative),s=lstatSync(p);need(!s.isSymbolicLink(),'managed_link_refused');
      if(s.isDirectory())for(const n of readdirSync(p))visit(relative+'/'+n);
      else {need(s.isFile(),'managed_special_refused');managed[relative]=sha(p);}
    };
    for(const scope of ['media','.settings','.secrets','.cache','archives'])if(existsSync(join(source,scope)))visit(scope);
    need(managed['.secrets/credentials.key']===sha(join(snapshot,'.secrets/credentials.key')),'snapshot_key_mismatch');
    const verify=(name,hash)=>{
      if(/^(https?:|data:)/i.test(name))return;
      need(typeof name==='string' && !/[\\:\x00-\x1f]/.test(name) && !name.startsWith('/') && name.split('/').every(x=>x && x!=='.' && x!=='..'),'unsafe_media_path');
      need(typeof hash==='string' && /^[a-f0-9]{64}$/i.test(hash) && managed[name]===hash.toLowerCase(),'media_reference_mismatch');media++;
    };
    for(const row of db.prepare("SELECT file_path,file_hash FROM knowledges WHERE type='file' AND deleted_at IS NULL AND file_path<>''").iterate())verify(row.file_path,row.file_hash);
    for(const row of db.prepare("SELECT storage_path,content_hash FROM knowledge_images WHERE deleted_at IS NULL AND storage_path<>''").iterate())verify(row.storage_path,row.content_hash);
    const meta=[...db.prepare("SELECT * FROM desktop_meta WHERE key NOT IN ('ipc.session','ipc.receipts')").iterate()].map(digest).sort();
    const oldMeta=[...db.prepare("SELECT * FROM desktop_meta WHERE key NOT IN ('ipc.session','ipc.receipts')").iterate()].map(oldDigest).sort();
    report={ok:true,algorithm:'typed-native-v1',all_current_table_digests:true,tables,protected_tables:protectedTables,legacy_protected_tables:legacyProtected,managed_files_sha256:managed,protected_desktop_meta_sha256:digest({rows:meta.join(',')}),legacy_protected_desktop_meta_sha256:oldDigest(oldMeta),verified_media:media,credential_fields_authenticated:fields,active_work:0,pending_auth_receipts:0,original_clone_db_opened:false,auth_or_model_requests:0};
  }finally{db.close();}
  const dbAfter=sha(database);need(dbAfter===dbBefore,'readonly_snapshot_database_changed');
  report.snapshot_database_before_sha256=dbBefore;report.snapshot_database_after_sha256=dbAfter;report.snapshot_database_unchanged=true;
  writeFileSync(output,JSON.stringify(report,null,2)+'\n',{flag:'wx'});
}
if(process.argv[1] && import.meta.url===pathToFileURL(process.argv[1]).href)main().catch(()=>{process.stderr.write('snapshot_audit_refused\n');process.exitCode=1;});
