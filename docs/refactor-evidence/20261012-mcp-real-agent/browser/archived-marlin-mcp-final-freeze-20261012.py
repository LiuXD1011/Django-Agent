import pathlib,json,hashlib,re,subprocess,shutil,datetime
root=pathlib.Path('/home/liuxuedeng/Django-Agent'); folder=root/'docs/refactor-evidence/20261012-mcp-real-agent/browser'; doc=root/'docs/desktop-refactor/MCP-REAL-AGENT-BROWSER.md'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def get(n):return json.loads(next(folder.glob(n+'-*.json')).read_text())
a,b,t,c=get('075'),get('105'),get('108'),get('100');checks=[]
def verify(name,value):
 assert value,name
 checks.append({'name':name,'passed':True})
verify('protected models key original documents wiki testsets exact',all(a[k]==b[k] for k in ['models_rows_sha256','models_count','credential_key_sha256','protected']))
verify('usage increment four bounded',b['model_usage_total']-a['model_usage_total']==4 and b['tenant2_model_usage']-a['tenant2_model_usage']==4)
verify('no active jobs',not b['active_jobs'])
def guard(d,i):return next(x for x in d['mcp_row_guards'] if x['id']==i)
own='e13171b1-5ca7-4622-b579-cc07c5247f1b';old='b0134fd6-52e3-4b95-a811-9af02c5428e8'
verify('cancel preserves own exact row and other historical service unchanged',guard(a,own)==guard(c,own) and guard(a,old)==guard(b,old))
verify('only self softdeleted',next(x for x in b['mcp_services_non_secret'] if x['id']==own)['deleted_at']=='2026-10-12T01:46:25.824Z')
config=json.loads(t['session'][0]['agent_config']);sid=t['session'][0]['id'];rid=t['messages'][0]['request_id']
verify('explicit empty KB no web self service',config['knowledge_base_ids']==[] and config['knowledge_selection_explicit'] is True and config['web_search_enabled'] is False and config['mcp_service_ids']==[own])
verify('two messages eighteen events one completed main and maintenance',len(t['messages'])==2 and len(t['events'])==18 and len(t['jobs'])==2 and all(j['status']=='completed' and j['attempt']==1 and j['error']=='' for j in t['jobs']))
u=t['usage'];verify('four actual successful distinct linked calls',len(u)==4 and len({x['id'] for x in u})==4 and all(x['request_count']==1 and x['success']==1 and x['request_id']==rid and json.loads(x['metadata'])['session_id']==sid and json.loads(x['metadata'])['model_call_id']==x['id'] for x in u))
verify('accurate tokens',sum(x['total_tokens'] for x in u)==3353 and t['usage_totals']=={'request_count':4,'prompt_tokens':2761,'completion_tokens':592,'total_tokens':3353,'cached_tokens':0,'reasoning_tokens':166})
proto=t['server_actual_gui_protocol_snapshot']; calls=[x for x in proto if x['event']=='tool_called']; receipt='62243c11-8d31-4df1-b4ff-9f411d5635ba:2'
verify('actual authenticated discovery one invocation new service receipt',len(proto)==13 and all(x['setupSmoke'] is False for x in proto) and all(x['matched'] is True for x in proto if x['event']=='protocol_request') and sum(x.get('method')=='tools/list' for x in proto)==1 and sum(x.get('method')=='tools/call' for x in proto)==1 and len(calls)==1 and calls[0]['quantity']==12 and calls[0]['unit_price']==79 and calls[0]['subtotal']==948 and calls[0]['receipt_id']==receipt)
result=[json.loads(x['data']) for x in t['events'] if x['type']=='tool/result'];verify('tool result and answer match actual receipt',len(result)==1 and result[0]['error']=='' and receipt in result[0]['output'] and receipt in t['messages'][1]['content'] and '948' in t['messages'][1]['content'])
verify('actual screenshot preserved',sha(folder/'089-mcp-agent-trajectory-render-screenshot.png')=='a41e6991a7295665862ace95f537adad7cefafb39c82b8073a94154146b3fc4f')
verify('original P1 freeze preserved',sha(folder/'p1-discovery/freeze.json')=='091228d729096b32b9b4e630b7ce8c428d4901c053a878706cb5ee7dbe408efd')
links=[]
for link in re.findall(r'\]\(([^)]+)\)',doc.read_text()):
 if re.match(r'\w+://',link):continue
 target=(doc.parent/link.split('#')[0]).resolve(); verify('link '+link,target.exists() or target==folder/'freeze.json');links.append(link)
p=subprocess.run(['git','diff','--check','--',str(doc.relative_to(root))],cwd=root,capture_output=True,text=True);verify('tracked diff check',p.returncode==0 and not p.stdout and not p.stderr)
p=subprocess.run(['git','diff','--no-index','--check','/dev/null',str(doc)],cwd=root,capture_output=True,text=True);verify('untracked document diff check',p.returncode in [0,1] and not p.stdout and not p.stderr)
cleanup=[]
for source in [pathlib.Path('/tmp/marlin-mcp-browser-20261012.py'),pathlib.Path('/tmp/marlin-mcp-protected-readonly-20261012.py'),pathlib.Path('/tmp/marlin-mcp-turn-readonly-20261012.py'),pathlib.Path(__file__)]:
 dest=folder/('archived-'+source.name);h=sha(source);shutil.copyfile(source,dest);verify('archive hash '+source.name,sha(dest)==h);source.unlink();cleanup.append({'temporary_path':str(source),'archive':str(dest.relative_to(root)),'sha256':h,'removed':not source.exists()})
files=[{'path':str(x.relative_to(root)),'sha256':sha(x),'bytes':x.stat().st_size} for x in sorted(folder.rglob('*')) if x.is_file() and x.name!='freeze.json']
files.append({'path':str((folder/'p1-discovery/freeze.json').relative_to(root)),'sha256':sha(folder/'p1-discovery/freeze.json'),'bytes':(folder/'p1-discovery/freeze.json').stat().st_size})
manifest={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'actual browser MCP only; original SDK log remains root owned; actual protocol snapshot bound','page':'22e0e212-30aa-4945-8a3d-7176cdfffdff','document':{'path':str(doc.relative_to(root)),'sha256':sha(doc)},'files':files,'checks':checks,'links':links,'temporary_cleanup':cleanup,'vendor_invocations':4,'total_tokens':3353,'active_jobs_at_final_snapshot':0,'goal_complete':False}
(folder/'freeze.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'files':len(files),'checks':len(checks),'links':len(links),'temporary_cleanup':len(cleanup),'document_sha256':sha(doc),'freeze_sha256':sha(folder/'freeze.json')},ensure_ascii=False))
