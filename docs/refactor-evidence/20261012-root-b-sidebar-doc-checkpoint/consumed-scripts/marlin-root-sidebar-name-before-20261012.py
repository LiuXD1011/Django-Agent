import datetime
import hashlib
import json
from pathlib import Path

root = Path('/home/liuxuedeng/Django-Agent')
source = root / 'docs/refactor-evidence/20261012-root-native-clone-gui/054-installed-actual-1024-layout.json'
raw = source.read_bytes()
receipt = json.loads(raw)
snapshot = receipt['receipt']['result']['snapshot']
assert receipt['exit_code'] == 0 and receipt['receipt']['ok']
assert snapshot['window']['width'] == 1024 and snapshot['window']['height'] == 768
tree = snapshot['treeText']
checks = {
    'chat_button_has_purpose': '13 按钮 对话' in tree,
    'knowledge_button_has_purpose': '15 按钮 知识库' in tree,
    'account_button_has_purpose': '17 按钮 账户与设置' in tree,
}
directory = root / 'docs/refactor-evidence/20261012-sidebar-accessible-names'
directory.mkdir(exist_ok=True)
target = directory / 'before-installed-1024.json'
assert not target.exists()
report = {
    'format': 'marlin-sidebar-real-uia-before-v1',
    'checked_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'observed_utc': receipt['finished_utc'],
    'source': str(source.relative_to(root)),
    'source_sha256': hashlib.sha256(raw).hexdigest(),
    'window': snapshot['window'],
    'checks': checks,
    'observed_button_lines': [line.strip() for line in tree.splitlines() if any(line.strip().startswith(str(index) + ' 按钮') for index in (13, 15, 17))],
    'runtime_gui_replayed': False,
    'source_or_installer_edited': False,
    'expected_red': not all(checks.values()),
}
with target.open('x') as stream:
    json.dump(report, stream, ensure_ascii=False, indent=2)
    stream.write('\n')
print(json.dumps({'evidence': str(target), 'checks': checks, 'expected_red': report['expected_red']}, ensure_ascii=False))
assert all(checks.values()), 'Collapsed sidebar controls lack their accessible purposes in real installed UIA snapshot'
