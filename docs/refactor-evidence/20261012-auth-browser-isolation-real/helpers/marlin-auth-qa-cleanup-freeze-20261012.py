import datetime, hashlib, json, os, pathlib, re, shutil, stat, subprocess, urllib.parse
ROOT=pathlib.Path('/home/liuxuedeng/Django-Agent')
OUT=ROOT/'docs/refactor-evidence/20261012-auth-browser-isolation-real'
DOC=ROOT/'docs/desktop-refactor/AUTH-BROWSER-ISOLATION-ACCEPTANCE.md'
PRIVATE=pathlib.Path('/tmp/marlin-auth-qa-credentials-20261012.json')
CACHE=pathlib.Path('/tmp/marlin-auth-vite-cache-20261012-5184')
FINAL_PATHS=[OUT/'161-temporary-cleanup.json',OUT/'162-final-readonly-check.json',OUT/'freeze.json']
if any(p.exists() for p in FINAL_PATHS): raise RuntimeError('Final evidence exists; do not overwrite')
if any(pathlib.Path('/proc',str(pid)).exists() for pid in [2574115,2574880]): raise RuntimeError('Owned process still alive')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def raw(label):return json.loads((OUT/(label+'.json')).read_text())
def cli(label):
    r=raw(label); data=json.loads(r['stdout'][r['stdout'].find('{'):]);return data

def evaluation(label):
    data=cli(label)
    if not data.get('ok'):raise RuntimeError('Recorded read is not successful: '+label)
    value=data['result']['result'];return json.loads(value) if isinstance(value,str) else value

def device(label,ident):return next(x for x in raw(label)['devices'] if x['id']==ident)
checks=[]
def check(name,condition):
    checks.append({'name':name,'passed':bool(condition)})
    if not condition:raise AssertionError(name)
