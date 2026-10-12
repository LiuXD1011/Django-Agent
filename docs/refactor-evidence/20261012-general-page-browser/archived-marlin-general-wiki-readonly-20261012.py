import datetime,json,sqlite3,sys
from pathlib import Path
root=Path('/home/liuxuedeng/Django-Agent')
db=Path('/home/liuxuedeng/.local/share/marlin-refactor/20261010-browser-qa/marlin.sqlite3')
c=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
kb='99218d30-8205-45bf-96ff-0a5d6c1c0a3f'
pages=[dict(x) for x in c.execute('SELECT id,tenant_id,knowledge_base_id,slug,title,content,summary,page_type,version,source_refs,chunk_refs,deleted_at FROM wiki_pages WHERE knowledge_base_id=? ORDER BY id',(kb,))]
r={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'query_only':True,'kb_id':kb,'pages':pages,'usage_total':c.execute('SELECT count(*) FROM model_usage').fetchone()[0]}
c.rollback();c.close()
(root/'docs/refactor-evidence/20261012-general-page-browser'/(sys.argv[1]+'.json')).write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(r,ensure_ascii=False,indent=2))
