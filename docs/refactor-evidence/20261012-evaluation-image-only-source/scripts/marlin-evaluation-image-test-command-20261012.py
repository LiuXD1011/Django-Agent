import datetime,hashlib,json,subprocess,sys,time
from pathlib import Path
root=Path('/home/liuxuedeng/Django-Agent');e=root/'docs/refactor-evidence/20261012-evaluation-image-only-source';label=sys.argv[1];cmd=sys.argv[2:]
paths=['packages/core/src/evaluation/isolated-index.ts','packages/core/test/evaluation-image-only-source.test.ts','packages/core/src/documents/chunker.ts']
def hashes():return {s:hashlib.sha256((root/s).read_bytes()).hexdigest() for s in paths}
before=hashes();started=datetime.datetime.now(datetime.timezone.utc).isoformat();t=time.monotonic()
with (e/(label+'.tap')).open('wb') as out, (e/(label+'.stderr.log')).open('wb') as err:
 p=subprocess.run(cmd,cwd=root/'packages/core',stdout=out,stderr=err)
stdout=(e/(label+'.tap')).read_bytes();stderr=(e/(label+'.stderr.log')).read_bytes()
r={'started_utc':started,'finished_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'command':cmd,'cwd':str(root/'packages/core'),'exit_code':p.returncode,'elapsed_ms':round((time.monotonic()-t)*1000,3),'sources_before':before,'sources_after':hashes(),'stdout_file':label+'.tap','stderr_file':label+'.stderr.log','vendor_requests':0,'gui_commands':0}
(e/(label+'.json')).write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps(r,ensure_ascii=False,indent=2));print(stdout.decode(errors='replace'));print(stderr.decode(errors='replace'));sys.exit(p.returncode)
