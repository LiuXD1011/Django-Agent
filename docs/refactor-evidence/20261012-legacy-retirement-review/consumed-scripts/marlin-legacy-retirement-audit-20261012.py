from pathlib import Path
import subprocess,json,hashlib,ast,re,datetime,time
ROOT=Path('/home/liuxuedeng/Django-Agent')
OUT=ROOT/'docs/refactor-evidence/20261012-legacy-retirement-review'
OUT.mkdir(exist_ok=False)
OLD=('config','personal_knowledge_base','accounts','agent','chat','knowledge','models_config','wiki','core')
CANDIDATE=[*OLD,'manage.py','requirements.txt','desktop/requirements-windows.lock','scripts/start_desktop.py','scripts/start_local.py','scripts/local_services.py','scripts/benchmark_open_rag_runtime.py','scripts/test_benchmark_open_rag_runtime.py','scripts/bench_langfuse_overhead.py','scripts/verify_langfuse_settings.py']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def binding(name):
 p=ROOT/name;return {'path':name,'bytes':p.stat().st_size,'sha256':sha(p)}
commands=[]
def run(label,args,acceptable=(0,1)):
 start=time.monotonic(); r=subprocess.run(args,cwd=ROOT,text=True,capture_output=True)
 assert r.returncode in acceptable,(args,r.returncode,r.stderr)
 (OUT/(label+'.stdout.txt')).write_text(r.stdout); (OUT/(label+'.stderr.txt')).write_text(r.stderr)
 commands.append({'label':label,'argv':args,'exit_code':r.returncode,'duration_ms':round((time.monotonic()-start)*1000,3),'kind':'read-only static inspection; not test/runtime acceptance'})
 return r.stdout
tracked=run('legacy-tracked',['git','ls-files','--',*CANDIDATE],(0,)).splitlines()
status=run('legacy-worktree-status',['git','status','--short','--untracked-files=normal','--',*CANDIDATE],(0,))
prod_roots=['packages/core/src','desktop','scripts/build_windows.py','scripts/bundle_windows_native.py','scripts/desktop','workers/document','workers/evaluation']
run('production-legacy-references',['rg','-n','--glob','!**/node_modules/**','--glob','!**/dist/**','--glob','!**/payload/**','--glob','!**/release/**','--glob','!**/package-lock.json','--glob','!*.lock','personal_knowledge_base|config\\.(bootstrap|settings|runtime_paths)|manage\\.py|start_desktop\\.py|start_local\\.py|requirements-windows\\.lock',*prod_roots])
run('current-test-django-boundaries',['rg','-n','--glob','!**/node_modules/**','--glob','!**/dist/**','from django|import django|spawnSync\\(.python|PBKDF2PasswordHasher|MARLIN_CRYPTO_TEST_PYTHON|from cryptography|manage\\.py', 'packages/core/test','frontend/playwright.auth.config.ts','scripts/test_build_windows.py'])
run('builder-allowlist',['rg','-n','source_inputs|BUILD_INPUT_FILES|CORE_GATE_TESTS|stage_build_sources|copy_workers|FORBIDDEN|django_packaged|manage\\\\.py|requirements-windows','scripts/build_windows.py','scripts/desktop/build-python-runtime.py','scripts/desktop/start-desktop.cjs'])
imports=[]; errors=[]
py_paths=[]
for folder in (*OLD,'scripts','tests','workers'):
 for p in sorted((ROOT/folder).rglob('*.py')):
  if '__pycache__' not in p.parts: py_paths.append(p)
for p in py_paths:
 try: tree=ast.parse(p.read_text(encoding='utf-8-sig'))
 except (SyntaxError,UnicodeError) as e:errors.append({'path':str(p.relative_to(ROOT)),'type':type(e).__name__});continue
 for n in ast.walk(tree):
  names=[x.name for x in n.names] if isinstance(n,ast.Import) else [n.module or ''] if isinstance(n,ast.ImportFrom) and n.level==0 else []
  for name in names:
   if name.split('.')[0] in (*OLD,'django'):
    imports.append({'path':str(p.relative_to(ROOT)),'line':n.lineno,'module':name})
