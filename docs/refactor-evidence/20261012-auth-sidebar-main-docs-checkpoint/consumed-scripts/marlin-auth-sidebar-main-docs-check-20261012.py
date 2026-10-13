import datetime,difflib,hashlib,json,pathlib,re,shutil,subprocess
ROOT=pathlib.Path('/home/liuxuedeng/Django-Agent');OUT=ROOT/'docs/refactor-evidence/20261012-auth-sidebar-main-docs-checkpoint'
DOCS=[ROOT/'docs/desktop-refactor'/n for n in ['STATUS.md','TEST-REPORT.md','TEST-MATRIX.md']]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads((ROOT/p).read_text())
checks=[]
def check(name,value):
    checks.append({'name':name,'passed':bool(value)})
    if not value:raise AssertionError(name)
AUTH_DOC='docs/desktop-refactor/AUTH-BROWSER-ISOLATION-ACCEPTANCE.md';AUTH_FREEZE='docs/refactor-evidence/20261012-auth-browser-isolation-real/freeze.json'
check('A report unchanged e834',sha(ROOT/AUTH_DOC)=='e83483fc873c3552ef631765ee3194124093ed533a66b70f7381822225033d38')
check('A freeze unchanged db5b33',sha(ROOT/AUTH_FREEZE)=='db5b33f9b3278d2cb5ada2c85473bcbc8d0bbdbd0cb4334a977349c24ae19cea')
a=load(AUTH_FREEZE)
check('A declared41 assertions81links178files',a['assertion_count']==41 and a['links_checked']==81 and a['evidence_file_count']==178)
a_errors=[x['path'] for x in a['evidence_files'] if not (ROOT/x['path']).is_file() or sha(ROOT/x['path'])!=x['sha256']]
check('all original178 A evidence bindings unchanged',not a_errors)
check('A cleanup original four devices revoked zero vendor/jobs',all(x['revoked_at'] for x in load('docs/refactor-evidence/20261012-auth-browser-isolation-real/156-own-devices-all-revoked-cleanup.json')['devices']) and all(load('docs/refactor-evidence/20261012-auth-browser-isolation-real/156-own-devices-all-revoked-cleanup.json')['counts'][k]==0 for k in ['model_usage','desktop_jobs']))
kb=load('docs/refactor-evidence/20261012-root-kb-list-followup/cleaned-readonly-db.json')
check('B own2 softdelete/unpin protectedexact usage174',len(kb['owned_knowledge_bases'])==2 and all(x['deleted_at'] and not x['is_pinned'] for x in kb['owned_knowledge_bases']) and kb['protected_unchanged'] and kb['model_usage_count']==174)
page=load('docs/refactor-evidence/20261012-root-kb-list-followup/077-cleanup-current-readonly.json')
page_data=json.loads(page['receipt']['result']['result'])
check('B stable GUI state2kb16docs10027chunks no loading',page_data['stats']=={'chunks':10027,'count':2,'knowledge':16,'processing':0} and not page_data['loading'] and not page_data['deleteLoading'])
source_path='docs/refactor-evidence/20261012-sidebar-a11y-integrated-source-freeze.json'
check('new integrated freeze exact6e37',sha(ROOT/source_path)=='6e37bc4f7e94dbc4714f322ee32c56d32da084a5a039f231603290466ce1b7d8')
source=load(source_path)
check('manifest457+5/438core85front523',len(source['sourceInputs'])==457 and len(source['additionalReviewedTestInputs'])==5 and len(source['localCompiledOutputs'])==523 and source['compiledOutputCounts']=={'core':438,'frontend':85,'total':523})
source_errors=[]
for group in ['sourceInputs','additionalReviewedTestInputs','localCompiledOutputs','requiredCompletedChecks']:
    for name,digest in source[group].items():
        if not (ROOT/name).is_file() or sha(ROOT/name)!=digest:source_errors.append({'group':group,'path':name})
