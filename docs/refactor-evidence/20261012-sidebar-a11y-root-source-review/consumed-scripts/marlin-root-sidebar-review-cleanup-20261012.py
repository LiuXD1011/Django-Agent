"""Check Root-owned docs and archive only precisely consumed helpers."""
from pathlib import Path
import datetime
import hashlib
import json
import re
import subprocess
from urllib.parse import unquote

ROOT = Path('/home/liuxuedeng/Django-Agent')
EVIDENCE = ROOT / 'docs/refactor-evidence/20261012-sidebar-a11y-root-source-review'
DOCS = [
    ROOT / 'docs/desktop-refactor/SIDEBAR-ACCESSIBLE-NAMES.md',
    ROOT / 'docs/desktop-refactor/FINAL-REPORT.md',
    ROOT / 'docs/desktop-refactor/KNOWLEDGE-LIST-FOLLOWUP-20261012.md',
]
HELPERS = [
    Path('/tmp/marlin-root-sidebar-frontend-checks-20261012.py'),
    Path('/tmp/marlin-root-sidebar-source-review-20261012.py'),
    Path(__file__),
]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def need(value, message):
    if not value:
        raise RuntimeError(message)

review = json.loads((EVIDENCE / 'review.json').read_text())
need(review['state'] == 'verified_source_and_preparation_only' and review['sourceBrowserDOMPassed'], 'source review not successful')
need(sha(HELPERS[1]) == review['reviewHelperSHA'], 'consumed source review helper changed')
for mode in ['unit', 'build']:
    receipt = json.loads((ROOT / f'docs/refactor-evidence/20261012-sidebar-accessible-names/{mode}-execution.json').read_text())
    need(receipt['exit_code'] == 0 and receipt['source_unchanged_during_check'], 'frontend helper is not fully consumed')
need(sha(HELPERS[0]) == '800ff597a6b3e9f5192f8237fdcb3e4b5f71b70403a1d858ddc28cb26c4da8f4', 'frontend helper changed')
links = 0
for document in DOCS:
    for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', document.read_text()):
        if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', target) or target.startswith('#'):
            continue
        local = unquote(target.split('#', 1)[0].strip('<>'))
        need((document.parent / local).resolve().exists(), 'missing local link in ' + document.name + ': ' + local)
        links += 1
diff = subprocess.run(['git', 'diff', '--check'], cwd=ROOT, capture_output=True, text=True)
need(diff.returncode == 0, 'diff check failed')
archive = EVIDENCE / 'consumed-scripts'
archive.mkdir(exist_ok=True)
consumed = []
for helper in HELPERS:
    target = archive / helper.name
    need(helper.is_file() and not helper.is_symlink() and not target.exists(), 'exact cleanup path invalid')
    before = sha(helper)
    with target.open('xb') as stream:
        stream.write(helper.read_bytes())
    need(sha(target) == before, 'archive hash differs')
    consumed.append({'path': str(helper), 'archive': str(target.relative_to(ROOT)), 'sha256': before})
for helper in HELPERS:
    helper.unlink()
need(all(not helper.exists() for helper in HELPERS), 'consumed helper remains')
value = {
    'format': 'marlin-root-sidebar-review-cleanup-v1',
    'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'state': 'verified_docs_and_consumed_cleanup_only',
    'documents': {str(path.relative_to(ROOT)): sha(path) for path in DOCS},
    'localLinksChecked': links,
    'missingLinks': [],
    'gitDiffCheckExitCode': diff.returncode,
    'consumed': consumed,
    'removedExactHelpers': True,
    'windowsOrGUIOrUserDataActions': 0,
    'sourceReviewSHA': sha(EVIDENCE / 'review.json'),
}
with (EVIDENCE / 'docs-and-cleanup.json').open('x', encoding='utf8') as stream:
    json.dump(value, stream, ensure_ascii=False, indent=2)
print(json.dumps(value, ensure_ascii=False))
