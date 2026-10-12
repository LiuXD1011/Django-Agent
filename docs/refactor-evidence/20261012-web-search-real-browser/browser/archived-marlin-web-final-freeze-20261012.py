import pathlib,json,hashlib,re,subprocess,shutil,datetime
root=pathlib.Path('/home/liuxuedeng/Django-Agent');folder=root/'docs/refactor-evidence/20261012-web-search-real-browser/browser';doc=root/'docs/desktop-refactor/WEB-SEARCH-REAL-AGENT-BROWSER.md'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def get(n):return json.loads(next(folder.glob(n+'-*.json')).read_text())
def result(n):return json.loads(get(n)['receipt']['result']['result'])
def snap(n):return get(n)['receipt']['result']['snapshot']
checks=[]
def verify(name,value):
 assert value,name
 checks.append({'name':name,'passed':True})
a,b,t=get('001'),get('205'),get('208');verify('original config null and no provider',a['web_search_original_or_current']['value'] is None and a['web_services_non_secret']==[])
verify('protected models vault knowledge wiki tests MCP exact',all(a[k]==b[k] for k in ['models_rows_sha256','models_count','credential_key_sha256','protected','mcp_row_guards']))
verify('exact UI cleanup config differs from original null',b['web_search_original_or_current']['safe_raw_json']=='{"enabled":false,"provider_id":""}' and b['web_search_original_or_current']['raw_sha256']=='5e2f253d5847922531fbf74063a50470d3d23e9a83fb0ae83c3695d9b7e439b4')
verify('only two own providers softdeleted',{x['id'] for x in b['web_services_non_secret']}=={'60e3bf87-c68f-46cf-8cfc-ab0567f98d6f','23cce0f8-c126-412e-b0ed-3a8433b6233c'} and all(x['deleted_at'] for x in b['web_services_non_secret']))
verify('zero active bounded four paid calls',not b['active_jobs'] and b['model_usage_total']-get('144')['model_usage_total']==4 and b['model_usage_total']==170)
verify('SearXNG credential cancellation exact row',get('043')['web_row_guards']==get('048')['web_row_guards'])
verify('clear credential real empty then encrypted restore',get('054')['web_services_non_secret'][0]['key_nonempty']==0 and get('062')['web_services_non_secret'][0]['key_encrypted']==1)
verify('DDG cancel exact own row',get('070')['web_row_guards']==get('079')['web_row_guards'])
verify('SearXNG delete cancel exact own row',get('194')['web_row_guards']==get('201')['web_row_guards'])
verify('original old-success defect preserved', '/failure' in snap('027') and '连接成功，本次返回 2 条结果' in snap('027'))
verify('fixed actual old success disappears', '连接成功' in snap('092') and '连接成功' not in snap('098') and '/failure' in snap('098'))
verify('fixed actual old failure disappears', 'External service request failed' in snap('101') and 'External service request failed' not in snap('107') and '连接成功，本次返回 2 条结果' in snap('110'))
verify('global off/on refreshed and persisted',get('119')['web_search_original_or_current']['value']['enabled'] is False and '[checked=false' in snap('121') and get('127')['web_search_original_or_current']['value']['enabled'] is True and '[checked=true' in snap('126'))
verify('before send genuine nonempty draft visible send and web enabled',result('143')['question'].startswith('请只调用一次 web_search') and not next(x for x in result('143')['controls'] if x['title']=='发送消息')['disabled'] and next(x for x in result('143')['controls'] if x['title']=='发送消息')['y']<result('143')['viewportHeight'] and next(x for x in result('143')['controls'] if x['title']=='联网搜索')['active'] and result('143')['selected']==[])
config=json.loads(t['session'][0]['agent_config']);sid=t['session'][0]['id'];rid=t['messages'][0]['request_id'];verify('one owned session explicit empty KB web true MCP none',sid=='889d8b97-1948-48f5-a726-47ba367a4430' and config['knowledge_base_ids']==[] and config['knowledge_selection_explicit'] is True and config['web_search_enabled'] is True and config['mcp_service_ids']==[])
verify('two real messages eighteen events no fallback',len(t['messages'])==2 and len(t['events'])==18 and all(x['is_completed']==1 and x['is_fallback']==0 for x in t['messages']))
verify('two jobs durable completed attempt one',len(t['jobs'])==2 and all(x['status']=='completed' and x['attempt']==1 and x['progress']==1 and x['error']=='' for x in t['jobs']))
u=t['usage'];verify('four distinct actual linked successful usage calls',len(u)==4 and len({x['id'] for x in u})==4 and all(x['success']==1 and x['request_count']==1 and x['request_id']==rid and json.loads(x['metadata'])['session_id']==sid and json.loads(x['metadata'])['model_call_id']==x['id'] for x in u))
verify('accurate role tokens and totals',[(x['scenario'],x['total_tokens']) for x in u]==[('memory_keywords',148),('agent_chat',1249),('agent_chat',1611),('memory_extraction',838)] and t['usage_totals']=={'request_count':4,'prompt_tokens':3066,'completion_tokens':780,'total_tokens':3846,'cached_tokens':1088,'reasoning_tokens':129})
call=[json.loads(x['data']) for x in t['events'] if x['type']=='tool/call'];res=[json.loads(x['data']) for x in t['events'] if x['type']=='tool/result'];verify('only one web search tool actual output two',len(call)==len(res)==1 and call[0]['name']==res[0]['name']=='web_search' and res[0]['error']=='' and len(json.loads(res[0]['output']))==2)
verify('answer marker standard facts two exact URLs',all(s in t['messages'][1]['content'] for s in ['WEB-QA-09a174e0','37 天','文件哈希','关联记录','http://127.0.0.1:44843/sources/retention','http://127.0.0.1:44843/sources/restore']))
proto=t['server_actual_gui_protocol_snapshot'];actual=[x for x in proto if x['requestNumber']==9];query='WEB-QA-09a174e0 资料保留期限 恢复验证流程';verify('real single Agent HTTP query hash matches',len(actual)==1 and actual[0]['setupSmoke'] is False and actual[0]['authenticated'] is True and actual[0]['status']==200 and actual[0]['resultCount']==2 and actual[0]['querySHA']==hashlib.sha256(query.encode()).hexdigest())
verify('five independent explicit connection checks distinct from paid query',len([x for x in proto if x['path'] in ['/search','/failure'] and x['requestNumber']<9])==5)
for n,url in [('165','http://127.0.0.1:44843/sources/retention'),('174','http://127.0.0.1:44843/sources/restore')]:
 d=result(n);verify('actual clicked source '+n,d['url']==url and d['navigation'][0]['status']==200 and all(s in d['text'] for s in ['WEB-QA-09a174e0','37 天','文件哈希','关联记录']))
