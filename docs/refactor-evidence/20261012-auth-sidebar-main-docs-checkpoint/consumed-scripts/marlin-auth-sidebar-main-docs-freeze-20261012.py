from pathlib import Path
import json, hashlib, datetime, subprocess
ROOT=Path('/home/liuxuedeng/Django-Agent')
OUT=ROOT/'docs/refactor-evidence/20261012-auth-sidebar-main-docs-checkpoint'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def item(p): return {'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':sha(p)}
validation=json.loads((OUT/'validation-final.json').read_text())
assert validation['all_passed'] and validation['assertion_count']==26
for expected in validation['documents']:
 p=ROOT/expected['path']; assert sha(p)==expected['sha256']
for expected in validation['inputs']:
 p=ROOT/expected['path']; assert sha(p)==expected['sha256']
owned=[Path('/tmp/marlin-auth-sidebar-main-docs-'+suffix+'-20261012.py') for suffix in ('update','review','check','freeze')]
archive=OUT/'consumed-scripts'; archive.mkdir(exist_ok=False)
records=[]
for p in owned:
 assert p.is_file()
 target=archive/p.name; b=p.read_bytes(); target.write_bytes(b)
 assert sha(p)==sha(target)
 records.append({'temporary_path':str(p),'archive':item(target),'deleted':False})
for p,r in zip(owned,records):
 assert sha(p)==r['archive']['sha256']; p.unlink(); r['deleted']=not p.exists()
assert all(r['deleted'] for r in records)
now=datetime.datetime.now(datetime.timezone.utc).isoformat()
(OUT/'cleanup.json').write_text(json.dumps({'at':now,'owned_helpers':records,'count':len(records),'all_deleted':True,'private_credentials_read_or_archived':False,'other_temporary_files_touched':False},ensure_ascii=False,indent=2)+'\n')
check=subprocess.run(['git','diff','--check','--','docs/desktop-refactor/STATUS.md','docs/desktop-refactor/TEST-REPORT.md','docs/desktop-refactor/TEST-MATRIX.md'],cwd=ROOT,capture_output=True,text=True)
assert check.returncode==0,check.stdout+check.stderr
freeze={'at':now,'scope':'documentation only; three main documents plus new own checkpoint evidence','goal':'active; not complete','documents':validation['documents'],'inputs':validation['inputs'],'validation':item(OUT/'validation-final.json'),'evidence':[item(p) for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='freeze.json'],'checks':{'assertions':26,'relative_links':821,'source_bindings':989,'original_A_evidence_bindings':178,'stable_groups':38,'stable_UI_rows':69,'whole_group_pass':['M-01','M-02'],'git_diff_check_exit':check.returncode,'temporary_helpers_deleted':4},'boundaries':{'prepare':'started; reviewed terminal not supplied at documentation checkpoint','GUI_API_models_ports_products_builds':0,'FINAL_and_other_existing_documents_edited':False,'original_failed_receipts_rewritten':False}}
(OUT/'freeze.json').write_text(json.dumps(freeze,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'freeze':item(OUT/'freeze.json'),'documents':validation['documents'],'evidence_count':len(freeze['evidence']),'all_helpers_deleted':True,'git_diff_check_exit':0},ensure_ascii=False,indent=2))
