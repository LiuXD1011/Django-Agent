import datetime,hashlib,json,re,subprocess
from pathlib import Path
root=Path('/home/liuxuedeng/Django-Agent');b=root/'docs/refactor-evidence/20261012-evaluation-minimum-samples';doc=root/'docs/desktop-refactor/EVALUATION-MINIMUM-SAMPLES.md'
owned=['frontend/src/views/Evaluation.vue','frontend/src/views/Evaluation.behavior.test.mjs','docs/desktop-refactor/EVALUATION-MINIMUM-SAMPLES.md']
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
links=[]
for m in re.finditer(r'\[[^\]]+\]\(([^)]+)\)',doc.read_text()):
 path=(doc.parent/m.group(1).split('#')[0]).resolve();links.append({'target':m.group(1),'exists':path.exists() or path==b/'final-check.json'})
legacy=root/'docs/refactor-evidence/20261012-evaluation-browser-page/freeze.json';frozen=json.loads(legacy.read_text());h_changed=[p for p,h in frozen['files_sha256'].items() if not (root/p).exists() or sha(root/p)!=h]
log=(b/'frontend-all-case-green.log').read_text();summary=[l for l in log.splitlines() if re.match(r'^(1\.\.|# (tests|suites|pass|fail|cancelled|skipped|todo|duration_ms) )',l)]
check=subprocess.run(['git','diff','--check','--',*owned],cwd=root,capture_output=True)
diff=subprocess.run(['git','diff','--',*owned[:2]],cwd=root,capture_output=True);(b/'product-and-test.diff').write_bytes(diff.stdout)
status=subprocess.run(['git','status','--short','--',*owned,str(b.relative_to(root))],cwd=root,capture_output=True)
source={p:sha(root/p) for p in owned};run=json.loads((b/'frontend-all-case-green.json').read_text());build=json.loads((b/'frontend-build.json').read_text())
r={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'only Evaluation RAG minimum and immutable partial instructions','source_sha256':source,'links_checked':len(links),'broken_links':[x for x in links if not x['exists']],'documentation_trailing_whitespace_lines':[i+1 for i,l in enumerate(doc.read_text().splitlines()) if l.rstrip()!=l],'git_diff_check_exit':check.returncode,'git_diff_check_stdout':check.stdout.decode(),'git_diff_check_stderr':check.stderr.decode(),'owned_git_status':status.stdout.decode(),'old_browser_evidence_files_checked':len(frozen['files_sha256']),'old_browser_evidence_changes':h_changed,'final_frontend_test_exit':run['exit_code'],'final_frontend_test_source_matches':all(source[p]==run['source_after_sha256'][p]==run['source_before_sha256'][p] for p in owned[:2]),'final_frontend_tap_summary':summary,'full_log_not_ok_lines':re.findall(r'^.*not ok.*$',log,re.M),'frontend_build_exit':build['exit_code'],'built_product_source_matches':source[owned[0]]==build['source_before_sha256'][owned[0]]==build['source_after_sha256'][owned[0]],'build_test_fixture_delta_only':source[owned[1]]!=build['source_before_sha256'][owned[1]],'real_vendor_calls_in_implementation':0,'live_gui_changed_by_implementation':False,'goal_complete':False}
(b/'final-check.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps(r,ensure_ascii=False,indent=2))
if r['broken_links'] or r['documentation_trailing_whitespace_lines'] or check.returncode or h_changed or run['exit_code'] or not r['final_frontend_test_source_matches'] or r['full_log_not_ok_lines'] or build['exit_code'] or not r['built_product_source_matches']:raise SystemExit(1)