verify('server confirms source clicks without credential forwarding',len([x for x in proto if x['path'].startswith('/sources/')])==2 and all(x['status']==200 and x['setupSmoke'] is False and x['authenticationPresent'] is False for x in proto if x['path'].startswith('/sources/')))
verify('cleanup actual DOM off blank empty no dialog',result('207')['enabled'] is False and result('207')['defaultValue']=='' and result('207')['providers']==[] and result('207')['dialogs']==[])
tabs=get('209')['receipt']['result']['tabs'];verify('own source tabs closed old pages preserved',len(tabs)==7 and {x['index'] for x in tabs}==set(range(7)) and all('44843' not in x['url'] for x in tabs) and next(x for x in tabs if x['index']==6)['browserPageId']==sid.replace(sid,'22e0e212-30aa-4945-8a3d-7176cdfffdff'))
for n in ['040','154','166','175']:
 f=next(folder.glob(n+'-*.png'));j=get(n)['receipt']['result'];verify('actual screenshot hash '+n,sha(f)==j['image_sha256'])
verify('root final integrated source freeze immutable',sha(root/'docs/refactor-evidence/20261012-web-search-result-integrated-source-freeze.json')=='5cabb11adcff22acf3c02f6cb70dce381acc3b19597d662ac95c6e2d471a7bac')
verify('actual root fixed product binding',sha(root/'frontend/src/views/settings/WebSearchSettings.vue')=='c1560c1d98ed8567a23cc6fd1e262dfb30e5fc5143f21a6f090636c15c591904')
links=[]
for link in re.findall(r'\]\(([^)]+)\)',doc.read_text()):
 if re.match(r'\w+://',link):continue
 target=(doc.parent/link.split('#')[0]).resolve();verify('link '+link,target.exists() or target==folder/'freeze.json');links.append(link)
for args,name in [(['git','diff','--check','--',str(doc.relative_to(root))],'tracked diff'),(['git','diff','--no-index','--check','/dev/null',str(doc)],'untracked document diff')]:
 p=subprocess.run(args,cwd=root,capture_output=True,text=True);verify(name+' check',p.returncode in ([0,1] if name.startswith('untracked') else [0]) and not p.stdout and not p.stderr)
cleanup=[]
for source in [pathlib.Path('/tmp/'+name) for name in ['marlin-web-browser-20261012.py','marlin-web-protected-readonly-20261012.py','marlin-web-turn-readonly-20261012.py','marlin-web-tabs-20261012.py','marlin-web-source-browser-20261012.py','marlin-web-final-freeze-20261012.py']]:
 dest=folder/('archived-'+source.name);h=sha(source);shutil.copyfile(source,dest);verify('archive hash '+source.name,sha(dest)==h);source.unlink();cleanup.append({'temporary_path':str(source),'archive':str(dest.relative_to(root)),'sha256':h,'removed':not source.exists()})
files=[{'path':str(x.relative_to(root)),'sha256':sha(x),'bytes':x.stat().st_size} for x in sorted(folder.rglob('*')) if x.is_file() and x.name!='freeze.json']
sources=[{'path':s,'sha256':sha(root/s)} for s in ['frontend/src/views/settings/WebSearchSettings.vue','frontend/src/views/chat/components/ChatInput.vue','frontend/src/views/chat/components/AssistantMessage.vue','frontend/src/utils/markdown-lite.mjs','packages/core/src/agents/tools.ts','packages/core/src/integrations/search.ts','packages/core/src/settings/settings.ts']]
manifest={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'only actual browser WebSearch; no product edits by child; root owns original HTTP log and later NULL maintenance','goal_complete':False,'document':{'path':str(doc.relative_to(root)),'sha256':sha(doc)},'files':files,'sources':sources,'checks':checks,'links':links,'temporary_cleanup':cleanup,'vendor_invocations':4,'total_tokens':3846,'ui_final_config':b['web_search_original_or_current'],'original_config':a['web_search_original_or_current'],'active_jobs_at_last_snapshot':0,'GUI_released_to_root':True,'root_NULL_maintenance_verified_by_child':False,'root_HTTP_stop_verified_by_child':False}
(folder/'freeze.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'files':len(files),'sources':len(sources),'checks':len(checks),'links':len(links),'temporary_cleanup':len(cleanup),'document_sha256':sha(doc),'freeze_sha256':sha(folder/'freeze.json')},ensure_ascii=False))
