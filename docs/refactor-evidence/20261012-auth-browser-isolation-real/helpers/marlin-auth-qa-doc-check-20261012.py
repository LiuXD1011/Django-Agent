import hashlib
import json
import pathlib
import re
import subprocess
import urllib.parse

ROOT = pathlib.Path('/home/liuxuedeng/Django-Agent')
DOC = ROOT/'docs/desktop-refactor/AUTH-BROWSER-ISOLATION-ACCEPTANCE.md'
OUT = ROOT/'docs/refactor-evidence/20261012-auth-browser-isolation-real'

links = re.findall(r'\]\(([^)]+)\)', DOC.read_text())
missing = []
for value in links:
    if '://' in value: continue
    target = DOC.parent/urllib.parse.unquote(value.split('#')[0])
    if not target.exists(): missing.append(value)
baseline = json.loads((OUT/'000-preflight.json').read_text())['source_files']
changed = [item['path'] for item in baseline if hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest() != item['sha256']]
diff = subprocess.run(['git','diff','--check','--',str(DOC.relative_to(ROOT))], cwd=ROOT, capture_output=True, text=True)
record = {'links_checked':len(links),'missing_links':missing,'source_bindings_checked':len(baseline),'changed_source_bindings':changed,'diff_check_exit':diff.returncode,'diff_stdout':diff.stdout,'diff_stderr':diff.stderr,'doc_sha256':hashlib.sha256(DOC.read_bytes()).hexdigest(),'original_source_process_alive':pathlib.Path('/proc/2245508').exists()}
print(json.dumps(record,ensure_ascii=False,indent=2))
if missing or changed or diff.returncode: raise SystemExit(1)
