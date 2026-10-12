import datetime,hashlib,json,re,subprocess
from pathlib import Path
from urllib.parse import unquote
root=Path('/home/liuxuedeng/Django-Agent');e=root/'docs/refactor-evidence/20261012-browser-nonempty-format-followup';doc=root/'docs/desktop-refactor/NONEMPTY-HTML-BROWSER-ACCEPTANCE.md'
load=lambda n:json.loads((e/(n+'.json')).read_text())
checks=[]
def check(name,value):
 checks.append({'name':name,'passed':bool(value)})
 if not value:raise AssertionError(name)
snap=lambda n:load(n)['receipt']['result']['snapshot']
value=lambda n:json.loads(load(n)['receipt']['result']['result'])
before=load('001-before-protected');pre=load('031-before-single-html-start');terminal=load('037-html-business-terminal');edited=load('052-own-library-edited-proof');cancelled=load('063-cancel-nonempty-delete-proof');after=load('068-after-nonempty-delete-business');protected=load('070-after-nonempty-delete-protected');bound=load('074-association-boundaries')
check('initial_no_own_library',before['own_knowledge_bases']==[])
check('actual_zero_index_choice',snap('009-disabled-index-controls').count('[checked=false')>=3)
check('all_off_create_did_not_create',load('013-after-no-index-attempt')['own_knowledge_bases']==[])
check('actual_parent_keyboard_disabled','启用父子分块" [checked=false' in snap('020-create-form-final'))
check('unique_html_selected','1 个文件' in snap('029-upload-controls-single-file') and '01 中文 HTML 小表.html' in snap('029-upload-controls-single-file'))
check('only_selection_no_business_upload',pre['own_related_counts'][terminal['kb_id']]['knowledges']==0 and pre['model_usage_total']==170)
check('actual_single_start',load('032-start-single-html-once')['receipt']['ok'] and load('032-start-single-html-once')['command'][1:4]==['click','--element','@e47'])
check('actual_processing_then_complete','处理中' in snap('033-html-processing') and '已完成' in snap('035-html-completed-ui'))
d=terminal['documents'][0];meta=json.loads(d['metadata']);kb=terminal['kb'][0];strategy=json.loads(kb['indexing_strategy']);config=json.loads(kb['chunking_config']);canonical=meta['content'];chunks=terminal['chunks']
check('only_one_html_document',len(terminal['documents'])==1 and d['file_type']=='html' and d['file_size']==480)
check('own_strategy',strategy=={'vector_enabled':True,'keyword_enabled':True,'wiki_enabled':False,'graph_enabled':False})
check('deterministic_recursive_no_parent',config['strategy']=='recursive' and config['enable_parent_child'] is False)
for text in ['HTML-QA-51FC','许清','14天','7台','23元','161元']:check('canonical_fact_'+text,text in canonical)
check('one_complete_source_range',len(chunks)==1 and chunks[0]['content']==canonical and chunks[0]['start_at']==0 and chunks[0]['end_at']==len(canonical)==142)
check('no_image_or_paid_extra_phase',meta['image_count']==0 and meta['parser_image_block_indices']==[] and meta['graph_status']==meta['wiki_status']=='skipped')
check('actual_ui_source_matches',all(x in snap('039-html-chunk-content') for x in ['HTML-QA-51FC','许清','14天','7台','23元','161元']))
check('completed_document_job',d['summary_status']=='completed' and d['pending_subtasks_count']==0 and meta['workflow_status']=='completed' and meta['processing_warnings']==[] and terminal['jobs'][0]['status']=='completed' and terminal['jobs'][0]['attempt']==1)
check('job_elapsed_8688ms',(datetime.datetime.fromisoformat(terminal['jobs'][0]['finished_at'].replace('Z','+00:00'))-datetime.datetime.fromisoformat(terminal['jobs'][0]['started_at'].replace('Z','+00:00'))).total_seconds()==8.688)
check('no_open_spans',len(terminal['spans'])==9 and all(s['status'] in ['done','skipped'] for s in terminal['spans']))
u=terminal['own_model_usage'];check('bounded_four_unique_success',len(u)==len({x['id'] for x in u})==4 and all(x['success']==1 and x['request_count']==1 and x['result_unknown']==0 for x in u))
check('ledger_scenario_identity',set(x['scenario'] for x in u)=={'embedding','summary','questions','metadata'} and all(x['request_id']=='kohauwkw3pc' and x['job_id']==terminal['jobs'][0]['id'] and x['knowledge_id']==d['id'] and x['attempt']==1 for x in u))
check('tokens_605',sum(x['prompt_tokens'] for x in u)==415 and sum(x['completion_tokens'] for x in u)==190 and sum(x['total_tokens'] for x in u)==605)
check('usage170to174',terminal['model_usage_total']==before['model_usage_total']+4==174)
check('owned_source_sha',terminal['source_files'][0]['sha256']==load('027-html-fixture')['sha256']=='41f79e2e5678819e95df868851e41755dd4d18f2b1a5dd7ab840eaa4828bd7ba')
check('original_fts_present',len(terminal['fts_rows_for_known_chunks'])==1)
check('physical_vector_present',load('044-vector-before-delete')['entries'][0]['physical_rows']=='1')
check('actual_kb_edit_and_reload','已编辑' in snap('051-own-library-edited-refresh') and '已编辑' in edited['kb'][0]['name'] and 'HTML-QA-51FC' in edited['kb'][0]['description'])
check('edit_preserved_doc_chunk_and_indices',edited['documents_sha256']==terminal['documents_sha256'] and edited['chunks_sha256']==terminal['chunks_sha256'] and edited['vector_entries']==terminal['vector_entries'] and edited['fts_rows_for_known_chunks']==terminal['fts_rows_for_known_chunks'])
check('actual_description_search_and_refresh','HTML-QA-51FC' in snap('057-search-one-nonempty-library') and snap('059-filtered-list-refresh-proof').count('article [')==1)
for k in ['kb','documents_sha256','chunks_sha256','jobs','task_records','spans','index_registration','vector_entries','index_meta','source_files','fts_rows_for_known_chunks']:check('cancel_preserves_'+k,cancelled[k]==edited[k])
check('delete_only_own_kb_doc_soft_deleted',after['kb'][0]['deleted_at']=='2026-10-12T03:22:52.540Z' and after['documents'][0]['deleted_at'] is not None)
for t in ['knowledges','chunks','knowledge_images','knowledge_tags','wiki_pages','wiki_folders','wiki_log_entries','search_index_meta','retrieval_chunk_ids','retrieval_vector_entries']:check('deleted_active_'+t,after['related_counts'][t]['active_records']==0)
check('old_fts_exact_rowid_cleared',after['retired_chunk_seq_ids']==['675847552571479314'] and after['fts_rows_for_retired_chunks']==[])
check('physical_vector_exact_rowid_cleared',load('069-vector-after-delete')['entries'][0]['physical_rows']=='0' and load('069-vector-after-delete')['entries'][0]['rowid']=='675847552571479314')
check('owned_file_removed',after['source_files'][0]['exists'] is False)
check('completed_audit_retained_not_active',bound['terminal_audit_rows_retained']=={'jobs':1,'task_records':1,'spans':9} and bound['all_active_jobs']==bound['own_active_tasks']==[])
check('21_actual_job_events',sum(x['n'] for x in bound['job_event_types'])==21)
check('local_cleanup_complete_remote_pending_distinct',bound['artifact_cleanup_pending']==bound['wiki_pending']==[] and len(bound['graph_pending'])==2 and all(x['status']=='pending' for x in bound['graph_pending']))
for k in ['models_rows_sha256','credential_key_sha256','models_count','protected','mcp_row_guards','web_row_guards','web_search_original_or_current']:check('protected_'+k,before[k]==protected[k])
check('no_model_calls_after_upload',protected['model_usage_total']==after['model_usage_total']==174 and protected['active_jobs']==[])
check('actual_final_original_list','10027' in snap('073-final-unfiltered-original-libraries') and 'Orca 非空 HTML' not in snap('073-final-unfiltered-original-libraries'))
lat=value('071-nonempty-delete-latency-dom');check('actual_delete_response_one',sum(1 for r in lat['api'] if r['path'].endswith(terminal['kb_id']) and r['start']>140000 and r['status']==200 and r['duration']==387.5)==1)
for p in load('075-readonly-source-binding')['sources']:check('source_frozen_'+p['path'],hashlib.sha256((root/p['path']).read_bytes()).hexdigest()==p['sha256'])
links=[]
for raw in re.findall(r'\]\(([^\n]+?)\)',doc.read_text()):
 target=raw.strip('<>').split('#',1)[0]
 if re.match(r'^(?:https?://|app://)',target):continue
 path=(doc.parent/unquote(target)).resolve();check('link_'+target,path.exists());links.append(str(path.relative_to(root)))
