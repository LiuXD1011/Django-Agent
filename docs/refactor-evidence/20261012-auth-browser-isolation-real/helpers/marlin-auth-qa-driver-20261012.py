import datetime
import hashlib
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path('/home/liuxuedeng/Django-Agent')
OUT = ROOT / 'docs/refactor-evidence/20261012-auth-browser-isolation-real'
OUT.mkdir(exist_ok=True)

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def run(label, arguments):
    if not label.replace('-', '').replace('_', '').isalnum():
        raise ValueError('Invalid evidence label')
    if arguments[0] != 'orca-ide':
        raise ValueError('Only public Orca commands allowed')
    forbidden = {'cookie', 'network', 'headers', 'credentials', 'password', 'clipboard'}
    if any(value in forbidden for value in arguments[1:]):
        raise ValueError('Potential credential command rejected')
    if any('password' in value.lower() for value in arguments[1:]):
        raise ValueError('Password expression rejected')
    started = now()
    start = time.monotonic()
    result = subprocess.run(arguments, cwd=ROOT, capture_output=True, text=True, timeout=120)
    item = {'started_at': started, 'ended_at': now(), 'tool_duration_ms': round((time.monotonic()-start)*1000, 3), 'arguments': arguments, 'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
    destination = OUT / (label+'.json')
    if destination.exists():
        raise FileExistsError(destination)
    destination.write_text(json.dumps(item, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'evidence': str(destination.relative_to(ROOT)), 'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(), 'exit_code': result.returncode, 'stdout': result.stdout}, ensure_ascii=False))

if __name__ == '__main__':
    run(sys.argv[1], sys.argv[2:])
