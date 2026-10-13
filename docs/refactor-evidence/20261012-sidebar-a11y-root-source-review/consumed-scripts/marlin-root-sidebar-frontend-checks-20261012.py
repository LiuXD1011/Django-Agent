import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

parser = argparse.ArgumentParser()
parser.add_argument('mode', choices=['unit', 'build'])
args = parser.parse_args()
root = Path('/home/liuxuedeng/Django-Agent')
directory = root / 'docs/refactor-evidence/20261012-sidebar-accessible-names'
source = root / 'frontend/src/views/Platform.vue'
digest = hashlib.sha256(source.read_bytes()).hexdigest()
if args.mode == 'build':
    unit = json.loads((directory / 'unit-execution.json').read_text())
    assert unit['exit_code'] == 0 and unit['counts']['fail'] == 0
    assert unit['source_sha256_before'] == digest
command = [shutil.which('npm'), 'run', 'test:unit' if args.mode == 'unit' else 'build']
assert command[0]
paths = {kind: directory / (args.mode + suffix) for kind, suffix in [('attempt', '-attempt.json'), ('stdout', '-stdout.log'), ('stderr', '-stderr.log'), ('receipt', '-execution.json')]}
assert all(not path.exists() for path in paths.values())
started = datetime.datetime.now(datetime.timezone.utc).isoformat()
with paths['attempt'].open('x') as stream:
    json.dump({'started_utc': started, 'command': command, 'cwd': str(root / 'frontend'), 'source': str(source.relative_to(root)), 'source_sha256_before': digest}, stream, indent=2)
    stream.write('\n')
start = time.monotonic()
with paths['stdout'].open('x') as stdout, paths['stderr'].open('x') as stderr:
    child = subprocess.run(command, cwd=root / 'frontend', stdout=stdout, stderr=stderr)
elapsed = (time.monotonic() - start) * 1000
text = paths['stdout'].read_text()
counts = {name: int(match.group(1)) for name in ['tests', 'pass', 'fail', 'skipped'] if (match := re.search(r'^# ' + name + r' (\d+)\s*$', text, re.M))}
after = hashlib.sha256(source.read_bytes()).hexdigest()
report = {'format': 'marlin-sidebar-frontend-check-v1', 'mode': args.mode, 'started_utc': started, 'finished_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'command': command, 'cwd': str(root / 'frontend'), 'exit_code': child.returncode, 'verification_duration_ms': elapsed, 'counts': counts, 'source': str(source.relative_to(root)), 'source_sha256_before': digest, 'source_sha256_after': after, 'source_unchanged_during_check': digest == after, 'logs': {kind: {'file': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for kind, path in paths.items() if kind in ['stdout', 'stderr']}, 'product_latency_claimed': False}
with paths['receipt'].open('x') as stream:
    json.dump(report, stream, ensure_ascii=False, indent=2)
    stream.write('\n')
print(json.dumps({'evidence': str(paths['receipt']), 'exit_code': child.returncode, 'counts': counts, 'source_unchanged': digest == after}))
assert child.returncode == 0 and digest == after
if args.mode == 'unit':
    assert counts['fail'] == 0 and counts['pass'] == counts['tests']
