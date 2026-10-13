"""Build-only real Windows gates. No Django, user data or paid model calls."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def tap_summary(output, minimum):
    fields = {}
    for name in ("tests", "pass", "fail", "cancelled", "skipped", "todo", "duration_ms"):
        values = re.findall(r"^# " + name + r" ([\d.]+)\s*$", output, re.MULTILINE)
        require(len(values) == 1, "Incomplete/ambiguous native test suite result")
        fields[name] = float(values[0]) if name == "duration_ms" else int(values[0])
    require(fields["tests"] >= minimum and fields["pass"] == fields["tests"] and fields["fail"] == fields["skipped"] == fields["cancelled"] == fields["todo"] == 0,
            "Native test suite failed, skipped or did not execute its required cases")
    return {"tests": fields["tests"], "passed": fields["pass"], "failed": fields["fail"],
            "skipped": fields["skipped"], "duration_ms": fields["duration_ms"]}


def runtime_fixture(original):
    """Keep the reviewed test body; adapt only its fixed module/bootstrap paths."""
    changes = (("require('./runtime.cjs')", "require('./app/runtime.cjs')", 1),
               ("require('./package.json')", "require('./app/package.json')", 1),
               ("path.resolve(__dirname, '../packages/core')", "path.resolve(__dirname, './app/payload/core')", 2),
               ("path.join(coreRoot, 'src/tools/desktop-process.ts')", "path.join(coreRoot, 'dist/tools/desktop-process.js')", 2),
               ("execArgv: ['--import', 'tsx']", "execArgv: [], nativeModulePath: path.join(__dirname, 'app/payload/owned-runtime/runtime-job.node')", 2))
    adapted = original
    for before, after, count in changes:
        require(adapted.count(before) == count, "Runtime fixture path shape changed; review its production adaptation")
        adapted = adapted.replace(before, after)
    require(adapted.count("assert.") == original.count("assert.") and adapted.count("test(") == original.count("test("),
            "Runtime fixture assertions changed")
    return adapted


def electron_fixture(original):
    before = "{ nodeExecutable, coreDirectory, entryPoint:"
    after = "{ nodeExecutable, nativeModulePath: path.join(coreDirectory, '../owned-runtime/runtime-job.node'), coreDirectory, entryPoint:"
    require(original.count(before) == 1, "Electron fixture native path shape changed; review its production adaptation")
    adapted = original.replace(before, after)
    require(adapted.count("assert.") == original.count("assert."), "Electron fixture assertions changed")
    return adapted


def validate_window_report(report, electron_version):
    fields = ("real_nextauth_protocol", "actual_private_child_json", "renderer_cookie_secret_absent", "isolated_memory_session",
              "httponly_host_only_lax", "sandbox_no_preload_node", "popups_denied", "owned_cookie_clear",
              "unrelated_browser_cookie_preserved", "public_cancel_no_window", "public_cancel_pending_navigation",
              "public_logout_clears_window", "public_configuration_change_clears_window")
    require(report.get("format") == "marlin-langfuse-native-test-v1" and report.get("state") == "verified" and
            report.get("platform") == "win32" and report.get("electron") == electron_version and
            report.get("paid_model_calls") == 0 and report.get("owned_core_exit_code") == 0 and
            report.get("foreign_project_requests") == 0 and all(report.get(name) is True for name in fields),
            "Actual controlled Electron/NextAuth gate did not verify every required boundary")


def load_module(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def execute(source, work, node, report_path, artifact_only=False):
    require(sys.platform == "win32", "Run actual gates with native Windows Python")
    build = load_module("marlin_build", Path(__file__).absolute().parents[1] / "build_windows.py")
    source, work, node, report_path = (Path(value).absolute() for value in (source, work, node, report_path))
    # Inspect caller spellings before resolve can erase a Windows junction alias.
    for value in (source, work, node, report_path):
        build.reject_links(value)
    source, work, node, report_path = (value.resolve() for value in (source, work, node, report_path))
    job = load_module("marlin_windows_job", source / "scripts/desktop/windows-job.py")
    marker = work / ".marlin-build"
    build.reject_links(marker)
    require(marker.is_file() and marker.read_text(encoding="utf-8") == build.MARKER_VALUE, "Not an owned build workspace")
    require(report_path.is_relative_to(work) and not report_path.is_relative_to(work / "app") and
            not report_path.is_relative_to(work / "python-work"), "Gate report must be outside runtime payload in the owned work directory")
    build.reject_links(report_path); report_path.unlink(missing_ok=True)
    app, payload = work / "app", work / "app/payload"
    manifest = build.verify_payload_inventory(payload)
    require(build.digest(payload / "node/node.exe") == build.NODE_EXE_SHA256, "Bundled Node pin changed")
    before = build.source_inputs(source)
    job_build_path = work / "runtime-job-build.json"; build.reject_links(job_build_path)
    runtime_job_build = build.validate_runtime_job_report(json.loads(job_build_path.read_text(encoding="utf-8")), payload, before)
    def selected_inputs(inputs):
        return {name: sha for name, sha in inputs.items() if name.startswith(("scripts/", "workers/", "desktop/")) or
                name in {"packages/core/test/" + test for test in build.CORE_GATE_TESTS}}
    if artifact_only:
        # Independent regression for an existing candidate; cannot authorize NSIS.
        before = selected_inputs(before)
    else:
        require(manifest.get("source_sha256") == before, "Gate source differs from frozen staged source")
    env = build.build_environment(node, work)
    build.build_node_version(node, work)
    directory = work / "controlled-gates"
    build.reject_links(directory)
    ownership = "marlin-controlled-build-gates-v1\n"
    if directory.exists():
        require((directory / ".owned").is_file() and (directory / ".owned").read_text(encoding="utf-8") == ownership,
                "Refusing an unowned gate fixture directory")
        shutil.rmtree(directory)
    directory.mkdir(); (directory / ".owned").write_text(ownership, encoding="utf-8")
    def run(command, cwd, label, timeout):
        result = job.run_owned(command, cwd, env, timeout, directory / (label + ".log"))
        require(result.returncode == 0, f"Actual Windows {label} gate failed (see owned fixture log)")
        print(f"WINDOWS_GATE_OK={label}", flush=True)
        return result.stdout
    entry_hash = build.digest(payload / "core/dist/tools/desktop-process.js")
    desktop_hashes = build.desktop_inventory(app)
    distribution = build.electron_distribution(app)
    for test in build.CORE_GATE_TESTS:
        build.copy_source(source / "packages/core/test" / test, work / "core-build/test" / test)
    core_tests = tap_summary(run([node, "--import", "tsx", "--test", *("test/" + name for name in build.CORE_GATE_TESTS)],
                                 work / "core-build", "core-tests", 180), 24)
    runtime_test = work / "native-desktop-runtime.test.cjs"
    build.reject_links(runtime_test)
    runtime_test.write_text(runtime_fixture((source / "desktop/runtime.test.cjs").read_text(encoding="utf-8")), encoding="utf-8")
    runtime_tests = tap_summary(run([payload / "node/node.exe", "--test", runtime_test], work, "production-runtime", 120), 6)
    checks = build.reset_staging(work, "verification-data"); checks.mkdir()
    native_report = work / "core-verification.json"
    build.reject_links(native_report); native_report.unlink(missing_ok=True)
    try:
        run([payload / "node/node.exe", source / "scripts/desktop/verify-payload.cjs", "--app", app,
             "--data-root", checks, "--report", native_report], work, "native-sqlite-ipc", 120)
    finally:
        build.reset_staging(work, "verification-data")
    native = json.loads(native_report.read_text(encoding="utf-8"))
    require(native.get("state") == "verified" and native.get("paid_model_calls") == 0 and
            native.get("native", {}).get("platform") == "win32" and native["native"].get("vector_version") == "v0.1.9" and
            native["native"].get("fts_id") == native["native"].get("vector_id") and int(native["native"]["fts_id"]) > 2**53 and
            native.get("ipc", {}).get("runtime") == "typescript" and native["ipc"].get("http_listener") is False and
            native["ipc"].get("exit_code") == 0, "Real SQLite/FTS/vector/IPC facts were not verified")
    python_report = work / "python-verification.json"
    build.reject_links(python_report); python_report.unlink(missing_ok=True)
    run([*build.python_runtime_command(sys.executable, work, source), "--verify-only"], work, "python-workers", 600)
    python = json.loads(python_report.read_text(encoding="utf-8"))
    require(python.get("state") == "verified" and python.get("paid_model_calls") == 0 and
            python.get("python", {}).get("isolated") == 1 and python["python"].get("no_site") == 1 and
            python["python"].get("django_spec") is False and python.get("django_import") == "ModuleNotFoundError" and
            len(python.get("fixtures", [])) >= 11 and python.get("ragas", {}).get("ragas_version") == "0.4.3",
            "Actual isolated Python/document/Ragas facts were not verified")
    electron_entry = directory / "electron-entry"
    for name in ("runtime.cjs", "owned-runtime.cjs", "runtime-bootstrap.cjs", "ipc.cjs", "preload.cjs", "langfuse.cjs"):
        build.copy_source(app / name, electron_entry / name)
        require(build.digest(source / "desktop" / name) == build.digest(app / name), "Electron fixture desktop source differs from staged app")
    (electron_entry / "fixture.cjs").write_text(electron_fixture((source / "desktop/langfuse-electron-test.cjs").read_text(encoding="utf-8")), encoding="utf-8")
    electron = app / "node_modules/electron/dist/electron.exe"
    require(electron.is_file(), "Prepared full Electron distribution missing")
    loader_script = directory / "owned-runtime-electron.cjs"
    loader_script.write_text("'use strict';\nconst {app}=require('electron'),fs=require('node:fs'),path=require('node:path');\n"
        "const data=path.join(__dirname,'owned-loader-data');fs.mkdirSync(data);app.setPath('userData',data);\ntry {\n"
        "const {probeOwnedRuntime}=require(process.argv[2]);\n"
        "const owned_runtime=probeOwnedRuntime(process.argv[3], 'v24.21.0');\n"
        "fs.writeFileSync(process.argv[4],JSON.stringify({format:'marlin-owned-runtime-loader-v1',state:'verified',"
        "versions:process.versions,owned_runtime,paid_model_calls:0,gui_started:false,core_started:false},null,2)+'\\n');app.exit(0);\n"
        "} catch(error) {console.error(error);app.exit(1);}\n", encoding="utf-8")
    loader_report = directory / "owned-runtime-electron.json"
    run([electron, loader_script, source / "scripts/desktop/verify-payload.cjs", payload, loader_report],
        directory, "owned-runtime-electron", 30)
    electron_loader = json.loads(loader_report.read_text(encoding="utf-8"))
    window_report = directory / "langfuse-native.json"
    # This fixture can create owned sandbox windows; it never touches QA or uses
    # the application's preload in the independent Langfuse project window.
    print("CONTROLLED_ELECTRON_FIXTURE_START", flush=True)
    run([electron, electron_entry / "fixture.cjs", directory / "electron-data", payload / "core", payload / "node/node.exe", window_report],
        electron_entry, "electron-nextauth", 90)
    print("CONTROLLED_ELECTRON_FIXTURE_END", flush=True)
    window = json.loads(window_report.read_text(encoding="utf-8"))
    metadata = json.loads((app / "package.json").read_text(encoding="utf-8"))
    validate_window_report(window, metadata["devDependencies"]["electron"])
    build.audit_production_modules(payload / "core/node_modules", source / "packages/core/package-lock.json")
    require(build.digest(payload / "core/dist/tools/desktop-process.js") == entry_hash and build.desktop_inventory(app) == desktop_hashes and
            build.electron_distribution(app) == distribution,
            "Staged code changed while gates ran")
    build.verify_payload_inventory(payload)
    after = build.source_inputs(source)
    require((selected_inputs(after) if artifact_only else after) == before, "Gate source changed during verification")
    report = {"format": "marlin-windows-build-gates-v1", "state": "verified", "scope": "artifact_only" if artifact_only else "frozen_source",
              "source_sha256": before, "source_before_after_equal": True, "core_entry_sha256": entry_hash,
              "frontend_index_sha256": build.digest(payload / "frontend/index.html"), "desktop_sha256": desktop_hashes,
              "electron_distribution": distribution,
              "core_tests": core_tests, "core_tests_scope": "staged core-build", "runtime_tests": runtime_tests,
              "native": native, "native_report_sha256": build.digest(native_report),
              "runtime_job_build": runtime_job_build, "runtime_job_build_report_sha256": build.digest(job_build_path),
              "owned_runtime_electron": electron_loader, "owned_runtime_electron_report_sha256": build.digest(loader_report),
              "python_report_sha256": build.digest(python_report), "python_fixture_count": len(python["fixtures"]),
              "langfuse_report_sha256": build.digest(window_report),
              "langfuse": window, "paid_model_calls": 0, "manual_gui_verified": False, "real_external_vendor_verified": False,
              "installer_executed": False}
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--build-node", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--artifact-only", action="store_true", help="independent existing-artifact regression; cannot authorize packaging")
    args = parser.parse_args()
    execute(args.source, args.work_dir, args.build_node, args.report, args.artifact_only)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(f"WINDOWS_GATE_ERROR={error}", file=sys.stderr)
        raise SystemExit(1)
