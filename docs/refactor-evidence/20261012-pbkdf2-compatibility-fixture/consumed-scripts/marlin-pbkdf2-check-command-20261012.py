from pathlib import Path
import sys,os,subprocess,shutil,time,datetime,json,hashlib
ROOT=Path('/home/liuxuedeng/Django-Agent');OUT=ROOT/'docs/refactor-evidence/20261012-pbkdf2-compatibility-fixture';CORE=ROOT/'packages/core';label=sys.argv[1]
allowed={
 'red-original-no-django':['--import','tsx','--test','--test-name-pattern=^TS generated passwords verify with Django,','test/auth.test.ts'],
 'green-auth-no-django':['--import','tsx','--test','test/auth.test.ts'],
 'green-related-no-django':['--import','tsx','--test','test/auth-reader.test.ts','test/auth-discard-issue.test.ts','test/migration.test.ts'],
}
assert label in (*allowed,'typecheck')
env=dict(os.environ);env['PATH']='/tmp/marlin-parser-isolation-20261010/bin'+os.pathsep+env['PATH'];env['PYTHONDONTWRITEBYTECODE']='1'
node=shutil.which('node');assert node
argv=[shutil.which('npm'),'run','typecheck'] if label=='typecheck' else [node,*allowed[label]]
assert not (OUT/(label+'.execution.json')).exists()
start=time.monotonic();at=datetime.datetime.now(datetime.timezone.utc).isoformat()
with (OUT/(label+'.stdout.tap' if label!='typecheck' else label+'.stdout.log')).open('w') as stdout,(OUT/(label+'.stderr.log')).open('w') as stderr:
 p=subprocess.run(argv,cwd=CORE,env=env,stdout=stdout,stderr=stderr)
execution={'started_at':at,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'argv':argv,'cwd':str(CORE),'env_override':{'PATH':'/tmp/marlin-parser-isolation-20261010/bin prefixed to inherited PATH for this child only','PYTHONDONTWRITEBYTECODE':'1'},'python_for_original_test':shutil.which('python',path=env['PATH']),'exit_code':p.returncode,'elapsed_ms':round((time.monotonic()-start)*1000,3),'classification':'isolated auth regression; original ModuleNotFoundError is test dependency, not production auth failure','production_auth_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('packages/core/src/auth/passwords.ts','packages/core/src/auth/index.ts')},'helper_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'GUI_API_vendor_live_data_actions':0}
(OUT/(label+'.execution.json')).write_text(json.dumps(execution,ensure_ascii=False,indent=2)+'\n');print(json.dumps(execution,ensure_ascii=False,indent=2));sys.exit(p.returncode)
