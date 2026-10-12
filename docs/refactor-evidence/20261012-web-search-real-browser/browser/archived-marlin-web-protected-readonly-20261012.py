import datetime,hashlib,json,sqlite3,sys
from pathlib import Path
root=Path('/home/liuxuedeng/Django-Agent');e=root/'docs/refactor-evidence/20261012-web-search-real-browser/browser';data=Path('/home/liuxuedeng/.local/share/marlin-refactor/20261010-browser-qa')
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
r['mcp_services_non_secret']=rows("SELECT id,tenant_id,status,deleted_at,name,json_extract(data,'$.url') AS url,json_extract(data,'$.enabled') AS enabled,CASE WHEN json_type(data,'$.api_key') IS NOT NULL THEN 1 ELSE 0 END AS key_field_present FROM generic_resources WHERE tenant_id=2 AND resource_type='mcp_services' ORDER BY id")
r['mcp_row_guards']=[{'id':x['id'],'resource_type':x['resource_type'],'row_sha256':digest([x]),'credential_field_encrypted':c.execute("SELECT substr(json_extract(data,'$.api_key'),1,7)='enc:v1:' FROM generic_resources WHERE id=?",(x['id'],)).fetchone()[0] == 1} for x in rows("SELECT * FROM generic_resources WHERE tenant_id=2 AND resource_type='mcp_services' ORDER BY id")]
configrows=rows('SELECT id,web_search_config FROM tenants WHERE id=2');raw=configrows[0]['web_search_config'];config=json.loads(raw) if raw else None
r['web_search_original_or_current']={'raw_type':type(raw).__name__,'value':config,'raw_sha256':hashlib.sha256((raw or '').encode()).hexdigest()}
if isinstance(config,dict) and set(config)<=set(['enabled','provider_id']): r['web_search_original_or_current']['safe_raw_json']=raw
r['web_services_non_secret']=rows("SELECT id,tenant_id,status,deleted_at,name,json_extract(data,'$.provider') AS provider,json_extract(data,'$.url') AS url,json_extract(data,'$.base_url') AS base_url,json_extract(data,'$.enabled') AS enabled,CASE WHEN json_type(data,'$.api_key') IS NOT NULL THEN 1 ELSE 0 END AS key_field_present,CASE WHEN length(coalesce(json_extract(data,'$.api_key'),''))>0 THEN 1 ELSE 0 END AS key_nonempty,substr(json_extract(data,'$.api_key'),1,7)='enc:v1:' AS key_encrypted FROM generic_resources WHERE tenant_id=2 AND resource_type='web_search_providers' ORDER BY id")
r['web_row_guards']=[{'id':x['id'],'row_sha256':digest([x])} for x in rows("SELECT * FROM generic_resources WHERE tenant_id=2 AND resource_type='web_search_providers' ORDER BY id")]
c.rollback();c.close();(e/(sys.argv[1]+'.json')).write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps(r,ensure_ascii=False,indent=2))
