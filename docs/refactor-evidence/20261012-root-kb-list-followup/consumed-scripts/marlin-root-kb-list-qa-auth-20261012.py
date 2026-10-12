import datetime
import json
import os
from pathlib import Path
import subprocess

credential = Path('/home/liuxuedeng/.local/share/marlin-refactor/20261010-browser-private-auth.json')
assert credential.stat().st_mode & 0o777 == 0o600
auth = json.loads(credential.read_text())
assert auth['email'] == 'orca-page-qa-20261010@example.invalid'
assert auth['data_directory'] == '/home/liuxuedeng/.local/share/marlin-refactor/20261010-browser-qa'
page = '22e0e212-30aa-4945-8a3d-7176cdfffdff'
directory = Path('/home/liuxuedeng/Django-Agent/docs/refactor-evidence/20261012-root-kb-list-followup')
target = directory / '051-qa-secret-fill-redacted.json'
attempt = directory / '051-qa-secret-fill-redacted.attempt.json'
assert not target.exists() and not attempt.exists()
started = datetime.datetime.now(datetime.timezone.utc).isoformat()
with attempt.open('x') as stream:
    json.dump({'started_utc': started, 'page': page, 'command': 'fill', 'element': '@e7', 'value': '[REDACTED]', 'owned_qa_account': True}, stream, indent=2)
    stream.flush()
    os.fsync(stream.fileno())
result = subprocess.run(['orca-ide', 'fill', '--page', page, '--element', '@e7', '--value', auth['password'], '--json'], text=True, capture_output=True, timeout=60)
safe_stdout = result.stdout.replace(auth['password'], '[REDACTED]')
safe_stderr = result.stderr.replace(auth['password'], '[REDACTED]')
receipt = json.loads(safe_stdout)
report = {'started_utc': started, 'finished_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'page': page, 'exit_code': result.returncode, 'receipt': receipt, 'stderr': safe_stderr, 'credential_values_emitted': False, 'credential_source_mode': '0600'}
with target.open('x') as stream:
    json.dump(report, stream, ensure_ascii=False, indent=2)
    stream.write('\n')
assert result.returncode == 0 and receipt.get('ok') is True
print(json.dumps({'evidence': str(target), 'exit_code': result.returncode, 'ok': receipt['ok'], 'credential_values_emitted': False}))