(OUT/'python-import-inventory.json').write_text(json.dumps({'python_files_parsed':len(py_paths),'parse_errors':errors,'old_absolute_imports':imports},ensure_ascii=False,indent=2)+'\n')
fixtures=[]
for name in ('sample.doc','sample.ppt'):
 old='personal_knowledge_base/testdata/legacy/'+name;new='workers/document/tests/fixtures/legacy/'+name
 fixtures.append({'old':binding(old),'new':binding(new),'equal':sha(ROOT/old)==sha(ROOT/new)})
(OUT/'legacy-office-preservation.json').write_text(json.dumps({'fixtures':fixtures,'license':binding('workers/document/tests/fixtures/legacy/LICENSE'),'source_notice':binding('workers/document/tests/fixtures/legacy/README.md'),'all_equal':all(v['equal'] for v in fixtures)},ensure_ascii=False,indent=2)+'\n')
code=(ROOT/'packages/core/src/evaluation/public-registry.ts').read_text(); specs=json.loads(code.split(' = ',1)[1].rstrip().rstrip(';'))
full_name='personal_knowledge_base/eval_datasets/open_rag_benchmark.manifest.json';sub_name='personal_knowledge_base/eval_datasets/open_rag_benchmark_180.manifest.json'
full=json.loads((ROOT/full_name).read_text()); sub=json.loads((ROOT/sub_name).read_text())
checks={'old_180_query_ids_equal':specs[0]['queryIds']==sub['query_ids'],'full_revision_equal':all(s['revision']==full['revision'] for s in specs),'full_files_equal':all(s['files']==full['files'] for s in specs),'full_license_equal':all(s['license']==full['license'] for s in specs),'full_corpus_tree_oid_equal':all(s['corpusTreeOid']==full['corpus_tree_oid'] for s in specs),'full_raw_manifest_sha_preserved':all(s['artifactManifestSha256']==sha(ROOT/full_name) for s in specs),'subset_raw_manifest_sha_preserved':specs[0]['manifestSha256']==sha(ROOT/sub_name)}
(OUT/'public-manifest-preservation.json').write_text(json.dumps({'checks':checks,'all_equal':all(checks.values()),'old_manifests':[binding(full_name),binding(sub_name)],'new_registry':binding('packages/core/src/evaluation/public-registry.ts'),'old_small_annotation_files':[binding(str(p.relative_to(ROOT))) for p in sorted((ROOT/'personal_knowledge_base/eval_datasets').glob('*.json')) if 'open_rag_benchmark' not in p.name],'note':'Small hand-labelled annotation assets have not been proven equal to new equivalents; keep/archive, do not discard wholesale.'},ensure_ascii=False,indent=2)+'\n')
source='docs/refactor-evidence/20261012-sidebar-a11y-integrated-source-freeze.json';freeze=json.loads((ROOT/source).read_text())
source_bindings={}
for section in ('sourceInputs','additionalReviewedTestInputs','localCompiledOutputs','requiredCompletedChecks'):
 value=freeze[section]
 if isinstance(value,dict):
  for path,digest in value.items():
   if isinstance(digest,str):source_bindings[path]=digest
   elif isinstance(digest,dict):source_bindings[path]=digest.get('sha256')
 elif isinstance(value,list):
  for v in value:
   if isinstance(v,dict) and 'path' in v:source_bindings[v['path']]=v.get('sha256')
mismatch=[{'path':name,'expected':digest,'actual':sha(ROOT/name) if (ROOT/name).is_file() else None} for name,digest in source_bindings.items() if not (ROOT/name).is_file() or sha(ROOT/name)!=digest]
(OUT/'source-freeze-check.json').write_text(json.dumps({'freeze':binding(source),'keys':list(freeze),'bindings_checked':len(source_bindings),'mismatches':mismatch,'all_equal':not mismatch},ensure_ascii=False,indent=2)+'\n')
# No broad .rglob over user data: only tracked legacy source names and public docs.
legacy_links=[]
for p in (ROOT/'docs/desktop-refactor').glob('*.md'):
 if p.name=='LEGACY-RETIREMENT-REVIEW.md':continue
 for m in re.finditer(r'(?<!!)\[[^\]]+\]\(([^)]+)\)',p.read_text()):
  target=m.group(1).split('#',1)[0]
  if target.startswith('../../') and any(target.startswith('../../'+folder+'/') for folder in OLD):
   legacy_links.append({'document':str(p.relative_to(ROOT)),'line':p.read_text()[:m.start()].count('\n')+1,'target':target,'exists':(p.parent/target).exists()})
