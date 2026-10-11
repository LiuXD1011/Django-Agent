"""Build the TS/Electron Windows x64 installer in disposable local staging.

Build host: native Windows x64 Python 3.13, Node >=22.22.2/npm, internet access.
From WSL, invoke Windows Python with Windows paths and a local --work-dir.
The installed application uses its bundled Node/Python; Django is not packaged.
--prepare-only builds and verifies the complete payload, without running NSIS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
import uuid
import zipfile


ROOT = Path(__file__).resolve().parents[1]
NODE_VERSION = "22.23.2"
NODE_ARCHIVE = f"node-v{NODE_VERSION}-win-x64.zip"
NODE_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/{NODE_ARCHIVE}"
# Both pins are published in https://nodejs.org/dist/v22.23.2/SHASUMS256.txt.
NODE_SHA256 = "1177b4137ba5adaa56354ae40f1080c7450e8ae09cecb47da459d1c52ac99f97"
NODE_EXE_SHA256 = "0d0f5e39f9f3d9587bc19f73eab3c2c9c4903fd02d6dbf9c853dd81b3d95fad4"
MARKER_VALUE = "marlin-electron-build-v1\n"
STAGING_NAMES = {"app", "frontend", "core-build", "core-prod", "verification-data"}
DESKTOP_FILES = ("package.json", "package-lock.json", "main.cjs", "runtime.cjs", "ipc.cjs",
                 "preload.cjs", "protocol.cjs", "langfuse.cjs", "loading.html")
APP_FILES = {name for name in DESKTOP_FILES if name != "package-lock.json"} | {"LICENSE", "icon.png"}
FRONTEND_SUFFIXES = {".html", ".ts", ".js", ".mjs", ".vue", ".css", ".json", ".webmanifest",
                     ".svg", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf"}
PRIVATE_PARTS = {".env", ".secrets", ".settings", ".git", "credentials", "secrets"}
PRIVATE_SUFFIXES = {".sqlite", ".sqlite3", ".db", ".key", ".p12", ".pfx", ".secret", ".log"}
CORE_GATE_TESTS = ("public-route-boundary.test.ts", "legacy-routes.test.ts", "channel-routes.test.ts",
                   "http.test.ts", "ipc.test.ts", "langfuse-native.test.ts")
BUILD_INPUT_FILES = ("LICENSE", "scripts/build_windows.py",
                     "scripts/bundle_windows_native.py", "scripts/test_build_windows.py",
                     "desktop/runtime.test.cjs", "desktop/langfuse-electron-test.cjs")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def reject_links(path):
    """Check parents too: a regular file inside a junction is not an allowlist."""
    path = Path(path).absolute()
    for candidate in (path, *path.parents):
        try:
            attributes = candidate.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(attributes.st_mode) and
                not getattr(attributes, "st_file_attributes", 0) & 0x400,
                f"Refusing symlink/junction in build path: {candidate}")


def copy_source(source, destination):
    source, destination = Path(source), Path(destination)
    reject_links(source)
    reject_links(destination)
    require(source.is_file(), f"Required build input missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def walk_files(directory):
    """Inspect each entry once; reject reparse points before descending.

    Every ancestor is checked at the root boundary. Repeating that same chain
    for each of 25,000 payload files needlessly slows Windows/UNC verification.
    """
    directory = Path(directory)
    reject_links(directory)
    require(directory.is_dir(), f"Required build directory missing: {directory}")
    def visit(folder):
        with os.scandir(folder) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                attributes = entry.stat(follow_symlinks=False)
                require(not stat.S_ISLNK(attributes.st_mode) and not getattr(attributes, "st_file_attributes", 0) & 0x400,
                        "Refusing symlink/junction in build inventory")
                if stat.S_ISDIR(attributes.st_mode):
                    yield from visit(Path(entry.path))
                else:
                    require(stat.S_ISREG(attributes.st_mode), "Unexpected non-regular build inventory entry")
                    yield Path(entry.path)
    yield from visit(directory)


def copy_tree(source, destination, accept=lambda path: True):
    source, destination = Path(source), Path(destination)
    reject_links(source)
    require(source.is_dir(), f"Required build directory missing: {source}")
    for path in sorted(source.rglob("*")):
        reject_links(path)
        if path.is_file() and accept(path.relative_to(source)):
            copy_source(path, destination / path.relative_to(source))


def guard_workspace(work):
    reject_links(work)
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    marker = work / ".marlin-build"
    reject_links(marker)
    require(marker.is_file() and marker.read_text(encoding="utf-8") == MARKER_VALUE or not any(work.iterdir()),
            "Use an empty --work-dir or one owned by this TS/Electron builder")
    marker.write_text(MARKER_VALUE, encoding="utf-8")
    return work


def reset_staging(work, name):
    work = Path(work).absolute()
    reject_links(work)
    require(name in STAGING_NAMES, "Unexpected disposable staging directory")
    marker = work / ".marlin-build"
    reject_links(marker)
    require(marker.is_file() and marker.read_text(encoding="utf-8") == MARKER_VALUE,
            "Not an owned TS/Electron build workspace")
    target = work / name
    reject_links(target)
    if target.exists():
        require(target.is_dir(), "Staging path is not a directory")
        shutil.rmtree(target)
    return target


def public_file(relative):
    return not any(part in PRIVATE_PARTS or part.startswith(".env.") for part in relative.parts) and relative.suffix.lower() not in PRIVATE_SUFFIXES


def source_inputs(root):
    """Hash actual build/verification inputs, including newly added source files."""
    root = Path(root)
    files = {}
    for folder in ("frontend/src", "frontend/public", "packages/core/src", "packages/core/test",
                   "workers/document", "workers/evaluation", "scripts/desktop"):
        reject_links(root / folder)
        require((root / folder).is_dir(), f"Required source directory missing: {folder}")
        for path in walk_files(root / folder):
            relative = path.relative_to(root)
            if path.is_file() and public_file(relative) and "__pycache__" not in relative.parts and path.suffix != ".pyc":
                files[relative.as_posix()] = digest(path)
    names = list(BUILD_INPUT_FILES)
    names.extend("desktop/" + name for name in DESKTOP_FILES)
    for folder, selected in (("frontend", ("package.json", "package-lock.json", "index.html", "vite.config.ts")),
                             ("packages/core", ("package.json", "package-lock.json", "tsconfig.json", "scripts/prepare-native.mjs"))):
        names.extend(folder + "/" + name for name in selected)
    for name in names:
        reject_links(root / name)
        require((root / name).is_file(), f"Required source input missing: {name}")
        files[name] = digest(root / name)
    return dict(sorted(files.items()))


def assert_source_unchanged(root, snapshot):
    require(source_inputs(root) == snapshot, "Source changed during build/verification; refresh the frozen inputs")


def payload_inventory(payload):
    payload = Path(payload)
    reject_links(payload)
    require(payload.is_dir(), "Payload inventory directory missing")
    files = {}
    for path in walk_files(payload):
        if path.is_file() and path != payload / "source-manifest.json":
            files[path.relative_to(payload).as_posix()] = digest(path)
    return files


def verify_payload_inventory(payload):
    manifest_path = Path(payload) / "source-manifest.json"
    reject_links(manifest_path)
    require(manifest_path.is_file(), "Payload inventory manifest missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(manifest.get("format") == "marlin-electron-payload-v1" and isinstance(manifest.get("files"), dict),
            "Payload inventory manifest invalid")
    require(payload_inventory(payload) == manifest["files"], "Payload inventory changed (added, deleted or modified files)")
    return manifest


def stage_build_sources(root, work):
    root, work = Path(root), Path(work)
    frontend, core, production = (reset_staging(work, name) for name in ("frontend", "core-build", "core-prod"))
    for name in ("package.json", "package-lock.json", "index.html", "vite.config.ts"):
        copy_source(root / "frontend" / name, frontend / name)
    for name in ("src", "public"):
        copy_tree(root / "frontend" / name, frontend / name,
                  lambda relative: public_file(relative) and relative.suffix.lower() in FRONTEND_SUFFIXES)
    for target in (core, production):
        for name in ("package.json", "package-lock.json", "scripts/prepare-native.mjs"):
            copy_source(root / "packages/core" / name, target / name)
    copy_source(root / "packages/core/tsconfig.json", core / "tsconfig.json")
    copy_tree(root / "packages/core/src", core / "src",
              lambda relative: public_file(relative) and relative.suffix in {".ts", ".txt", ".md"})
    copy_tree(root / "packages/core/test", core / "test", public_file)
    # Existing frontend static regression reads the new TS startup source.
    # Preserve its relative path in build staging; do not import legacy Django.
    copy_source(root / "packages/core/src/settings/startup.ts", work / "packages/core/src/settings/startup.ts")


def installed_packages(modules, prefix="node_modules"):
    for path in sorted(modules.iterdir()):
        reject_links(path)
        if path.name in {".bin", ".package-lock.json"}:
            continue
        require(path.is_dir() and not path.name.startswith("."), "Unexpected production module entry")
        if path.name.startswith("@"):
            for scoped in sorted(path.iterdir()):
                reject_links(scoped)
                require(scoped.is_dir(), "Unexpected scoped production module entry")
                yield scoped, f"{prefix}/{path.name}/{scoped.name}"
        else:
            yield path, f"{prefix}/{path.name}"


def audit_production_modules(modules, lockfile):
    modules = Path(modules)
    reject_links(modules)
    lock = json.loads(Path(lockfile).read_text(encoding="utf-8"))["packages"]
    installed = {}
    pending = [(modules, "node_modules")]
    while pending:
        directory, prefix = pending.pop()
        for package, key in installed_packages(directory, prefix):
            entry = lock.get(key)
            require(entry is not None and not entry.get("dev"), f"Unpinned/dev package in production modules: {key}")
            metadata = json.loads((package / "package.json").read_text(encoding="utf-8"))
            require(metadata.get("version") == entry.get("version"), f"Production dependency version differs from lock: {key}")
            installed[key] = metadata["version"]
            nested = package / "node_modules"
            if nested.exists():
                pending.append((nested, key + "/node_modules"))
    for key, entry in lock.items():
        if not key or entry.get("dev") or entry.get("optional"):
            continue
        require(key in installed, f"Missing required production dependency: {key}")
    return installed


def stage_application(root, app, frontend_dist, core_dist, production_modules):
    root, app = Path(root), Path(app)
    reject_links(app)
    require(not app.exists() or not any(app.iterdir()), "Application staging must be empty")
    audit_production_modules(production_modules, root / "packages/core/package-lock.json")
    metadata = json.loads((root / "desktop/package.json").read_text(encoding="utf-8"))
    require(set(metadata["build"]["files"]) == APP_FILES, "Desktop build.files must use the explicit application allowlist")
    require(metadata["build"]["extraResources"] == [{"from": "payload", "to": "runtime", "filter": ["**/*", "!**/__pycache__/**", "!**/*.pyc"]}],
            "Unexpected Electron extraResources; payload must be the only runtime resource")
    require((Path(frontend_dist) / "index.html").is_file() and
            (Path(core_dist) / "index.js").is_file() and
            (Path(core_dist) / "tools/desktop-process.js").is_file(), "Fresh frontend/core build outputs are incomplete")
    for name in DESKTOP_FILES:
        copy_source(root / "desktop" / name, app / name)
    copy_source(root / "LICENSE", app / "LICENSE")
    copy_source(root / "frontend/public/icons/icon-512.png", app / "icon.png")
    payload = app / "payload"
    copy_source(root / "LICENSE", payload / "LICENSE")
    copy_tree(frontend_dist, payload / "frontend", lambda relative: public_file(relative) and relative.suffix.lower() in FRONTEND_SUFFIXES)
    copy_tree(core_dist, payload / "core/dist", lambda relative: public_file(relative) and relative.suffix == ".js")
    copy_source(root / "packages/core/src/evaluation/LICENSE-MT19937.txt", payload / "core/dist/evaluation/LICENSE-MT19937.txt")
    for name in ("package.json", "package-lock.json"):
        copy_source(root / "packages/core" / name, payload / "core" / name)
    # Only npm ci --omit=dev output is copied, never repository node_modules.
    copy_tree(production_modules, payload / "core/node_modules")


def download_node(cache):
    cache = Path(cache)
    reject_links(cache)
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / NODE_ARCHIVE
    reject_links(archive)
    if not archive.exists():
        temporary = cache / f"{NODE_ARCHIVE}.{uuid.uuid4().hex}.download"
        try:
            urllib.request.urlretrieve(NODE_URL, temporary)
            require(digest(temporary) == NODE_SHA256, "Official Node archive SHA256 mismatch")
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    require(digest(archive) == NODE_SHA256, "Cached Node archive SHA256 mismatch")
    return archive


def stage_node(archive, target):
    archive, target = Path(archive), Path(target)
    reject_links(archive)
    reject_links(target)
    require(digest(archive) == NODE_SHA256, "Official Node archive SHA256 mismatch")
    require(not target.exists(), "Node staging directory must be fresh")
    prefix = f"node-v{NODE_VERSION}-win-x64/"
    with zipfile.ZipFile(archive) as bundle:
        names = set()
        for member in bundle.infolist():
            path = PurePosixPath(member.filename)
            require(member.orig_filename == member.filename and not path.is_absolute() and ".." not in path.parts and ":" not in member.filename and "\\" not in member.orig_filename and
                    not stat.S_ISLNK(member.external_attr >> 16) and member.filename.casefold() not in names,
                    "Unsafe official Node archive entry")
            names.add(member.filename.casefold())
        binary, license_text = bundle.read(prefix + "node.exe"), bundle.read(prefix + "LICENSE")
    require(hashlib.sha256(binary).hexdigest() == NODE_EXE_SHA256, "Official Node executable SHA256 mismatch")
    require(binary.startswith(b"MZ") and bool(license_text), "Official Node executable/license missing")
    target.mkdir(parents=True)
    (target / "node.exe").write_bytes(binary)
    (target / "LICENSE").write_bytes(license_text)
    manifest = {"version": NODE_VERSION, "platform": "win32-x64", "url": NODE_URL,
                "archive_sha256": NODE_SHA256, "node_exe_sha256": NODE_EXE_SHA256,
                "license_sha256": hashlib.sha256(license_text).hexdigest()}
    (target / "runtime-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def build_environment(node, work, source=None):
    source = os.environ if source is None else source
    allowed = {"systemroot", "windir", "systemdrive", "comspec", "pathext", "temp", "tmp", "userprofile", "localappdata", "appdata"}
    env = {key: value for key, value in source.items() if key.lower() in allowed}
    system = next((value for key, value in source.items() if key.lower() == "systemroot"), None)
    require(bool(system), "SystemRoot is required on the Windows build host")
    # electron-builder's Windows npm collector launches PowerShell directly.
    # Add only its standard OS directory, never the developer's ambient PATH.
    paths = [Path(node).parent, Path(system) / "System32", Path(system) / "System32/WindowsPowerShell/v1.0"]
    env.update(PATH=os.pathsep.join(map(str, paths)),
               PYTHONUTF8="1", PYTHONIOENCODING="utf-8", RAGAS_DO_NOT_TRACK="true",
               HF_HUB_DISABLE_TELEMETRY="1", DO_NOT_TRACK="1",
               NPM_CONFIG_USERCONFIG=str(Path(work) / "empty.npmrc"),
               NPM_CONFIG_GLOBALCONFIG=str(Path(work) / "empty-global.npmrc"),
               NPM_CONFIG_REGISTRY="https://registry.npmjs.org/", CSC_IDENTITY_AUTO_DISCOVERY="false",
               PLAYWRIGHT_BROWSERS_PATH=str(Path(work) / "playwright-browsers"))
    return env


def python_runtime_command(python, work, root=ROOT):
    work = Path(work)
    return [str(python), str(Path(root) / "scripts/desktop/build-python-runtime.py"),
            "--payload-dir", str(work / "app/payload"), "--work-dir", str(work / "python-work"),
            "--report", str(work / "python-verification.json")]


def build_node_version(node, work):
    version = subprocess.check_output([str(node), "--version"], text=True,
                                      env=build_environment(node, work), timeout=15).strip()
    require(re.fullmatch(r"v\d+\.\d+\.\d+", version), "Build-host Node version is invalid")
    number = tuple(map(int, version[1:].split(".")))
    require(number[0] == 22 and number >= (22, 22, 2) or number[0] == 24 and number >= (24, 15, 0) or number[0] >= 26,
            "Build-host Node must satisfy ^22.22.2 || ^24.15.0 || >=26; recommended official Node 22.23.2")
    return version


def write_manifest(root, payload, source_snapshot=None):
    root, payload = Path(root), Path(payload)
    inputs = ("desktop/package-lock.json", "packages/core/package-lock.json", "frontend/package-lock.json",
              "scripts/desktop/python-runtime-lock-windows-x64.txt", "scripts/desktop/python-runtime-lock-native.txt")
    files = payload_inventory(payload)
    versions = {name: json.loads((root / folder / "package.json").read_text(encoding="utf-8"))["version"]
                for name, folder in (("desktop", "desktop"), ("core", "packages/core"), ("frontend", "frontend"))}
    manifest = {"format": "marlin-electron-payload-v1", "platform": "win32-x64", "versions": versions,
                "node_version": NODE_VERSION, "node_archive_sha256": NODE_SHA256,
                "input_sha256": {name: digest(root / name) for name in inputs}, "files": files,
                "system_node_required_at_runtime": False, "system_python_required_at_runtime": False,
                "django_packaged": False}
    if source_snapshot is not None:
        manifest["source_sha256"] = source_snapshot
    (payload / "source-manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def run(command, cwd, env=None, timeout=None):
    values = [str(value) for value in command]
    print("RUN", subprocess.list2cmdline(values), flush=True)
    return subprocess.run(values, cwd=cwd, env=env, check=True, timeout=timeout)


def prepare_electron_shell(app, node, env):
    # Electron 44 publishes this installer as a bin without a postinstall hook.
    # Its fixed checksums.json verifies both cached and newly downloaded ZIPs;
    # build_environment excludes mirror, override and checksum-disable options.
    app = Path(app)
    installer = app / "node_modules/electron/install.js"
    reject_links(installer)
    require(installer.is_file(), "Official Electron installer missing")
    run([node, installer], app, env, timeout=300)
    require((app / "node_modules/electron/dist/electron.exe").is_file(), "Prepared Electron shell missing")


def desktop_inventory(app):
    return {name: digest(Path(app) / name) for name in sorted(APP_FILES)}


def electron_distribution(app):
    app = Path(app)
    module = app / "node_modules/electron"
    for name in ("package.json", "path.txt", "dist/version", "dist/electron.exe"):
        reject_links(module / name)
        require((module / name).is_file(), "Prepared Electron distribution is incomplete")
    expected = json.loads((app / "package.json").read_text(encoding="utf-8"))["devDependencies"]["electron"]
    version = json.loads((module / "package.json").read_text(encoding="utf-8"))["version"]
    require(version == expected and (module / "dist/version").read_text(encoding="utf-8").removeprefix("v") == expected and
            (module / "path.txt").read_text(encoding="utf-8") == "electron.exe", "Prepared Electron distribution version/path differs")
    return {"format": "marlin-electron-distribution-v1", "version": version,
            "package_sha256": digest(module / "package.json"), "path_sha256": digest(module / "path.txt"),
            "files": {path.relative_to(module / "dist").as_posix(): digest(path) for path in walk_files(module / "dist")}}


def validate_gate_report(gates, app, snapshot):
    app = Path(app); payload = app / "payload"
    require(isinstance(gates, dict) and gates.get("format") == "marlin-windows-build-gates-v1" and gates.get("state") == "verified" and
            gates.get("scope") == "frozen_source" and gates.get("source_before_after_equal") is True and gates.get("paid_model_calls") == 0,
            "Windows native gates schema/state/scope invalid")
    for name, minimum in (("core_tests", 24), ("runtime_tests", 6)):
        result = gates.get(name, {})
        require(isinstance(result, dict) and all(type(result.get(key)) is int for key in ("tests", "passed", "failed", "skipped")) and
                result["tests"] == result["passed"] and result["passed"] >= minimum and result["failed"] == result["skipped"] == 0,
                "Windows gates did not execute their required real suites")
        duration = result.get("duration_ms")
        require(type(duration) in {int, float} and math.isfinite(duration) and duration >= 0, "Windows gate duration is invalid")
    distribution = electron_distribution(app)
    window = gates.get("langfuse", {})
    fields = ("real_nextauth_protocol", "actual_private_child_json", "renderer_cookie_secret_absent", "isolated_memory_session",
              "httponly_host_only_lax", "sandbox_no_preload_node", "popups_denied", "owned_cookie_clear",
              "unrelated_browser_cookie_preserved", "public_cancel_no_window", "public_cancel_pending_navigation",
              "public_logout_clears_window", "public_configuration_change_clears_window")
    require(isinstance(window, dict) and window.get("format") == "marlin-langfuse-native-test-v1" and window.get("state") == "verified" and
            window.get("platform") == "win32" and window.get("electron") == distribution["version"] and window.get("paid_model_calls") == 0 and
            window.get("owned_core_exit_code") == 0 and window.get("foreign_project_requests") == 0 and all(window.get(name) is True for name in fields),
            "Controlled Electron gate facts invalid")
    require(gates.get("source_sha256") == snapshot and gates.get("desktop_sha256") == desktop_inventory(app) and
            gates.get("electron_distribution") == distribution and gates.get("core_entry_sha256") == digest(payload / "core/dist/tools/desktop-process.js") and
            gates.get("frontend_index_sha256") == digest(payload / "frontend/index.html"), "Windows gates used different source/distribution/outputs")
    require(all(gates.get(name) is False for name in ("manual_gui_verified", "real_external_vendor_verified", "installer_executed")),
            "Windows gate scope incorrectly claims GUI/vendor/installer validation")
    work = app.parent
    def report(name, sha_field):
        path = work / name; reject_links(path)
        require(path.is_file() and digest(path) == gates.get(sha_field), "Windows gate referenced report bytes differ")
        value = json.loads(path.read_text(encoding="utf-8"))
        require(isinstance(value, dict), "Windows gate referenced report invalid")
        return value
    actual_window = report("controlled-gates/langfuse-native.json", "langfuse_report_sha256")
    require(actual_window == window, "Electron gate referenced facts differ")
    native = report("core-verification.json", "native_report_sha256")
    database, ipc = native.get("native", {}), native.get("ipc", {})
    native_id = database.get("fts_id") if isinstance(database, dict) else None
    require(native == gates.get("native") and native.get("format") == "marlin-core-payload-verification-v1" and native.get("state") == "verified" and
            native.get("paid_model_calls") == 0 and native.get("gui_verified") is False and native.get("installer_verified") is False and
            isinstance(database, dict) and database.get("node_version") == "v" + NODE_VERSION and database.get("platform") == "win32" and
            database.get("arch") == "x64" and database.get("vector_version") == "v0.1.9" and database.get("paid_model_calls") == 0 and
            isinstance(native_id, str) and re.fullmatch(r"[1-9][0-9]*", native_id) and database.get("vector_id") == native_id and int(native_id) > 2**53 and
            isinstance(ipc, dict) and ipc.get("protocol") == 1 and ipc.get("runtime") == "typescript" and ipc.get("http_listener") is False and
            ipc.get("capabilities_status") == 200 and ipc.get("setup_required") is True and ipc.get("exit_code") == 0 and ipc.get("paid_model_calls") == 0,
            "Native SQLite/FTS/vector/IPC gate facts invalid")
    python = report("python-verification.json", "python_report_sha256")
    runtime = python.get("python", {}); ragas = python.get("ragas", {}); fixtures = python.get("fixtures", [])
    require(python.get("state") == "verified" and python.get("paid_model_calls") == 0 and python.get("system_python_required_at_runtime") is False and
            python.get("django_import") == "ModuleNotFoundError" and isinstance(runtime, dict) and
            isinstance(runtime.get("version"), str) and runtime["version"].startswith("3.13.16 ") and
            runtime.get("isolated") == 1 and runtime.get("no_site") == 1 and runtime.get("django_spec") is False and
            isinstance(ragas, dict) and ragas.get("ragas_version") == "0.4.3" and ragas.get("django_imported") is False and ragas.get("model_transport") == "core_rpc" and
            isinstance(fixtures, list) and len(fixtures) >= 11 and len(fixtures) == gates.get("python_fixture_count") and
            all(isinstance(row, dict) and isinstance(row.get("name"), str) and isinstance(row.get("canonical_sha256"), str) and
                re.fullmatch(r"[a-f0-9]{64}", row["canonical_sha256"]) for row in fixtures) and len({row["name"] for row in fixtures}) == len(fixtures),
            "Python/document/Ragas/isolation gate facts invalid")
    def dependencies(rows):
        require(isinstance(rows, list) and rows and all(isinstance(row, dict) and isinstance(row.get("name"), str) and
                isinstance(row.get("version"), str) for row in rows), "Python gate dependencies invalid")
        result = {re.sub(r"[-_.]+", "-", row["name"]).lower(): row["version"] for row in rows}
        require(len(result) == len(rows), "Python gate dependencies duplicated")
        return result
    python_manifest = json.loads((payload / "python/runtime-manifest.json").read_text(encoding="utf-8"))
    input_manifest = json.loads((payload / "source-manifest.json").read_text(encoding="utf-8"))
    pins = python_manifest.get("inputs", {})
    require(python_manifest.get("format") == "marlin-python-runtime-v1" and python_manifest.get("platform") == "win_amd64" and
            pins.get("python_version") == "3.13.16" and pins.get("dependency_lock_sha256") == input_manifest["input_sha256"].get("scripts/desktop/python-runtime-lock-windows-x64.txt") and
            pins.get("native_lock_sha256") == input_manifest["input_sha256"].get("scripts/desktop/python-runtime-lock-native.txt") and
            dependencies(runtime.get("dependencies")) == dependencies(python_manifest.get("dependencies")), "Python gate dependencies/pins differ")
    return distribution


def run_windows_gates(root, work, node, snapshot):
    root, work = Path(root), Path(work)
    payload = work / "app/payload"
    report = work / "windows-gates.json"
    reject_links(report)
    report.unlink(missing_ok=True)
    run([sys.executable, "-I", root / "scripts/desktop/windows-gates.py", "--source", root,
         "--work-dir", work, "--build-node", node, "--report", report], work,
        build_environment(node, work), timeout=1200)
    require(report.is_file(), "Windows gates did not produce a result")
    gates = json.loads(report.read_text(encoding="utf-8"))
    distribution = validate_gate_report(gates, work / "app", snapshot)
    assert_source_unchanged(root, snapshot)
    verify_payload_inventory(payload)
    prepared = {"format": "marlin-prepared-windows-build-v1", "state": "verified", "source_sha256": snapshot,
                "payload_manifest_sha256": digest(payload / "source-manifest.json"),
                "desktop_sha256": desktop_inventory(work / "app"), "gates_sha256": digest(report), "electron_distribution": distribution}
    path = work / "prepared-build.json"
    reject_links(path)
    path.write_text(json.dumps(prepared, indent=2) + "\n", encoding="utf-8")
    return gates


def verify_prepared(root, work):
    root, work = Path(root), Path(work)
    marker = work / ".marlin-build"
    reject_links(marker)
    require(marker.is_file() and marker.read_text(encoding="utf-8") == MARKER_VALUE, "Not an owned prepared build")
    path = work / "prepared-build.json"
    reject_links(path)
    require(path.is_file(), "A fresh repository prepare/verification is required; old evidence cannot authorize packaging")
    prepared = json.loads(path.read_text(encoding="utf-8"))
    require(prepared.get("format") == "marlin-prepared-windows-build-v1" and prepared.get("state") == "verified",
            "Prepared build state is invalid")
    assert_source_unchanged(root, prepared.get("source_sha256"))
    payload = work / "app/payload"
    manifest = verify_payload_inventory(payload)
    require(manifest.get("source_sha256") == prepared["source_sha256"] and
            digest(payload / "source-manifest.json") == prepared.get("payload_manifest_sha256") and
            desktop_inventory(work / "app") == prepared.get("desktop_sha256") and
            digest(work / "windows-gates.json") == prepared.get("gates_sha256"), "Prepared build inventory/report changed")
    require(digest(payload / "node/node.exe") == NODE_EXE_SHA256, "Bundled Node binary changed")
    gates = json.loads((work / "windows-gates.json").read_text(encoding="utf-8"))
    distribution = validate_gate_report(gates, work / "app", prepared["source_sha256"])
    require(prepared.get("electron_distribution") == distribution, "Prepared Electron distribution inventory changed")
    audit_production_modules(payload / "core/node_modules", root / "packages/core/package-lock.json")
    return prepared


def verify_reusable(root, work):
    """Reuse dependencies only, after checking all bytes and both worker sets."""
    root, work = Path(root), Path(work)
    marker = work / ".marlin-build"
    reject_links(marker)
    require(marker.is_file() and marker.read_text(encoding="utf-8") == MARKER_VALUE, "Not an owned refresh workspace")
    payload = work / "app/payload"
    manifest = verify_payload_inventory(payload)
    require(manifest.get("node_version") == NODE_VERSION and manifest.get("node_archive_sha256") == NODE_SHA256 and
            digest(payload / "node/node.exe") == NODE_EXE_SHA256, "Bundled Node pin differs; rebuild clean")
    for name, before in manifest.get("input_sha256", {}).items():
        require(digest(root / name) == before, "Dependency lock changed; rebuild clean")
    expected_locks = {"desktop/package-lock.json", "packages/core/package-lock.json", "frontend/package-lock.json",
                      "scripts/desktop/python-runtime-lock-windows-x64.txt", "scripts/desktop/python-runtime-lock-native.txt"}
    require(set(manifest.get("input_sha256", {})) == expected_locks, "Dependency lock inventory invalid")
    for folder, source in (("frontend", "frontend"), ("core-build", "packages/core"), ("core-prod", "packages/core"),
                           ("app", "desktop"), ("app/payload/core", "packages/core")):
        reject_links(work / folder / "package-lock.json")
        require(digest(work / folder / "package-lock.json") == digest(root / source / "package-lock.json"),
                "Staged dependency lock differs; rebuild clean")
    for name in ("python-runtime-lock-windows-x64.txt", "python-runtime-lock-native.txt"):
        require(digest(payload / "python" / name) == digest(root / "scripts/desktop" / name), "Python lock differs; rebuild clean")
    for group in ("document", "evaluation"):
        source = root / "workers" / group
        installed = payload / "workers" / group
        actual = {}
        for path in walk_files(source):
            relative = path.relative_to(source)
            if "__pycache__" in relative.parts or "tests" in relative.parts or path.name.startswith("test_") or path.name == ".gitattributes":
                continue
            if path.is_file() and path.suffix != ".pyc":
                actual[relative.as_posix()] = digest(path)
        recorded = json.loads((installed / "source-manifest.json").read_text(encoding="utf-8"))
        require(isinstance(recorded, list) and len({row["path"] for row in recorded}) == len(recorded) and
                actual == {row["path"]: row["sha256"] for row in recorded}, "Worker source set changed; rebuild clean")
        require(all(digest(installed / name) == sha for name, sha in actual.items()), "Worker payload bytes changed")
    audit_production_modules(payload / "core/node_modules", root / "packages/core/package-lock.json")
    return manifest


def clear_refresh(work, relative):
    allowed = {"frontend/src", "frontend/public", "frontend/dist", "core-build/src", "core-build/test", "core-build/dist",
               "app/payload/frontend", "app/payload/core/dist"}
    require(relative in allowed, "Unexpected refresh directory")
    marker = Path(work) / ".marlin-build"
    reject_links(marker)
    require(marker.is_file() and marker.read_text(encoding="utf-8") == MARKER_VALUE, "Not an owned refresh workspace")
    target = Path(work) / relative
    reject_links(target)
    if target.exists():
        require(target.is_dir(), "Refresh path is not a directory")
        shutil.rmtree(target)


def refresh_windows(root, work, node, npm, output, prepare_only=False):
    root, work, node, npm = map(Path, (root, work, node, npm))
    verify_reusable(root, work)
    snapshot = source_inputs(root)
    env = build_environment(node, work)
    for name in ("prepared-build.json", "windows-gates.json"):
        reject_links(work / name)
        (work / name).unlink(missing_ok=True)
    for name in ("frontend/src", "frontend/public", "frontend/dist", "core-build/src", "core-build/test", "core-build/dist"):
        clear_refresh(work, name)
    frontend, core, app = work / "frontend", work / "core-build", work / "app"
    for name in ("package.json", "package-lock.json", "index.html", "vite.config.ts"):
        copy_source(root / "frontend" / name, frontend / name)
    for name in ("src", "public"):
        copy_tree(root / "frontend" / name, frontend / name, lambda relative: public_file(relative) and relative.suffix.lower() in FRONTEND_SUFFIXES)
    for name in ("package.json", "package-lock.json", "tsconfig.json", "scripts/prepare-native.mjs"):
        copy_source(root / "packages/core" / name, core / name)
    copy_tree(root / "packages/core/src", core / "src", lambda relative: public_file(relative) and relative.suffix in {".ts", ".txt", ".md"})
    copy_tree(root / "packages/core/test", core / "test", public_file)
    copy_source(root / "packages/core/src/settings/startup.ts", work / "packages/core/src/settings/startup.ts")
    run([node, frontend / "node_modules/playwright/cli.js", "install", "chromium", "--only-shell"], frontend, env, timeout=300)
    run([node, npm, "run", "test:unit"], frontend, dict(env, NODE_OPTIONS="--experimental-strip-types"))
    run([node, npm, "run", "build"], frontend, env)
    run([node, npm, "run", "build"], core, env)
    for name in ("app/payload/frontend", "app/payload/core/dist"):
        clear_refresh(work, name)
    payload = app / "payload"
    copy_tree(frontend / "dist", payload / "frontend", lambda relative: public_file(relative) and relative.suffix.lower() in FRONTEND_SUFFIXES)
    copy_tree(core / "dist", payload / "core/dist", lambda relative: public_file(relative) and relative.suffix == ".js")
    copy_source(root / "packages/core/src/evaluation/LICENSE-MT19937.txt", payload / "core/dist/evaluation/LICENSE-MT19937.txt")
    for name in ("package.json", "package-lock.json"):
        copy_source(root / "packages/core" / name, payload / "core" / name)
    for name in DESKTOP_FILES:
        copy_source(root / "desktop" / name, app / name)
    copy_source(root / "LICENSE", app / "LICENSE")
    copy_source(root / "LICENSE", payload / "LICENSE")
    copy_source(root / "frontend/public/icons/icon-512.png", app / "icon.png")
    prepare_electron_shell(app, node, env)
    assert_source_unchanged(root, snapshot)
    write_manifest(root, payload, snapshot)
    run_windows_gates(root, work, node, snapshot)
    return payload if prepare_only else package_windows(root, work, node, output)


def package_windows(root, work, node, output):
    root, work, node, output = map(Path, (root, work, node, output))
    prepared = verify_prepared(root, work)
    app, payload = work / "app", work / "app/payload"
    env = build_environment(node, work)
    run([node, app / "node_modules/electron-builder/cli.js", "--win", "nsis", "--x64", "--publish", "never"], app, env)
    # Check again AFTER NSIS, before publishing even a local output artifact.
    assert_source_unchanged(root, prepared["source_sha256"])
    verify_prepared(root, work)
    audit = work / "asar-audit.json"
    reject_links(audit)
    audit.unlink(missing_ok=True)
    run([node, root / "scripts/desktop/audit-asar.cjs", "--app", app, "--report", audit], work, env, timeout=180)
    require(audit.is_file() and json.loads(audit.read_text(encoding="utf-8")).get("state") == "verified", "ASAR/runtime audit failed")
    assert_source_unchanged(root, prepared["source_sha256"])
    verify_prepared(root, work)
    metadata = json.loads((app / "package.json").read_text(encoding="utf-8"))
    name = metadata["build"]["win"]["artifactName"].replace("${version}", metadata["version"]).replace("${arch}", "x64").replace("${ext}", "exe")
    require(Path(name).name == name and name.endswith(".exe"), "Unexpected installer artifact name")
    installer = app / metadata["build"]["directories"]["output"] / name
    require(installer.is_file(), "NSIS did not produce the configured installer")
    reject_links(output)
    output.mkdir(parents=True, exist_ok=True)
    copy_source(installer, output / name)
    reject_links(output / (name + ".sha256"))
    (output / (name + ".sha256")).write_text(f"{digest(installer)}  {name}\n", encoding="utf-8")
    for source in (payload / "source-manifest.json", work / "core-verification.json", work / "python-verification.json",
                   work / "windows-gates.json", work / "prepared-build.json", work / "controlled-gates/langfuse-native.json", audit):
        copy_source(source, output / f"{Path(name).stem}-{source.name}")
    print(f"INSTALLER_DIRECTORY={output}", flush=True)
    return output / name


def build_windows(root, work, node, npm, node_cache, output, prepare_only=False):
    root, work, node, npm, output = map(Path, (root, work, node, npm, output))
    env = build_environment(node, work)
    for name in ("empty.npmrc", "empty-global.npmrc"):
        reject_links(work / name)
        (work / name).write_text("", encoding="utf-8")
    inputs_before = source_inputs(root)
    stage_build_sources(root, work)
    frontend, core, production = (work / name for name in ("frontend", "core-build", "core-prod"))
    ci = [node, npm, "ci", "--no-audit", "--no-fund"]
    run(ci, frontend, env)
    # The existing unit suite includes real keyboard/filechooser browser tests.
    # Download only the locked Chromium headless shell into build-only cache.
    reject_links(work / "playwright-browsers")
    run([node, frontend / "node_modules/playwright/cli.js", "install", "chromium", "--only-shell"], frontend, env, timeout=300)
    # Existing frontend tests import TS directly. Set the capability explicitly
    # rather than forwarding ambient developer NODE_OPTIONS.
    run([node, npm, "run", "test:unit"], frontend,
        dict(env, NODE_OPTIONS="--experimental-strip-types"))
    run([node, npm, "run", "build"], frontend, env)
    # npm10's lock-derived metadata omits better-sqlite3's gypfile:false and
    # incorrectly runs node-gyp despite its published Windows N-API binary.
    # The pinned core has no dependency install hooks needed by tsc/runtime;
    # its own SQLite postinstall is executed explicitly in both clean trees.
    # Frontend esbuild and Electron keep their ordinary install hooks.
    run([*ci, "--ignore-scripts"], core, env)
    run([node, core / "scripts/prepare-native.mjs"], core, env)
    run([node, npm, "run", "build"], core, env)
    run([*ci, "--omit=dev", "--ignore-scripts"], production, env)
    run([node, production / "scripts/prepare-native.mjs"], production, env)
    app = reset_staging(work, "app")
    stage_application(root, app, frontend / "dist", core / "dist", production / "node_modules")
    payload = app / "payload"
    stage_node(download_node(node_cache), payload / "node")
    run(python_runtime_command(sys.executable, work, root), work, env)
    # Warm both maintained OpenAI tokenizer vocabularies during the build, so
    # installed helpers need no first-use tokenizer download. No model call.
    python_env = dict(env, PATH=str(payload / "python") + os.pathsep + str(Path(env.get("SystemRoot", env.get("SYSTEMROOT", "C:/Windows"))) / "System32"),
                      TIKTOKEN_CACHE_DIR=str(payload / "tokenizer-cache"))
    run([payload / "python/python.exe", "-B", "-c", "import tiktoken; tiktoken.get_encoding('cl100k_base'); tiktoken.get_encoding('o200k_base'); print('TOKENIZER_CACHE_OK')"], work, python_env, timeout=180)
    checks = reset_staging(work, "verification-data")
    checks.mkdir()
    run([payload / "node/node.exe", root / "scripts/desktop/verify-payload.cjs", "--app", app, "--data-root", checks,
         "--report", work / "core-verification.json"], work, env, timeout=120)
    reset_staging(work, "verification-data")
    audit_production_modules(payload / "core/node_modules", root / "packages/core/package-lock.json")
    write_manifest(root, payload, inputs_before)
    assert_source_unchanged(root, inputs_before)
    run(ci, app, env)
    prepare_electron_shell(app, node, env)
    run_windows_gates(root, work, node, inputs_before)
    print(f"PAYLOAD_DIRECTORY={payload}", flush=True)
    print(f"CORE_VERIFICATION_REPORT={work / 'core-verification.json'}", flush=True)
    if prepare_only:
        return payload
    return package_windows(root, work, node, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--work-dir", type=Path, help="empty or builder-owned local Windows directory (not a UNC share)")
    parser.add_argument("--prepare-only", action="store_true", help="build and verify the full payload; skip NSIS")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--refresh", action="store_true", help="rebuild frozen source using verified unchanged dependencies")
    modes.add_argument("--verify-only", action="store_true", help="rerun native gates for this exact previously prepared source")
    modes.add_argument("--package-only", action="store_true", help="package only this exact previously verified source; recheck after NSIS")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist/windows")
    parser.add_argument("--node-cache", type=Path, help="cache containing the SHA-pinned official Node ZIP")
    parser.add_argument("--build-node", type=Path, help="installed build-host node.exe with npm alongside it")
    args = parser.parse_args()
    require(not (args.prepare_only and (args.verify_only or args.package_only)), "prepare-only cannot be combined with verify-only/package-only")
    require(sys.platform == "win32" and platform.machine().lower() in {"amd64", "x86_64"} and sys.maxsize > 2**32 and sys.version_info[:2] == (3, 13),
            "Build using native Windows x64 Python 3.13. From WSL invoke Windows Python and use a local Windows --work-dir.")
    raw_work = args.work_dir or Path(tempfile.mkdtemp(prefix="marlin-windows-ts-"))
    require(not str(raw_work).startswith("\\\\"), "npm/NSIS staging must be a local Windows directory, not UNC")
    work = guard_workspace(raw_work)
    require(not any(work.is_relative_to(ROOT / name) for name in ("frontend", "packages", "desktop", "scripts", "workers")), "Build staging cannot be inside application source directories")
    node_value = args.build_node or shutil.which("node")
    require(bool(node_value), "Installed Node/npm is required on the build host")
    node = Path(node_value).resolve()
    npm = node.parent / "node_modules/npm/bin/npm-cli.js"
    require(node.is_file() and npm.is_file(), "npm-cli.js must be installed alongside the selected build-host Node")
    build_version = build_node_version(node, work)
    node_cache = args.node_cache or work / "node-cache"
    require(not any(node_cache.resolve().is_relative_to(work / name) for name in STAGING_NAMES), "Node cache cannot be inside disposable staging")
    print(f"BUILD_WORK_DIR={work}", flush=True)
    print(f"BUILD_NODE_VERSION={build_version}; PRODUCT_NODE_VERSION={NODE_VERSION}", flush=True)
    if args.package_only:
        package_windows(ROOT, work, node, args.output_dir)
    elif args.verify_only:
        prepared = verify_prepared(ROOT, work)
        run_windows_gates(ROOT, work, node, prepared["source_sha256"])
    elif args.refresh:
        refresh_windows(ROOT, work, node, npm, args.output_dir, args.prepare_only)
    else:
        build_windows(ROOT, work, node, npm, node_cache, args.output_dir, args.prepare_only)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(f"BUILD_ERROR={error}", file=sys.stderr)
        raise SystemExit(1)
