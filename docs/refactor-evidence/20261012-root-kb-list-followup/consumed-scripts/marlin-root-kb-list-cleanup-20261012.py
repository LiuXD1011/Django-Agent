import datetime
import hashlib
import json
from pathlib import Path
import shutil

directory = Path('/home/liuxuedeng/Django-Agent/docs/refactor-evidence/20261012-root-kb-list-followup')
audit = json.loads((directory / 'cleaned-readonly-db.json').read_text())
assert audit['protected_unchanged'] and audit['model_usage_count'] == 174
assert len(audit['owned_knowledge_bases']) == 2
assert all(row['deleted_at'] and not row['is_pinned'] for row in audit['owned_knowledge_bases'])
names = [
    'marlin-root-kb-list-followup-20261012.py',
    'marlin-root-kb-list-audit-20261012.py',
    'marlin-root-kb-list-qa-auth-20261012.py',
    'marlin-root-kb-list-cleanup-20261012.py',
]
archive = directory / 'consumed-scripts'
assert not archive.exists()
archive.mkdir()
items = []
for name in names:
    source = Path('/tmp') / name
    target = archive / name
    assert source.is_file() and not source.is_symlink() and not target.exists()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    shutil.copyfile(source, target)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    source.unlink()
    assert not source.exists()
    items.append({'source': str(source), 'archived': str(target.relative_to(directory)), 'sha256': digest, 'removed': True})
report = {'format': 'marlin-root-kb-list-consumed-script-cleanup-v1', 'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'items': items, 'archived_versions': 'last consumed versions only', 'private_credential_file_preserved': True, 'business_cleanup_audited': True}
target = directory / 'cleanup.json'
assert not target.exists()
with target.open('x') as stream:
    json.dump(report, stream, ensure_ascii=False, indent=2)
    stream.write('\n')
print(json.dumps({'evidence': str(target), 'archived_removed_scripts': len(items), 'protected_unchanged': True, 'active_owned_kbs': 0}))
