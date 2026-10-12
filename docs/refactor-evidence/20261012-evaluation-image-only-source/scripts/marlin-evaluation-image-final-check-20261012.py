import datetime
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote

root = Path('/home/liuxuedeng/Django-Agent')
evidence = root / 'docs/refactor-evidence/20261012-evaluation-image-only-source'
doc = root / 'docs/desktop-refactor/EVALUATION-IMAGE-ONLY-SOURCE.md'
source_paths = [
    'packages/core/src/evaluation/isolated-index.ts',
    'packages/core/src/documents/chunker.ts',
    'packages/core/test/evaluation-image-only-source.test.ts',
]
dist_paths = [f'packages/core/dist/{module}{extension}'
              for module in ['evaluation/isolated-index', 'documents/chunker']
              for extension in ['.js', '.d.ts', '.js.map']]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

scripts = evidence / 'scripts'
scripts.mkdir(exist_ok=True)
cleanup = []
for temporary in [Path('/tmp/marlin-evaluation-image-test-command-20261012.py'), Path(__file__)]:
    archived = scripts / temporary.name
    shutil.copyfile(temporary, archived)
    cleanup.append({'temporary': str(temporary), 'archived': str(archived.relative_to(root)),
                    'sha256': sha(archived), 'delete_planned': True})

check_path, freeze_path = evidence / 'final-check.json', evidence / 'freeze.json'
check_path.write_text('{}\n')
freeze_path.write_text('{}\n')
links = []
for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', doc.read_text()):
    if target.startswith(('https:', 'http:', '#')):
        continue
    candidate = (doc.parent / unquote(target.split('#', 1)[0].strip('<>'))).resolve()
    links.append({'target': target, 'exists': candidate.exists()})
assert all(link['exists'] for link in links), links

commands = [
    ['git', 'diff', '--check', '--', *source_paths, str(doc.relative_to(root))],
    ['git', 'diff', '--no-index', '--check', '/dev/null', source_paths[2]],
]
checks = []
for command in commands:
    result = subprocess.run(command, cwd=root, capture_output=True, text=True)
    checks.append({'command': command, 'exit_code': result.returncode,
                   'stdout': result.stdout, 'stderr': result.stderr})
    if '--no-index' in command:
        checks[-1]['exit_one_means_new_file_diff'] = result.returncode == 1
        assert result.returncode in (0, 1) and not result.stdout and not result.stderr, checks[-1]
    else:
        assert result.returncode == 0, checks[-1]

for item in cleanup:
    temporary = Path(item['temporary'])
    temporary.unlink()
    item['deleted'] = not temporary.exists()
checks_document = {
    'checked_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'commands': checks, 'links': links, 'temporary_scripts': cleanup,
    'browser_recheck_helpers_retained_for_pending_task': [
        '/tmp/marlin-evaluation-recheck-browser-20261012.py',
        '/tmp/marlin-evaluation-recheck-readonly-20261012.py',
        '/tmp/marlin-evaluation-recheck-source-review-20261012.py',
    ],
    'vendor_requests': 0, 'gui_commands': 0, 'live_database_writes': 0,
}
check_path.write_text(json.dumps(checks_document, ensure_ascii=False, indent=2) + '\n')

verification = {}
for label in ['semantic-red', 'semantic-green', 'final-related-evaluation-green',
              'small-chunker-related-green', 'final-typecheck', 'build']:
    verification[label] = json.loads((evidence / f'{label}.json').read_text())
freeze = {
    'frozen_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'source_sha256': {path: sha(root / path) for path in source_paths},
    'compiled_sha256': {path: sha(root / path) for path in dist_paths},
    'document_sha256': {str(doc.relative_to(root)): sha(doc)},
    'evidence_sha256': {str(path.relative_to(root)): sha(path)
                        for path in sorted(evidence.rglob('*'))
                        if path.is_file() and path != freeze_path},
    'verification': verification,
    'limitations': ['No GUI or live data change in this implementation phase',
                    'No vendor model requests; controlled Ragas fixtures are not real-provider acceptance',
                    'Linux core build passed; Windows rebuilt/installed acceptance and actual browser recheck remain pending',
                    'Goal remains active'],
}
freeze_path.write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'source_sha256': freeze['source_sha256'],
                  'compiled_sha256': freeze['compiled_sha256'],
                  'document_sha256': freeze['document_sha256'],
                  'freeze_sha256': sha(freeze_path),
                  'final_check_sha256': sha(check_path),
                  'relative_links_checked': len(links),
                  'diff_checks': checks, 'temporary_scripts': cleanup}, ensure_ascii=False, indent=2))
