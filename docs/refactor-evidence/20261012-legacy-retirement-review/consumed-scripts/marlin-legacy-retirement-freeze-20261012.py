from pathlib import Path
import hashlib,json,re,datetime,subprocess,time
from urllib.parse import unquote,urlparse
ROOT=Path('/home/liuxuedeng/Django-Agent');OUT=ROOT/'docs/refactor-evidence/20261012-legacy-retirement-review';DOC=ROOT/'docs/desktop-refactor/LEGACY-RETIREMENT-REVIEW.md'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def item(p):return {'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':sha(p)}
assert not (OUT/'freeze.json').exists()
a=json.loads((OUT/'audit.json').read_text()); assertions=[]
def check(name,condition):
 assertions.append({'name':name,'passed':bool(condition)});assert condition,name
all_inputs=a['legacy_source_inventory']+a['selected_source_bindings'];bad=[v['path'] for v in all_inputs if sha(ROOT/v['path'])!=v['sha256']]
check('legacy265 plus selected source hashes remain exact',not bad)
s=json.loads((OUT/'source-freeze-check.json').read_text());f=json.loads((ROOT/s['freeze']['path']).read_text());check('6e37 same manifest bytes',sha(ROOT/s['freeze']['path'])==s['freeze']['sha256']); bindings={}
for section in ('sourceInputs','additionalReviewedTestInputs','localCompiledOutputs','requiredCompletedChecks'):
 v=f[section]
 if isinstance(v,dict):
  for p,x in v.items():bindings[p]=x if isinstance(x,str) else x.get('sha256')
 elif isinstance(v,list):
  for x in v:
   if isinstance(x,dict) and 'path' in x:bindings[x['path']]=x.get('sha256')
check('all989 current source compiled check bindings unchanged',len(bindings)==989 and all(sha(ROOT/p)==h for p,h in bindings.items()))
i=json.loads((OUT/'python-import-inventory.json').read_text());check('312 Python AST complete no parse errors',i['python_files_parsed']==312 and not i['parse_errors']);check('no workers old application absolute imports',not [v for v in i['old_absolute_imports'] if v['path'].startswith('workers/')]);check('office source/new two fixtures exact',json.loads((OUT/'legacy-office-preservation.json').read_text())['all_equal']);check('seven public manifest compatibility comparisons exact',json.loads((OUT/'public-manifest-preservation.json').read_text())['all_equal'])
status=subprocess.run(['git','status','--short','--untracked-files=normal','--',*('config','personal_knowledge_base','accounts','agent','chat','knowledge','models_config','wiki','core','manage.py','requirements.txt','desktop/requirements-windows.lock','scripts/start_desktop.py','scripts/start_local.py','scripts/local_services.py','scripts/benchmark_open_rag_runtime.py','scripts/test_benchmark_open_rag_runtime.py','scripts/bench_langfuse_overhead.py','scripts/verify_langfuse_settings.py')],cwd=ROOT,capture_output=True,text=True)
check('legacy scoped status unchanged',status.returncode==0 and status.stdout==a['legacy_status_at_start'])
text=DOC.read_text(); missing=[];links=[]
for m in re.finditer(r'(?<!!)\[[^\]]+\]\(([^)]+)\)',text):
 target=m.group(1);u=urlparse(target)
 if u.scheme or target.startswith('#'):continue
 p=DOC.parent/unquote(u.path);links.append(target)
 if not p.exists():missing.append(target)
check('new review relative links exist',not missing);check('new doc no trailing whitespace',all(line==line.rstrip() for line in text.splitlines()))
diff=subprocess.run(['git','diff','--check','--',str(DOC.relative_to(ROOT))],cwd=ROOT,capture_output=True,text=True);check('new doc diff check0',diff.returncode==0)
check('report no retirement no completed goal claim','未删除代码' in text and 'Goal active' in text and '当前 Windows 构建冻结期间不改来源' in text)
now=datetime.datetime.now(datetime.timezone.utc).isoformat();(OUT/'validation.json').write_text(json.dumps({'at':now,'assertions':assertions,'all_passed':True,'assertion_count':len(assertions),'links_checked':len(links),'missing_links':missing,'before_after_source_binding_count':989,'before_after_candidate_and_selected_bindings':len(all_inputs),'git_diff_check_exit':diff.returncode,'static_only':True,'product_GUI_API_model_tests_builds':0},ensure_ascii=False,indent=2)+'\n')
archive=OUT/'consumed-scripts';archive.mkdir(exist_ok=False);cleanup=[]
for name in ('audit','freeze'):
 p=Path('/tmp/marlin-legacy-retirement-'+name+'-20261012.py');b=p.read_bytes();target=archive/p.name;target.write_bytes(b);assert sha(p)==sha(target);cleanup.append({'temporary_path':str(p),'archive':item(target),'deleted':False})
for entry in cleanup:
 p=Path(entry['temporary_path']);assert sha(p)==entry['archive']['sha256'];p.unlink();entry['deleted']=not p.exists()
check('two own helpers archived verified and deleted',all(e['deleted'] for e in cleanup))
(OUT/'cleanup.json').write_text(json.dumps({'at':now,'helpers':cleanup,'all_deleted':True,'other_temp_or_private_files_touched':False},ensure_ascii=False,indent=2)+'\n')
freeze={'at':now,'scope':'legacy retirement static review only; no source removal or product/runtime acceptance','goal':'active','document':item(DOC),'evidence':[item(p) for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='freeze.json'],'bound_source':s['freeze'],'checks':{'assertions_in_validation':len(assertions)-1,'links':len(links),'source_compiled_check_bindings':989,'candidate_and_selected_bindings':len(all_inputs),'helpers_deleted':2,'diff_exit':diff.returncode},'protected_data_read_or_written':False,'product_GUI_API_models_tests_builds':0}
(OUT/'freeze.json').write_text(json.dumps(freeze,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'freeze':item(OUT/'freeze.json'),'document':item(DOC),'validation_assertions':len(assertions)-1,'cleanup_assertion':True,'links':len(links),'source_bindings_unchanged':989,'helper_cleanup':True,'files_frozen':len(freeze['evidence'])},ensure_ascii=False,indent=2))
