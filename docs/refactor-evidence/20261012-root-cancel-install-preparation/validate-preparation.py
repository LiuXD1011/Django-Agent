"""Freeze only the preparation files; never execute the upgrade harness."""
import hashlib
import json
from pathlib import Path
import re
from datetime import datetime, timezone

ROOT = Path('/home/liuxuedeng/Django-Agent')
HERE = Path(__file__).resolve().parent
SCRIPT = Path('/tmp/marlin-agent-cancel-install-20261012.py')
SCRIPT_SHA = '102b230813fece9297b8ce11a16dbb5d37ca8d3405cd1af8ac0a25ff95cd4965'
SURVEY_SHA = '670301123570dd4c183eb6b0bcfe362f581b8e77e95163d8e10789fe333e94c8'
SOURCE_SHA = '120dea90cc8ea26d4f7388589181fe5ea7f12f7f3603ea397a1e6f645d80a77e'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


assert sha(SCRIPT) == sha(HERE / 'reviewed-harness.source.txt') == SCRIPT_SHA
assert sha(HERE / 'survey-harness.source.txt') == '963646425e67f9161a288ab3d2fcb9e26c2ecda1b234dbbf1bf6bc0f7578be6b'
assert sha(HERE / 'readonly-survey.json') == SURVEY_SHA
survey = json.loads((HERE / 'readonly-survey.json').read_text())
assert survey['state'] == 'verified_readonly' and len(survey['retained']['business_tables']) == 12
assert survey['processes']['candidate_count'] == 0
assert survey['processes']['protected_outside_scope'] == [{'pid': 25268, 'image': r'C:\Users\lxd\AppData\Local\Temp\Marlin Desktop TS QA 20261010\electron-runtime\electron.exe', 'creation_filetime': 134361236166333286}]
assert survey['processes']['historical_pids'][0]['status'] == 'not_present'
for name in ('default-linux-final.log', 'default-windows-final.log'):
    result = json.loads((HERE / name).read_text())
    assert result['state'] == 'review_only' and result['script_sha256'] == SCRIPT_SHA
    assert result['windows_child_processes_started'] == 0
    assert all(result[field] is False for field in ('application_started', 'installer_executed', 'registry_writes', 'data_changes'))
for name in ('guards-linux.log', 'guards-windows.log'):
    text = (HERE / name).read_text()
    assert re.search(r'Ran 6 tests in [\d.]+s\s+OK\s*$', text)
    assert text.count(' ... ok') == 6
for name in ('default-windows.log', 'survey-command-first.log'):
    result = json.loads((HERE / name).read_bytes().decode('cp936'))
    assert result['state'] in ('review_only', 'verified_readonly')
freeze_path = ROOT / 'docs/refactor-evidence/20261012-root-cancel-source-freeze.json'
assert sha(freeze_path) == SOURCE_SHA
freeze = json.loads(freeze_path.read_text())
for group, count in (('sourceInputs', 350), ('compiledArtifacts', 435)):
    assert len(freeze[group]) == count
    assert all(sha(ROOT / file) == expected for file, expected in freeze[group].items())
links = []
readme = HERE / 'README.md'
text = readme.read_text()
assert all(line == line.rstrip() for line in text.splitlines())
for relative in re.findall(r'\]\(([^)]+)\)', text):
    target = (HERE / relative).resolve()
    if relative != 'preparation-manifest.json':
        assert target.is_file(), relative
    links.append(relative)
assert not (HERE / 'executed-upgrade.json').exists()
assert not Path('/mnt/c/Users/lxd/AppData/Local/Temp/Marlin 安装验收 20261010/.cancel-code-upgrade-20261012').exists()
files = {}
for file in sorted(HERE.iterdir()):
    assert file.is_file()
    if file.suffix == '.json':
        json.loads(file.read_text())
    files[file.name] = {'sha256': sha(file), 'bytes': file.stat().st_size}
