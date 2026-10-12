import datetime, hashlib, json, re, shutil, subprocess
from pathlib import Path
from urllib.parse import unquote
root=Path('/home/liuxuedeng/Django-Agent')
e=root/'docs/refactor-evidence/20261012-evaluation-real-recheck'
doc=root/'docs/desktop-refactor/EVALUATION-REAL-RECHECK.md'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
scripts=e/'scripts';scripts.mkdir(exist_ok=True)
general=root/'docs/refactor-evidence/20261012-general-page-browser';general.mkdir(exist_ok=True)
browser=Path('/tmp/marlin-evaluation-recheck-browser-20261012.py')
next_browser=Path('/tmp/marlin-general-page-browser-20261012.py')
next_browser.write_text(browser.read_text().replace("evidence=root/'docs/refactor-evidence/20261012-evaluation-real-recheck'", "evidence=root/'docs/refactor-evidence/20261012-general-page-browser'"))
cleanup=[]
for path in [browser,Path('/tmp/marlin-evaluation-recheck-readonly-20261012.py'),Path('/tmp/marlin-evaluation-recheck-source-review-20261012.py'),Path('/tmp/marlin-evaluation-keyword-read-diagnostic-20261012.mjs'),Path(__file__)]:
 archive=scripts/path.name;shutil.copyfile(path,archive);path.unlink();cleanup.append({'temporary':str(path),'archived':str(archive.relative_to(root)),'sha256':sha(archive),'deleted':not path.exists()})
for name in ['freeze.json','final-check.json']:(e/name).write_text('{}\n')
links=[]
for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)',doc.read_text()):
 if target.startswith(('https:','http:','#')):continue
 candidate=(doc.parent/unquote(target.split('#',1)[0].strip('<>'))).resolve();links.append({'target':target,'exists':candidate.exists()})
assert all(x['exists'] for x in links),links
command=['git','diff','--check','--',str(doc.relative_to(root))]
r=subprocess.run(command,cwd=root,capture_output=True,text=True);assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
check={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'command':command,'exit_code':r.returncode,'stdout':r.stdout,'stderr':r.stderr,'relative_links':links,'temporary_scripts':cleanup,'new_general_helper':str(next_browser),'new_general_helper_sha256':sha(next_browser),'new_general_helper_is_separate_pending_task':True}
(e/'final-check.json').write_text(json.dumps(check,ensure_ascii=False,indent=2)+'\n')
freeze={'frozen_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'page_guid':'22e0e212-30aa-4945-8a3d-7176cdfffdff','document_sha256':{str(doc.relative_to(root)):sha(doc)},'evidence_sha256':{str(p.relative_to(root)):sha(p) for p in sorted(e.rglob('*')) if p.is_file() and p.name!='freeze.json'},'coverage':{'generation':'one real manual/simple 5/5, five stop invocations, 849 tokens, reviewed and published','original_image_only_failure':'original 422 retained; actual fixed repeat 200, corpus includes PNG, zero new usage','report_download':'actual GUI history download; fresh file opened, 4827 bytes, SHA e88c3d855909eaa06498bdafbf2cdb731e4d560e96e33a6c04303be7d731bb96','keyword_diagnosis':'one real stored one-question keyword/no-rerank UI run, zero usage; native readonly SQL exact candidate path found 0 for old question and new five','paid_ragas':'not clicked; paused by root for CJK query recall repair'},'limitations':['No public/full datasets or auto/sample modes tested in this segment','No final installed Windows evaluation acceptance','No quality pass: actual keyword Hit/MRR/Recall were zero','Goal remains active']}
(e/'freeze.json').write_text(json.dumps(freeze,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'document_sha256':sha(doc),'freeze_sha256':sha(e/'freeze.json'),'final_check_sha256':sha(e/'final-check.json'),'evidence_files':len(freeze['evidence_sha256']),'links_checked':len(links),'temporary_scripts_deleted':all(x['deleted'] for x in cleanup)},indent=2))
