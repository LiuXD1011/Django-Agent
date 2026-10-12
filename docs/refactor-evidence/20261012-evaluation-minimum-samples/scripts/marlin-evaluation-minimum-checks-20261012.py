import datetime,hashlib,json,subprocess,sys,time
from pathlib import Path
root=Path('/home/liuxuedeng/Django-Agent');e=root/'docs/refactor-evidence/20261012-evaluation-minimum-samples';e.mkdir(exist_ok=True)
paths=['frontend/src/views/Evaluation.vue','frontend/src/views/Evaluation.behavior.test.mjs']
def hashes():return {p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths}
label=sys.argv[1];argv=sys.argv[2:];started=datetime.datetime.now(datetime.timezone.utc).isoformat();before=hashes();clock=time.monotonic()
p=subprocess.run(argv,cwd=root/'frontend',stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=300)
(e/(label+'.log')).write_bytes(p.stdout)
r={'started_utc':started,'finished_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'cwd':str(root/'frontend'),'argv':argv,'exit_code':p.returncode,'elapsed_ms':round((time.monotonic()-clock)*1000,3),'source_before_sha256':before,'source_after_sha256':hashes(),'raw_output':str((e/(label+'.log')).relative_to(root))}
(e/(label+'.json')).write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps(r,ensure_ascii=False,indent=2));print(p.stdout.decode(errors='replace'))
sys.exit(p.returncode)
