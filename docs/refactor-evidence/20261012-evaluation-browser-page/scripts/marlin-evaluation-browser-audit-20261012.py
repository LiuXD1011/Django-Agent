import datetime,hashlib,json,sqlite3,sys
from pathlib import Path
root=Path('/home/liuxuedeng/Django-Agent');base=root/'docs/refactor-evidence/20261012-evaluation-browser-page'
path=Path('/home/liuxuedeng/.local/share/marlin-refactor/20261010-browser-qa/marlin.sqlite3')
db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
def digest(values):return hashlib.sha256(json.dumps(values,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
resources=[]
for r in db.execute("SELECT * FROM generic_resources WHERE tenant_id=2 AND resource_type IN ('rag_eval_datasets','rag_eval_testsets','rag_eval_runs','rag_eval_reports','rag_eval_deterministic_runs') ORDER BY id"):
    row=dict(r);data=json.loads(row['data']);item={k:row[k] for k in ['id','resource_type','name','status','deleted_at','created_at','updated_at']}
    item['row_sha256']=digest(row)
    if row['resource_type'] in ['rag_eval_datasets','rag_eval_testsets']:
        item['data']=data
    else:
        item['data']={key:data[key] for key in ['report_id','run_id','requested_configuration','effective_pipeline','verification_status','metrics','source','sample_size','dataset','fingerprint'] if key in data}
    resources.append(item)
models=[dict(r) for r in db.execute('SELECT * FROM models WHERE tenant_id=2 ORDER BY id')]
result={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'database':str(path),'tenant_id':2,'query_only':bool(db.execute('PRAGMA query_only').fetchone()[0]),'evaluation_resources':resources,'model_rows_sha256':digest(models),'model_rows':len(models),'usage_rows':db.execute('SELECT count(*) FROM model_usage WHERE tenant_id=2').fetchone()[0],'generation_usage':[dict(r) for r in db.execute("SELECT id,model_name,model_type,scenario,success,request_count,prompt_tokens,completion_tokens,total_tokens,cached_tokens,reasoning_tokens,duration_ms,error_message,created_at,request_id,metadata FROM model_usage WHERE tenant_id=2 AND scenario='evaluation_generation' ORDER BY created_at,id")],'active_evaluation_jobs':[dict(r) for r in db.execute("SELECT id,kind,status,request_id FROM desktop_jobs WHERE tenant_id=2 AND kind='rag_evaluation' AND status IN ('queued','running')")],'secret_values_reported':False}
db.rollback();db.close();base.mkdir(parents=True,exist_ok=True)
(base/(sys.argv[1]+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'label':sys.argv[1],'resources':[{key:v for key,v in r.items() if key!='data'}|({'entries':len(r['data'].get('entries',[])),'version':r['data'].get('version')} if 'entries' in r['data'] else {}) for r in resources],'model_rows':len(models),'generation_usage_rows':len(result['generation_usage']),'active_evaluation_jobs':result['active_evaluation_jobs']},ensure_ascii=False,indent=2))