(OUT/'baseline-source-link-impact.json').write_text(json.dumps({'existing_legacy_source_links':legacy_links,'count':len(legacy_links),'note':'Deleting these targets breaks historical baseline links; do not rewrite frozen evidence. Plan preserved/reference archive or controlled unfrozen doc updates.'},ensure_ascii=False,indent=2)+'\n')
selected=['AGENTS.md','README.md','package.json','.gitignore','LICENSE','docs/desktop-refactor/SPEC.md','docs/desktop-refactor/PLAN.md','docs/desktop-refactor/MIGRATION.md','docs/desktop-refactor/DATA-BASELINE.md','packages/core/src/storage/legacy.ts','packages/core/src/storage/credentials.ts','packages/core/src/storage/files.ts','packages/core/src/storage/schema-manifest.ts','packages/core/src/storage/graph-legacy.ts','packages/core/src/auth/passwords.ts','packages/core/test/auth.test.ts','packages/core/test/credentials.test.ts','packages/core/test/migration.test.ts','packages/core/test/graph-legacy.test.ts','packages/core/src/legacy/index.ts','packages/core/src/legacy/README.md','packages/core/src/evaluation/public-registry.ts','packages/core/src/evaluation/selection.ts','packages/core/src/evaluation/LICENSE-MT19937.txt','packages/core/package.json','desktop/package.json','desktop/runtime.cjs','frontend/package.json','frontend/vite.config.ts','frontend/playwright.config.ts','frontend/playwright.mobile.config.ts','frontend/playwright.auth.config.ts','scripts/build_windows.py','scripts/bundle_windows_native.py','scripts/test_build_windows.py','scripts/desktop/start-desktop.cjs','scripts/desktop/build-python-runtime.py','scripts/desktop/python-runtime-lock-windows-x64.txt','scripts/desktop/python-runtime-lock-native.txt','workers/document/requirements.txt','workers/document/README.md','workers/document/worker.py','workers/document/tests/test_worker.py','workers/document/tests/test_boundaries.py','workers/evaluation/requirements.txt','workers/evaluation/worker.py','workers/evaluation/LICENSE','workers/document/LICENSE','tests/test_readme_links.py','tests/test_frontend_contracts.py','tests/test_frontend_playwright_e2e.py']
summary={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'static retirement dependency review only; no product mutation/test/build/GUI/API/model/live data reads','commands':commands,'legacy_source_inventory':[binding(name) for name in tracked if (ROOT/name).is_file()],'legacy_tracked_count':len(tracked),'legacy_status_at_start':status,'old_import_records':len(imports),'python_files_parsed':len(py_paths),'selected_source_bindings':[binding(name) for name in selected],'protected_locations_not_opened':['user databases/media','.secrets','.settings','.env','private baseline snapshot','Windows runtime/stage'],'limitations':['Spec describes 452-file private baseline; this audit did not open or reverify that snapshot.','Static no-reference results do not prove all replacement behavior/permissions/page/installer acceptance.','No files retired or dependencies removed; no skipped tests.']}
(OUT/'audit.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'evidence_directory':str(OUT.relative_to(ROOT)),'tracked_legacy_files':len(tracked),'legacy_status_empty':not status,'python_files_parsed':len(py_paths),'old_absolute_imports':len(imports),'parse_errors':errors,'public_manifest_checks':checks,'legacy_source_links':len(legacy_links),'current_freeze_bindings':len(source_bindings),'current_source_mismatches':mismatch,'product_API_GUI_models_builds_tests':0},ensure_ascii=False,indent=2))
