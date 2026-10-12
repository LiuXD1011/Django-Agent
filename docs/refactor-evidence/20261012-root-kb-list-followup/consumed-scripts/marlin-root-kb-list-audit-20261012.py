import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path('/home/liuxuedeng/Django-Agent/docs/refactor-evidence/20261012-root-kb-list-followup')
SOURCE = Path('/home/liuxuedeng/.local/share/marlin-refactor/20261010-browser-qa')
label = sys.argv[1]
assert label in {'before', 'created', 'copied', 'pinned', 'reloaded', 'cleaned'}
target = ROOT / (label + '-readonly-db.json')
assert not target.exists()

def normalized(value):
    if isinstance(value, bytes):
        return {'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
    return value

def digest(rows):
    hashes = []
    for row in rows:
        safe = {name: normalized(value) for name, value in dict(row).items()}
        hashes.append(hashlib.sha256(json.dumps(safe, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest())
    return {'count': len(hashes), 'digest': hashlib.sha256(json.dumps(sorted(hashes), separators=(',', ':')).encode()).hexdigest()}

db = sqlite3.connect('file:' + str(SOURCE / 'marlin.sqlite3') + '?mode=ro', uri=True)
db.row_factory = sqlite3.Row
try:
    db.execute('PRAGMA query_only=ON')
    db.execute('BEGIN')
    protected = {}
    for table in ['users', 'tenants', 'tenant_memberships', 'models', 'model_usage', 'knowledges', 'chunks', 'wiki_pages', 'wiki_folders', 'knowledge_tags', 'task_records', 'desktop_jobs']:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if exists:
            protected[table] = digest(db.execute('SELECT * FROM "' + table + '"'))
    protected['original_knowledge_bases'] = digest(db.execute("SELECT * FROM knowledge_bases WHERE name NOT LIKE 'Orca 列表续验 20261012%'"))
    owned = [dict(row) for row in db.execute("SELECT id,name,description,is_pinned,pinned_at,deleted_at,tenant_id FROM knowledge_bases WHERE name LIKE 'Orca 列表续验 20261012%' ORDER BY created_at,id")]
    model_count = db.execute('SELECT count(*) FROM model_usage').fetchone()[0]
    files = {}
    for scope in ['.secrets', '.settings', 'media']:
        folder = SOURCE / scope
        if folder.exists():
            for path in sorted(folder.rglob('*')):
                if path.is_file():
                    files[str(path.relative_to(SOURCE))] = hashlib.sha256(path.read_bytes()).hexdigest()
    report = {'format': 'marlin-root-kb-list-readonly-audit-v1', 'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'label': label, 'source_root': str(SOURCE), 'protected': protected, 'owned_knowledge_bases': owned, 'managed_files_sha256': files, 'model_usage_count': model_count, 'read_only': True, 'secrets_reported': False}
    if label != 'before':
        baseline = json.loads((ROOT / 'before-readonly-db.json').read_text())
        report['protected_unchanged'] = protected == baseline['protected'] and files == baseline['managed_files_sha256']
        assert report['protected_unchanged']
finally:
    db.close()
with target.open('x') as stream:
    json.dump(report, stream, ensure_ascii=False, indent=2)
    stream.write('\n')
print(json.dumps({'label': label, 'owned_knowledge_bases': owned, 'protected_unchanged': report.get('protected_unchanged'), 'model_usage_count': model_count, 'evidence': str(target)}, ensure_ascii=False))