D1='fbc66ba1-50c7-4df2-94d4-59bd0224628f';D2='f925c705-87f7-4ce9-9d8b-e88513ccbcbe';D3='c62fff52-25f7-4527-b5f8-2ac3aea6f305';D4='089e7176-f7bd-48cf-a8ed-a3eb6e16ca98'
before=device('046-natural-expiry-readonly-observation',D1);after=device('047-natural-access-expired-before-revoke',D1)
check('original default access TTL is 600 seconds', (datetime.datetime.fromisoformat(before['access_expires_at'].replace('Z','+00:00'))-datetime.datetime.fromisoformat(before['created_at'].replace('Z','+00:00'))).total_seconds()==600)
check('same deadline before and after natural wait',before['access_expires_at']==after['access_expires_at'])
check('original device naturally expired, not revoked during wait',not before['access_expired_at_observation'] and after['access_expired_at_observation'] and after['revoked_at'] is None)
check('device still naturally expired immediately before effective confirm',device('070-visible-confirm-expiry',D1)['access_expired_at_observation'])
network=evaluation('076-current-device-final-network')
r=network.get('resources',network.get('requests',[]))
# Some earlier observations use authRequests as the public field; inspect the actual recorded payload only.
if not r:r=network.get('authRequests',[])
check('natural-expiry final page is login',network['url'].endswith('/login'))
check('refresh200 observed in natural-expiry chain',any(x['path']=='/api/v1/auth/refresh' and x['status']==200 for x in r))
check('one exact D1 revoke request200',len([x for x in r if x['path']=='/api/v1/auth/devices/'+D1 and x['status']==200])==1)
check('D1 persisted user_revoked',device('075-current-device-final-audit',D1)['revoke_reason']=='user_revoked')
check('D2 actual login200',any(x['path']=='/api/v1/auth/login' and x['status']==200 for x in evaluation('100-d2-readonly-after-runtime-recovered')['resources']))
shared=evaluation('105-d2-late-sibling-readonly');ended=evaluation('112-shared-sibling-after-logout-no-reload')
check('shared page actually authenticated before logout',shared['url'].endswith('/platform/knowledge-bases') and shared['userText']=='auth-qa-20261012' and any(x['path']=='/api/v1/auth/me' and x['status']==200 for x in shared['resources']))
check('shared page automatically returned login without sidebar',ended['url'].endswith('/login') and ended['sidebarPresent'] is False and ended['loginHeading'] is True)
check('shared automatic login navigation preserved',ended['navigation'][0]['type']=='navigate')
logout=evaluation('114-d2-single-logout-final-network')['resources']
check('one actual D2 logout200',len([x for x in logout if x['path']=='/api/v1/auth/logout' and x['status']==200])==1)
check('D2 persisted logout',device('113-shared-logout-db-outcome',D2)['revoke_reason']=='logout')
check('logout protected-deep-link rejected401',any(x['path']=='/api/v1/auth/me' and x['status']==401 for x in evaluation('116-loggedout-deeplink-auth-rejected')['resources']))
pre=raw('141-two-valid-devices-before-current-revoke')
check('new D3 and D4 valid simultaneously',all(device('141-two-valid-devices-before-current-revoke',d)['revoked_at'] is None and not device('141-two-valid-devices-before-current-revoke',d)['access_expired_at_observation'] for d in [D3,D4]))
check('new D3 persisted user_revoked',device('143-current-d3-single-revoke-durable',D3)['revoke_reason']=='user_revoked')
check('one exact D3 revoke200',len([x for x in evaluation('144-d3-revoke-final-network')['resources'] if x['path']=='/api/v1/auth/devices/'+D3 and x['status']==200])==1)
check('D3 page returned login',evaluation('144-d3-revoke-final-network')['url'].endswith('/login'))
public_keys=['id','user_id','name','client_type','created_at','last_seen_at','access_expires_at','idle_expires_at','absolute_expires_at','revoked_at','revoke_reason']
pre_d4=device('141-two-valid-devices-before-current-revoke',D4);post_d4=device('148-d4-preserved-device-after-new-document',D4)
check('other-partition D4 public fields exactly preserved',all(pre_d4[k]==post_d4[k] for k in public_keys))
profiles=raw('129-two-devices-profile-pages')['owned_profile_tabs']
check('two independent profiles for new devices',next(x for x in profiles if x['browserPageId']=='e4fa4cd8-169e-4b52-9584-8782c73189a7')['profileId']!=next(x for x in profiles if x['browserPageId']=='9196f757-1a9d-407e-b44a-c32566d70c4e')['profileId'])
check('actual owned tab close observed after timeout',not any(x['browserPageId']=='9196f757-1a9d-407e-b44a-c32566d70c4e' for x in raw('145-d4-close-late-final-state')['owned_profile_tabs']))
restore=evaluation('150-d4-restored-page-final-public-read')
check('new document opened protected device page',restore['url'].endswith('/platform/settings/devices') and restore['navigation'][0]['type']=='navigate')
check('correct own user restored',restore['user']=='auth-qa-20261012')
check('new document me and devices200',all(any(x['path']=='/api/v1/auth/'+path and x['status']==200 for x in restore['resources']) for path in ['me','devices']))
check('no login or refresh to restore still-valid D4',not any(x['path'] in ['/api/v1/auth/login','/api/v1/auth/refresh'] for x in restore['resources']))
check('device page has one current and three revoked',sum('当前设备' in x for x in restore['deviceRows'])==1 and sum('已撤销' in x for x in restore['deviceRows'])==3)
final=raw('156-own-devices-all-revoked-cleanup')
check('all four QA devices revoked after cleanup',len(final['devices'])==4 and all(x['revoked_at'] for x in final['devices']))
check('one final cleanup logout200',len([x for x in evaluation('157-cleanup-logout-final-network')['resources'] if x['path']=='/api/v1/auth/logout' and x['status']==200])==1)
check('zero vendor usage and unrelated QA data',all(final['counts'][key]==0 for key in ['knowledge_bases','knowledges','chunks','model_usage','desktop_jobs']))
stop=raw('158-owned-services-normal-stop')
check('only owned two SIGTERM pidfd stops',len(stop['signals'])==2 and all(x['signal']=='SIGTERM' and x['through']=='pidfd' and x['kernel_exit_observed'] and not x['forced_termination'] for x in stop['signals']))
check('source ownership preserved across own stop',stop['source_guard_before'] and stop['source_guard_after'])
check('auth public state preserved across own stop',stop['public_auth_state_unchanged_across_stop'] and stop['before']==stop['after'])
check('no owned process remains',not stop['remaining_own_process_pids'])
exit_receipt=raw('160-owned-exec-final-receipts')
check('actual core0 and Vite143 retained',exit_receipt['core']['value']['exit_code']==0 and exit_receipt['vite']['value']['exit_code']==143)
check('no GUI after handover in own close receipts',stop['browser_commands_after_gui_handover']==0 and exit_receipt['gui_commands_after_handover']==0)
if PRIVATE.is_symlink() or PRIVATE.stat().st_uid!=os.getuid() or stat.S_IMODE(PRIVATE.stat().st_mode)!=0o600:raise RuntimeError('Private QA file guard failed')
secret=json.loads(PRIVATE.read_text())['password'].encode()
helper_names=['marlin-auth-vite-20261012.mjs','marlin-auth-qa-driver-20261012.py','marlin-auth-qa-private-fill-20261012.py','marlin-auth-qa-observe-20261012.py','marlin-auth-qa-tab-metadata-20261012.py','marlin-auth-qa-doc-check-20261012.py','marlin-auth-qa-evidence-privacy-20261012.py','marlin-auth-qa-screenshot-20261012.py','marlin-auth-qa-update-doc-20261012.py','marlin-auth-qa-stop-owned-20261012.py','marlin-auth-qa-finalize-doc-20261012.py','marlin-auth-qa-cleanup-freeze-20261012.py']
archive=OUT/'helpers';archive.mkdir(exist_ok=False)
helpers=[]
for name in helper_names:
    source=pathlib.Path('/tmp')/name
    if source.is_symlink() or not source.is_file() or source.stat().st_uid!=os.getuid():raise RuntimeError('Owned helper guard failed: '+name)
    target=archive/name
    shutil.copyfile(source,target)
    helpers.append({'temporary_path':str(source),'archived_path':str(target.relative_to(ROOT)),'sha256':sha(source)})
