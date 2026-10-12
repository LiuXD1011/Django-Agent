import datetime,hashlib,json,sqlite3
from pathlib import Path
root=Path('/home/liuxuedeng/Django-Agent'); evidence=root/'docs/refactor-evidence/20261012-evaluation-browser-page'
p=Path('/home/liuxuedeng/.local/share/marlin-refactor/20261010-browser-qa/marlin.sqlite3')
c=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True); c.row_factory=sqlite3.Row
c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
kb='86f94109-c3f2-4cba-819e-d7bfdea42709'
docs=[dict(r) for r in c.execute('SELECT id,title,file_name,file_hash,parse_status,enable_status,metadata FROM knowledges WHERE tenant_id=2 AND knowledge_base_id=? AND deleted_at IS NULL ORDER BY id',(kb,))]
for d in docs:
 m=json.loads(d.pop('metadata'));d['source_generation']=m.get('source_generation');d['canonical_text']=m.get('content', '');d['canonical_text_field']='metadata.content'
chunks=[dict(r) for r in c.execute("SELECT id,knowledge_id,content,start_at,end_at,chunk_type,is_enabled,metadata FROM chunks WHERE tenant_id=2 AND knowledge_base_id=? AND deleted_at IS NULL AND chunk_type='text' ORDER BY id",(kb,))]
for r in chunks:r['metadata']=json.loads(r['metadata'])
r={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'query_only':True,'tenant_id':2,'knowledge_base_id':kb,'documents':docs,'text_chunks':chunks}
c.rollback();c.close()
(evidence/'034-source-ground-truth-corrected.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(r,ensure_ascii=False,indent=2))
