import datetime,hashlib,json,sqlite3,sys
from pathlib import Path
r=Path('/home/liuxuedeng/Django-Agent');e=r/'docs/refactor-evidence/20261012-mcp-real-agent/browser';db=Path('/home/liuxuedeng/.local/share/marlin-refactor/20261010-browser-qa/marlin.sqlite3')
c=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
rows=lambda sql,args=():[dict(x) for x in c.execute(sql,args)]
sid='3c0d3ccd-3b6d-4e05-9908-e25b09d6dc28'
session=rows('SELECT id,tenant_id,user_id,title,knowledge_base_id,agent_config,created_at,updated_at,deleted_at FROM sessions WHERE id=?',(sid,))
messages=rows('SELECT id,request_id,session_id,role,content,is_completed,is_fallback,knowledge_references,agent_duration_ms,created_at,updated_at FROM messages WHERE session_id=? ORDER BY created_at,id',(sid,))
events=rows('SELECT seq,type,request_id,data,created_at FROM session_events WHERE session_id=? ORDER BY seq',(sid,))
usage=rows("SELECT * FROM model_usage WHERE tenant_id=2 AND json_extract(metadata,'$.session_id')=? ORDER BY created_at,id",(sid,))
jobs=rows("SELECT id,request_id,kind,status,attempt,progress,error,started_at,finished_at,json_extract(payload,'$.input') AS input,result FROM desktop_jobs WHERE tenant_id=2 AND json_extract(payload,'$.input.session_id')=? ORDER BY created_at,id",(sid,))
protocol=[json.loads(x) for x in (r/'docs/refactor-evidence/20261012-mcp-real-agent/server-protocol.jsonl').read_text().splitlines() if x.strip()]
actual=[x for x in protocol if x.get('setupSmoke') is False]
counts={t:c.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ['sessions','messages','session_events','model_usage','desktop_jobs','knowledge_bases','knowledges','chunks','wiki_pages','generic_resources','models','users','auth_device_sessions'] if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(t,)).fetchone()}
out={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'query_only':True,'session':session,'messages':messages,'events':events,'usage':usage,'usage_totals':{k:sum(x[k] for x in usage) for k in ['request_count','prompt_tokens','completion_tokens','total_tokens','cached_tokens','reasoning_tokens']},'jobs':jobs,'server_snapshot_sha256':hashlib.sha256((r/'docs/refactor-evidence/20261012-mcp-real-agent/server-protocol.jsonl').read_bytes()).hexdigest(),'server_actual_gui_protocol_snapshot':actual,'counts':counts,'secrets_output':False}
c.rollback();c.close();(e/(sys.argv[1]+'.json')).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in out.items() if k not in ['messages','events','usage','server_actual_gui_protocol_snapshot']},ensure_ascii=False,indent=2))