check('all sourcecompiled/check bindings unchanged',not source_errors)
check('sole product delta Platform without added source',source['changedFromPrior']==['frontend/src/views/Platform.vue'] and not source['addedFromPrior'])
old=load(source['priorSourceFreeze'])
check('438 core outputs equal old5cab',all(old['localCompiledOutputs'].get(k)==v for k,v in source['localCompiledOutputs'].items() if k.startswith('packages/core/dist/')))
unit=load('docs/refactor-evidence/20261012-sidebar-accessible-names/unit-execution.json');build=load('docs/refactor-evidence/20261012-sidebar-accessible-names/build-execution.json')
check('sidebar actual unit361/361 exit0',unit['exit_code']==0 and unit['counts']=={'tests':361,'pass':361,'fail':0,'skipped':0})
check('sidebar actual build0 source same',build['exit_code']==0 and build['source_sha256_before']==build['source_sha256_after']==unit['source_sha256_before']==unit['source_sha256_after'])
copy_path='docs/refactor-evidence/20261012-sidebar-a11y-windows-build/copy-execution.json';copy=load(copy_path);terminal=load('docs/refactor-evidence/20261012-sidebar-a11y-windows-build/copy-native-terminal.json');copy_result=load('docs/refactor-evidence/20261012-sidebar-a11y-windows-build/copy-stage-result.json')
check('copy exact f601 actual0/treeclosed',sha(ROOT/copy_path)=='f60184d9f43c4918345614537d90488834b9e0b82e9121562e2af7fb3d2e15de' and copy['exitCode']==0 and copy['ownedProcessTreeClosed'] and terminal['actual_tool_exit_code']==0)
check('copy81263files2146851880B onlycopy',copy_result['copied_files']==terminal['files']==81263 and copy_result['copied_bytes']==terminal['bytes']==2146851880 and not copy_result['builder_started'] and not copy_result['installer_executed'] and not terminal['prepare_or_package_executed'])
prepare=load('docs/refactor-evidence/20261012-sidebar-a11y-windows-build/prepare-attempt.json');native=load('docs/refactor-evidence/20261012-sidebar-a11y-windows-build/prepare-native-session-start.json')
check('prepare actualstart only no terminalpreclaimed',prepare['phase']=='prepare' and prepare['RootGUILeaseReleaseConfirmed'] and native['authorized_phase']=='prepare_only' and native['session_id']==30038 and not native['package_or_installer_authorized'])
current_terminal=(ROOT/'docs/refactor-evidence/20261012-sidebar-a11y-windows-build/prepare-execution.json').exists()
# Do not consume a late terminal as a result without the parent's explicit reviewed update.
rows=lambda text:re.findall(r'^\| ((?:[A-Z]-\d{2}|E-GOLD|PERF)) \|.*$',text,re.M)
ui=lambda text:re.findall(r'^\| (UI-[A-Z]+-\d{3}) \|.*$',text,re.M)
before=(OUT/'before/TEST-MATRIX.md').read_text();matrix=DOCS[2].read_text()
check('38 stable group IDs exact same order',len(rows(before))==38 and rows(matrix)==rows(before))
check('69 UI IDs exact same order',len(ui(before))==69 and ui(matrix)==ui(before))
full_pass=[]
for line in matrix.splitlines():
    if line.startswith('| ') and re.match(r'^\| (?:[A-Z]-\d{2}|E-GOLD|PERF) \|',line):
        if line.split(' | ')[-1].startswith('通过'):full_pass.append(line.split(' | ')[0][2:])
check('only M01 M02 whole-groupPASS',full_pass==['M-01','M-02'])
links=[];missing=[];trailing=[]
for doc in DOCS:
    for n,line in enumerate(doc.read_text().splitlines(),1):
        if line.rstrip()!=line:trailing.append({'path':str(doc.relative_to(ROOT)),'line':n})
    for target in re.findall(r'\]\(([^)]+)\)',doc.read_text()):
        if '://' in target:continue
        path=(doc.parent/target.split('#')[0]).resolve()
        links.append({'document':str(doc.relative_to(ROOT)),'target':target})
        if not path.exists():missing.append(links[-1])
