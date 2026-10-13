"""Windows packaging regressions using only disposable synthetic inputs."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile
from contextlib import redirect_stdout

from scripts import build_windows as build


def put(root, name, content="fixture"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class PackageTests(unittest.TestCase):
    # WIN-ASAR-BOOTSTRAP-001: an archive member cannot bootstrap external Node.
    def test_physical_bootstrap_is_mandatory_and_bound_to_source_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root, work = self.reuse_fixture(Path(directory))
            payload = work / 'app/payload'
            bootstrap = payload / 'owned-runtime/runtime-bootstrap.cjs'
            build.copy_source(root / 'desktop/runtime-bootstrap.cjs', bootstrap)
            build.write_manifest(root, payload, build.source_inputs(root))
            build.verify_payload_inventory(payload)
            bootstrap.unlink()
            manifest = json.loads((payload / 'source-manifest.json').read_text())
            manifest['files'].pop('owned-runtime/runtime-bootstrap.cjs')
            put(payload, 'source-manifest.json', json.dumps(manifest))
            with self.assertRaisesRegex(RuntimeError, 'bootstrap'):
                build.verify_payload_inventory(payload)
            put(payload, 'owned-runtime/runtime-bootstrap.cjs', 'rehashed wrong bootstrap')
            manifest['files']['owned-runtime/runtime-bootstrap.cjs'] = build.digest(bootstrap)
            put(payload, 'source-manifest.json', json.dumps(manifest))
            with self.assertRaisesRegex(RuntimeError, 'bootstrap'):
                build.verify_payload_inventory(payload)

    def test_packaged_bootstrap_regression_is_an_explicit_frozen_desktop_gate(self):
        self.assertIn('packaged-bootstrap.test.cjs', getattr(build, 'DESKTOP_GATE_FILES', ()))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.fixture(root)
            put(root, 'desktop/packaged-bootstrap.test.cjs', 'regression')
            self.assertEqual(build.source_inputs(root).get('desktop/packaged-bootstrap.test.cjs'),
                             build.digest(root / 'desktop/packaged-bootstrap.test.cjs'))

    # WIN-ASAR-BOOTSTRAP-001: the target gate must reject Node/RunAsNode before any Core starts.
    def test_packaged_runtime_gate_refuses_ordinary_node_execution(self):
        helper = build.ROOT / 'scripts/desktop/verify-packaged-runtime.cjs'
        self.assertTrue(helper.is_file(), 'Actual packaged Electron gate is required')
        completed = subprocess.run([self.native_node(), str(helper)], capture_output=True, text=True, timeout=10)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn('official Electron main', completed.stderr)

    def test_packaged_bootstrap_fixture_preserves_assertions_and_refuses_path_drift(self):
        original = (build.ROOT / 'desktop/packaged-bootstrap.test.cjs').read_text()
        adapt = getattr(self.gates(), 'packaged_bootstrap_fixture', None)
        self.assertTrue(callable(adapt), 'Official target gate must execute the new packed regression')
        adapted = adapt(original)
        self.assertEqual(adapted.count('assert.'), original.count('assert.'))
        self.assertEqual(adapted.count('test('), original.count('test('))
        self.assertIn("require('./app/owned-runtime.cjs')", adapted)
        with self.assertRaisesRegex(RuntimeError, 'fixture'):
            adapt(original.replace("require('@electron/asar')", "require('other')"))

    def packaged_report(self, root, work):
        app = work / 'app'
        resources = app / 'release/win-unpacked/resources'
        if not resources.exists():
            shutil.copytree(app / 'payload', resources / 'runtime')
        put(resources, 'app.asar', 'synthetic archive projection; not an actual ASAR gate')
        payload = resources / 'runtime'
        manifest = json.loads((payload / 'source-manifest.json').read_text())
        audit = {'state': 'verified', 'asar_sha256': build.digest(resources / 'app.asar'),
                 'asset_sha256': {'runtime.cjs': build.digest(app / 'runtime.cjs')},
                 'physical_bootstrap_sha256': build.digest(app / 'runtime-bootstrap.cjs'),
                 'runtime_manifest_sha256': build.digest(payload / 'source-manifest.json')}
        put(work, 'asar-audit.json', json.dumps(audit))
        return {'format': 'marlin-packaged-runtime-verification-v1', 'state': 'verified', 'scope': 'actual_asar',
                'platform': 'win32', 'arch': 'x64', 'electron': '44.7.0',
                'electron_executable': str(app / 'node_modules/electron/dist/electron.exe'),
                'electron_executable_sha256': build.digest(app / 'node_modules/electron/dist/electron.exe'),
                'asar_path': str(resources / 'app.asar'), 'runtime_path': str(resources / 'app.asar/runtime.cjs'),
                'payload_root': str(payload), 'asar_sha256': audit['asar_sha256'], 'runtime_sha256': audit['asset_sha256']['runtime.cjs'],
                'bootstrap_sha256': audit['physical_bootstrap_sha256'], 'physical_bootstrap_matches_asar': True,
                'native_addon_sha256': build.digest(payload / 'owned-runtime/runtime-job.node'),
                'core_entry_sha256': build.digest(payload / 'core/dist/tools/desktop-process.js'),
                'node_sha256': build.digest(payload / 'node/node.exe'), 'node_version': 'v22.23.2',
                'source_sha256': manifest['source_sha256'], 'payload_manifest_sha256': build.digest(payload / 'source-manifest.json'),
                'core_pid': 123, 'ready': {'type': 'ready', 'protocol': 1, 'runtime': 'typescript', 'http_listener': False, 'service_id': 'synthetic'},
                'actual_exit_code': 0, 'owned_runner_sha256': build.digest(root / 'scripts/desktop/windows-job.py'),
                'capabilities_status': 200, 'setup_required': True, 'owned_runtime_job_bound': True,
                'owned_runtime_job_closed': True, 'core_exit_code': 0, 'core_signal': None,
                'model_usage_rows': 0, 'paid_model_calls': 0, 'renderer_count': 0, 'gui_verified': False, 'installer_executed': False}

    # WIN-ASAR-BOOTSTRAP-001: a rehashed report cannot stand in for the packaged chain.
    def test_packaged_runtime_report_refuses_missing_wrong_bytes_and_unclosed_job(self):
        validate = self.api('validate_packaged_runtime_report')
        with tempfile.TemporaryDirectory() as directory:
            root, work = self.reuse_fixture(Path(directory)); self.electron_fixture(work / 'app')
            good = self.packaged_report(root, work)
            validate(good, work, build.source_inputs(root))
            for field, value in [('scope', 'physical_staging'), ('electron', 'other'), ('runtime_path', 'foreign'),
                                 ('bootstrap_sha256', '0' * 64), ('asar_sha256', '0' * 64), ('node_sha256', '0' * 64),
                                 ('source_sha256', {}), ('core_pid', 0), ('owned_runtime_job_bound', False),
                                 ('actual_exit_code', 1), ('owned_runner_sha256', '0' * 64),
                                 ('owned_runtime_job_closed', False), ('core_exit_code', 1), ('core_signal', 'SIGTERM'),
                                 ('model_usage_rows', 1), ('renderer_count', 1), ('gui_verified', True)]:
                with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, 'Packaged'):
                    validate({**good, field: value}, work, build.source_inputs(root))
            file = work / 'app/release/win-unpacked/resources/runtime/owned-runtime/runtime-bootstrap.cjs'
            file.unlink()
            with self.assertRaisesRegex(RuntimeError, 'bootstrap|inventory'):
                validate(good, work, build.source_inputs(root))

    def test_packaged_gate_failure_and_timeout_clean_only_owned_fixture_and_refuse_stale_report(self):
        for outcome in ('nonzero', 'timeout', 'missing-report'):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                root, work = self.reuse_fixture(Path(directory)); self.electron_fixture(work / 'app')
                put(work, 'packaged-runtime.json', 'stale success cannot authorize this run')
                unrelated = put(work, 'unrelated/keep.txt', 'keep')
                def runner(command, cwd, env, timeout, log, source):
                    fixture = work / 'packaged-runtime-fixture'
                    put(fixture, '.owned', 'marlin-packaged-runtime-gate-v1\n')
                    put(fixture, 'data/synthetic.sqlite3', 'synthetic')
                    if outcome == 'timeout':
                        raise RuntimeError('Owned Windows build fixture timed out; its JobObject tree was terminated')
                    return subprocess.CompletedProcess(command, 1 if outcome == 'nonzero' else 0)
                with patch.object(build, 'run_owned', runner), patch.dict(os.environ, {'SystemRoot': 'C:/Windows'}, clear=True), self.assertRaisesRegex(RuntimeError, 'timed out|Packaged'):
                    build.run_packaged_runtime_gate(root, work, work / 'app/payload/node/node.exe', build.source_inputs(root))
                self.assertFalse((work / 'packaged-runtime-fixture').exists())
                self.assertFalse((work / 'packaged-runtime.json').exists())
                self.assertEqual(unrelated.read_text(), 'keep')

    def test_owned_runtime_assets_are_explicit_and_native_inputs_are_frozen(self):
        for name in ("owned-runtime.cjs", "runtime-bootstrap.cjs"):
            self.assertIn(name, build.DESKTOP_FILES)
            self.assertIn(name, build.APP_FILES)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.fixture(root)
            for name in ("desktop/owned-runtime.cjs", "desktop/runtime-bootstrap.cjs",
                         "desktop/native/runtime-job/runtime_job.cc", "scripts/desktop/build-runtime-job.py"):
                put(root, name, "owned-runtime build input")
            snapshot = build.source_inputs(root)
            for name in ("desktop/owned-runtime.cjs", "desktop/runtime-bootstrap.cjs",
                         "desktop/native/runtime-job/runtime_job.cc", "scripts/desktop/build-runtime-job.py"):
                self.assertEqual(snapshot.get(name), build.digest(root / name))
            put(root, "desktop/native/runtime-job/new-fixture.cjs", "new native gate")
            with self.assertRaisesRegex(RuntimeError, "Source"):
                build.assert_source_unchanged(root, snapshot)

    def test_runtime_job_command_uses_product_node_and_separate_owned_work(self):
        command = self.api("runtime_job_command")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); work = build.guard_workspace(base / "work")
            argv = command(Path(sys.executable), work, base / "source")
            self.assertEqual(Path(argv[argv.index("--source-dir") + 1]), base / "source/desktop/native/runtime-job")
            self.assertEqual(Path(argv[argv.index("--node-executable") + 1]), work / "app/payload/node/node.exe")
            staging = Path(argv[argv.index("--work-dir") + 1])
            output = Path(argv[argv.index("--output") + 1])
            self.assertEqual(output, work / "app/payload/owned-runtime/runtime-job.node")
            self.assertFalse(output.is_relative_to(staging))
            self.assertFalse(staging.is_relative_to(work / "app"))
            self.assertEqual(Path(argv[argv.index("--report") + 1]), work / "runtime-job-build.json")

    def runtime_job_fixture(self, root, work):
        artifact = put(work, "app/payload/owned-runtime/runtime-job.node", "MZ synthetic addon")
        node = work / "app/payload/node/node.exe"
        report = {"schemaVersion": 1, "target": {"platform": "win32", "arch": "x64", "napiVersion": 8, "nodeVersion": "22.23.2"},
                  "sourceFiles": [{"path": path.relative_to(root / "desktop/native/runtime-job").as_posix(),
                                   "size": path.stat().st_size, "sha256": build.digest(path)}
                                  for path in sorted((root / "desktop/native/runtime-job").rglob("*")) if path.is_file()],
                  "nodeExecutable": {"path": str(node), "sha256": build.digest(node), "platform": "win32", "arch": "x64", "versions": {"node": "22.23.2", "napi": "10"}},
                  "ownedRunnerSha256": build.digest(root / "scripts/desktop/windows-job.py"),
                  "identitySmoke": {"pid": 123, "createdAt": "1", "executable": str(node)},
                  "inputs": dict(build.RUNTIME_JOB_INPUT_SHA256),
                  "compiler": {"path": "C:/BuildTools/cl.exe", "sha256": "4" * 64},
                  "artifact": {"path": str(artifact), "size": artifact.stat().st_size, "sha256": build.digest(artifact)},
                  "imports": ["KERNEL32.dll", "node.exe"], "commands": [{"argv": ["cl.exe"], "exitCode": 0, "log": "compiled"}], "actualExitCode": 0}
        put(work, "runtime-job-build.json", json.dumps(report))
        return report

    def test_runtime_job_report_rejects_rehashed_wrong_target_source_and_artifact(self):
        validate = self.api("validate_runtime_job_report")
        with tempfile.TemporaryDirectory() as directory:
            root, work = self.reuse_fixture(Path(directory))
            snapshot = build.source_inputs(root)
            good = self.runtime_job_fixture(root, work)
            validate(good, work / "app/payload", snapshot)
            for damage in ("napi", "platform", "node-version", "node-hash", "node-platform", "runner", "smoke", "source", "source-omitted", "artifact", "size", "compiler", "inputs", "input-pin", "imports", "command", "exit"):
                bad = json.loads(json.dumps(good))
                if damage == "napi": bad["target"]["napiVersion"] = 9
                if damage == "platform": bad["target"]["platform"] = "linux"
                if damage == "node-version": bad["nodeExecutable"]["versions"]["node"] = "0.0.0"
                if damage == "node-hash": bad["nodeExecutable"]["sha256"] = "0" * 64
                if damage == "node-platform": bad["nodeExecutable"]["platform"] = "linux"
                if damage == "runner": bad["ownedRunnerSha256"] = "0" * 64
                if damage == "smoke": bad["identitySmoke"]["createdAt"] = 1
                if damage == "source": bad["sourceFiles"][0]["sha256"] = "0" * 64
                if damage == "source-omitted": bad["sourceFiles"] = []
                if damage == "artifact": bad["artifact"]["sha256"] = "0" * 64
                if damage == "size": bad["artifact"]["size"] += 1
                if damage == "compiler": bad["compiler"]["sha256"] = "wrong"
                if damage == "inputs": del bad["inputs"]["nodeLibSha256"]
                if damage == "input-pin": bad["inputs"]["nodeLibSha256"] = "0" * 64
                if damage == "imports": bad["imports"].append("VCRUNTIME140.dll")
                if damage == "command": bad["commands"][0]["exitCode"] = 1
                if damage == "exit": bad["actualExitCode"] = 1
                with self.subTest(damage=damage), self.assertRaisesRegex(RuntimeError, "Runtime Job"):
                    validate(bad, work / "app/payload", snapshot)

    def test_windows_runtime_fixture_points_bootstrap_at_staged_native_addon(self):
        original = (build.ROOT / "desktop/runtime.test.cjs").read_text(encoding="utf-8")
        adapted = self.gates().runtime_fixture(original)
        self.assertEqual(adapted.count("nativeModulePath: path.join(__dirname, 'app/payload/owned-runtime/runtime-job.node')"), 2)
        self.assertIn("require('./app/runtime.cjs')", adapted)
        self.assertNotIn("execArgv: ['--import', 'tsx']", adapted)
        electron = (build.ROOT / "desktop/langfuse-electron-test.cjs").read_text(encoding="utf-8")
        adapted_electron = self.gates().electron_fixture(electron)
        self.assertEqual(adapted_electron.count("assert."), electron.count("assert."))
        self.assertIn("nativeModulePath: path.join(coreDirectory, '../owned-runtime/runtime-job.node')", adapted_electron)
        with self.assertRaisesRegex(RuntimeError, "fixture"):
            self.gates().electron_fixture(electron.replace("{ nodeExecutable, coreDirectory, entryPoint:", "{ coreDirectory, nodeExecutable, entryPoint:"))

    def test_gate_requires_actual_electron_loader_report_for_same_addon(self):
        with tempfile.TemporaryDirectory() as directory:
            root, work = self.reuse_fixture(Path(directory)); self.electron_fixture(work / "app")
            good = self.good_gate(root, work)
            good["owned_runtime_electron"] = {"format": "marlin-owned-runtime-loader-v1", "state": "verified",
                "versions": {"node": "24.21.0", "electron": "44.7.0", "napi": "10"},
                "owned_runtime": {"node_version": "v24.21.0", "platform": "win32", "arch": "x64", "napi_version": "10",
                    "addon_sha256": "0" * 64, "identity_verified": True, "api_verified": True},
                "paid_model_calls": 0, "gui_started": False, "core_started": False}
            put(work, "controlled-gates/owned-runtime-electron.json", json.dumps(good["owned_runtime_electron"]))
            good["owned_runtime_electron_report_sha256"] = build.digest(work / "controlled-gates/owned-runtime-electron.json")
            with self.assertRaisesRegex(RuntimeError, "Runtime Job|loader"):
                build.validate_gate_report(good, work / "app", build.source_inputs(root))


    def api(self, name):
        value = getattr(build, name, None)
        self.assertTrue(callable(value), f"TS/Electron packaging must implement {name}")
        return value

    def fixture(self, root):
        desktop = {
            "name": "marlin-desktop", "version": "0.6.2", "main": "main.cjs",
            "devDependencies": {"electron": "44.7.0", "electron-builder": "26.15.3"},
            "build": {"files": ["main.cjs", "runtime.cjs", "owned-runtime.cjs", "runtime-bootstrap.cjs", "ipc.cjs", "preload.cjs", "protocol.cjs", "langfuse.cjs", "loading.html", "package.json", "LICENSE", "icon.png"],
                      "extraResources": [{"from": "payload", "to": "runtime", "filter": ["**/*", "!**/__pycache__/**", "!**/*.pyc"]}],
                      "directories": {"output": "release"},
                      "win": {"artifactName": "Marlin-Setup-${version}-${arch}.${ext}"}},
        }
        core = {"name": "@marlin/core", "version": "0.7.0", "type": "module", "main": "dist/index.js",
                "dependencies": {"native-fixture": "1.0.0"}, "devDependencies": {"typescript": "6.0.3"}}
        for folder, package in (("desktop", desktop), ("packages/core", core), ("frontend", {"name": "frontend", "version": "0.6.2-django"})):
            put(root, folder + "/package.json", json.dumps(package))
            lock = {"lockfileVersion": 3, "packages": {"": package}}
            if folder == "packages/core":
                lock["packages"].update({"node_modules/native-fixture": {"version": "1.0.0"}, "node_modules/typescript": {"version": "6.0.3", "dev": True}})
            put(root, folder + "/package-lock.json", json.dumps(lock))
        for name in ("main.cjs", "runtime.cjs", "owned-runtime.cjs", "runtime-bootstrap.cjs", "ipc.cjs", "preload.cjs", "protocol.cjs", "langfuse.cjs", "loading.html"):
            put(root, "desktop/" + name)
        for name in ("LICENSE", "frontend/public/icons/icon-512.png", "frontend/index.html", "frontend/vite.config.ts", "frontend/src/main.ts", "frontend/public/manifest.webmanifest", "packages/core/tsconfig.json", "packages/core/src/index.ts", "packages/core/src/settings/startup.ts", "packages/core/scripts/prepare-native.mjs", "packages/core/src/evaluation/LICENSE-MT19937.txt"):
            put(root, name)
        for name in (".env", ".secrets/credentials.key", "db.sqlite3", "media/private.pdf", "manage.py", "requirements.txt", "chat/views.py", "desktop/node_modules/private-dev/private.key", "frontend/dist/index.html", "packages/core/dist/index.js", "packages/core/node_modules/private-dev/package.json"):
            put(root, name, "synthetic-private-or-stale")
        for name in ("LICENSE", "scripts/build_windows.py", "scripts/test_build_windows.py", "scripts/bundle_windows_native.py",
                     "scripts/desktop/build-python-runtime.py", "scripts/desktop/verify-payload.cjs",
                     "scripts/desktop/windows-gates.py", "scripts/desktop/windows-job.py", "scripts/desktop/audit-asar.cjs",
                     "scripts/desktop/python-runtime-lock-windows-x64.txt", "scripts/desktop/python-runtime-lock-native.txt",
                     "desktop/runtime.test.cjs", "desktop/runtime-shutdown.test.cjs", "desktop/runtime-bootstrap.test.cjs", "desktop/runtime-quit.test.cjs", "desktop/packaged-bootstrap.test.cjs", "desktop/langfuse-electron-test.cjs",
                     "desktop/native/runtime-job/runtime_job.cc", "scripts/desktop/build-runtime-job.py",
                     "workers/document/worker.py", "workers/document/tests/fixtures/unicode.txt", "workers/evaluation/worker.py"):
            if not (root / name).exists():
                put(root, name)
        for name in ("public-route-boundary.test.ts", "legacy-routes.test.ts", "channel-routes.test.ts",
                     "http.test.ts", "ipc.test.ts", "langfuse-native.test.ts"):
            put(root, "packages/core/test/" + name)

    def test_source_inputs_include_all_build_sources_and_detect_new_files(self):
        inputs = self.api("source_inputs")
        unchanged = self.api("assert_source_unchanged")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            snapshot = inputs(root)
            for name in ("frontend/src/main.ts", "packages/core/src/index.ts", "packages/core/src/settings/startup.ts",
                         "scripts/bundle_windows_native.py", "workers/document/tests/fixtures/unicode.txt",
                         "scripts/desktop/python-runtime-lock-native.txt", "desktop/runtime.test.cjs"):
                self.assertEqual(snapshot[name], build.digest(root / name))
            for name in (".env", "db.sqlite3", "media/private.pdf", "packages/core/dist/index.js",
                         "desktop/node_modules/private-dev/private.key"):
                self.assertNotIn(name, snapshot)
            unchanged(root, snapshot)
            put(root, "packages/core/src/new-domain.ts", "new trusted input")
            with self.assertRaisesRegex(RuntimeError, "[Ss]ource"):
                unchanged(root, snapshot)
            (root / "packages/core/src/new-domain.ts").unlink()
            put(root, "frontend/src/main.ts", "changed input")
            with self.assertRaisesRegex(RuntimeError, "[Ss]ource"):
                unchanged(root, snapshot)

    def test_payload_reuse_rejects_added_changed_and_deleted_files(self):
        verify = self.api("verify_payload_inventory")
        with tempfile.TemporaryDirectory() as directory:
            root, payload = Path(directory) / "source", Path(directory) / "payload"
            self.fixture(root)
            original = put(payload, "core/dist/index.js", "trusted bytes")
            build.copy_source(root / 'desktop/runtime-bootstrap.cjs', payload / build.PHYSICAL_BOOTSTRAP)
            build.write_manifest(root, payload)
            verify(payload)
            extra = put(payload, "core/dist/untracked.js", "new file")
            with self.assertRaisesRegex(RuntimeError, "inventory"):
                verify(payload)
            extra.unlink()
            original.write_text("changed")
            with self.assertRaisesRegex(RuntimeError, "inventory"):
                verify(payload)
            original.write_text("trusted bytes")
            original.unlink()
            with self.assertRaisesRegex(RuntimeError, "inventory"):
                verify(payload)

    def reuse_fixture(self, base):
        root, work = base / "source", build.guard_workspace(base / "work")
        self.fixture(root)
        for folder, source in (("frontend", "frontend"), ("core-build", "packages/core"),
                               ("core-prod", "packages/core"), ("app", "desktop"),
                               ("app/payload/core", "packages/core")):
            for name in ("package.json", "package-lock.json"):
                build.copy_source(root / source / name, work / folder / name)
        for name in build.APP_FILES:
            source = root / "desktop" / name if name not in {"LICENSE", "icon.png"} else root / ("LICENSE" if name == "LICENSE" else "frontend/public/icons/icon-512.png")
            build.copy_source(source, work / "app" / name)
        for group in ("document", "evaluation"):
            build.copy_source(root / "workers" / group / "worker.py", work / "app/payload/workers" / group / "worker.py")
            put(work, "app/payload/workers/" + group + "/.marlin-python-worker", "marlin-python-build-v1\n")
            put(work, "app/payload/workers/" + group + "/source-manifest.json", json.dumps([{"path": "worker.py", "sha256": build.digest(root / "workers" / group / "worker.py")}]))
        for name in ("python-runtime-lock-windows-x64.txt", "python-runtime-lock-native.txt"):
            build.copy_source(root / "scripts/desktop" / name, work / "app/payload/python" / name)
        put(work, "app/payload/node/node.exe", "MZsynthetic-node")
        put(work, "app/payload/core/dist/tools/desktop-process.js", "production core")
        put(work, "app/payload/frontend/index.html", "production frontend")
        put(work, "app/payload/core/node_modules/native-fixture/package.json", '{"version":"1.0.0"}')
        build.copy_source(root / 'desktop/runtime-bootstrap.cjs', work / 'app/payload' / build.PHYSICAL_BOOTSTRAP)
        self.verification_fixture(root, work)
        build.write_manifest(root, work / "app/payload", build.source_inputs(root))
        return root, work

    def verification_fixture(self, root, work):
        job = self.runtime_job_fixture(root, work)
        native = {"format": "marlin-core-payload-verification-v1", "state": "verified", "paid_model_calls": 0,
                  "gui_verified": False, "installer_verified": False,
                  "owned_runtime": {"node_version": "v22.23.2", "platform": "win32", "arch": "x64", "napi_version": "10",
                                    "addon_sha256": job["artifact"]["sha256"], "identity_verified": True, "api_verified": True,
                                    "identity": {"pid": 123, "createdAt": "1", "executable": str(work / "app/payload/node/node.exe")}},
                  "native": {"node_version": "v22.23.2", "platform": "win32", "arch": "x64", "vector_version": "v0.1.9",
                             "fts_id": str(2**60 + 321), "vector_id": str(2**60 + 321), "paid_model_calls": 0},
                  "ipc": {"protocol": 1, "runtime": "typescript", "http_listener": False, "capabilities_status": 200,
                          "setup_required": True, "exit_code": 0, "paid_model_calls": 0, "owned_runtime_job_bound": True}}
        dependencies = [{"name": "fixture-dependency", "version": "1.0.0"}]
        python = {"state": "verified", "paid_model_calls": 0, "system_python_required_at_runtime": False,
                  "python": {"version": "3.13.16 (synthetic unit fixture)", "isolated": 1, "no_site": 1, "django_spec": False,
                             "dependencies": dependencies}, "django_import": "ModuleNotFoundError",
                  "fixtures": [{"name": f"fixture-{i}", "canonical_sha256": "0" * 64} for i in range(11)],
                  "ragas": {"ragas_version": "0.4.3", "django_imported": False, "model_transport": "core_rpc"}}
        put(work, "app/payload/python/runtime-manifest.json", json.dumps({
            "format": "marlin-python-runtime-v1", "platform": "win_amd64", "dependencies": dependencies,
            "inputs": {"python_version": "3.13.16", "dependency_lock_sha256": build.digest(root / "scripts/desktop/python-runtime-lock-windows-x64.txt"),
                       "native_lock_sha256": build.digest(root / "scripts/desktop/python-runtime-lock-native.txt")}}))
        put(work, "core-verification.json", json.dumps(native))
        put(work, "python-verification.json", json.dumps(python))

    def electron_fixture(self, app):
        put(app, "node_modules/electron/package.json", '{"version":"44.7.0"}')
        put(app, "node_modules/electron/install.js", "official installer fixture")
        put(app, "node_modules/electron/path.txt", "electron.exe")
        put(app, "node_modules/electron/dist/version", "44.7.0")
        put(app, "node_modules/electron/dist/electron.exe", "synthetic build-host executable")
        put(app, "node_modules/electron/dist/icudtl.dat", "synthetic required resource")

    def good_gate(self, root, work):
        fields = ("real_nextauth_protocol", "actual_private_child_json", "renderer_cookie_secret_absent", "isolated_memory_session",
                  "httponly_host_only_lax", "sandbox_no_preload_node", "popups_denied", "owned_cookie_clear",
                  "unrelated_browser_cookie_preserved", "public_cancel_no_window", "public_cancel_pending_navigation",
                  "public_logout_clears_window", "public_configuration_change_clears_window")
        window = {"format": "marlin-langfuse-native-test-v1", "state": "verified", "platform": "win32", "electron": "44.7.0",
                  "paid_model_calls": 0, "owned_core_exit_code": 0, "foreign_project_requests": 0, **{name: True for name in fields}}
        put(work, "controlled-gates/langfuse-native.json", json.dumps(window))
        electron_loader = {"format": "marlin-owned-runtime-loader-v1", "state": "verified", "versions": {"electron": "44.7.0", "node": "24.21.0", "napi": "10"},
            "owned_runtime": {"node_version": "v24.21.0", "platform": "win32", "arch": "x64", "napi_version": "10", "identity_verified": True, "api_verified": True,
                "addon_sha256": build.digest(work / "app/payload/owned-runtime/runtime-job.node"),
                "identity": {"pid": 456, "createdAt": "2", "executable": str(work / "app/node_modules/electron/dist/electron.exe")}},
            "paid_model_calls": 0, "gui_started": False, "core_started": False}
        put(work, "controlled-gates/owned-runtime-electron.json", json.dumps(electron_loader))
        return {"format": "marlin-windows-build-gates-v1", "state": "verified", "scope": "frozen_source", "source_before_after_equal": True,
                "source_sha256": build.source_inputs(root), "desktop_sha256": build.desktop_inventory(work / "app"),
                "electron_distribution": build.electron_distribution(work / "app"),
                "core_entry_sha256": build.digest(work / "app/payload/core/dist/tools/desktop-process.js"),
                "frontend_index_sha256": build.digest(work / "app/payload/frontend/index.html"),
                "core_tests": {"tests": 24, "passed": 24, "failed": 0, "skipped": 0, "duration_ms": 1.0},
                "packaged_bootstrap_tests": {"tests": 2, "passed": 2, "failed": 0, "skipped": 0, "duration_ms": 1.0},
                "packaged_bootstrap_tests_scope": "actual_asar_external_node_unit_native_core_doubles",
                "runtime_tests": {"tests": 6, "passed": 6, "failed": 0, "skipped": 0, "duration_ms": 1.0}, "langfuse": window, "paid_model_calls": 0,
                "native": json.loads((work / "core-verification.json").read_text()), "native_report_sha256": build.digest(work / "core-verification.json"),
                "runtime_job_build": json.loads((work / "runtime-job-build.json").read_text()), "runtime_job_build_report_sha256": build.digest(work / "runtime-job-build.json"),
                "owned_runtime_electron": electron_loader, "owned_runtime_electron_report_sha256": build.digest(work / "controlled-gates/owned-runtime-electron.json"),
                "python_report_sha256": build.digest(work / "python-verification.json"), "python_fixture_count": 11,
                "langfuse_report_sha256": build.digest(work / "controlled-gates/langfuse-native.json"),
                "manual_gui_verified": False, "real_external_vendor_verified": False, "installer_executed": False}

    def test_frozen_gate_rejects_native_artifact_even_when_manifest_is_rebound(self):
        with tempfile.TemporaryDirectory() as directory:
            root, work = self.reuse_fixture(Path(directory)); self.electron_fixture(work / "app")
            good = self.good_gate(root, work)
            put(work, "app/payload/owned-runtime/runtime-job.node", "MZ different addon bytes")
            build.write_manifest(root, work / "app/payload", build.source_inputs(root))
            with self.assertRaisesRegex(RuntimeError, "Runtime Job|Native"):
                build.validate_gate_report(good, work / "app", build.source_inputs(root))

    def test_gate_refuses_rehashed_invalid_native_python_window_and_duration_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root, work = self.reuse_fixture(Path(directory)); self.electron_fixture(work / "app")
            for kind in ("native", "python", "window", "duration"):
                self.verification_fixture(root, work)
                good = self.good_gate(root, work)
                if kind == "native":
                    good["native"]["ipc"]["http_listener"] = True
                    put(work, "core-verification.json", json.dumps(good["native"]))
                    good["native_report_sha256"] = build.digest(work / "core-verification.json")
                elif kind == "python":
                    path = work / "python-verification.json"; value = json.loads(path.read_text()); value["python"]["django_spec"] = True
                    put(work, "python-verification.json", json.dumps(value)); good["python_report_sha256"] = build.digest(path)
                elif kind == "window":
                    good["langfuse"]["paid_model_calls"] = 1
                    put(work, "controlled-gates/langfuse-native.json", json.dumps(good["langfuse"]))
                    good["langfuse_report_sha256"] = build.digest(work / "controlled-gates/langfuse-native.json")
                else:
                    good["core_tests"]["duration_ms"] = float("inf")
                with self.subTest(kind=kind), self.assertRaisesRegex(RuntimeError, "gate|Gate|Electron|Python|Native"):
                    build.validate_gate_report(good, work / "app", build.source_inputs(root))

    def test_electron_distribution_rejects_modified_added_deleted_and_wrong_version(self):
        inventory = self.api("electron_distribution")
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory)
            put(app, "package.json", '{"devDependencies":{"electron":"44.7.0"}}')
            self.electron_fixture(app)
            before = inventory(app)
            self.assertEqual(before["format"], "marlin-electron-distribution-v1")
            self.assertEqual(before["version"], "44.7.0")
            binary = app / "node_modules/electron/dist/electron.exe"
            binary.write_text("altered executable")
            self.assertNotEqual(inventory(app), before)
            self.electron_fixture(app)
            extra = put(app, "node_modules/electron/dist/extra.dll", "new")
            self.assertNotEqual(inventory(app), before)
            extra.unlink()
            (app / "node_modules/electron/dist/icudtl.dat").unlink()
            self.assertNotEqual(inventory(app), before)
            self.electron_fixture(app)
            put(app, "node_modules/electron/dist/version", "other")
            with self.assertRaisesRegex(RuntimeError, "Electron"):
                inventory(app)

    def test_gate_schema_rejects_unknown_failed_artifact_and_partial_success(self):
        validate = self.api("validate_gate_report")
        with tempfile.TemporaryDirectory() as directory:
            root, work = self.reuse_fixture(Path(directory))
            self.electron_fixture(work / "app")
            good = self.good_gate(root, work)
            validate(good, work / "app", build.source_inputs(root))
            for field, value in (("format", "unknown"), ("state", "failed"), ("scope", "artifact_only"),
                                 ("core_tests", {"tests": 24, "passed": 24, "failed": 1, "skipped": 0}),
                                 ("runtime_tests", {"tests": 6, "passed": 6, "failed": 0, "skipped": 1}),
                                 ("langfuse", {"state": "verified"})):
                with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, "gate|Gate|Electron"):
                    validate({**good, field: value}, work / "app", build.source_inputs(root))

    def test_refresh_reuse_checks_all_locks_and_complete_worker_source_set(self):
        verify = self.api("verify_reusable")
        with tempfile.TemporaryDirectory() as directory:
            root, work = self.reuse_fixture(Path(directory))
            self.electron_fixture(work / "app")
            with patch.object(build, "NODE_EXE_SHA256", build.digest(work / "app/payload/node/node.exe")):
                verify(root, work)
                extra = put(root, "workers/document/new-production.py", "new worker capability")
                with self.assertRaisesRegex(RuntimeError, "[Ww]orker"):
                    verify(root, work)
                extra.unlink()
                # New tests need not change installed worker production bytes.
                put(root, "workers/document/tests/new.test.py")
                verify(root, work)
                lock = root / "scripts/desktop/python-runtime-lock-native.txt"
                lock.write_text("changed pin")
                with self.assertRaisesRegex(RuntimeError, "[Ll]ock|[Dd]ependen"):
                    verify(root, work)

    def test_prepared_gate_rejects_old_missing_evidence_and_changed_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root, work = self.reuse_fixture(Path(directory))
            self.electron_fixture(work / "app")
            with patch.object(build, "NODE_EXE_SHA256", build.digest(work / "app/payload/node/node.exe")):
                with self.assertRaisesRegex(RuntimeError, "fresh|old evidence"):
                    build.verify_prepared(root, work)
                put(work, "windows-gates.json", json.dumps(self.good_gate(root, work)))
                put(work, "prepared-build.json", json.dumps({
                    "format": "marlin-prepared-windows-build-v1", "state": "verified", "source_sha256": build.source_inputs(root),
                    "payload_manifest_sha256": build.digest(work / "app/payload/source-manifest.json"),
                    "desktop_sha256": build.desktop_inventory(work / "app"), "gates_sha256": build.digest(work / "windows-gates.json"),
                    "electron_distribution": build.electron_distribution(work / "app")}))
                build.verify_prepared(root, work)
                binary = work / "app/node_modules/electron/dist/electron.exe"
                binary.write_text("modified Electron outside payload")
                with self.assertRaisesRegex(RuntimeError, "distribution|outputs|Electron"):
                    build.verify_prepared(root, work)
                self.electron_fixture(work / "app")
                extra = put(work, "app/node_modules/electron/dist/untracked.dll", "new resource")
                with self.assertRaisesRegex(RuntimeError, "distribution|outputs|Electron"):
                    build.verify_prepared(root, work)
                extra.unlink()
                put(work, "windows-gates.json", '{"state":"unverified"}')
                with self.assertRaisesRegex(RuntimeError, "report|inventory"):
                    build.verify_prepared(root, work)

    def test_refresh_rebuilds_fresh_source_and_reverifies_without_dependency_ci(self):
        with tempfile.TemporaryDirectory() as directory:
            root, work = self.reuse_fixture(Path(directory))
            self.electron_fixture(work / "app")
            put(work, "frontend/src/stale.ts", "stale source")
            put(work, "core-build/dist/storage/withdrawn-owner.js", "withdrawn output")
            calls = []
            def runner(command, cwd, env=None, timeout=None):
                command = [str(value) for value in command]; cwd = Path(cwd); calls.append(command)
                if any(value.endswith("build-runtime-job.py") for value in command):
                    self.runtime_job_fixture(root, work)
                if command[-2:] == ["run", "build"]:
                    if cwd.name == "frontend":
                        put(cwd, "dist/index.html", "fresh frontend")
                    else:
                        for name in ("index.js", "tools/desktop-process.js"):
                            put(cwd, "dist/" + name, "fresh core")
                if any(value.endswith("windows-gates.py") for value in command):
                    put(work, "windows-gates.json", json.dumps(self.good_gate(root, work)))
            with patch.object(build, "run", runner), patch.object(build, "NODE_EXE_SHA256", build.digest(work / "app/payload/node/node.exe")), patch.dict(os.environ, {"SystemRoot": "C:/Windows"}, clear=True):
                self.assertEqual(build.refresh_windows(root, work, work / "node.exe", work / "npm-cli.js", work / "output", True), work / "app/payload")
                build.verify_prepared(root, work)
            self.assertFalse(any("ci" in command for command in calls))
            self.assertTrue(any(command[-2:] == ["run", "test:unit"] for command in calls))
            self.assertFalse((work / "frontend/src/stale.ts").exists())
            self.assertFalse((work / "core-build/dist/storage/withdrawn-owner.js").exists())
            self.assertEqual((work / "packages/core/src/settings/startup.ts").read_bytes(), (root / "packages/core/src/settings/startup.ts").read_bytes())

    def test_artifact_only_evidence_cannot_authorize_prepared_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root, work = self.reuse_fixture(Path(directory))
            def runner(command, cwd, env=None, timeout=None):
                put(work, "windows-gates.json", '{"format":"marlin-windows-build-gates-v1","state":"verified","scope":"artifact_only"}')
            with patch.object(build, "run", runner), patch.dict(os.environ, {"SystemRoot": "C:/Windows"}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "native gates"):
                    build.run_windows_gates(root, work, work / "node.exe", build.source_inputs(root))
            self.assertFalse((work / "prepared-build.json").exists())

    def test_refresh_prepares_missing_electron_shell_with_its_official_installer(self):
        with tempfile.TemporaryDirectory() as directory:
            root, work = self.reuse_fixture(Path(directory))
            put(work, "app/node_modules/electron/package.json", '{"version":"44.7.0"}')
            installer = put(work, "app/node_modules/electron/install.js", "official installer fixture")
            calls = []
            def runner(command, cwd, env=None, timeout=None):
                command = list(map(str, command)); calls.append(command)
                if any(value.endswith("build-runtime-job.py") for value in command):
                    self.runtime_job_fixture(root, work)
                if command[-1] == str(installer):
                    self.electron_fixture(work / "app")
                elif command[-2:] == ["run", "build"]:
                    if Path(cwd).name == "frontend":
                        put(Path(cwd), "dist/index.html", "fresh frontend")
                    else:
                        for name in ("index.js", "tools/desktop-process.js"):
                            put(Path(cwd), "dist/" + name, "fresh core")
                elif any(value.endswith("windows-gates.py") for value in command):
                    put(work, "windows-gates.json", json.dumps(self.good_gate(root, work)))
            with patch.object(build, "run", runner), patch.object(build, "NODE_EXE_SHA256", build.digest(work / "app/payload/node/node.exe")), patch.dict(os.environ, {"SystemRoot": "C:/Windows"}, clear=True):
                build.refresh_windows(root, work, work / "node.exe", work / "npm-cli.js", work / "output", True)
                build.verify_prepared(root, work)
            installed = next(i for i, command in enumerate(calls) if command[-1] == str(installer))
            gated = next(i for i, command in enumerate(calls) if any(value.endswith("windows-gates.py") for value in command))
            self.assertLess(installed, gated)
            self.assertFalse(any("ci" in command for command in calls))

    def test_node_engine_range_refuses_unsupported_odd_and_early_24_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            for version in ("v22.22.1", "v23.9.0", "v24.14.9", "v25.9.0"):
                with self.subTest(version=version), patch.object(subprocess, "check_output", return_value=version), patch.dict(os.environ, {"SystemRoot": "C:/Windows"}, clear=True):
                    with self.assertRaisesRegex(RuntimeError, "22.22.2"):
                        build.build_node_version(work / "node.exe", work)
            for version in ("v22.23.2", "v24.15.0", "v26.0.0"):
                with self.subTest(version=version), patch.object(subprocess, "check_output", return_value=version), patch.dict(os.environ, {"SystemRoot": "C:/Windows"}, clear=True):
                    self.assertEqual(build.build_node_version(work / "node.exe", work), version)

    def gates(self):
        helper = build.ROOT / "scripts/desktop/windows-gates.py"
        self.assertTrue(helper.is_file(), "The parameterized real Windows gate must be in the repository")
        spec = importlib.util.spec_from_file_location("windows_gates", helper)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_tap_gate_refuses_failed_skipped_incomplete_or_too_small_suites(self):
        gates = self.gates()
        good = "# tests 6\n# pass 6\n# fail 0\n# cancelled 0\n# skipped 0\n# todo 0\n# duration_ms 4.2\n"
        self.assertEqual(gates.tap_summary(good, 6)["passed"], 6)
        for bad in (good.replace("# fail 0", "# fail 1"), good.replace("# skipped 0", "# skipped 1"),
                    good.replace("# pass 6", "# pass 5"), good.replace("# todo 0", "# todo 1"),
                    good.replace("# cancelled 0", "# cancelled 1"), "# tests 6\n", good.replace("# tests 6", "# tests 5")):
            with self.subTest(text=bad), self.assertRaisesRegex(RuntimeError, "suite"):
                gates.tap_summary(bad, 6)

    def test_windows_gate_checks_actual_private_window_facts_before_verified(self):
        gates = self.gates()
        validate = getattr(gates, "validate_window_report", None)
        self.assertTrue(callable(validate), "The gate must reject partial/foreign Electron evidence")
        good = {"format": "marlin-langfuse-native-test-v1", "state": "verified", "platform": "win32", "paid_model_calls": 0,
                "electron": "44.7.0", "owned_core_exit_code": 0, "foreign_project_requests": 0}
        fields = ("real_nextauth_protocol", "actual_private_child_json", "renderer_cookie_secret_absent", "isolated_memory_session",
                  "httponly_host_only_lax", "sandbox_no_preload_node", "popups_denied", "owned_cookie_clear",
                  "unrelated_browser_cookie_preserved", "public_cancel_no_window", "public_cancel_pending_navigation",
                  "public_logout_clears_window", "public_configuration_change_clears_window")
        good.update({name: True for name in fields})
        validate(good, "44.7.0")
        for key, value in (("state", "failed"), ("renderer_cookie_secret_absent", False), ("foreign_project_requests", 1),
                           ("paid_model_calls", 1), ("electron", "other"), ("platform", "linux")):
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "Electron"):
                validate({**good, key: value}, "44.7.0")

    def test_runtime_fixture_keeps_all_original_assertions_and_refuses_changed_path_shape(self):
        gates = self.gates()
        original = (build.ROOT / "desktop/runtime.test.cjs").read_text(encoding="utf-8")
        adapted = gates.runtime_fixture(original)
        self.assertEqual(adapted.count("assert."), original.count("assert."))
        self.assertEqual(adapted.count("test("), original.count("test("))
        self.assertIn("dist/tools/desktop-process.js", adapted)
        self.assertNotIn("src/tools/desktop-process.ts", adapted)
        self.assertNotIn("execArgv: ['--import', 'tsx']", adapted)
        with self.assertRaisesRegex(RuntimeError, "fixture"):
            gates.runtime_fixture(original.replace("require('./runtime.cjs')", "require('./different.cjs')"))

    def test_actual_asar_audit_checks_twelve_assets_and_native_bytes(self):
        helper = build.ROOT / "scripts/desktop/audit-asar.cjs"
        self.assertTrue(helper.is_file(), "The actual ASAR audit must be reproducible from the repository")
        node = os.environ.get("MARLIN_TEST_NODE") or shutil.which("node")
        module = Path(os.environ.get("MARLIN_TEST_ASAR_DIRECTORY", str(build.ROOT / "desktop/node_modules/@electron/asar")))
        self.assertTrue(node and module.is_dir(), "Install the locked build dependencies for the actual ASAR regression")
        with tempfile.TemporaryDirectory() as directory:
            root, app = Path(directory) / "source", Path(directory) / "app"
            self.fixture(root)
            for name in build.APP_FILES:
                source = root / "desktop" / name if name not in {"LICENSE", "icon.png"} else root / ("LICENSE" if name == "LICENSE" else "frontend/public/icons/icon-512.png")
                build.copy_source(source, app / name)
            put(app, "payload/core/dist/index.js", "production fixture")
            put(app, "payload/owned-runtime/runtime-job.node", "MZ controlled addon bytes")
            build.copy_source(root / 'desktop/runtime-bootstrap.cjs', app / 'payload' / build.PHYSICAL_BOOTSTRAP)
            build.write_manifest(root, app / "payload")
            script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const [helper,app,module]=process.argv.slice(1),asar=require(module),{auditAsar}=require(helper);
const output=path.join(app,'release/win-unpacked/resources'),stage=path.join(app,'archive-fixture');
fs.mkdirSync(stage,{recursive:true});fs.mkdirSync(output,{recursive:true});
const names=['main.cjs','runtime.cjs','owned-runtime.cjs','runtime-bootstrap.cjs','ipc.cjs','preload.cjs','protocol.cjs','langfuse.cjs','loading.html','package.json','LICENSE','icon.png'];
for(const name of names)fs.copyFileSync(path.join(app,name),path.join(stage,name));
const metadata=JSON.parse(fs.readFileSync(path.join(stage,'package.json')));for(const key of ['build','scripts','devDependencies'])delete metadata[key];
fs.writeFileSync(path.join(stage,'package.json'),JSON.stringify(metadata));
const archive=path.join(output,'app.asar');fs.cpSync(path.join(app,'payload'),path.join(output,'runtime'),{recursive:true});
(async()=>{await asar.createPackage(stage,archive);assert.equal(auditAsar(app,asar).state,'verified');
fs.writeFileSync(path.join(output,'runtime','unexpected.js'),'new');assert.throws(()=>auditAsar(app,asar),/inventory/);fs.unlinkSync(path.join(output,'runtime','unexpected.js'));
fs.writeFileSync(path.join(stage,'main.cjs'),'wrong');await asar.createPackage(stage,archive);assert.throws(()=>auditAsar(app,asar),/bytes/);
fs.copyFileSync(path.join(app,'main.cjs'),path.join(stage,'main.cjs'));fs.writeFileSync(path.join(stage,'extra.cjs'),'unexpected');await asar.createPackage(stage,archive);assert.throws(()=>auditAsar(app,asar),/allowlist/);
fs.unlinkSync(path.join(stage,'extra.cjs'));await asar.createPackage(stage,archive);
const addon=path.join(output,'runtime/owned-runtime/runtime-job.node'),bytes=fs.readFileSync(addon);fs.writeFileSync(addon,'MZ tampered addon');assert.throws(()=>auditAsar(app,asar),/inventory/);fs.writeFileSync(addon,bytes);
const stagedBootstrap=path.join(app,'payload/owned-runtime/runtime-bootstrap.cjs'),packedBootstrap=path.join(output,'runtime/owned-runtime/runtime-bootstrap.cjs');
const stagedManifest=path.join(app,'payload/source-manifest.json'),packedManifest=path.join(output,'runtime/source-manifest.json');
const originalManifest=fs.readFileSync(stagedManifest),originalBootstrap=fs.readFileSync(stagedBootstrap);
fs.writeFileSync(stagedBootstrap,'rebound different bootstrap');fs.writeFileSync(packedBootstrap,'rebound different bootstrap');
const rebound=JSON.parse(originalManifest);rebound.files['owned-runtime/runtime-bootstrap.cjs']=require('node:crypto').createHash('sha256').update(fs.readFileSync(stagedBootstrap)).digest('hex');rebound.bootstrap_sha256=rebound.files['owned-runtime/runtime-bootstrap.cjs'];
fs.writeFileSync(stagedManifest,JSON.stringify(rebound));fs.writeFileSync(packedManifest,JSON.stringify(rebound));
assert.throws(()=>auditAsar(app,asar),/bootstrap/i);
fs.writeFileSync(stagedBootstrap,originalBootstrap);fs.writeFileSync(packedBootstrap,originalBootstrap);fs.writeFileSync(stagedManifest,originalManifest);fs.writeFileSync(packedManifest,originalManifest);
fs.unlinkSync(addon);fs.unlinkSync(path.join(app,'payload/owned-runtime/runtime-job.node'));
const manifestFile=path.join(app,'payload/source-manifest.json'),manifest=JSON.parse(fs.readFileSync(manifestFile));delete manifest.files['owned-runtime/runtime-job.node'];fs.writeFileSync(manifestFile,JSON.stringify(manifest));fs.copyFileSync(manifestFile,path.join(output,'runtime/source-manifest.json'));
assert.throws(()=>auditAsar(app,asar),/owned|native/i);
console.log('ASAR_REAL_REGRESSION_OK');})().catch(error=>{console.error(error);process.exitCode=1});
"""
            completed = subprocess.run([node, "-e", script, str(helper), str(app), str(module)], capture_output=True, text=True, timeout=60)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("ASAR_REAL_REGRESSION_OK", completed.stdout)

    def test_python_native_bootstrap_cannot_add_bytecode_excluded_from_actual_resources(self):
        # Actual make_runtime bootstrap and host Python process; only archive,
        # network and wheel installation use explicitly controlled fixtures.
        spec = importlib.util.spec_from_file_location("python_runtime_build", build.ROOT / "scripts/desktop/build-python-runtime.py")
        producer = importlib.util.module_from_spec(spec); spec.loader.exec_module(producer)
        node = self.native_node()
        asar = Path(os.environ.get("MARLIN_TEST_ASAR_DIRECTORY", str(build.ROOT / "desktop/node_modules/@electron/asar")))
        matcher = asar.parents[1] / "app-builder-lib/out/fileMatcher.js"
        self.assertTrue(asar.is_dir() and matcher.is_file(), "Install the locked real ASAR/FileMatcher build dependencies")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); root, app, work = base / "source", base / "app", base / "python-work"
            self.fixture(root); work.mkdir()
            # Use the current real production resource policy, not a looser
            # test-only mapping. No Electron/installer/application is started.
            build.copy_source(build.ROOT / "desktop/package.json", root / "desktop/package.json")
            for name in build.APP_FILES:
                source = root / "desktop" / name if name not in {"LICENSE", "icon.png"} else root / ("LICENSE" if name == "LICENSE" else "frontend/public/icons/icon-512.png")
                build.copy_source(source, app / name)
            archive = base / "controlled-python.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("LICENSE.txt", "controlled interpreter license")
            native_script = put(root, "scripts/bundle_windows_native.py", "import json,sys,zstandard\nfrom pathlib import Path\nPath(sys.argv[-1], 'bootstrap-probe.json').write_text(json.dumps({'imported':zstandard.VALUE == 42,'no_bytecode':sys.dont_write_bytecode}))\n")
            def runner(command, cwd, env=None, timeout=None, capture=False):
                command = list(map(str, command))
                if "pip" in command:
                    if "install" in command:
                        put(work, "python-stage/Lib/site-packages/zstandard/__init__.py", "VALUE = 42\n")
                    return subprocess.CompletedProcess(command, 0)
                # This is the producer's unmodified native shim, executed by a
                # real isolated interpreter with its controlled import path.
                self.assertIn(str(native_script), command)
                return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=30, check=True)
            with patch.object(producer, "ROOT", root), patch.object(producer, "LOCK", root / "scripts/desktop/python-runtime-lock-windows-x64.txt"), patch.object(producer, "NATIVE_LOCK", root / "scripts/desktop/python-runtime-lock-native.txt"), patch.object(producer, "download_python", return_value=archive), patch.object(producer, "run", runner), patch.dict(os.environ, {"SystemRoot": os.environ.get("SystemRoot", str(base / "system"))}):
                runtime = producer.make_runtime(app / "payload", work, [])
            self.assertTrue(json.loads((runtime / "bootstrap-probe.json").read_text())["imported"])
            self.assertEqual(list(runtime.rglob("*.pyc")), [], "The actual native bootstrap must not create resources intentionally excluded by production packaging")
            self.assertTrue(json.loads((runtime / "bootstrap-probe.json").read_text())["no_bytecode"])
            self.assertEqual((runtime / "Lib/site-packages/zstandard/__init__.py").read_text(), "VALUE = 42\n")
            self.assertEqual((runtime / "LICENSE.txt").read_text(), "controlled interpreter license")
            put(app, "payload/owned-runtime/runtime-job.node", "MZ controlled addon fixture")
            build.copy_source(root / 'desktop/runtime-bootstrap.cjs', app / 'payload' / build.PHYSICAL_BOOTSTRAP)
            build.write_manifest(root, app / "payload")
            script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const [helper,app,asarModule,matcherModule]=process.argv.slice(1),asar=require(asarModule),{auditAsar}=require(helper);
