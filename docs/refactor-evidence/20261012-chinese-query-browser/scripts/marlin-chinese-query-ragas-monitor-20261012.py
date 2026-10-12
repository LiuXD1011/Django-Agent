import datetime,hashlib,json,sqlite3,sys
from pathlib import Path
data=Path('/home/liuxuedeng/.local/share/marlin-refactor/20261010-browser-qa');e=Path('/home/liuxuedeng/Django-Agent/docs/refactor-evidence/20261012-chinese-query-browser');run='9a8de0eb-a2bf-48cc-8883-7474b1cd037d'
c=sqlite3.connect((data/'marlin.sqlite3').as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
job=dict(c.execute('SELECT id,tenant_id,user_id,status,progress,attempt,created_at,started_at,finished_at,error FROM desktop_jobs WHERE id=? AND tenant_id=2',(run,)).fetchone())
if job['error']:
 raw=json.loads(job['error']);job['error']={k:raw.get(k) for k in ['code','message','name'] if k in raw}
usages=[dict(r) for r in c.execute("SELECT id,scenario,success,request_count,prompt_tokens,completion_tokens,total_tokens,cached_tokens,reasoning_tokens,duration_ms,error_message,created_at,metadata FROM model_usage WHERE tenant_id=2 AND json_extract(metadata,'$.job_id')=? ORDER BY created_at,id",(run,))]
for u in usages:u['metadata']=json.loads(u['metadata'])
ledger=[dict(r) for r in c.execute("SELECT id,status,created_at,updated_at,json_extract(data,'$.invocation_id') invocation_id,json_extract(data,'$.error_code') error_code FROM generic_resources WHERE tenant_id=2 AND resource_type='rag_eval_invocations' AND json_extract(data,'$.ledger_id')=? ORDER BY created_at,id",(run,))]
models=[dict(x) for x in c.execute('SELECT * FROM models WHERE tenant_id=2 ORDER BY id')]
row=c.execute("SELECT data,status FROM generic_resources WHERE tenant_id=2 AND id=? AND resource_type='rag_eval_runs'",(run,)).fetchone();d=json.loads(row['data'])
current=datetime.datetime.now(datetime.timezone.utc);start=datetime.datetime.fromisoformat(job['started_at'].replace('Z','+00:00'));finish=datetime.datetime.fromisoformat(job['finished_at'].replace('Z','+00:00')) if job['finished_at'] else current
groups={}
for u in usages:
 g=groups.setdefault(u['scenario'],{'rows':0,'request_count':0,'success':0,'failed':0,'prompt_tokens':0,'completion_tokens':0,'total_tokens':0,'cached_tokens':0,'reasoning_tokens':0})
 g['rows']+=1;g['success']+=int(u['success']==1);g['failed']+=int(u['success']!=1)
 for k in ['request_count','prompt_tokens','completion_tokens','total_tokens','cached_tokens','reasoning_tokens']:g[k]+=u[k] or 0
r={'observed_utc':current.isoformat(),'query_only':True,'run_id':run,'job':job,'elapsed_core_seconds':(finish-start).total_seconds(),'usage_rows_for_exact_job':len(usages),'usage_groups':groups,'usage':usages,'ledger':ledger,'run_resource_status':row['status'],'requested_configuration':d.get('requested_configuration'),'metrics':d.get('metrics'),'report_id':d.get('report_id'),'source_fingerprint':d.get('fingerprint'),'model_rows_sha256':hashlib.sha256(json.dumps(models,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'credential_key_sha256':hashlib.sha256((data/'.secrets/credentials.key').read_bytes()).hexdigest(),'limits':{'maximum_new_usage_rows':65,'maximum_elapsed_seconds':1800,'usage_exceeded':len(usages)>65,'time_exceeded':(finish-start).total_seconds()>1800},'live_database_writes':0,'secret_values_reported':False}
c.rollback();c.close();(e/(sys.argv[1]+'.json')).write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:r[k] for k in ['observed_utc','run_id','job','elapsed_core_seconds','usage_rows_for_exact_job','usage_groups','ledger','run_resource_status','metrics','report_id','limits']},ensure_ascii=False,indent=2))
