import datetime,hashlib,json,shutil,sys
from pathlib import Path
e=Path('/home/liuxuedeng/Django-Agent/docs/refactor-evidence/20261012-chinese-query-browser');label,report=sys.argv[1:3]
p=Path('/mnt/c/Users/lxd/Downloads')/f'rag-eval-{report}.json';raw=p.read_bytes();data=json.loads(raw)
r={'opened_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'actual_file':str(p),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'report_json':data};(e/(label+'.json')).write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');shutil.copyfile(p,e/(label+'-downloaded.json'));print(json.dumps({'actual_file':str(p),'bytes':len(raw),'sha256':r['sha256'],'report_id':data.get('report_id'),'type':data.get('evaluation_type'),'configuration':data.get('requested_configuration'),'effective':data.get('effective_pipeline'),'source_fingerprint':data.get('source_fingerprint'),'metrics':data.get('metrics')},ensure_ascii=False,indent=2))
