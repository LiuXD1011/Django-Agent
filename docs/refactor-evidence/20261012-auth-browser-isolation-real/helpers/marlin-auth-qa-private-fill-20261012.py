import datetime
import json
import os
import pathlib
import secrets
import stat
import subprocess
import sys
import time

ROOT = pathlib.Path('/home/liuxuedeng/Django-Agent')
OUT = ROOT / 'docs/refactor-evidence/20261012-auth-browser-isolation-real'
PRIVATE = pathlib.Path('/tmp/marlin-auth-qa-credentials-20261012.json')
PROFILES = {'f97e4ab1-3837-49fd-881a-45ebecd5d211','a372a0fd-72c3-4efe-b908-855756682c3c'}

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def init():
    payload = {'email': 'auth-qa-20261012@knowledge.local', 'password': 'QA-'+secrets.token_urlsafe(30)+'-9x!'}
    fd = os.open(PRIVATE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(payload, handle)
    print(json.dumps({'created_new_dedicated_qa_credentials': True, 'mode': oct(stat.S_IMODE(PRIVATE.stat().st_mode)), 'email': payload['email'], 'password_output': False}))

def operate(label, page, action, element=None):
    if PRIVATE.is_symlink() or stat.S_IMODE(PRIVATE.stat().st_mode) != 0o600 or PRIVATE.stat().st_uid != os.getuid():
        raise RuntimeError('Private credential file ownership mismatch')
    private = json.loads(PRIVATE.read_text())
    guard = subprocess.run(['orca-ide', 'tab', 'profile', 'show', '--page', page, '--json'], cwd=ROOT, capture_output=True, text=True, timeout=45)
    data = json.loads(guard.stdout[guard.stdout.find('{'):])
    if not data.get('ok') or data['result']['profileId'] not in PROFILES:
        raise RuntimeError('Page not bound to owned isolated profile')
    args = ['orca-ide', action, '--page', page]
    if action == 'fill':
        args += ['--element', element, '--value', private['password']]
    elif action != 'snapshot':
        raise RuntimeError('Only private fill and sanitized snapshot permitted')
    args += ['--json']
    started = now(); tick = time.monotonic()
    try:
        response = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=90)
        item = {'started_at': started, 'tool_duration_ms': round((time.monotonic()-tick)*1000,3), 'action': action, 'page': page, 'element': element, 'secret_transport': 'transient child argv only; not stdin', 'dedicated_synthetic_qa_only': True, 'arguments_persisted': False, 'exit_code': response.returncode, 'stdout': response.stdout.replace(private['password'], '[REDACTED QA PASSWORD]'), 'stderr': response.stderr.replace(private['password'], '[REDACTED QA PASSWORD]')}
    except subprocess.TimeoutExpired:
        item = {'started_at': started, 'action': action, 'page': page, 'exit_code': None, 'error': 'private operation timed out; arguments/output omitted', 'arguments_persisted': False}
    destination = OUT / (label+'.json')
    if destination.exists():
        raise FileExistsError('Evidence label already exists')
    destination.write_text(json.dumps(item, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(item, ensure_ascii=False))

if __name__ == '__main__':
    try:
        if sys.argv[1] == 'init': init()
        else: operate(*sys.argv[1:])
    except Exception as error:
        print(json.dumps({'private_helper_failed': True, 'exception_type': type(error).__name__, 'secret_output': False}))
        sys.exit(1)
