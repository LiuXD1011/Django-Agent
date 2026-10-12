import datetime,hashlib,json
from pathlib import Path
b=Path('/home/liuxuedeng/Django-Agent/docs/refactor-evidence/20261012-evaluation-browser-page')
def read(name):return json.loads((b/(name+'.json')).read_text())
def resource(snapshot,id):return next(r for r in snapshot['evaluation_resources'] if r['id']==id)
original='2f99f534-5d8a-45b8-ba67-3ddd87f740d5';version2='24e9e43f-742d-4de1-99d5-fb33e7835dc8'
checks=[]
def check(name,condition):checks.append({'name':name,'passed':bool(condition)})
before=read('006-readonly-before');failed=read('048-generation-second-readonly');edited=read('064-after-edit-readonly');cancelled=read('072-after-delete-cancel-readonly');published=read('077-published-readonly');new=read('080-new-version-readonly');deleted=read('085-after-v2-delete-readonly')
f=resource(failed,original);e=resource(edited,original);p=resource(published,original);v=resource(new,version2);d=resource(deleted,version2)
check('current tenant has no preexisting evaluation resources',not before['evaluation_resources'])
check('single failed generation preserves one candidate',len(failed['evaluation_resources'])==1 and f['data']['generation']['status']=='failed' and f['data']['generation']['requested_count']==5 and f['data']['generation']['completed_count']==1 and f['data']['generation']['error_code']=='evaluation_generation_invalid' and not f['data']['generation']['result_unknown'] and len(f['data']['entries'])==1)
check('manual generated candidate requires review',f['data']['entries'][0]['status']=='pending_review')
ground=read('034-source-ground-truth-corrected');entry=f['data']['entries'][0];evidence=entry['evidence'][0];doc=next(r for r in ground['documents'] if r['id']==evidence['knowledge_id']);chunk=next(r for r in ground['text_chunks'] if r['id']==evidence['chunk_id'])
check('quote equals current Unicode code point source span',doc['canonical_text'][evidence['source_start']:evidence['source_end']]==evidence['source_quote']==chunk['content'])
check('file hash and source generation remain precise',doc['file_hash']==evidence['file_hash'] and doc['source_generation']==evidence['source_generation']==chunk['metadata']['source_generation'])
check('human edited question and answer persisted',e['data']['entries'][0]['question']=='按照晨星项目现行手册，P1故障首次响应应在多少分钟内？' and e['data']['entries'][0]['reference_answer']=='P1故障首次响应时限为15分钟。')
check('editing preserves original evidence and documents',e['data']['entries'][0]['evidence']==entry['evidence'] and e['data']['entries'][0]['documents']==entry['documents'] and e['data']['entries'][0]['status']=='pending_review')
check('cancelled deletion leaves whole resource row unchanged',resource(cancelled,original)['row_sha256']==e['row_sha256'])
check('one manually reviewed candidate is published approved',p['status']=='published' and p['data']['entries'][0]['status']=='approved' and len(p['data']['entries'])==1)
check('published partial generation history retained',p['data']['generation']==f['data']['generation'])
check('new draft version references original and clears entry approval',v['data']['version']==2 and v['data']['parent_dataset_id']==original and v['status']=='draft' and v['data']['entries'][0]['status']=='pending_review')
check('new version keeps source evidence',v['data']['entries'][0]['evidence']==entry['evidence'])
check('confirmed own new-version deletion leaves zero entries',d['status']=='draft' and not d['data']['entries'])
check('published original unchanged by version and confirmed deletion',resource(new,original)['row_sha256']==p['row_sha256']==resource(deleted,original)['row_sha256'])
for name,r in [('failed',failed),('edit',edited),('cancel',cancelled),('published',published),('version',new),('delete',deleted)]:
 check(name+' model row SHA equals baseline',r['model_rows_sha256']==before['model_rows_sha256'] and r['model_rows']==4)
 check(name+' has no report, run, or active evaluation job',all(x['resource_type']=='rag_eval_testsets' for x in r['evaluation_resources']) and not r['active_evaluation_jobs'])
usage=failed['generation_usage'];check('only two exact generation invocation IDs consumed',len(usage)==2 and {r['id'] for r in usage}=={'41458018-aece-43f5-8ce3-913f8cc88611','fe299e73-374e-48e2-a1f8-bd479f146daf'} and usage==deleted['generation_usage'])
check('vendor-reported token totals equal 1648 with no cache',sum(r['total_tokens'] for r in usage)==1648 and sum(r['cached_tokens'] for r in usage)==0 and sum(r['reasoning_tokens'] for r in usage)==1321 and all(r['request_count']==1 for r in usage))
r={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'kind':'read-only saved evidence consistency, not a product unit test','checks':checks,'passed':sum(c['passed'] for c in checks),'total':len(checks),'all_passed':all(c['passed'] for c in checks)}
(b/'evidence-consistency.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps(r,ensure_ascii=False,indent=2))
if not r['all_passed']:raise SystemExit(1)