check('all doc relative links exist',not missing)
check('no trailing whitespace in3documents',not trailing)
check('current STATUS no old A GUIwait or B cleanup待 terminal',not any(x in '\n'.join(DOCS[0].read_text().splitlines()[:24]) for x in ['A代理零GUI等待Root租约','两个自有空库尚未清理','B搜索/两个自有空库清理仍待Root终态']))
check('accurate A distinctcases and B DOM boundaries eachdocument',all('自然过期与独立保持为两个案例' in p.read_text() and '不计真实鼠标通过' in p.read_text() for p in DOCS))
check('prepare checkpoint explicitly no reviewed terminal',all('本checkpoint尚未收到prepare终态' in p.read_text() for p in DOCS))
protect_paths=[AUTH_DOC,AUTH_FREEZE,'docs/desktop-refactor/KNOWLEDGE-LIST-FOLLOWUP-20261012.md','docs/desktop-refactor/SIDEBAR-ACCESSIBLE-NAMES.md',source_path,copy_path,'docs/refactor-evidence/20261012-sidebar-accessible-names/unit-execution.json','docs/refactor-evidence/20261012-sidebar-accessible-names/build-execution.json','docs/refactor-evidence/20261012-sidebar-a11y-windows-build/prepare-attempt.json','docs/refactor-evidence/20261012-sidebar-a11y-windows-build/prepare-native-session-start.json']
bindings=[{'path':p,'bytes':(ROOT/p).stat().st_size,'sha256':sha(ROOT/p)} for p in protect_paths]
diffs=[]
for doc in DOCS:
    old_text=(OUT/'before'/doc.name).read_text();new_text=doc.read_text()
    patch=''.join(difflib.unified_diff(old_text.splitlines(keepends=True),new_text.splitlines(keepends=True),fromfile='before/'+doc.name,tofile=str(doc.relative_to(ROOT))))
    path=OUT/(doc.stem.lower()+'-changes-final.diff');path.write_text(patch);diffs.append({'path':str(path.relative_to(ROOT)),'sha256':sha(path)})
diff=subprocess.run(['git','diff','--check','--',*[str(p.relative_to(ROOT)) for p in DOCS]],cwd=ROOT,capture_output=True,text=True)
check('git diff check0',diff.returncode==0)
record={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'assertions':checks,'assertion_count':len(checks),'all_passed':True,'links_checked':len(links),'missing_links':missing,'trailing_whitespace':trailing,'group_count':38,'ui_count':69,'whole_group_pass':full_pass,'source_bindings_verified':457+5+523+4,'source_mismatches':source_errors,'A_evidence_bindings_verified':178,'original_failures_and_source_freezes_rewritten':False,'prepare_checkpoint':'started; actual reviewed terminal not supplied','prepare_terminal_path_exists_at_doccheck':current_terminal,'prepare_terminal_not_consumed_without_parent_update':True,'copy_only_actual_exit0':True,'product_GUI_API_models_ports_commands':0,'git_diff_check_exit':diff.returncode,'git_diff_check_stdout':diff.stdout,'git_diff_check_stderr':diff.stderr,'inputs':bindings,'diffs':diffs,'documents':[{'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':sha(p)} for p in DOCS]}
(OUT/'validation-final.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'assertions':len(checks),'all_passed':True,'links_checked':len(links),'bad_links':len(missing),'groups':38,'ui':69,'whole_group_pass':full_pass,'source_bindings_verified':989,'A_bindings_verified':178,'prepare_status':record['prepare_checkpoint'],'prepare_terminal_path_exists':current_terminal,'documents':record['documents']},ensure_ascii=False,indent=2))
