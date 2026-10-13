from pathlib import Path
import hashlib, json, re, shutil, subprocess, tempfile

root = Path('/home/liuxuedeng/Django-Agent')
evidence = root / 'docs/refactor-evidence/20261013-asar-bootstrap-packaging-fix'
expected = json.loads((evidence / 'after-sha256.json').read_text())
directory = Path(tempfile.mkdtemp(prefix='marlin-asar-diff-owned-'))
try:
    for name in expected:
        source = evidence / 'before' / name
        if source.exists():
            target = directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    result = subprocess.run(['patch', '-p1', '-i', str(evidence / 'code-complete.diff')], cwd=directory,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr + result.stdout
    for name, digest in expected.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, name
        assert (directory / name).read_bytes() == (root / name).read_bytes(), name
    links = re.findall(r'\[[^\]]+\]\(([^)]+)\)', (evidence / 'REPORT.md').read_text())
    for link in links:
        assert not link.startswith(('http:', 'https:')), link
        target = (evidence / link.split('#')[0]).resolve()
        assert target.is_relative_to(evidence) and target.exists(), link
    facts = {'actual_exit_code': 0, 'scope_files': len(expected), 'diff_reconstructed_byte_exact': True,
             'report_links': len(links), 'report_links_exist': True,
             'diff_sha256': hashlib.sha256((evidence / 'code-complete.diff').read_bytes()).hexdigest(),
             'audit_temp_directory_cleaned_in_finally': True}
    (evidence / 'final-audit.json').write_text(json.dumps(facts, indent=2) + '\n')
    print(json.dumps(facts))
finally:
    shutil.rmtree(directory)