paths=[DOC]+[p for p in OUT.rglob('*') if p.is_file()]
check('own synthetic plaintext absent from new doc/evidence/helpers',not any(secret in p.read_bytes() for p in paths))
privacy_files_checked=len(paths)
PRIVATE.unlink()
for name in helper_names:(pathlib.Path('/tmp')/name).unlink()
cache_before={'path':str(CACHE),'exists':CACHE.exists(),'files':0}
if CACHE.exists():
    if CACHE.is_symlink() or CACHE.resolve()!=CACHE or CACHE.stat().st_uid!=os.getuid():raise RuntimeError('Own cache guard failed')
    cache_before['files']=sum(p.is_file() for p in CACHE.rglob('*'))
    shutil.rmtree(CACHE)
cleanup={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'archived_then_removed_helpers':helpers,'helper_count':len(helpers),'synthetic_private_file_removed':not PRIVATE.exists(),'synthetic_private_file_archived':False,'synthetic_password_hash_printed':False,'private_file_mode_before':'0600','own_plaintext_scan_files':privacy_files_checked,'own_plaintext_matches':[],'cache_before':cache_before,'cache_removed':not CACHE.exists(),'temporary_helper_paths_remaining':[name for name in helper_names if (pathlib.Path('/tmp')/name).exists()],'qa_data_root_retained':True,'new_orca_profiles_and_login_pages_retained_for_root':True,'authorized_backup_profile_last_observed':'default','authorized_backup_url_last_observed':'http://127.0.0.1:5173/login','source_gui_or_cookie_cleanup_performed':False,'gui_commands_after_handover':0}
FINAL_PATHS[0].write_text(json.dumps(cleanup,ensure_ascii=False,indent=2)+'\n')
s=DOC.read_text().replace('临时私有QA口令、助手与独立Vite cache的清理，以及最终链接/差异/源码绑定与独立freeze见后置凭证。','[161临时清理凭证](../refactor-evidence/20261012-auth-browser-isolation-real/161-temporary-cleanup.json)核定12个助手已归档SHA并删除、0600合成口令文件未归档且已删除、独立Vite cache已删除；自有口令仅对本批文档/证据/归档助手扫描，没有明文匹配，不扩大为全系统秘密审计。[162最终只读检查](../refactor-evidence/20261012-auth-browser-isolation-real/162-final-readonly-check.json)绑定原始结果、链接/差异和12个既有源码SHA，独立freeze.json位于同证据目录。')
DOC.write_text(s)
base=raw('000-preflight')['source_files']
changed=[x['path'] for x in base if sha(ROOT/x['path'])!=x['sha256']]
check('12 pre-existing auth/core source/compiled bindings unchanged',not changed)
source_proc=pathlib.Path('/proc/2245508')
check('original source remains same PID/startTicks',source_proc.exists() and (source_proc/'stat').read_text().rsplit(') ',1)[1].split()[19]=='17581590')
links=re.findall(r'\]\(([^)]+)\)',DOC.read_text())
missing=[]
for value in links:
    if '://' in value:continue
    target=(DOC.parent/urllib.parse.unquote(value.split('#')[0])).resolve()
    if not target.exists() and target!=FINAL_PATHS[1]:missing.append(value)
