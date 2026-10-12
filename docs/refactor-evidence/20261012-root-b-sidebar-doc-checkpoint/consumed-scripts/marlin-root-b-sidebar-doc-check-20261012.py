import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

root = Path('/home/liuxuedeng/Django-Agent')
evidence = root / 'docs/refactor-evidence/20261012-root-kb-list-followup'
docs = [root / 'docs/desktop-refactor' / name for name in ['KNOWLEDGE-LIST-FOLLOWUP-20261012.md', 'SIDEBAR-ACCESSIBLE-NAMES.md', 'FINAL-REPORT.md']]
links = []
for path in docs:
    text = path.read_text()
    for match in re.finditer(r'\[[^\]]+\]\(([^)]+)\)', text):
        target = match.group(1).strip().strip('<>')
        if urlsplit(target).scheme or target.startswith('#'):
            continue
        local = (path.parent / unquote(target.split('#', 1)[0])).resolve()
        assert local.is_file(), (path.name, target)
        links.append({'document': str(path.relative_to(root)), 'target': str(local.relative_to(root))})

def result(name):
    row = json.loads((evidence / name).read_text())
    assert row['exit_code'] == 0 and row['receipt']['ok']
    return json.loads(row['receipt']['result']['result'])

audit = json.loads((evidence / 'cleaned-readonly-db.json').read_text())
assert audit['protected_unchanged'] and audit['model_usage_count'] == 174
assert {row['id'] for row in audit['owned_knowledge_bases']} == {'e58bb317-bc0f-45ba-819f-90faae0afb2f', 'c897759a-fbe8-4b80-b9be-a339ec56da32'}
assert all(row['deleted_at'] and not row['is_pinned'] for row in audit['owned_knowledge_bases'])
final = result('077-cleanup-current-readonly.json')
assert final['cards'] == ['Orca 格式验收 20261011', 'Orca 全流程验收 20261010']
assert final['stats'] == {'chunks': 10027, 'count': 2, 'knowledge': 16, 'processing': 0}
assert not final['loading'] and not final['deleteLoading'] and final['deleteTargetName'] is None
assert result('072-empty-favorites-readonly.json')['cards'] == []
assert result('062-delete-cancel-preserved-readonly.json')['deleteTarget'] is None
auth = result('054-auth-safe-request-observation.json')
assert auth['url'].endswith('/platform/knowledge-bases')
assert any(row['path'] == '/api/v1/auth/login' and row['responseStatus'] == 200 for row in auth['authRequests'])
for name in ['027-search-by-list-refresh.json', '031-clear-search.json', '076-two-protected-kbs-poststate.json']:
    assert json.loads((evidence / name).read_text())['exit_code'] == 1
cleanup = json.loads((evidence / 'cleanup.json').read_text())
for row in cleanup['items']:
    assert row['removed'] and not Path(row['source']).exists()
    assert hashlib.sha256((evidence / row['archived']).read_bytes()).hexdigest() == row['sha256']
before = json.loads((root / 'docs/refactor-evidence/20261012-sidebar-accessible-names/before-installed-1024.json').read_text())
assert before['expected_red'] and not any(before['checks'].values())
diff = subprocess.run(['git', 'diff', '--check', '--', *[str(path.relative_to(root)) for path in docs]], cwd=root, text=True, capture_output=True)
assert diff.returncode == 0, diff.stdout + diff.stderr
out = root / 'docs/refactor-evidence/20261012-root-b-sidebar-doc-checkpoint'
assert not out.exists()
out.mkdir()
report = {'format': 'marlin-root-b-sidebar-doc-check-v1', 'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'local_links_checked': len(links), 'missing_links': [], 'links': links, 'documents': [{'path': str(path.relative_to(root)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in docs], 'source_b_cleanup_protected': True, 'ordinary_click_delivery_not_claimed': True, 'sidebar_before_expected_red': True, 'product_fix_not_claimed': True, 'git_diff_check_exit': diff.returncode}
with (out / 'verification.json').open('x') as stream:
    json.dump(report, stream, ensure_ascii=False, indent=2)
    stream.write('\n')
print(json.dumps({'evidence': str(out / 'verification.json'), 'links': len(links), 'missing': 0, 'diff_check_exit': diff.returncode, 'source_b_cleanup_protected': True}))
