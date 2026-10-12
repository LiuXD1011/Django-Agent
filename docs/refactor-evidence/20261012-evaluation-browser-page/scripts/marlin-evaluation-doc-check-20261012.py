import datetime,hashlib,json,re,subprocess
from pathlib import Path
root=Path('/home/liuxuedeng/Django-Agent'); doc=root/'docs/desktop-refactor/EVALUATION-BROWSER-ACCEPTANCE.md'; base=root/'docs/refactor-evidence/20261012-evaluation-browser-page'
s=doc.read_text();links=[]
for match in re.finditer(r'\[[^\]]+\]\(([^)]+)\)',s):
 target=match.group(1);path=(doc.parent/target.split('#')[0]).resolve();links.append({'target':target,'exists':path.exists()})
whitespace=[i+1 for i,line in enumerate(s.splitlines()) if line.rstrip()!=line]
p=subprocess.run(['git','diff','--no-index','--check','/dev/null',str(doc)],cwd=root,capture_output=True)
patch=subprocess.run(['git','diff','--no-index','--','/dev/null',str(doc)],cwd=root,capture_output=True)
(base/'acceptance-document.diff').write_bytes(patch.stdout)
final=json.loads((base/'091-final-readonly.json').read_text()); prev=json.loads((base/'085-after-v2-delete-readonly.json').read_text())
checks={'markdown_link_count':len(links),'broken_links':[r for r in links if not r['exists']],'trailing_whitespace_lines':whitespace,'no_index_diff_check_exit':p.returncode,'diff_check_stdout':p.stdout.decode(),'diff_check_stderr':p.stderr.decode(),'final_resource_rows_equal_post_delete':final['evaluation_resources']==prev['evaluation_resources'],'final_usage_rows_equal_post_delete':final['generation_usage']==prev['generation_usage'],'final_model_rows_equal_post_delete':final['model_rows_sha256']==prev['model_rows_sha256'],'final_no_active_evaluation_jobs':not final['active_evaluation_jobs'],'scope_goal_still_active':'Goal仍active' in s,'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
(base/'document-check-corrected.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n');print(json.dumps(checks,ensure_ascii=False,indent=2))
if checks['broken_links'] or whitespace or p.returncode not in (0,1) or p.stdout or p.stderr or not all(checks[k] for k in ['final_resource_rows_equal_post_delete','final_usage_rows_equal_post_delete','final_model_rows_equal_post_delete','final_no_active_evaluation_jobs','scope_goal_still_active']):raise SystemExit(1)
