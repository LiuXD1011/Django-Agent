import datetime,hashlib,json,re,shutil,subprocess
from pathlib import Path
r=Path('/home/liuxuedeng/Django-Agent');browser=r/'docs/refactor-evidence/20261012-mcp-real-agent/browser';e=browser/'p1-discovery';e.mkdir(exist_ok=True);d=r/'docs/desktop-refactor/MCP-EDIT-PROJECTION-BROWSER-FAILURE.md'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
links=re.findall(r'\]\(([^)]+)\)',d.read_text());assert all((d.parent/x).exists() for x in links)
f=json.loads((browser/'034-mcp-p1-protected-before-fix-readonly.json').read_text());g=json.loads((r/'docs/refactor-evidence/20261012-general-page-browser/123-general-final-protected-readonly.json').read_text())
assert f['protected']==g['protected'] and f['models_rows_sha256']==g['models_rows_sha256'] and f['credential_key_sha256']==g['credential_key_sha256'] and f['model_usage_total']==162 and not f['active_jobs']
new=next(x for x in f['mcp_row_guards'] if x['id']=='e13171b1-5ca7-4622-b579-cc07c5247f1b');assert new['credential_field_encrypted']
for p in sorted(browser.iterdir()):
 if p.is_file() and p.suffix in ('.json','.py') and p.name!='freeze.json':shutil.copyfile(p,e/p.name)
p=Path(__file__);q=e/('archived-'+p.name);shutil.copyfile(p,q);s=sha(p);p.unlink();assert not p.exists() and sha(q)==s
diff=subprocess.run(['git','diff','--check','--no-index','/dev/null',str(d)],capture_output=True);assert diff.returncode in (0,1) and not diff.stdout and not diff.stderr
diag={'first_protected_helper_error':'sqlite3.OperationalError: no such column: payload','classification':'readonly fixture schema mistake; valid source column is data; no product RED','failed_script':'protected-helper-schema-error.py','first_add_click_no_modal':'004/005 did not open modal; 006 scroll then 007 actual visible click opened 008; first receipt not success','server_logs_in_freeze':False}
(e/'diagnostics.json').write_text(json.dumps(diag,ensure_ascii=False,indent=2)+'\n')
sources=['frontend/src/views/Settings.vue','frontend/src/views/chat/components/ChatInput.vue','frontend/src/views/Chat.vue','packages/core/src/settings/settings.ts','packages/core/src/settings/internal.ts','packages/core/src/storage/credentials.ts']
out={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'document':{'path':str(d.relative_to(r)),'sha256':sha(d)},'evidence':[{'path':str(x.relative_to(r)),'sha256':sha(x),'bytes':x.stat().st_size} for x in sorted(e.iterdir()) if x.is_file() and x.name!='freeze.json'],'source_binding':[{'path':x,'sha256':sha(r/x)} for x in sources],'checks':{'links_checked':len(links),'missing_links':[],'protected_exact':True,'usage':162,'active_jobs':0,'new_mcp_row_guard':new,'diff_check_exit':diff.returncode,'diff_stdout':'','diff_stderr':'','cleanup':{'temp':str(p),'archive':str(q.relative_to(r)),'sha256':s,'removed':True}},'scope':'actual MCP create success/edit400 only; no GUI tool-schema discovery or paid Agent; server logs not frozen'}
(e/'freeze.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'doc_sha256':sha(d),'freeze_sha256':sha(e/'freeze.json'),'files':len(out['evidence']),'checks':out['checks']},ensure_ascii=False,indent=2))
