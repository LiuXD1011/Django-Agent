import datetime
import json
import pathlib
import stat

ROOT = pathlib.Path('/home/liuxuedeng/Django-Agent')
OUT = ROOT/'docs/refactor-evidence/20261012-auth-browser-isolation-real'
DOC = ROOT/'docs/desktop-refactor/AUTH-BROWSER-ISOLATION-ACCEPTANCE.md'
PRIVATE = pathlib.Path('/tmp/marlin-auth-qa-credentials-20261012.json')

if PRIVATE.is_symlink() or stat.S_IMODE(PRIVATE.stat().st_mode) != 0o600:
    raise SystemExit('Private synthetic QA file safety check failed')
secret = json.loads(PRIVATE.read_text())['password']
paths = [path for path in OUT.rglob('*') if path.is_file()] + [DOC]
matches = [str(path.relative_to(ROOT)) for path in paths if secret.encode() in path.read_bytes()]
record = {'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'files_checked':len(paths),'dedicated_qa_plaintext_matches':matches,'private_mode':'0600','private_retained_for_next_authorized_gui_segment':True,'scope':'Only this agent new A document/evidence scanned for its own new synthetic QA password. Not a global CLI/OS log or source-user-secret audit.'}
print(json.dumps(record,ensure_ascii=False,indent=2))
if matches: raise SystemExit(1)
