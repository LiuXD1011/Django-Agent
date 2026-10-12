import datetime,hashlib,json,sqlite3,sys
from pathlib import Path
root=Path('/home/liuxuedeng/Django-Agent');e=root/'docs/refactor-evidence/20261012-general-page-browser';data=Path('/home/liuxuedeng/.local/share/marlin-refactor/20261010-browser-qa')
c=sqlite3.connect((data/'marlin.sqlite3').as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
digest=lambda rows:hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
rows=lambda sql,args=():[dict(x) for x in c.execute(sql,args)]
ids=('86f94109-c3f2-4cba-819e-d7bfdea42709','595a878c-2192-4595-9965-166386eb46f6')
models=rows('SELECT * FROM models WHERE tenant_id=2 ORDER BY id')
own=rows("SELECT id,name,description,type,indexing_strategy,chunking_config,is_pinned,deleted_at FROM knowledge_bases WHERE tenant_id=2 AND name LIKE 'Orca 页面补验%' ORDER BY created_at,id")
guard={
 'original_knowledge_bases':rows('SELECT * FROM knowledge_bases WHERE id IN (?,?) ORDER BY id',ids),
 'gold_documents':rows('SELECT * FROM knowledges WHERE knowledge_base_id=? ORDER BY id',(ids[0],)),
 'gold_chunks':rows('SELECT * FROM chunks WHERE knowledge_base_id=? ORDER BY id',(ids[0],)),
 'original_wiki':rows('SELECT * FROM wiki_pages WHERE tenant_id=2 AND knowledge_base_id IN (?,?) ORDER BY id',ids),
 'protected_three_testsets':rows('SELECT * FROM generic_resources WHERE id IN (?,?,?) ORDER BY id',('2f99f534-5d8a-45b8-ba67-3ddd87f740d5','24e9e43f-742d-4de1-99d5-fb33e7835dc8','6c630a4d-309d-4dfd-8bac-b31bfdd20bec')),
}
r={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'query_only':True,'models_rows_sha256':digest(models),'models_count':len(models),'credential_key_sha256':hashlib.sha256((data/'.secrets/credentials.key').read_bytes()).hexdigest(),'protected':{k:{'rows':len(v),'sha256':digest(v)} for k,v in guard.items()},'model_usage_total':c.execute('SELECT count(*) FROM model_usage').fetchone()[0],'tenant2_model_usage':c.execute('SELECT count(*) FROM model_usage WHERE tenant_id=2').fetchone()[0],'own_knowledge_bases':own,'own_related_counts':{x['id']:{t:c.execute(f'SELECT count(*) FROM {t} WHERE knowledge_base_id=?',(x['id'],)).fetchone()[0] for t in ['knowledges','chunks','wiki_pages']} for x in own},'active_jobs':rows("SELECT id,kind,status FROM desktop_jobs WHERE tenant_id=2 AND status IN ('queued','running')"),'secret_values_reported':False}
c.rollback();c.close();(e/(sys.argv[1]+'.json')).write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps(r,ensure_ascii=False,indent=2))
