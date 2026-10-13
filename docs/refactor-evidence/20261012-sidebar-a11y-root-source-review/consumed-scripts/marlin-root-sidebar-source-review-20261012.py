"""Independent, read-only Root review. No Windows or GUI actions."""
from pathlib import Path
import datetime
import hashlib
import importlib.util
import json
import subprocess

ROOT = Path('/home/liuxuedeng/Django-Agent')
EVIDENCE = ROOT / 'docs/refactor-evidence/20261012-sidebar-a11y-root-source-review'
FREEZE = ROOT / 'docs/refactor-evidence/20261012-sidebar-a11y-integrated-source-freeze.json'
FROZEN_SHA = '6e37bc4f7e94dbc4714f322ee32c56d32da084a5a039f231603290466ce1b7d8'
COPY = Path('/tmp/marlin-agent-sidebar-a11y-stage-copy-ready-20261012.py')
RUNNER = Path('/tmp/marlin-agent-sidebar-a11y-windows-build-20261012.py')
COPY_SHA = '6059070aea8c0c7263eaca1beef50b763312108a8f5323384fffccc6b142fe95'
RUNNER_SHA = 'b8578b1ba0361145e0d95c7a0a97a2e205034ea980f4a7835330675b71ca3348'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def need(condition, message):
    if not condition:
        raise RuntimeError(message)

need(sha(FREEZE) == FROZEN_SHA, 'source freeze changed')
need(sha(COPY) == COPY_SHA and sha(RUNNER) == RUNNER_SHA, 'reviewed helper changed')
need(sha(ROOT / 'scripts/build_windows.py') == '1ce81933b82fd67200cf74348c8c7ccb9de938dabb4745ded5f75f4ecc89a835', 'formal builder changed')
frozen = json.loads(FREEZE.read_text())
spec = importlib.util.spec_from_file_location('root_readonly_windows_builder', ROOT / 'scripts/build_windows.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
need(builder.source_inputs(ROOT) == frozen['sourceInputs'], 'actual source inputs differ')
for key in ['additionalReviewedTestInputs', 'localCompiledOutputs', 'requiredCompletedChecks']:
    need(all(sha(ROOT / path) == expected for path, expected in frozen[key].items()), key + ' changed')
for key in ['frontendFreeze', 'coreFreeze']:
    need(sha(ROOT / frozen[key]['path']) == frozen[key]['sha256'], key + ' changed')
prior = json.loads((ROOT / frozen['priorSourceFreeze']).read_text())
need(sha(ROOT / frozen['priorSourceFreeze']) == frozen['priorSourceFreezeSHA'], 'prior freeze changed')
changed = [path for path in prior['sourceInputs'] if frozen['sourceInputs'].get(path) != prior['sourceInputs'][path]]
need(changed == ['frontend/src/views/Platform.vue'] and set(prior['sourceInputs']) == set(frozen['sourceInputs']), 'sole source change boundary failed')
core = {path: value for path, value in frozen['localCompiledOutputs'].items() if path.startswith('packages/core/dist/')}
front = {path: value for path, value in frozen['localCompiledOutputs'].items() if path.startswith('frontend/dist/')}
need(len(core) == 438 and len(front) == 85 and len(frozen['localCompiledOutputs']) == 523, 'compiled counts differ')
need(core == {path: value for path, value in prior['localCompiledOutputs'].items() if path.startswith('packages/core/dist/')}, 'core compiled changed')
need(frozen['additionalReviewedTestInputs'] == prior['additionalReviewedTestInputs'], 'additional test scope changed')
for mode in ['unit', 'build']:
    receipt = json.loads((ROOT / f'docs/refactor-evidence/20261012-sidebar-accessible-names/{mode}-execution.json').read_text())
    need(receipt['exit_code'] == 0 and receipt['source_unchanged_during_check'], mode + ' did not pass')
    need(receipt['source_sha256_before'] == receipt['source_sha256_after'] == frozen['sourceInputs']['frontend/src/views/Platform.vue'], mode + ' wrong source')
    for log in receipt['logs'].values():
        need(sha(ROOT / 'docs/refactor-evidence/20261012-sidebar-accessible-names' / log['file']) == log['sha256'], mode + ' log differs')
dom_path = ROOT / 'docs/refactor-evidence/20261012-auth-browser-isolation-real/102-d2-platform-sidebar-accessibility.json'
dom_receipt = json.loads(dom_path.read_text())
need(dom_receipt['exit_code'] == 0, 'source browser DOM observation failed')
dom = json.loads(json.loads(dom_receipt['stdout'])['result']['result'])
need(dom['url'] == 'http://127.0.0.1:5184/platform/knowledge-bases', 'unexpected source page')
need([item['ariaLabel'] for item in dom['sidebar']] == ['对话', '知识库', '账户与设置'], 'sidebar labels differ')
need(all(item['title'] == item['ariaLabel'] and item['type'] == 'button' and item['disabled'] is False for item in dom['sidebar']), 'sidebar attributes differ')
need([item['ariaCurrent'] for item in dom['sidebar']] == [None, 'page', None], 'active navigation differs')
reviews = []
for path in [COPY, RUNNER]:
    result = subprocess.run(['python3', '-B', str(path)], cwd=ROOT, capture_output=True, text=True, check=True)
    value = json.loads(result.stdout)
    need(value['state'] == 'review_only' and value['builder_started'] is False and value['Windows_process_actions'] == 0, 'helper performed an execution')
    reviews.append(value)
diff = subprocess.run(['git', 'diff', '--check'], cwd=ROOT, capture_output=True, text=True)
need(diff.returncode == 0, 'diff check failed')
EVIDENCE.mkdir(exist_ok=True)
value = {
    'format': 'marlin-root-sidebar-source-review-v1',
    'state': 'verified_source_and_preparation_only',
    'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'sourceFreezeSHA': FROZEN_SHA,
    'sourceInputCount': len(frozen['sourceInputs']),
    'additionalTestCount': len(frozen['additionalReviewedTestInputs']),
    'changedSourceInputs': changed,
    'compiledCounts': {'core': len(core), 'frontend': len(front), 'total': len(core) + len(front)},
    'coreCompiledUnchanged': True,
    'sourceBrowserDOMReceiptSHA': sha(dom_path),
    'sourceBrowserDOMPassed': True,
    'narrowInstalledGUIValidated': False,
    'reviewedHelpers': reviews,
    'actualWindowsCopyOrBuildStarted': False,
    'gitDiffCheckExitCode': diff.returncode,
    'reviewHelperSHA': sha(Path(__file__)),
}
with (EVIDENCE / 'review.json').open('x', encoding='utf8') as stream:
    json.dump(value, stream, indent=2, ensure_ascii=False)
print(json.dumps(value, ensure_ascii=False))