native_command = [r'C:\Python313\python.exe', '-I', '-B', r'\\wsl.localhost\Ubuntu-20.04\tmp\marlin-agent-cancel-install-20261012.py']
commands = [
    {'command': ['python', '-B', str(SCRIPT)], 'exitCode': 0, 'log': 'default-linux.log', 'scriptSHA': survey['script_sha256_at_survey']},
    {'command': native_command, 'exitCode': 0, 'log': 'default-windows.log', 'logEncoding': 'cp936', 'scriptSHA': survey['script_sha256_at_survey']},
    {'command': native_command + ['--survey-readonly'], 'exitCode': 0, 'log': 'survey-command-first.log', 'logEncoding': 'cp936', 'scriptSHA': survey['script_sha256_at_survey']},
    {'command': ['python', '-B', str(SCRIPT)], 'exitCode': 0, 'log': 'default-linux-final.log', 'scriptSHA': SCRIPT_SHA},
    {'command': native_command, 'exitCode': 0, 'log': 'default-windows-final.log', 'logEncoding': 'utf-8', 'scriptSHA': SCRIPT_SHA},
    {'command': ['python', '-B', str(HERE / 'test-harness-guards.py')], 'exitCode': 0, 'log': 'guards-linux.log', 'testsPassed': 6},
    {'command': [r'C:\Python313\python.exe', '-I', '-B', r'\\wsl.localhost\Ubuntu-20.04\home\liuxuedeng\Django-Agent\docs\refactor-evidence\20261012-root-cancel-install-preparation\test-harness-guards.py'], 'exitCode': 0, 'log': 'guards-windows.log', 'testsPassed': 6},
    {'command': ['git', 'diff', '--no-index', '--', str(HERE / 'survey-harness.source.txt'), str(SCRIPT)], 'exitCode': 1, 'log': 'post-survey-harness.diff', 'meaning': 'Expected actual source differences; not a test failure'},
]
record = {'createdUtc': datetime.now(timezone.utc).isoformat(), 'state': 'prepared_not_executed', 'files': files, 'reviewedHarness': {'path': str(SCRIPT), 'sha256': SCRIPT_SHA, 'retainedForRootExecution': True}, 'survey': {'path': str((HERE / 'readonly-survey.json').relative_to(ROOT)), 'sha256': SURVEY_SHA, 'protectedProcesses': survey['processes']['protected_outside_scope'], 'historicalPids': survey['processes']['historical_pids'], 'dataFiles': len(survey['retained']['data_files_sha256']), 'credentialMaterialFiles': len(survey['retained']['credential_material_sha256']), 'businessTableCount': 12}, 'sourceFreeze': {'sha256': SOURCE_SHA, 'sourceInputs': 350, 'compiledArtifacts': 435, 'allMatchDuringPreparation': True}, 'actualCommands': commands, 'markdownLinksChecked': links, 'whitespaceChecked': ['README.md'], 'reservedFutureOutputs': ['executed-upgrade.json'], 'futureExecuteCommand': native_command + ['--execute-reviewed-upgrade', '--reviewed-script-sha256', SCRIPT_SHA, '--readonly-survey-sha256', SURVEY_SHA], 'limits': {'installerExecuted': False, 'productStarted': False, 'GUIUsed': False, 'registryWritten': False, 'retainedDataWritten': False, 'rowOrCredentialContentsReported': False, 'paidModelCalls': 0, 'upgradeBranchExecuted': False, 'formalValidationBranchExecuted': False, 'sourceChanged': False}}
target = HERE / 'preparation-manifest.json'
with target.open('x', encoding='utf-8') as stream:
    stream.write(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'state': record['state'], 'manifest': str(target), 'manifestSHA': sha(target), 'preparedFiles': len(files), 'scriptSHA': SCRIPT_SHA, 'surveySHA': SURVEY_SHA, 'dataFiles': record['survey']['dataFiles'], 'scriptRetained': SCRIPT.is_file()}))
