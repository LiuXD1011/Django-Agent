from pathlib import Path
from urllib.parse import urlparse,unquote
import hashlib,json,re,subprocess,datetime
ROOT=Path('/home/liuxuedeng/Django-Agent');OUT=ROOT/'docs/refactor-evidence/20261012-pbkdf2-compatibility-fixture';DOC=ROOT/'docs/desktop-refactor/PBKDF2-COMPATIBILITY-CHECK.md'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def binding(p):return {'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':sha(p)}
def loaded(name):return json.loads((OUT/name).read_text())
assert not (OUT/'freeze.json').exists();checks=[]
def check(name,value):checks.append({'name':name,'passed':bool(value)});assert value,name
before=loaded('source-before.json');protected=[v for v in before['bindings'] if v['path']!='packages/core/test/auth.test.ts'];check('production auth E2E config spec installed Node types unchanged',all(sha(ROOT/v['path'])==v['sha256'] for v in protected))
auth=ROOT/'packages/core/test/auth.test.ts';fixture=ROOT/'packages/core/test/fixtures/django-pbkdf2.json';check('owned auth stable b5ca',sha(auth)=='b5ca199457bcf451028a87128521d7e86370c742266109a2444896dd2965dc41');check('static fixture copied exact from actual Django candidate',sha(fixture)==sha(OUT/'golden-candidate.json')=='44d9c2002335ac14a13bc0ffd3ae0cfe7d705e605b0923db3d5032502f3f4363')
def tap(label):
 value=(OUT/(label+'.stdout.tap')).read_text();return {key:int(re.search(r'^# '+key+r' (\d+)$',value,re.M)[1]) for key in ('tests','pass','fail','skipped')}
red=loaded('red-original-no-django.execution.json');redtap=tap('red-original-no-django');check('original targeted no-Django RED exact1FAIL',red['exit_code']==1 and redtap=={'tests':1,'pass':0,'fail':1,'skipped':0} and "ModuleNotFoundError: No module named 'django'" in (OUT/'red-original-no-django.stdout.tap').read_text())
final=loaded('green-auth-final-no-django.execution.json');finaltap=tap('green-auth-final-no-django');check('final current-source auth12PASS0skip same no-Django env',final['exit_code']==0 and finaltap=={'tests':12,'pass':12,'fail':0,'skipped':0} and final['source_unchanged'] and final['actual_python']=='/tmp/marlin-parser-isolation-20261010/bin/python' and final['source_after']['packages/core/test/auth.test.ts']==sha(auth))
related=loaded('green-related-no-django.execution.json');relatedtap=tap('green-related-no-django');check('related auth reader discard migration17PASS0skip',related['exit_code']==0 and relatedtap=={'tests':17,'pass':17,'fail':0,'skipped':0})
check('core npm typecheck0',loaded('typecheck.execution.json')['exit_code']==0);check('focused initial and original baseline same2 Json diagnostics retained',loaded('focused-test-typecheck.execution.json')['exit_code']==2 and loaded('focused-baseline-typecheck.execution.json')['exit_code']==2 and (OUT/'focused-test-typecheck.stdout.log').read_text().count('error TS')==2 and (OUT/'focused-baseline-typecheck.stdout.log').read_text().count('error TS')==2);check('final changed auth test strict noEmit typecheck0',loaded('focused-test-typecheck-green.execution.json')['exit_code']==0)
source=auth.read_text();check('removed dynamic Django/Python probe no test skips','spawnSync' not in source and 'verify-password.py' not in source and 'PBKDF2PasswordHasher' not in source and not re.search(r'\btest\.(skip|todo)\b',source))
original=subprocess.run(['git','show','HEAD:packages/core/test/auth.test.ts'],cwd=ROOT,capture_output=True,check=True).stdout;check('original source exact49faa',hashlib.sha256(original).hexdigest()=='49faa356fcb011d93390f9c44aa2cd1cb7eb9e6dd3d4c6c7c8a0db960261d8cb');original=original.decode()
def blocks(text):
 matches=list(re.finditer(r"^test\('([^']+)'",text,re.M));return {m[1]:text[m.start():matches[i+1].start() if i+1<len(matches) else len(text)] for i,m in enumerate(matches)}
