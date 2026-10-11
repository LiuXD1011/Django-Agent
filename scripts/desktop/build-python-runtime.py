"""Build and verify relocatable Windows x64 document/Ragas helpers, without Django.

Build machine: Windows x64 Python 3.13 with pip and internet access.
Installed application: only payload/python/python.exe and the copied helpers.
Use --prepare-only to defer copying helpers; --verify-only never installs wheels.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import uuid
import zipfile


ROOT = Path(__file__).resolve().parents[2]
PYTHON_VERSION = "3.13.16"
PYTHON_SHA256 = "97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
LOCK = Path(__file__).with_name("python-runtime-lock-windows-x64.txt")
NATIVE_LOCK = Path(__file__).with_name("python-runtime-lock-native.txt")
BUILD_MARKER = ".marlin-python-build"
RUNTIME_MARKER = ".marlin-python-runtime"
WORKER_MARKER = ".marlin-python-worker"
MARKER_VALUE = "marlin-python-build-v1\n"
PTH = "python313.zip\n.\nLib/site-packages\n../workers/document\n../workers/evaluation\n"
FORBIDDEN = {"django", "djangorestframework", "django-cors-headers", "gunicorn", "waitress", "whitenoise"}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def guarded_directory(path: Path, marker: str) -> Path:
    require(not path.is_symlink(), "Refusing a symlink build directory")
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=True)
    existing = path / marker
    require(existing.is_file() and existing.read_text() == MARKER_VALUE or not any(path.iterdir()),
            f"Use an empty or builder-owned directory: {path}")
    existing.write_text(MARKER_VALUE, encoding="utf-8")
    return path


def run(command, cwd: Path, env=None, timeout=None, capture=False):
    values = [str(value) for value in command]
    print("RUN", subprocess.list2cmdline(values), flush=True)
    return subprocess.run(values, cwd=cwd, env=env, timeout=timeout, check=True,
                          capture_output=capture, text=capture, encoding="utf-8" if capture else None)


def runtime_env(python_dir: Path) -> dict[str, str]:
    allowed = {"systemroot", "windir", "systemdrive", "comspec", "temp", "tmp", "userprofile", "localappdata", "appdata"}
    env = {key: value for key, value in os.environ.items() if key.lower() in allowed}
    env.update(PATH=str(python_dir) + os.pathsep + str(Path(os.environ["SystemRoot"]) / "System32"),
               PYTHONUTF8="1", RAGAS_DO_NOT_TRACK="true",
               HF_HUB_DISABLE_TELEMETRY="1", DO_NOT_TRACK="1")
    return env


def lock_entries():
    entries = []
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        match = re.fullmatch(r"([\w.-]+)==([^\s]+) --hash=sha256:([a-f0-9]{64})", line)
        require(match is not None, "Every runtime wheel must have an exact version and SHA256")
        name, version, sha = match.groups()
        normalized = re.sub(r"[-_.]+", "-", name).lower()
        require(normalized not in FORBIDDEN and not normalized.startswith("django"), "Legacy service dependency refused")
        entries.append({"name": name, "version": version, "sha256": sha})
    require(bool(entries) and len({row["name"].lower() for row in entries}) == len(entries), "Invalid dependency lock")
    return entries


def download_python(work: Path) -> Path:
    target = work / f"python-{PYTHON_VERSION}-embed-amd64.zip"
    require(not target.is_symlink(), "Refusing a symlink archive")
    if not target.exists():
        temporary = target.with_suffix(".download")
        urllib.request.urlretrieve(PYTHON_URL, temporary)
        require(digest(temporary) == PYTHON_SHA256, "Official Python archive SHA256 mismatch")
        temporary.replace(target)
    require(digest(target) == PYTHON_SHA256, "Cached Python archive SHA256 mismatch")
    return target


def make_runtime(payload: Path, work: Path, entries) -> Path:
    destination = payload / "python"
    stamp = {"python_version": PYTHON_VERSION, "python_sha256": PYTHON_SHA256,
             "dependency_lock_sha256": digest(LOCK), "native_lock_sha256": digest(NATIVE_LOCK)}
    if destination.exists():
        require(not destination.is_symlink() and (destination / RUNTIME_MARKER).read_text() == MARKER_VALUE,
                "Existing Python runtime is not owned by this builder")
        manifest = json.loads((destination / "runtime-manifest.json").read_text())
        require(manifest["inputs"] == stamp, "Existing runtime inputs differ; choose a new payload directory")
        return destination
    stage = work / "python-stage"
    if stage.exists():
        guarded_directory(stage, RUNTIME_MARKER)
        # Failed builds can leave old wheels. Remove only this exclusive staging
        # directory, so a changed dependency lock cannot publish stale packages.
        shutil.rmtree(stage)
    stage = guarded_directory(stage, RUNTIME_MARKER)
    archive = download_python(work)
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            path = PurePosixPath(member.filename)
            require(not path.is_absolute() and ".." not in path.parts and ":" not in member.filename and "\\" not in member.filename,
                    "Unsafe official archive entry")
        bundle.extractall(stage)
    (stage / "python313._pth").write_text(PTH, encoding="utf-8")
    wheels = work / "wheels"
    wheels.mkdir(exist_ok=True)
    pip = [sys.executable, "-m", "pip", "--isolated", "--disable-pip-version-check"]
    run([*pip, "download", "--index-url", "https://pypi.org/simple", "--only-binary=:all:",
         "--require-hashes", "--no-deps", "--dest", wheels, "-r", LOCK], work)
    run([*pip, "install", "--no-index", "--find-links", wheels, "--only-binary=:all:", "--require-hashes",
         "--no-deps", "--ignore-installed", "--no-compile", "--no-warn-script-location", "--target",
         stage / "Lib" / "site-packages", "-r", LOCK], work)
    # This existing narrow utility copies only hash-pinned Cairo DLLs and notices;
    # it imports no backend modules and installs no Python dependencies.
    # Windows cannot overwrite a VC DLL currently mapped by its own interpreter.
    # Execute the packaging utility using the build interpreter; only its pinned
    # zstandard wheel is taken from staging, never a target Python installation.
    native_command = "import sys,runpy;sys.path.insert(0,sys.argv.pop(1));script=sys.argv.pop(1);sys.argv[0]=script;runpy.run_path(script,run_name='__main__')"
    run([sys.executable, "-I", "-B", "-S", "-c", native_command, stage / "Lib" / "site-packages",
         ROOT / "scripts" / "bundle_windows_native.py", NATIVE_LOCK, work / "native-downloads", stage],
        work, runtime_env(stage), timeout=600)
    require((stage / "LICENSE.txt").is_file(), "Python license missing")
    shutil.copy2(LOCK, stage / LOCK.name)
    shutil.copy2(NATIVE_LOCK, stage / NATIVE_LOCK.name)
    manifest = {"format": "marlin-python-runtime-v1", "platform": "win_amd64", "inputs": stamp,
                "python_url": PYTHON_URL, "dependencies": entries, "isolated_path_file": PTH,
                "ocr": {"available": False, "reason": "worker_ocr_not_implemented"}}
    (stage / "runtime-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    payload.mkdir(parents=True, exist_ok=True)
    stage.replace(destination)
    return destination


def copy_workers(payload: Path) -> None:
    for name in ("document", "evaluation"):
        source = ROOT / "workers" / name
        target = payload / "workers" / name
        guarded_directory(target, WORKER_MARKER)
        files = []
        for path in source.rglob("*"):
            if "__pycache__" in path.parts or "tests" in path.relative_to(source).parts or path.name.startswith("test_") or path.name == ".gitattributes":
                continue
            require(not path.is_symlink(), "Refusing symlink helper source")
            if not path.is_file() or path.suffix == ".pyc":
                continue
            require(path.suffix == ".py" or path.name in {"LICENSE", "README.md", "requirements.txt"}, "Unexpected helper source file")
            relative = path.relative_to(source)
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            files.append({"path": relative.as_posix(), "sha256": digest(destination)})
        (target / "source-manifest.json").write_text(json.dumps(files, indent=2) + "\n", encoding="utf-8")


def invoke_worker(python: Path, worker: Path, request, work: Path, env):
    completed = subprocess.run([str(python), "-B", str(worker)], input=json.dumps(request, ensure_ascii=False) + "\n",
                               cwd=work, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120, check=True)
    values = [json.loads(line) for line in completed.stdout.splitlines() if line]
    require(len(values) == 1 and values[0].get("type") == "result", f"Helper protocol failed: {worker.parent.name}")
    require(values[0].get("protocol") == 1 and values[0].get("id") == request["id"], "Helper protocol identity mismatch")
    return values[0]["result"]


def verify(payload: Path, work: Path) -> dict:
    python_dir = payload / "python"
    python = python_dir / "python.exe"
    require(python.is_file(), "Bundled interpreter missing")
    env = runtime_env(python_dir)
    # Both Python environment overrides must be ignored, even if they contain a
    # usable Django-shaped module. No real user site or developer keys are read.
    with tempfile.TemporaryDirectory(prefix="isolation-", dir=work) as temporary:
        poison = Path(temporary)
        (poison / "django").mkdir()
        (poison / "django" / "__init__.py").write_text("raise RuntimeError('untrusted Python path leaked')\n")
        poisoned = dict(env, PYTHONPATH=str(poison), PYTHONHOME=str(poison))
        probe = run([python, "-c", "import sys,json,importlib.util,importlib.metadata; print(json.dumps({'version':sys.version,'executable':sys.executable,'path':sys.path,'isolated':sys.flags.isolated,'no_site':sys.flags.no_site,'django_spec':importlib.util.find_spec('django') is not None,'ragas_version':importlib.metadata.version('ragas'),'dependencies':[{'name':d.metadata['Name'],'version':d.version} for d in importlib.metadata.distributions()]}))"], work, poisoned, timeout=30, capture=True)
        isolation = json.loads(probe.stdout)
        require(isolation["isolated"] == 1 and isolation["no_site"] == 1 and not isolation["django_spec"], "Python isolation failed")
        require(isolation["ragas_version"] == "0.4.3", "Ragas version mismatch")
        normalized = lambda name: re.sub(r"[-_.]+", "-", name).lower()
        expected = {normalized(row["name"]): row["version"] for row in lock_entries()}
        installed = {normalized(row["name"]): row["version"] for row in isolation["dependencies"]}
        require(installed == expected, "Installed dependency versions differ from the complete helper lock")
        require(all(Path(path).resolve().is_relative_to(payload.resolve()) for path in isolation["path"]), "External Python search path leaked")
        blocked = subprocess.run([str(python), "-c", "import django"], cwd=work, env=poisoned, capture_output=True, text=True, encoding="utf-8", timeout=30)
        require(blocked.returncode != 0 and "ModuleNotFoundError" in blocked.stderr, "Django import unexpectedly succeeded")
    document_worker = payload / "workers" / "document" / "worker.py"
    evaluation_worker = payload / "workers" / "evaluation" / "worker.py"
    capabilities = invoke_worker(python, document_worker, {"protocol": 1, "id": str(uuid.uuid4()), "operation": "capabilities"}, work, env)
    for format_name in ("txt", "pdf", "docx", "csv", "xlsx", "xls", "pptx", "png", "svg"):
        require(capabilities["format_status"][format_name] is True, f"Required format unavailable: {format_name}")
    outputs = []
    fixtures = ROOT / "workers" / "document" / "tests" / "fixtures"
    for name in ("unicode.txt", "unicode.md", "text.pdf", "table.docx", "records.csv", "records.xlsx", "records.xls", "slides.pptx", "image.png", "image.svg", "scanned.pdf"):
        source = fixtures / name
        with tempfile.TemporaryDirectory(prefix="parse-", dir=work) as temporary:
            request = {"protocol": 1, "id": str(uuid.uuid4()), "operation": "parse", "input": {"path": str(source), "name": name, "sha256": digest(source), "size_bytes": source.stat().st_size}, "artifact_dir": temporary}
            result = invoke_worker(python, document_worker, request, work, env)
            content = result["document"]["canonical_text"]
            texts = [block for block in result["blocks"] if block["kind"] == "text"]
            images = [block for block in result["blocks"] if block["kind"] == "image"]
            for block in texts:
                require(content[block["canonical_range"]["start"]:block["canonical_range"]["end"]] == block["text"], "Unicode source range mismatch")
            for block in images:
                artifact = Path(temporary) / block["artifact_path"]
                require(artifact.resolve().is_relative_to(Path(temporary).resolve()), "Artifact escaped scratch directory")
                require(digest(artifact) == block["sha256"], "Artifact hash mismatch")
            require(sum((Path(temporary) / block["artifact_path"]).stat().st_size for block in images) == result["diagnostics"]["artifact_bytes"], "Artifact byte accounting mismatch")
            require(bool(texts or images), f"Empty successful fixture: {name}")
            if name == "unicode.txt":
                require(content == "季度收入😀\nQ1 100\n", "Unicode fixture content changed")
            if name == "scanned.pdf":
                require(not texts and any(block["provenance"]["source_type"] == "scanned_pdf" for block in images), "Scan rendering behavior changed")
            if name == "table.docx":
                require(any(block["block_type"] == "table" for block in texts) and bool(images), "DOCX table/media missing")
            if name.endswith((".xlsx", ".xls")):
                require(any(block["block_type"] == "record" for block in texts), "Spreadsheet record provenance missing")
            outputs.append({"name": name, "text_blocks": len(texts), "images": len(images), "canonical_sha256": result["document"]["canonical_sha256"]})
    ragas = invoke_worker(python, evaluation_worker, {"protocol": 1, "id": str(uuid.uuid4()), "operation": "capabilities"}, work, env)
    require(ragas["ragas_version"] == "0.4.3" and ragas["django_imported"] is False and ragas["model_transport"] == "core_rpc", "Ragas startup capability failed")
    return {"state": "verified", "platform": platform.platform(), "python": isolation, "django_import": "ModuleNotFoundError", "document_capabilities": capabilities,
            "fixtures": outputs, "ragas": ragas, "ocr": {"available": capabilities["ocr_available"], "reason": "worker_ocr_not_implemented"},
            "launch_environment": {"PATH": ["<python_directory>", "<SystemRoot>/System32"], "PYTHONUTF8": "1"},
            "paid_model_calls": 0, "system_python_required_at_runtime": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    require(sys.platform == "win32" and platform.machine().lower() in {"amd64", "x86_64"} and sys.version_info[:2] == (3, 13), "Build using Windows x64 Python 3.13")
    require(not (args.prepare_only and args.verify_only), "Choose prepare-only or verify-only")
    payload = args.payload_dir.resolve()
    work = guarded_directory(args.work_dir or Path(tempfile.mkdtemp(prefix="marlin-python-build-")), BUILD_MARKER)
    require(not payload.is_relative_to(work) and not work.is_relative_to(payload), "Payload and disposable work directory must be separate")
    if not args.verify_only:
        make_runtime(payload, work, lock_entries())
        if args.prepare_only:
            print("PYTHON_RUNTIME_DIRECTORY=" + str(payload / "python"), flush=True)
            return
        copy_workers(payload)
    report = verify(payload, work)
    output = args.report or work / "verification.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("PYTHON_RUNTIME_DIRECTORY=" + str(payload / "python"), flush=True)
    print("VERIFICATION_REPORT=" + str(output), flush=True)


if __name__ == "__main__":
    main()
