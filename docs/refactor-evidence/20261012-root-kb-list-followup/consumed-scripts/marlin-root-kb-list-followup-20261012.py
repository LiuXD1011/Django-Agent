import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess

PAGE = '22e0e212-30aa-4945-8a3d-7176cdfffdff'
EVIDENCE = Path('/home/liuxuedeng/Django-Agent/docs/refactor-evidence/20261012-root-kb-list-followup')
parser = argparse.ArgumentParser()
parser.add_argument('name')
parser.add_argument('command', choices=['snapshot', 'click', 'fill', 'keypress', 'reload', 'eval', 'switch'])
parser.add_argument('arguments', nargs=argparse.REMAINDER)
args = parser.parse_args()
assert args.name.replace('-', '').isalnum()
assert all('password' not in item.casefold() and 'cookie' not in item.casefold() and 'token' not in item.casefold() for item in args.arguments)
EVIDENCE.mkdir(exist_ok=True)
target = EVIDENCE / (args.name + '.json')
attempt = EVIDENCE / (args.name + '.attempt.json')
assert not target.exists() and not attempt.exists()
before = datetime.datetime.now(datetime.timezone.utc).isoformat()
with attempt.open('x') as stream:
    json.dump({'started_utc': before, 'page': PAGE, 'command': args.command, 'arguments': args.arguments}, stream, ensure_ascii=False, indent=2)
    stream.flush()
    os.fsync(stream.fileno())
command = ['orca-ide', 'tab', 'switch', '--page', PAGE, '--focus'] if args.command == 'switch' else ['orca-ide', args.command, '--page', PAGE]
result = subprocess.run([*command, *args.arguments, '--json'], text=True, capture_output=True, timeout=60)
try:
    receipt = json.loads(result.stdout)
except json.JSONDecodeError:
    receipt = {'parse_error': True, 'stdout': result.stdout, 'stderr': result.stderr}
report = {'started_utc': before, 'finished_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'page': PAGE, 'command': args.command, 'arguments': args.arguments, 'exit_code': result.returncode, 'receipt': receipt}
with target.open('x') as stream:
    json.dump(report, stream, ensure_ascii=False, indent=2)
    stream.write('\n')
if args.command == 'snapshot':
    print(receipt.get('result', {}).get('snapshot', receipt))
else:
    print(json.dumps(receipt, ensure_ascii=False))
assert result.returncode == 0 and receipt.get('ok') is True
