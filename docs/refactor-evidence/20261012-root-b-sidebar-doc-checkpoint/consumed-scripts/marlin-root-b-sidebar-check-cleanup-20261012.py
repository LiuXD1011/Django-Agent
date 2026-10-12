import datetime
import hashlib
import json
from pathlib import Path
import shutil

directory = Path('/home/liuxuedeng/Django-Agent/docs/refactor-evidence/20261012-root-b-sidebar-doc-checkpoint')
verification = json.loads((directory / 'verification.json').read_text())
assert verification['git_diff_check_exit'] == 0 and verification['missing_links'] == []
assert verification['source_b_cleanup_protected'] and verification['sidebar_before_expected_red']
names = ['marlin-root-b-sidebar-doc-check-20261012.py', 'marlin-root-sidebar-name-before-20261012.py', 'marlin-root-b-sidebar-check-cleanup-20261012.py']
archive = directory / 'consumed-scripts'
assert not archive.exists()
archive.mkdir()
items = []
for name in names:
    source = Path('/tmp') / name
    target = archive / name
    assert source.is_file() and not source.is_symlink()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    shutil.copyfile(source, target)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    source.unlink()
    assert not source.exists()
    items.append({'source': str(source), 'archived': str(target.relative_to(directory)), 'sha256': digest, 'removed': True})
target = directory / 'cleanup.json'
assert not target.exists()
with target.open('x') as stream:
    json.dump({'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'items': items, 'exact_named_consumed_scripts_only': True}, stream, ensure_ascii=False, indent=2)
    stream.write('\n')
print(json.dumps({'evidence': str(target), 'archived_removed_scripts': len(items)}))
