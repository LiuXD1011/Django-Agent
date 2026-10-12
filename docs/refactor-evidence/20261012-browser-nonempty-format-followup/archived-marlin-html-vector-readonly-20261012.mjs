import { createRequire } from 'node:module';
import { readFileSync, writeFileSync } from 'node:fs';
import { openNativeDatabase } from '/home/liuxuedeng/Django-Agent/packages/core/dist/storage/database.js';
const require = createRequire('/home/liuxuedeng/Django-Agent/packages/core/package.json');
const sqliteVec = require('sqlite-vec');
const evidence='/home/liuxuedeng/Django-Agent/docs/refactor-evidence/20261012-browser-nonempty-format-followup';
const kb='51fcf8ab-6c68-4ac1-ae8d-2fbcffcfe00d';
const db=openNativeDatabase('/home/liuxuedeng/.local/share/marlin-refactor/20261010-browser-qa/marlin.sqlite3',{readonly:true,fileMustExist:true});
try {
 db.defaultSafeIntegers();db.pragma('query_only=ON');sqliteVec.load(db);
 const result=db.transaction(()=>{
  let refs=db.prepare('SELECT table_name,rowid,chunk_id FROM retrieval_vector_entries WHERE tenant_id=2 AND knowledge_base_id=? ORDER BY rowid').all(kb);
  if(!refs.length) {const old=JSON.parse(readFileSync(evidence+'/044-vector-before-delete.json','utf8'));refs=old.entries.map(x=>({table_name:x.table_name,rowid:BigInt(x.rowid),chunk_id:x.chunk_id}));}
  return {created_utc:new Date().toISOString(),native_readonly:db.readonly,query_only:db.pragma('query_only',{simple:true}).toString(),kb_id:kb,entries:refs.map(x=>{if(!/^retrieval_vec_[a-f0-9]{32}$/.test(x.table_name))throw Error('unexpected vec table');return {table_name:x.table_name,rowid:x.rowid.toString(),chunk_id:x.chunk_id,physical_rows:db.prepare(`SELECT count(*) AS n FROM ${x.table_name} WHERE rowid=?`).get(x.rowid).n.toString()};})};
 }).deferred();
 writeFileSync(evidence+'/'+process.argv[2]+'.json',JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result,null,2));
}finally{db.close();}