check('document links resolved, except the check receipt generated now',not missing)
diff=subprocess.run(['git','diff','--check','--',str(DOC.relative_to(ROOT)),str(OUT.relative_to(ROOT))],cwd=ROOT,capture_output=True,text=True)
check('git diff check exit0',diff.returncode==0)
record={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'assertion_count':len(checks),'assertions':checks,'links_checked':len(links),'missing_links':missing,'source_bindings_checked':len(base),'changed_source_bindings':changed,'platform_vue_current_sha256':sha(ROOT/'frontend/src/views/Platform.vue'),'diff_check_exit':diff.returncode,'diff_stdout':diff.stdout,'diff_stderr':diff.stderr,'doc_sha256':sha(DOC),'original_source_pid':2245508,'original_source_start_ticks':'17581590','vendor_calls':0,'gui_after_lease_handover':0,'check_kind':'Read-only original evidence/content/link/source validation; not a product test rerun or new GUI acceptance','temporary_helpers_cleaned':len(helpers),'owned_core_stopped':True,'owned_vite_exec_exit':143,'remaining':'Whole browser restart; post-final-revoke reopen; same logout with other active device; late refresh barrier; extra permission/source/download/subscription cases; installed GUI.'}
FINAL_PATHS[1].write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
if any(not (DOC.parent/urllib.parse.unquote(v.split('#')[0])).exists() for v in links if '://' not in v):raise AssertionError('Links not actually present after check receipt publication')
files=[{'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(OUT.rglob('*')) if p.is_file()]
manifest={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'document':{'path':str(DOC.relative_to(ROOT)),'bytes':DOC.stat().st_size,'sha256':sha(DOC)},'evidence_files':files,'evidence_file_count':len(files),'original_auth_source_bindings':base,'additional_platform_source':{'path':'frontend/src/views/Platform.vue','sha256':sha(ROOT/'frontend/src/views/Platform.vue')},'assertion_count':len(checks),'links_checked':len(links),'all_assertions_passed':all(x['passed'] for x in checks),'all_links_exist':True,'goal_status':'active; this isolated batch complete only for listed subcases','source_product_files_edited_by_this_batch':0,'models_calls':0,'gui_lease_released':True,'owned_services_stopped':True,'actual_exec_exit_codes':{'core':0,'vite':143},'temporary_helper_count_removed':len(helpers),'synthetic_private_file_removed':not PRIVATE.exists(),'retained_profiles':['f97e4ab1-3837-49fd-881a-45ebecd5d211','a372a0fd-72c3-4efe-b908-855756682c3c'],'retained_owned_pages_last_seen':['e4fa4cd8-169e-4b52-9584-8782c73189a7','e87a76af-50bc-49b2-9b29-e9f6d19c88a5','c238d027-40e5-4e54-91f0-6890763922a3'],'retained_qa_data_root':'/home/liuxuedeng/.local/share/marlin-refactor/20261012-auth-browser-isolation'}
FINAL_PATHS[2].write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'document_sha256':sha(DOC),'freeze_sha256':sha(FINAL_PATHS[2]),'evidence_file_count':len(files),'assertion_count':len(checks),'links_checked':len(links),'helpers_removed':len(helpers),'private_removed':not PRIVATE.exists(),'own_cache_removed':not CACHE.exists(),'original_source_alive_unchanged':True,'all_assertions_passed':True},ensure_ascii=False,indent=2))
