import datetime,hashlib,json,re,shutil,subprocess
from pathlib import Path
r=Path('/home/liuxuedeng/Django-Agent');e=r/'docs/refactor-evidence/20261012-general-page-browser';d=r/'docs/desktop-refactor/GENERAL-PAGE-BROWSER-ACCEPTANCE.md'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
load=lambda name:json.loads((e/name).read_text())
links=[x for x in re.findall(r'\]\(([^)]+)\)',d.read_text()) if not x.startswith(('http:','https:','#'))]
assert all((d.parent/x.split('#')[0]).exists() for x in links)
b=load('002-general-before-protected-readonly.json');f=load('123-general-final-protected-readonly.json')
assert b['protected']==f['protected']
assert b['models_rows_sha256']==f['models_rows_sha256'] and b['credential_key_sha256']==f['credential_key_sha256']
assert f['model_usage_total']==162 and not f['active_jobs']
assert len(f['own_knowledge_bases'])==2 and all(x['deleted_at'] and not x['is_pinned'] for x in f['own_knowledge_bases'])
assert all(all(v==0 for v in counts.values()) for counts in f['own_related_counts'].values())
p=load('103-own-wiki-version2-actual-readonly.json')['pages'][0];c=load('111-own-wiki-delete-cancel-readonly.json')['pages'][0];z=load('116-own-wiki-deleted-readonly.json')['pages'][0]
assert p==c and p['version']==2 and p['deleted_at'] is None and z['version']==3 and z['deleted_at']
temps=[Path('/tmp/marlin-general-page-browser-20261012.py'),Path('/tmp/marlin-general-page-readonly-20261012.py'),Path('/tmp/marlin-general-wiki-readonly-20261012.py'),Path(__file__)]
cleanup=[]
for p in temps:
 q=e/('archived-'+p.name);shutil.copyfile(p,q);s=sha(p);assert sha(q)==s;p.unlink();cleanup.append({'temporary_path':str(p),'archive':str(q.relative_to(r)),'sha256':s,'removed':not p.exists()})
diag={'old_wiki_guard':{'original_evidence':'089-own-manual-wiki-saved-protected-readonly.json','reason':'v1 selected all tenant Wiki rows, including authorized own new page; corrected fixed two-KB scope restores exact original 13-row SHA','corrected_evidence':'092-original-wiki-guard-scope-corrected-readonly.json'},'first_wiki_helper_error':{'command':'python3 /tmp/marlin-general-wiki-readonly-20261012.py 098-own-wiki-version2-readonly','error':'sqlite3.OperationalError: no such column: links','archive':'wiki-readonly-helper-first-schema-error.py','classification':'read-only fixture schema mistake, no product RED or database writes'},'cli_prefix_errors':['052-own-filtered-refresh-click.json','053-own-filtered-after-refresh-snapshot.json']}
(e/'diagnostics.json').write_text(json.dumps(diag,ensure_ascii=False,indent=2)+'\n')
p=subprocess.run(['git','diff','--check','--no-index','/dev/null',str(d)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
assert p.returncode in (0,1) and not p.stdout and not p.stderr
checks={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'links_checked':len(links),'missing_links':[],'protected_exact':True,'own_objects_cleaned':True,'no_model_calls_in_bf_segment':True,'last_usage':162,'wiki_cancel_preserved_exact_v2':True,'diff_check':{'exit_code':p.returncode,'stdout':p.stdout.decode(),'stderr':p.stderr.decode(),'exit1_is_new_file_diff':p.returncode==1},'temporary_cleanup':cleanup,'scope':'B empty KB operations and manual Wiki subitems only; no whole Goal/installed pass'}
(e/'checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n')
files=[{'path':str(x.relative_to(r)),'sha256':sha(x),'bytes':x.stat().st_size} for x in sorted(e.iterdir()) if x.is_file() and x.name!='freeze.json']
out={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'document':{'path':str(d.relative_to(r)),'sha256':sha(d)},'files':files,'scope':'General B/F GUI stage frozen; no product edits'}
(e/'freeze.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'doc_sha256':sha(d),'freeze_sha256':sha(e/'freeze.json'),'evidence_files':len(files),'links':len(links),'checks':checks},ensure_ascii=False,indent=2))