const {getFileMatchers,copyFiles}=require(matcherModule),metadata=JSON.parse(fs.readFileSync(path.join(app,'package.json')));
const output=path.join(app,'release/win-unpacked/resources'),stage=path.join(app,'archive-fixture');
fs.mkdirSync(stage,{recursive:true});fs.mkdirSync(output,{recursive:true});
for(const name of metadata.build.files)fs.copyFileSync(path.join(app,name),path.join(stage,name));
const clean={...metadata};for(const key of ['build','scripts','devDependencies'])delete clean[key];
fs.writeFileSync(path.join(stage,'package.json'),JSON.stringify(clean));
(async()=>{
const matchers=getFileMatchers(metadata.build,'extraResources',output,{macroExpander:x=>x,customBuildOptions:{},globalOutDir:path.join(app,'release'),defaultSrc:app});
assert.equal(matchers.length,1);assert.equal(matchers[0].from,path.join(app,'payload'));
await copyFiles(matchers,null,false);await asar.createPackage(stage,path.join(output,'app.asar'));
assert.equal(auditAsar(app,asar).state,'verified');
const module=path.join(output,'runtime/python/Lib/site-packages/zstandard/__init__.py'),original=fs.readFileSync(module);
fs.writeFileSync(module,'changed normal module');assert.throws(()=>auditAsar(app,asar),/inventory/);fs.writeFileSync(module,original);
const notice=path.join(output,'runtime/python/LICENSE.txt'),license=fs.readFileSync(notice);fs.unlinkSync(notice);assert.throws(()=>auditAsar(app,asar),/inventory/);fs.writeFileSync(notice,license);
const extra=path.join(output,'runtime/extra.pyc');fs.writeFileSync(extra,'untracked');assert.throws(()=>auditAsar(app,asar),/inventory/);fs.unlinkSync(extra);
assert.equal(auditAsar(app,asar).state,'verified');console.log('REAL_BOOTSTRAP_RESOURCES_ASAR_OK');
})().catch(error=>{console.error(error);process.exitCode=1});
"""
            completed = subprocess.run([node, "-e", script, str(build.ROOT / "scripts/desktop/audit-asar.cjs"), str(app), str(asar), str(matcher)], capture_output=True, text=True, timeout=60)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("REAL_BOOTSTRAP_RESOURCES_ASAR_OK", completed.stdout)

    def job_helper(self):
        helper = build.ROOT / "scripts/desktop/windows-job.py"
        self.assertTrue(helper.is_file(), "The build gate must own and clean its actual Windows child tree")
        spec = importlib.util.spec_from_file_location("windows_job", helper)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_job_guard_rejects_shell_search_relative_paths_and_unbounded_timeout(self):
        job = self.job_helper()
        with tempfile.TemporaryDirectory() as directory:
            for command, timeout in ((["node", "file.js"], 1), ([sys.executable], 0), ([sys.executable], float("inf"))):
                with self.subTest(command=command, timeout=timeout), self.assertRaisesRegex(RuntimeError, "absolute|timeout"):
                    job.validate(command, Path(directory), {}, timeout)

    @unittest.skipUnless(os.name == "nt", "Actual Windows junction inventory boundary")
    def test_windows_full_inventory_rejects_junction_before_descending(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            payload = base / "payload"; payload.mkdir()
            outside = base / "outside"; outside.mkdir(); put(outside, "protected.txt", "keep")
            link = payload / "junction"
            system = os.environ["SystemRoot"]
            subprocess.run([str(Path(system) / "System32/cmd.exe"), "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
            try:
                with self.assertRaisesRegex(RuntimeError, "symlink|junction"):
                    build.payload_inventory(payload)
                with self.assertRaisesRegex(RuntimeError, "symlink|junction"):
                    self.gates().execute(build.ROOT, link, self.native_node(), base / "unused-report.json", True)
                self.assertEqual((outside / "protected.txt").read_text(), "keep")
            finally:
                os.rmdir(link)

    @unittest.skipUnless(os.name == "nt", "Real Win32 JobObject regression runs on Windows")
    def test_windows_job_timeout_and_parent_exit_clean_owned_descendants_only(self):
        job = self.job_helper()
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            unrelated = subprocess.Popen([sys.executable, "-I", "-c", "import time;time.sleep(30)"])
            try:
                for mode in ("timeout", "parent-exit"):
                    pidfile = base / (mode + ".pid")
                    program = "import subprocess,sys,time,pathlib;p=subprocess.Popen([sys.executable,'-I','-c','import time;time.sleep(30)']);pathlib.Path(sys.argv[1]).write_text(str(p.pid));" + ("time.sleep(30)" if mode == "timeout" else "sys.exit(0)")
                    started = time.monotonic()
                    command = [sys.executable, "-I", "-c", program, str(pidfile)]
                    if mode == "timeout":
                        with self.assertRaisesRegex(RuntimeError, "timed out"):
                            job.run_owned(command, base, dict(os.environ), 1, base / (mode + ".log"))
                    else:
                        self.assertEqual(job.run_owned(command, base, dict(os.environ), 5, base / (mode + ".log")).returncode, 0)
                    self.assertLess(time.monotonic() - started, 8)
                    self.assertTrue(pidfile.is_file(), "A real descendant must exist before cleanup")
                    handle = kernel.OpenProcess(0x00100000, False, int(pidfile.read_text()))
                    if handle:
                        try:
                            self.assertEqual(kernel.WaitForSingleObject(handle, 0), 0, "The owned descendant must actually terminate")
                        finally:
                            kernel.CloseHandle(handle)
                    self.assertIsNone(unrelated.poll(), "An unrelated child must remain alive")
            finally:
                unrelated.terminate(); unrelated.wait(timeout=5)

    def test_disposable_reset_requires_exact_ownership_and_keeps_other_paths(self):
        guard = self.api("guard_workspace")
        reset = self.api("reset_staging")
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / "work"
            work.mkdir()
            put(work, "unrelated.txt", "keep")
            with self.assertRaises(RuntimeError):
                guard(work)
            put(work, ".marlin-build", "another builder")
            with self.assertRaises(RuntimeError):
                reset(work, "app")
            put(work, ".marlin-build", build.MARKER_VALUE)
            put(work, "app/payload/.secrets/test.key")
            self.assertEqual(reset(work, "app"), work / "app")
            self.assertFalse((work / "app").exists())
            self.assertEqual((work / "unrelated.txt").read_text(), "keep")
            for name in ("..", "", "unrelated.txt", "app/payload", "python-work"):
                with self.assertRaises(RuntimeError, msg=name):
                    reset(work, name)

    @unittest.skipIf(os.name == "nt", "Windows junction rejection has separate build-host coverage")
    def test_source_and_reset_reject_symlink_ancestors(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            real = base / "real"
            put(real, "secret.txt")
            (base / "alias").symlink_to(real, target_is_directory=True)
            with self.assertRaises(RuntimeError):
                build.copy_source(base / "alias/secret.txt", base / "copied.txt")
            guard = self.api("guard_workspace")
            work = guard(base / "work")
            outside = base / "outside"
            put(outside, "keep", "keep")
            (work / "app").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(RuntimeError):
                self.api("reset_staging")(work, "app")
            self.assertTrue((outside / "keep").exists())

    @unittest.skipIf(os.name == "nt", "POSIX symlink ownership fixture")
    def test_ownership_marker_cannot_be_a_link_to_another_file(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            work = base / "work"
            work.mkdir()
            other = put(base, "other-marker", build.MARKER_VALUE)
            (work / ".marlin-build").symlink_to(other)
            put(work, "app/keep", "keep")
            with self.assertRaises(RuntimeError):
                build.guard_workspace(work)
            with self.assertRaises(RuntimeError):
                build.reset_staging(work, "app")
            self.assertTrue((work / "app/keep").exists())

    def test_build_sources_are_fresh_and_do_not_copy_workspace_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "source"
            self.fixture(root)
            work = self.api("guard_workspace")(base / "work")
            put(work, "frontend/src/stale.ts")
            put(work, "core-build/src/stale.ts")
            self.api("stage_build_sources")(root, work)
            for folder in ("frontend", "core-build", "core-prod"):
                self.assertTrue((work / folder / "package-lock.json").is_file())
                self.assertFalse((work / folder / "node_modules").exists())
                self.assertFalse((work / folder / "dist").exists())
            self.assertFalse((work / "frontend/src/stale.ts").exists())
            self.assertFalse((work / "core-build/src/stale.ts").exists())
            self.assertTrue((work / "core-build/src/index.ts").exists())
            self.assertFalse((work / "core-prod/src").exists())

    def test_application_allowlist_uses_new_builds_and_only_production_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "source"
            self.fixture(root)
            fresh_frontend = base / "frontend-dist"
            fresh_core = base / "core-dist"
            modules = base / "production/node_modules"
            put(fresh_frontend, "index.html", "fresh frontend")
            put(fresh_frontend, "assets/main.js")
            put(fresh_frontend, "assets/main.js.map")
            put(fresh_core, "index.js", "fresh core")
            put(fresh_core, "tools/desktop-process.js")
            put(fresh_core, "tools/desktop-wire.js")
            put(fresh_core, "index.js.map")
            put(fresh_core, "index.d.ts")
            put(modules, "native-fixture/package.json", '{"name":"native-fixture","version":"1.0.0"}')
            put(modules, "native-fixture/LICENSE", "dependency notice")
            app = base / "app"
            self.api("stage_application")(root, app, fresh_frontend, fresh_core, modules)
            self.assertEqual((app / "payload/frontend/index.html").read_text(), "fresh frontend")
            self.assertEqual((app / "payload/core/dist/index.js").read_text(), "fresh core")
            self.assertTrue((app / "payload/core/dist/tools/desktop-wire.js").is_file())
            self.assertTrue((app / "payload/core/node_modules/native-fixture/LICENSE").is_file())
            self.assertTrue((app / "payload/core/dist/evaluation/LICENSE-MT19937.txt").is_file())
            self.assertTrue((app / "LICENSE").is_file())
            self.assertTrue((app / "payload/LICENSE").is_file())
            self.assertTrue((app / "icon.png").is_file())
            for name in (".env", "db.sqlite3", "manage.py", "requirements.txt", "chat", "node_modules", "payload/backend", "payload/core/src", "payload/core/dist/index.js.map", "payload/frontend/assets/main.js.map"):
                self.assertFalse((app / name).exists(), name)
            self.assertEqual(json.loads((app / "package.json").read_text())["version"], "0.6.2")

    def test_langfuse_window_helper_is_an_explicit_production_asset_without_tests(self):
        self.assertIn("langfuse.cjs", build.DESKTOP_FILES)
        self.assertIn("langfuse.cjs", build.APP_FILES)
        for excluded in ("langfuse.test.cjs", "langfuse-electron-test.cjs"):
            self.assertNotIn(excluded, build.DESKTOP_FILES)
            self.assertNotIn(excluded, build.APP_FILES)

    def test_production_dependency_validation_rejects_dev_and_wrong_versions(self):
        audit = self.api("audit_production_modules")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "source"
            self.fixture(root)
            modules = base / "node_modules"
            lock = root / "packages/core/package-lock.json"
            put(modules, "native-fixture/package.json", '{"name":"native-fixture","version":"1.0.0"}')
            audit(modules, lock)
            put(modules, "typescript/package.json", '{"name":"typescript","version":"6.0.3"}')
            with self.assertRaisesRegex(RuntimeError, "[Dd]ev|production"):
                audit(modules, lock)
            shutil.rmtree(modules / "typescript")
            put(modules, "native-fixture/package.json", '{"name":"native-fixture","version":"wrong"}')
            with self.assertRaisesRegex(RuntimeError, "version|lock"):
                audit(modules, lock)

    def node_archive(self, base, extra=None):
        archive = base / "node.zip"
        contents = {f"node-v22.23.2-win-x64/{name}": value for name, value in {"node.exe": b"MZsynthetic-node", "LICENSE": b"official-license-fixture", "node_modules/npm/private.key": b"not-a-runtime-file"}.items()}
        contents.update(extra or {})
        with zipfile.ZipFile(archive, "w") as bundle:
            for name, content in contents.items():
                # ZipInfo normally normalizes backslashes on Windows. Preserve
                # the malicious raw member spelling to test the validator.
                member = zipfile.ZipInfo(name)
                member.filename = name
                bundle.writestr(member, content)
        return archive

    def test_node_archive_is_pinned_and_only_binary_and_license_enter_payload(self):
        stage = self.api("stage_node")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = self.node_archive(base)
            target = base / "payload/node"
            with self.assertRaisesRegex(RuntimeError, "SHA256"):
                stage(archive, target)
            self.assertFalse(target.exists())
            with patch.object(build, "NODE_SHA256", build.digest(archive)), patch.object(build, "NODE_EXE_SHA256", hashlib.sha256(b"MZsynthetic-node").hexdigest()):
                stage(archive, target)
            self.assertEqual({p.name for p in target.iterdir()}, {"node.exe", "LICENSE", "runtime-manifest.json"})
            manifest = json.loads((target / "runtime-manifest.json").read_text())
            self.assertEqual(manifest["version"], "22.23.2")
            self.assertEqual(manifest["archive_sha256"], build.digest(archive))

    def test_node_zip_paths_are_checked_before_any_publication(self):
        stage = self.api("stage_node")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for unsafe in ("../escaped", "/absolute", "C:/unsafe", "prefix\\unsafe"):
                with self.subTest(unsafe=unsafe):
                    archive = self.node_archive(base, {unsafe: b"unsafe"})
                    with patch.object(build, "NODE_SHA256", build.digest(archive)), patch.object(build, "NODE_EXE_SHA256", hashlib.sha256(b"MZsynthetic-node").hexdigest()):
                        with self.assertRaises(RuntimeError):
                            stage(archive, base / "node")
                    self.assertFalse((base / "node").exists())
                    self.assertFalse((base.parent / "escaped").exists())

    def test_build_environment_does_not_forward_keys_or_vite_overrides(self):
        env = self.api("build_environment")(Path("C:/Build Node/node.exe"), Path("C:/Build Work"), {
            "SystemRoot": "C:/Windows", "TEMP": "C:/Temp", "USERPROFILE": "C:/Users/fixture",
            "PATH": "developer-bin", "NODE_OPTIONS": "--import poison", "OPENAI_API_KEY": "synthetic",
            "VITE_API_KEY": "synthetic", "CSC_LINK": "private.pfx", "GH_TOKEN": "synthetic",
            "ELECTRON_OVERRIDE_DIST_PATH": "untrusted-dist", "ELECTRON_MIRROR": "untrusted-mirror",
            "ELECTRON_USE_REMOTE_CHECKSUMS": "1", "electron_use_remote_checksums": "1",
            "npm_config_electron_use_remote_checksums": "1", "force_no_cache": "true",
        })
        for key in ("NODE_OPTIONS", "OPENAI_API_KEY", "VITE_API_KEY", "CSC_LINK", "GH_TOKEN", "ELECTRON_OVERRIDE_DIST_PATH",
                    "ELECTRON_MIRROR", "ELECTRON_USE_REMOTE_CHECKSUMS", "electron_use_remote_checksums",
                    "npm_config_electron_use_remote_checksums", "force_no_cache"):
            self.assertNotIn(key, env)
        self.assertNotIn("developer-bin", env["PATH"])
        self.assertTrue(env["PATH"].endswith(str(Path("C:/Windows/System32/WindowsPowerShell/v1.0"))),
                        "The Windows electron-builder module collector requires trusted PowerShell")
        self.assertEqual(env["NPM_CONFIG_USERCONFIG"], str(Path("C:/Build Work/empty.npmrc")))

    @unittest.skipIf(os.name == "nt", "Executable build-host isolation fixture uses a POSIX shebang")
    def test_node_preflight_also_discards_ambient_node_options(self):
        version = self.api("build_node_version")
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            node = put(work, "node", f"#!{sys.executable}\nimport os\nprint('v22.23.2' if 'NODE_OPTIONS' not in os.environ else 'poisoned')\n")
            node.chmod(0o700)
            with patch.dict(os.environ, {"SystemRoot": "/synthetic-system", "NODE_OPTIONS": "--import synthetic-poison", "OPENAI_API_KEY": "synthetic"}, clear=True):
                self.assertEqual(version(node, work), "v22.23.2")

    @unittest.skipIf(os.name == "nt", "Executable build-host version fixture uses a POSIX shebang")
    def test_node_preflight_rejects_versions_older_than_locked_core_tools_require(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            node = put(work, "node", f"#!{sys.executable}\nprint('v22.22.1')\n")
            node.chmod(0o700)
            with patch.dict(os.environ, {"SystemRoot": "/synthetic-system"}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "22.22.2"):
                    build.build_node_version(node, work)

    def test_python_builder_receives_nonoverlapping_payload_and_work(self):
        with tempfile.TemporaryDirectory() as directory:
            work = self.api("guard_workspace")(Path(directory) / "work")
            command = self.api("python_runtime_command")(Path("C:/Python313/python.exe"), work, Path(directory) / "source")
            payload = Path(command[command.index("--payload-dir") + 1])
            helper_work = Path(command[command.index("--work-dir") + 1])
            self.assertEqual(payload, work / "app/payload")
            self.assertFalse(payload.is_relative_to(helper_work))
            self.assertFalse(helper_work.is_relative_to(payload))
            self.assertNotIn("--prepare-only", command)

    def test_manifest_hashes_staged_files_and_not_environment_or_user_data(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "source"
            self.fixture(root)
            for name in ("scripts/desktop/python-runtime-lock-windows-x64.txt", "scripts/desktop/python-runtime-lock-native.txt"):
                put(root, name)
            payload = base / "payload"
            put(payload, "LICENSE")
            staged = put(payload, "frontend/index.html", "fresh")
            build.copy_source(root / 'desktop/runtime-bootstrap.cjs', payload / build.PHYSICAL_BOOTSTRAP)
            manifest = self.api("write_manifest")(root, payload)
            self.assertEqual(manifest["files"]["frontend/index.html"], build.digest(staged))
            self.assertEqual(manifest["versions"]["desktop"], "0.6.2")
            self.assertNotIn("synthetic-private", json.dumps(manifest))
            self.assertNotIn("source-manifest.json", manifest["files"])

    def test_pipeline_orders_real_builds_and_never_publishes_or_rewrites_locks(self):
        # The runner replaces unavailable Win tools/network, not business code.
        # This checks packaging orchestration; actual NSIS is separate Windows QA.
        for prepare_only, mutate_after_nsis in ((True, False), (False, False), (False, True)):
            with self.subTest(prepare_only=prepare_only, mutate_after_nsis=mutate_after_nsis), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                root = base / "source"
                self.fixture(root)
                for name in ("scripts/desktop/python-runtime-lock-windows-x64.txt", "scripts/desktop/python-runtime-lock-native.txt"):
                    put(root, name)
                work = build.guard_workspace(base / "work")
                archive = self.node_archive(base)
                calls = []
                locks = {name: (root / name / "package-lock.json").read_bytes() for name in ("desktop", "packages/core", "frontend")}

                def runner(command, cwd, env=None, timeout=None):
                    command = [str(value) for value in command]
                    cwd = Path(cwd)
                    calls.append((command, cwd))
                    if any(value.endswith("build-runtime-job.py") for value in command):
                        self.runtime_job_fixture(root, work)
                    if "ci" in command:
                        self.assertEqual("--ignore-scripts" in command, cwd.name in {"core-build", "core-prod"},
                                         "Only the pinned core packages bypass npm10's false default node-gyp detection")
                        if cwd.name == "app":
                            # Electron 44.7.0 publishes install.js as a bin but
                            # has no npm postinstall. A real clean ci leaves no
                            # executable until that official installer runs.
                            put(cwd, "node_modules/electron/package.json", '{"version":"44.7.0"}')
                            put(cwd, "node_modules/electron/install.js", "official installer fixture")
                    if command[-1] == str(work / "app/node_modules/electron/install.js"):
                        self.assertEqual(cwd, work / "app")
                        self.electron_fixture(cwd)
                    if command[-2:] == ["run", "test:unit"]:
                        self.assertEqual(env.get("NODE_OPTIONS"), "--experimental-strip-types",
                                         "Existing TS unit imports must use only the trusted type stripping flag")
                        self.assertEqual(env.get("PLAYWRIGHT_BROWSERS_PATH"), str(work / "playwright-browsers"))
                    if command[-2:] == ["run", "build"]:
                        if cwd.name == "frontend":
                            put(cwd, "dist/index.html", "fresh")
                        else:
                            for name in ("index.js", "tools/desktop-process.js"):
                                put(cwd, "dist/" + name)
                    if cwd.name == "core-prod":
                        put(cwd, "node_modules/native-fixture/package.json", '{"name":"native-fixture","version":"1.0.0"}')
                    if any(value.endswith("build-python-runtime.py") for value in command):
                        put(work, "app/payload/python/python.exe")
                        put(work, "app/payload/python/LICENSE.txt")
                        self.verification_fixture(root, work)
                    if any(value.endswith("verify-payload.cjs") for value in command):
                        put(work, "verification-data/marlin.sqlite3", "synthetic disposable check")
                        self.verification_fixture(root, work)
                    if any(value.endswith("windows-gates.py") for value in command):
                        put(work, "windows-gates.json", json.dumps(self.good_gate(root, work)))
                    if any(value.replace("\\", "/").endswith("electron-builder/cli.js") for value in command):
                        put(work, "app/release/Marlin-Setup-0.6.2-x64.exe", "synthetic installer fixture")
                        if mutate_after_nsis:
                            put(root, "frontend/src/main.ts", "source changed while NSIS ran")
                    if any(value.endswith("audit-asar.cjs") for value in command):
                        put(work, "asar-audit.json", '{"state":"verified"}')
                    if any(value.endswith("verify-packaged-runtime.cjs") for value in command):
                        self.assertEqual(command[0], str(work / 'app/node_modules/electron/dist/electron.exe'))
                        self.assertNotIn('ELECTRON_RUN_AS_NODE', env)
                        self.assertEqual(command[command.index('--fixture') + 1], str(work / 'packaged-runtime-fixture'))
                        report = self.packaged_report(root, work)
                        put(work, 'packaged-runtime.json', json.dumps(report))
                    return subprocess.CompletedProcess(command, 0)

                with patch.object(build, "run", runner), patch.object(build, "run_owned", lambda command, cwd, env, timeout, log, root: runner(command, cwd, env, timeout)), patch.object(build, "download_node", return_value=archive), patch.object(build, "NODE_SHA256", build.digest(archive)), patch.object(build, "NODE_EXE_SHA256", hashlib.sha256(b"MZsynthetic-node").hexdigest()), patch.dict(os.environ, {"SystemRoot": "C:/Windows"}, clear=True), redirect_stdout(io.StringIO()):
                    if mutate_after_nsis:
                        with self.assertRaisesRegex(RuntimeError, "Source"):
                            build.build_windows(root, work, base / "build/node.exe", base / "build/npm-cli.js", base / "cache", base / "output", prepare_only)
                        self.assertFalse((base / "output/Marlin-Setup-0.6.2-x64.exe").exists(), "Do not publish a stale source artifact")
                        continue
                    result = build.build_windows(root, work, base / "build/node.exe", base / "build/npm-cli.js", base / "cache", base / "output", prepare_only)
                commands = [command for command, _ in calls]
                browser = next(i for i, command in enumerate(commands)
                               if command[-3:] == ["install", "chromium", "--only-shell"])
                self.assertLess(browser, next(i for i, command in enumerate(commands) if command[-2:] == ["run", "test:unit"]))
                self.assertLess(next(i for i, (command, cwd) in enumerate(calls) if cwd.name == "frontend" and command[-2:] == ["run", "build"]), next(i for i, (command, cwd) in enumerate(calls) if cwd.name == "core-build" and command[-2:] == ["run", "build"]))
                self.assertTrue(any("--omit=dev" in command and cwd.name == "core-prod" for command, cwd in calls))
                for folder in ("core-build", "core-prod"):
                    native = next(i for i, (command, cwd) in enumerate(calls)
                                  if cwd.name == folder and command[-1] == str(work / folder / "scripts/prepare-native.mjs"))
                    install = next(i for i, (command, cwd) in enumerate(calls) if cwd.name == folder and "ci" in command)
                    self.assertGreater(native, install)
                    self.assertLess(native, next(i for i, (command, _) in enumerate(calls)
                                                if any(value.endswith("verify-payload.cjs") for value in command)))
                self.assertTrue(any(any(value.replace("\\", "/").endswith("node/node.exe") for value in command) and any(value.endswith("verify-payload.cjs") for value in command) for command in commands))
                addon_build = next(i for i, command in enumerate(commands) if any(value.endswith("build-runtime-job.py") for value in command))
                self.assertLess(addon_build, next(i for i, command in enumerate(commands) if any(value.endswith("verify-payload.cjs") for value in command)))
                self.assertEqual(commands[addon_build][commands[addon_build].index("--node-executable") + 1], str(work / "app/payload/node/node.exe"))
                builder = [command for command in commands if any(value.replace("\\", "/").endswith("electron-builder/cli.js") for value in command)]
                self.assertEqual(len(builder), 0 if prepare_only else 1)
                if builder:
                    self.assertEqual(builder[0][-5:], ["--win", "nsis", "--x64", "--publish", "never"])
                    audit = next(i for i, command in enumerate(commands) if any(value.endswith('audit-asar.cjs') for value in command))
                    packaged = next(i for i, command in enumerate(commands) if any(value.endswith('verify-packaged-runtime.cjs') for value in command))
                    self.assertLess(audit, packaged)
                app_ci = next((i for i, (command, cwd) in enumerate(calls) if cwd.name == "app" and "ci" in command), None)
                self.assertIsNotNone(app_ci, "prepare-only must install its Electron development shell")
                electron_install = next((i for i, command in enumerate(commands)
                                         if command[-1] == str(work / "app/node_modules/electron/install.js")), None)
                self.assertIsNotNone(electron_install, "Electron 44's official install.js must run explicitly after clean ci")
                native_gate = next((i for i, command in enumerate(commands) if any(value.endswith("windows-gates.py") for value in command)), None)
                self.assertIsNotNone(native_gate, "The repository entry must execute the real Windows gates")
                self.assertLess(app_ci, electron_install)
                self.assertLess(electron_install, native_gate, "prepare-only must prepare Electron before its controlled gate")
                self.assertTrue((work / "app/node_modules/electron/dist/electron.exe").is_file())
                self.assertFalse((work / "verification-data").exists())
                self.assertFalse((work / "app/payload/backend").exists())
                self.assertTrue(result.exists())
                for name, before in locks.items():
                    self.assertEqual((root / name / "package-lock.json").read_bytes(), before)
                if not prepare_only:
                    self.assertTrue((base / "output/Marlin-Setup-0.6.2-x64.exe.sha256").is_file())
                    self.assertTrue((base / 'output/Marlin-Setup-0.6.2-x64-packaged-runtime.json').is_file())

    def native_node(self):
        node = os.environ.get("MARLIN_TEST_NODE") or shutil.which("node")
        self.assertTrue(node, "Pinned Node is required for the real native probe")
        return node

    def probe_app(self, base):
        if os.name == "nt":
            value = os.environ.get("MARLIN_TEST_APP_DIRECTORY")
            self.assertTrue(value, "Set MARLIN_TEST_APP_DIRECTORY to the owned prepared Windows app, never QA")
            app = Path(value)
            self.assertEqual((app.parent / ".marlin-build").read_text(encoding="utf-8"), build.MARKER_VALUE)
            self.assertEqual(build.digest(app / "payload/node/node.exe"), build.NODE_EXE_SHA256)
            return app
        app = base / "app"
        (app / "payload/node/bin").mkdir(parents=True)
        shutil.copy2(build.ROOT / "desktop/runtime.cjs", app / "runtime.cjs")
        shutil.copy2(build.ROOT / "desktop/owned-runtime.cjs", app / "owned-runtime.cjs")
        shutil.copy2(build.ROOT / "desktop/runtime-bootstrap.cjs", app / "runtime-bootstrap.cjs")
        (app / "payload/core").symlink_to(build.ROOT / "packages/core", target_is_directory=True)
        (app / "payload/node/bin/node").symlink_to(self.native_node())
        return app

    def test_native_probe_exercises_actual_sqlite_fts_vec_and_60bit_ids(self):
        helper = build.ROOT / "scripts/desktop/verify-payload.cjs"
        self.assertTrue(helper.is_file(), "Packaging must verify the runtime's native database")
        core = Path(os.environ.get("MARLIN_TEST_CORE_DIRECTORY", str(build.ROOT / "packages/core")))
        self.assertFalse(os.name == "nt" and str(core).startswith("\\\\"), "Windows native tests require Windows-built local production modules")
        command = [self.native_node(), "-e", "require(process.argv[1]).probeNative(process.argv[2],process.platform).then(value=>console.log(JSON.stringify(value))).catch(error=>{console.error(error.message);process.exitCode=1})", str(helper), str(core)]
        completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
        result = json.loads(completed.stdout)
        self.assertEqual(result["fts_id"], result["vector_id"])
        self.assertGreater(int(result["vector_id"]), 2**53)
        self.assertEqual(result["vector_version"], "v0.1.9")
        self.assertEqual(result["paid_model_calls"], 0)

    def test_ipc_probe_consumes_the_actual_core_capabilities_envelope(self):
        helper = build.ROOT / "scripts/desktop/verify-payload.cjs"
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            app = self.probe_app(base)
            command = [self.native_node(), "-e", "require(process.argv[1]).probeIpc(process.argv[2],process.argv[3]).then(value=>console.log(JSON.stringify(value))).catch(error=>{console.error(error.message);process.exitCode=1})", str(helper), str(app), str(base / "isolated-data")]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=45)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(result["runtime"], "typescript")
            self.assertTrue(result["setup_required"])
            self.assertEqual(result["exit_code"], 0)
            self.assertTrue((base / "isolated-data/marlin.sqlite3").is_file())

    def test_ipc_verification_refuses_a_nonempty_data_directory_before_opening_db(self):
        helper = build.ROOT / "scripts/desktop/verify-payload.cjs"
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            app = self.probe_app(base)
            protected = base / "synthetic-nonempty-data"
            put(protected, "keep.txt", "keep")
            command = [self.native_node(), "-e", "require(process.argv[1]).probeIpc(process.argv[2],process.argv[3]).catch(error=>{console.error(error.message);process.exitCode=1})", str(helper), str(app), str(protected)]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=45)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("empty", completed.stderr)
            self.assertEqual((protected / "keep.txt").read_text(), "keep")
            self.assertFalse((protected / "marlin.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
