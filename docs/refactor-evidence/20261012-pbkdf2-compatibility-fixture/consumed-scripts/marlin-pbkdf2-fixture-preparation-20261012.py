from pathlib import Path
import hashlib, json, datetime, subprocess, sys, importlib.metadata, time
from django.conf import settings
from django.contrib.auth.hashers import PBKDF2PasswordHasher, PBKDF2SHA1PasswordHasher
ROOT=Path('/home/liuxuedeng/Django-Agent');OUT=ROOT/'docs/refactor-evidence/20261012-pbkdf2-compatibility-fixture'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def binding(p):return {'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
assert not settings.configured
specs=[
 {'id':'legacy-sha256-unicode-260000','algorithm':'pbkdf2_sha256','password':'迁移Password✓','wrong_password':'wrong','salt':'fixtureSalt2026','iterations':260000},
 {'id':'sha256-one-round-ascii','algorithm':'pbkdf2_sha256','password':'password','wrong_password':'Password','salt':'salt','iterations':1},
 {'id':'sha256-two-round-combining-utf8-salt','algorithm':'pbkdf2_sha256','password':'Cafe\u0301雪😀','wrong_password':'Café雪😀','salt':'中文Salt2026','iterations':2},
 {'id':'sha256-current-factor-1000000','algorithm':'pbkdf2_sha256','password':'新Password✓','wrong_password':'新Password','salt':'MarlinFixtureSalt2026','iterations':1000000},
 {'id':'legacy-sha1-nul-unicode-4096','algorithm':'pbkdf2_sha1','password':'旧$Password\u0000✓😀','wrong_password':'旧$Password✓😀','salt':'SHA1Fixture2026','iterations':4096},
]
start=time.monotonic();outputs=[]
for item in specs:
 hasher=PBKDF2PasswordHasher() if item['algorithm']=='pbkdf2_sha256' else PBKDF2SHA1PasswordHasher()
 encoded=hasher.encode(item['password'],item['salt'],item['iterations'])
 assert hasher.verify(item['password'],encoded) is True
 assert hasher.verify(item['wrong_password'],encoded) is False
 outputs.append({**item,'encoded':encoded,'correct_password_verified':True,'wrong_password_verified':False})
assert outputs[0]['encoded']=='pbkdf2_sha256$260000$fixtureSalt2026$/JWBBute1JewIrQ1fXbtSUNUgST4EwcvVlOB7qkos9c='
assert not settings.configured
D=importlib.metadata.distribution('Django');source=[D.locate_file(p) for p in ('django/contrib/auth/hashers.py','django/utils/crypto.py','django/utils/encoding.py')]
fixture={'schema':1,'purpose':'Synthetic PBKDF2 compatibility vectors; no user credentials or API keys','generated_with':{'Django':D.version,'python':sys.version,'source_sha256':{str(p):sha(p) for p in source},'django_settings_configured':settings.configured,'generator_sha256':sha(Path(__file__))},'cases':outputs}
(OUT/'golden-candidate.json').write_text(json.dumps(fixture,ensure_ascii=False,indent=2)+'\n')
probe=['/tmp/marlin-parser-isolation-20261010/bin/python','-B','-I','-c',"import sys,importlib.util,json;print(json.dumps({'python_executable':sys.executable,'python_version':sys.version,'django_spec':importlib.util.find_spec('django') is not None,'isolated':sys.flags.isolated,'dont_write_bytecode':sys.dont_write_bytecode}))"]
r=subprocess.run(probe,capture_output=True,text=True);assert r.returncode==0;rprobe=json.loads(r.stdout);assert rprobe['django_spec'] is False
(OUT/'no-django-environment.json').write_text(json.dumps({'argv':probe,'exit_code':r.returncode,'actual':rprobe,'stderr':r.stderr,'purpose':'Only auth regression-specific child Python PATH after root unlock; no global PATH change'},ensure_ascii=False,indent=2)+'\n')
(OUT/'golden-generation.json').write_text(json.dumps({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'argv':[sys.executable,'-B',str(Path(__file__))],'candidate':binding(OUT/'golden-candidate.json'),'generator':binding(Path(__file__)),'django_sources':[binding(p) for p in source],'Django':D.version,'python_executable':sys.executable,'python_version':sys.version,'cases_generated':len(outputs),'elapsed_ms':round((time.monotonic()-start)*1000,3),'production_or_repo_test_mutations':0,'auth_database_or_account_calls':0,'GUI_models_requests':0},ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'synthetic_cases_generated':len(outputs),'Django':D.version,'candidate_sha256':sha(OUT/'golden-candidate.json'),'no_django_regression_environment':rprobe,'production_or_repo_test_mutations':0,'actual_auth_tests_executed':False},ensure_ascii=False,indent=2))