a,b=blocks(original),blocks(source);same=[name for name in a if name in b and a[name]==b[name]];check('all11 original cases retained with9 exact blocks and scoped2 updates',len(a)==11 and len(b)==12 and len(same)==9);check('original real imported unicode login wrong no-rehash block exact','actual Django unicode PBKDF2 fixture verifies without resetting password and bad password issues nothing' in same)
anchor='    for (const malformed of ';check('original malformed absolute expiry and preference-validation assertions tail exact',original[original.index(anchor):]==source[source.index(anchor):]);check('preference enable_memory false original meaning retained with Json shape narrow','assert.equal(preferences.enable_memory, false);' in source and "assert.ok(preferences && typeof preferences === 'object' && !Array.isArray(preferences));" in source)
(OUT/'regression-preservation.json').write_text(json.dumps({'original_cases':len(a),'final_cases':len(b),'exact_original_blocks':same,'exact_count':len(same),'changed_original_cases':['setup preferences JSON shape narrowing, enable_memory false preserved','fresh password validates independent specification instead of Django subprocess, malformed/absolute assertions exact'],'new_cases':['five actual Django-generated static compatibility vectors plus low-round oracle calibration'],'new_skips':0},ensure_ascii=False,indent=2)+'\n')
missing=[];links=[]
for m in re.finditer(r'(?<!!)\[[^\]]+\]\(([^)]+)\)',DOC.read_text()):
 u=urlparse(m[1])
 if u.scheme or m[1].startswith('#'):continue
 links.append(m[1])
 if not (DOC.parent/unquote(u.path)).exists():missing.append(m[1])
check('all focused doc local links exist',not missing);check('owned code doc fixture no trailing whitespace',all(line==line.rstrip() for p in (DOC,auth,fixture) for line in p.read_text().splitlines()))
diff=subprocess.run(['git','diff','--check','--','packages/core/test/auth.test.ts','docs/desktop-refactor/PBKDF2-COMPATIBILITY-CHECK.md'],cwd=ROOT,text=True,capture_output=True);check('scoped git diff check0',diff.returncode==0)
patch=subprocess.run(['git','diff','--','packages/core/test/auth.test.ts'],cwd=ROOT,capture_output=True,check=True).stdout;(OUT/'auth-test-final.diff').write_bytes(patch)
now=datetime.datetime.now(datetime.timezone.utc).isoformat();validation={'at':now,'checks':checks,'count':len(checks),'all_passed':True,'relative_links':len(links),'missing_links':missing,'red':redtap,'final_auth':finaltap,'related':relatedtap,'git_diff_check_exit':diff.returncode,'production_GUI_models_live_data_build_commands':0}
(OUT/'validation-final.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2)+'\n')
archive=OUT/'consumed-scripts';archive.mkdir(exist_ok=True)
owned=['/tmp/marlin-pbkdf2-check-command-20261012.py','/tmp/marlin-pbkdf2-baseline-auth-20261012.mts','/tmp/marlin-pbkdf2-final-check-20261012.py','/tmp/marlin-pbkdf2-document-results-20261012.py','/tmp/marlin-pbkdf2-freeze-20261012.py'];cleanup=[]
for name in owned:
 p=Path(name);target=archive/p.name;assert not target.exists();target.write_bytes(p.read_bytes());assert sha(target)==sha(p);cleanup.append({'temporary_path':name,'archive':binding(target),'deleted':False})
for entry in cleanup:
 p=Path(entry['temporary_path']);assert sha(p)==entry['archive']['sha256'];p.unlink();entry['deleted']=not p.exists()
assert all(e['deleted'] for e in cleanup)
prep=loaded('preparation-check.json')['helper_consumed'];assert prep['deleted'] and not Path(prep['path']).exists()
(OUT/'cleanup-final.json').write_text(json.dumps({'at':now,'helpers':cleanup,'all_five_stage_helpers_deleted':True,'preparation_helper_already_verified_deleted':prep,'total_consumed_helpers':6,'private_or_other_temp_files_touched':False},ensure_ascii=False,indent=2)+'\n')
freeze={'at':now,'scope':'default auth test Django dependency removal only; all production auth preserved','goal':'active','owned_source':[binding(auth),binding(fixture)],'document':binding(DOC),'protected_source':protected,'input_artifact_receipt':loaded('source-unlock.json')['artifact_receipt'],'validation':binding(OUT/'validation-final.json'),'evidence':[binding(p) for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='freeze.json'],'checks':{'doc_links':len(links),'assertions':len(checks),'auth_final':finaltap,'related':relatedtap,'core_typecheck_exit':0,'focused_test_typecheck_exit':0,'helpers_archived_deleted_total':6},'limitations':['Original no-Django red is a test-dependency failure, not a production authentication defect.','Core typecheck excludes test; focused strict test compile separately passed after retaining/fixing old Json narrowing.','One million-round HMAC oracle is test CPU cost, not product/P95 latency.','No fullsuite/build/GUI/vendor/real users/live root/Windows work; old installed6e immutable receipt is not new-test acceptance.','Legacy Playwright auth config and root requirements not changed.']}
(OUT/'freeze.json').write_text(json.dumps(freeze,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'freeze':binding(OUT/'freeze.json'),'source':freeze['owned_source'],'document':freeze['document'],'checks':freeze['checks'],'evidence_files':len(freeze['evidence'])},ensure_ascii=False,indent=2))
