import datetime,hashlib,json,re,shutil,subprocess
from pathlib import Path
from urllib.parse import unquote
r=Path('/home/liuxuedeng/Django-Agent');e=r/'docs/refactor-evidence/20261012-chinese-query-browser';doc=r/'docs/desktop-refactor/EVALUATION-CHINESE-QUERY-BROWSER.md';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
before=json.loads((e/'039-real-ragas-before-baseline-readonly.json').read_text());after=json.loads((e/'060-real-ragas-report-after-delete-cancel-readonly.json').read_text());monitor=json.loads((e/'047-real-ragas-budget-progress-readonly.json').read_text());report=json.loads((e/'053-real-ragas-actual-report-opened.json').read_text())
testsets=['2f99f534-5d8a-45b8-ba67-3ddd87f740d5','24e9e43f-742d-4de1-99d5-fb33e7835dc8','6c630a4d-309d-4dfd-8bac-b31bfdd20bec']
identity=lambda d,i:next(x for x in d['evaluation_resources'] if x['id']==i)['row_sha256']
checks={
 'three_testsets_unchanged':all(identity(before,i)==identity(after,i) for i in testsets),
 'models_unchanged':before['four_models_row_sha256']==after['four_models_row_sha256'],
 'vault_unchanged':before['credential_key_sha256']==after['credential_key_sha256'],
 'paid_run_completed_first_attempt':monitor['job']['status']=='completed' and monitor['job']['attempt']==1,
 'all_45_calls_successful':len(monitor['usage'])==45 and all(x['success']==1 and x['request_count']==1 for x in monitor['usage']),
 'all_45_unique_ledger_completed':len(monitor['ledger'])==45 and len({x['invocation_id'] for x in monitor['ledger']})==45 and all(x['status']=='completed' for x in monitor['ledger']),
 'within_bound':not monitor['limits']['usage_exceeded'] and not monitor['limits']['time_exceeded'],
 'report_actual_file_exact':sha(Path(report['actual_file']))==report['sha256'],
 'samples_5':report['report_json']['metrics']['samples']==5,
 'unavailable_metrics_null':report['report_json']['metrics']['context_recall'] is None and report['report_json']['metrics']['answer_correctness'] is None,
 'protected_sources_exact':json.loads((r/'docs/refactor-evidence/20261012-general-page-browser/002-general-before-protected-readonly.json').read_text())['protected']==json.loads((e/'063-protected-originals-after-ragas-readonly.json').read_text())['protected'],
}
assert all(checks.values()),checks
scripts=e/'scripts';scripts.mkdir(exist_ok=True);cleanup=[]
for p in [Path('/tmp/marlin-chinese-query-browser-20261012.py'),Path('/tmp/marlin-chinese-query-readonly-20261012.py'),Path('/tmp/marlin-chinese-query-report-open-20261012.py'),Path('/tmp/marlin-chinese-query-source-review-20261012.py'),Path('/tmp/marlin-chinese-query-ragas-monitor-20261012.py'),Path(__file__)]:
 archive=scripts/p.name;shutil.copyfile(p,archive);p.unlink();cleanup.append({'temporary':str(p),'archived':str(archive.relative_to(r)),'sha256':sha(archive),'deleted':not p.exists()})
for n in ['final-check.json','freeze.json']:(e/n).write_text('{}\n')
links=[]
for t in re.findall(r'\[[^\]]*\]\(([^)]+)\)',doc.read_text()):
 if t.startswith(('https:','http:','#')):continue
 target=(doc.parent/unquote(t.split('#',1)[0].strip('<>'))).resolve();links.append({'target':t,'exists':target.exists()})
assert all(x['exists'] for x in links),links
cmd=['git','diff','--check','--',str(doc.relative_to(r))];p=subprocess.run(cmd,cwd=r,capture_output=True,text=True);assert p.returncode==0,(p.stdout,p.stderr)
final={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'checks':checks,'command':cmd,'exit_code':p.returncode,'stdout':p.stdout,'stderr':p.stderr,'relative_links':links,'temporary_scripts':cleanup,'general_helpers_retained_for_pending_task':['/tmp/marlin-general-page-browser-20261012.py','/tmp/marlin-general-page-readonly-20261012.py']}
(e/'final-check.json').write_text(json.dumps(final,ensure_ascii=False,indent=2)+'\n')
freeze={'frozen_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'page_guid':'22e0e212-30aa-4945-8a3d-7176cdfffdff','document_sha256':{str(doc.relative_to(r)):sha(doc)},'evidence_sha256':{str(p.relative_to(r)):sha(p) for p in sorted(e.rglob('*')) if p.is_file() and p.name!='freeze.json'},'actual_ragas':{'run_id':monitor['run_id'],'report_id':monitor['report_id'],'job_status':monitor['job']['status'],'attempt':1,'elapsed_seconds':monitor['elapsed_core_seconds'],'model_usage_rows':45,'tokens':sum(x['total_tokens'] for x in monitor['usage']),'usage_groups':monitor['usage_groups'],'metrics':report['report_json']['metrics']['ragas'],'report_file_sha256':report['sha256']},'limitations':['Five simple questions from one fictional manual; not a general production benchmark','Public/full datasets, auto/sample, cancellation/resumption and other strategies not covered','Browser success does not replace final Windows installer/IPC acceptance','No product source changes in this GUI phase','Goal remains active']}
(e/'freeze.json').write_text(json.dumps(freeze,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'document_sha256':sha(doc),'freeze_sha256':sha(e/'freeze.json'),'final_check_sha256':sha(e/'final-check.json'),'evidence_files':len(freeze['evidence_sha256']),'links_checked':len(links),'checks':checks,'temporary_scripts_deleted':all(x['deleted'] for x in cleanup)},indent=2))
