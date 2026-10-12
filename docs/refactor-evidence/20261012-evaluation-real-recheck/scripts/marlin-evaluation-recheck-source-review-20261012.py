import datetime,hashlib,json,sqlite3
from pathlib import Path
p=Path('/home/liuxuedeng/.local/share/marlin-refactor/20261010-browser-qa/marlin.sqlite3');b=Path('/home/liuxuedeng/Django-Agent/docs/refactor-evidence/20261012-evaluation-real-recheck')
c=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
dataset=dict(c.execute('SELECT * FROM generic_resources WHERE id=? AND tenant_id=2',('6c630a4d-309d-4dfd-8bac-b31bfdd20bec',)).fetchone());d=json.loads(dataset['data']);kb=d['knowledge_base_id']
rows=[]
for e in d['entries']:
 checks=[];sources=[]
 for v in e['evidence']:
  doc=dict(c.execute('SELECT id,tenant_id,knowledge_base_id,file_hash,metadata,enable_status,deleted_at FROM knowledges WHERE id=?',(v['knowledge_id'],)).fetchone());ch=dict(c.execute('SELECT id,tenant_id,knowledge_base_id,knowledge_id,content,start_at,end_at,chunk_type,is_enabled,deleted_at FROM chunks WHERE id=?',(v['chunk_id'],)).fetchone());m=json.loads(doc.pop('metadata'));canonical=m.get('content','')
  check={'tenant_scope':doc['tenant_id']==ch['tenant_id']==2,'kb_scope':doc['knowledge_base_id']==ch['knowledge_base_id']==kb,'document_active':doc['deleted_at'] is None and doc['enable_status']=='enabled','chunk_active':ch['deleted_at'] is None and ch['is_enabled']==1 and ch['chunk_type']=='text','document_link':ch['knowledge_id']==doc['id'],'source_range':0<=v['source_start']<v['source_end']<=len(canonical),'unicode_quote_exact':canonical[v['source_start']:v['source_end']]==v['source_quote'],'chunk_range_exact':ch['start_at']==v['source_start'] and ch['end_at']==v['source_end'],'chunk_content_exact':ch['content']==v['source_quote'],'file_hash_exact':doc['file_hash']==v['file_hash'],'source_generation_exact':m.get('source_generation')==v['source_generation']};checks.append(check);sources.append({'document':doc,'chunk':ch,'source_generation':m.get('source_generation'),'canonical_text':canonical,'canonical_codepoints':len(canonical)})
 rows.append({'entry_id':e['id'],'question':e['question'],'answer':e['reference_answer'],'status':e['status'],'validation_errors':e['validation_errors'],'evidence':e['evidence'],'checks':checks,'sources':sources})
c.rollback();c.close()
notes=['P1首次响应15分钟，来源服务与退订段一致。','晨星A交付总量80套，未将首批32套或其他库交付日期当总量。','手册现行v3.2，2026年9月30日生效，附加日期也由当前版本段明确支持。','晨星A/曙光计划负责人林青，未混淆晨星B的周宁。','测试传感器小计948元，等于12×79，未误用网关903或合计1851。']
for row,note in zip(rows,notes):row['human_factual_review']=note;row['correction_required']=False
r={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'query_only':True,'dataset_id':dataset['id'],'dataset_status':dataset['status'],'knowledge_base_id':kb,'entries':rows,'all_source_checks_pass':all(all(z.values()) for row in rows for z in row['checks']),'distinct_question_count':len({x['question'].strip().lower() for x in rows}),'approval_write_performed':False,'review_method':'independent current native readonly SQLite quote/range/hash/generation checks plus human factual comparison; actual UI evidence expansion and publish are separate'}
assert len(rows)==5 and r['all_source_checks_pass'] and r['distinct_question_count']==5
(b/'026-current-source-and-five-review.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'dataset_id':r['dataset_id'],'entries':len(rows),'all_source_checks_pass':r['all_source_checks_pass'],'distinct_question_count':r['distinct_question_count'],'human_factual_reviews':notes,'approval_write_performed':False},ensure_ascii=False,indent=2))
