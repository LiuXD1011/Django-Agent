import datetime,hashlib,json,re,shutil,subprocess
from pathlib import Path
r=Path('/home/liuxuedeng/Django-Agent');e=r/'docs/refactor-evidence/20261012-web-search-config-browser';d=r/'docs/desktop-refactor/WEB-SEARCH-CONFIG-BROWSER-REVIEW.md'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
links=re.findall(r'\]\(([^)]+)\)',d.read_text());assert all((d.parent/x).exists() for x in links)
c=json.loads((e/'007-web-provider-counts-readonly.json').read_text());assert c['web_search_provider_live_count']==0 and c['web_search_provider_active_count']==0 and c['usage_total']==162 and c['active_jobs']==0
cleanup=[]
for p in [Path('/tmp/marlin-web-search-browser-20261012.py'),Path('/tmp/marlin-web-search-readonly-20261012.py'),Path(__file__)]:
 q=e/('archived-'+p.name);shutil.copyfile(p,q);s=sha(p);assert sha(q)==s;p.unlink();cleanup.append({'temp':str(p),'archive':str(q.relative_to(r)),'sha256':s,'removed':not p.exists()})
diff=subprocess.run(['git','diff','--check','--no-index','/dev/null',str(d)],capture_output=True);assert diff.returncode in (0,1) and not diff.stdout and not diff.stderr
sources=['frontend/src/views/Settings.vue','frontend/src/api/index.ts','frontend/src/router/index.ts','packages/core/src/adapters/settings-routes.ts','packages/core/src/agents/tools.ts','packages/core/src/integrations/index.ts']
out={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'document':{'path':str(d.relative_to(r)),'sha256':sha(d)},'evidence':[{'path':str(p.relative_to(r)),'sha256':sha(p)} for p in sorted(e.iterdir()) if p.is_file() and p.name!='freeze.json'],'readonly_source_binding':[{'path':x,'sha256':sha(r/x)} for x in sources],'links_checked':len(links),'missing_links':[],'diff_check':{'exit_code':diff.returncode,'stdout':'','stderr':''},'cleanup':cleanup,'scope':'actual UI configuration gap; no enable save/provider call/model/UI repair'}
(e/'freeze.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'document_sha256':sha(d),'freeze_sha256':sha(e/'freeze.json'),'evidence_count':len(out['evidence']),'links':len(links),'cleanup':cleanup},ensure_ascii=False,indent=2))