diff=subprocess.run(['git','diff','--check'],cwd=root,capture_output=True,text=True);check('git_diff_check',diff.returncode==0)
(e/'076-frozen-assertions.json').write_text(json.dumps({'checked_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'checks':checks,'check_count':len(checks),'link_count':len(links),'diff_check_exit':diff.returncode,'diff_check_output':diff.stdout+diff.stderr,'gui_released':True,'new_paid_calls_not_replayed':True,'goal_complete':False},ensure_ascii=False,indent=2)+'\n')
cleanup=[]
for p in [Path('/tmp/marlin-format-browser-20261012.py'),Path('/tmp/marlin-format-protected-readonly-20261012.py'),Path('/tmp/marlin-html-business-readonly-20261012.py'),Path('/tmp/marlin-html-vector-readonly-20261012.mjs'),Path(__file__)]:
 raw=p.read_bytes();archive=e/('archived-'+p.name);archive.write_bytes(raw);p.unlink();cleanup.append({'path':str(p),'archived_path':str(archive.relative_to(root)),'sha256':hashlib.sha256(raw).hexdigest(),'deleted':not p.exists()})
fixture=e/'fixtures/01 中文 HTML 小表.html';src=Path('/mnt/c/Users/lxd/AppData/Local/Temp/Marlin HTML QA 20261012/01 中文 HTML 小表.html');expected='41f79e2e5678819e95df868851e41755dd4d18f2b1a5dd7ab840eaa4828bd7ba'
assert not src.is_symlink() and not src.parent.is_symlink()
check('windows_exact_owned_input_sha',hashlib.sha256(src.read_bytes()).hexdigest()==hashlib.sha256(fixture.read_bytes()).hexdigest()==expected)
src.unlink();empty=not any(src.parent.iterdir());folder=str(src.parent)
if empty:src.parent.rmdir()
(e/'077-cleanup-receipt.json').write_text(json.dumps({'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'temporary_scripts':cleanup,'windows_input':{'path':str(src),'verified_sha256':expected,'deleted':not src.exists(),'directory':folder,'directory_was_empty_after_file_delete':empty,'empty_directory_removed':empty and not src.parent.exists()},'fixture_preserved':str(fixture.relative_to(root)),'other_windows_paths_touched':False},ensure_ascii=False,indent=2)+'\n')
manifest={'frozen_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'document':{'path':str(doc.relative_to(root)),'sha256':hashlib.sha256(doc.read_bytes()).hexdigest()},'sources':load('075-readonly-source-binding')['sources'],'checks':len(checks),'links':len(links),'temporary_scripts_cleaned':len(cleanup),'inputs':[{'path':str(p.relative_to(root)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(e.rglob('*')) if p.is_file() and p.name!='freeze.json'],'scope':'one HTML upload plus own nonempty KB edit/search/refresh/cancel-delete/confirm-delete; JSON/SVG not selected, no additional providers, no Windows installed GUI claim; remote graph pending retained','gui_released':True,'goal_complete':False}
manifest['files']=len(manifest['inputs']);(e/'freeze.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'files':manifest['files'],'checks':len(checks),'links':len(links),'temp_cleanup':len(cleanup),'document_sha256':manifest['document']['sha256'],'freeze_sha256':hashlib.sha256((e/'freeze.json').read_bytes()).hexdigest(),'windows_input_cleaned':True},ensure_ascii=False,indent=2))
