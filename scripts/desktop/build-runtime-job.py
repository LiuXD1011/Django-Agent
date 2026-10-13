"""Build the NAPI8 Win32 owned-runtime adapter. Build host only; no runtime Python.

Official Node22 headers/import library are pinned against its release SHASUMS.
All compiler, identity smoke and inspection commands run in private build Jobs.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tarfile
import urllib.request


NODE_VERSION = "22.23.2"
NODE_SHA256 = "0d0f5e39f9f3d9587bc19f73eab3c2c9c4903fd02d6dbf9c853dd81b3d95fad4"
HEADERS_SHA256 = "daaf13ec5d45a38bbcfcff06d0723f72a6813b89ab27bb5af2ac8e1f6259dde0"
NODE_LIB_SHA256 = "ac15f1e9d7c8279353723a77f6319967f1a41c06026521094a8234c2e6fbe052"
SHASUMS_SHA256 = "778ac5b2fcdbd68d9c0ae9f4310674faa3af0910bd0d18e7f6597787c40a3e39"
BASE_URL = f"https://nodejs.org/download/release/v{NODE_VERSION}/"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def plain_path(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        require(not item.is_symlink() and not getattr(item, "is_junction", lambda: False)(),
                "Native build paths cannot contain links or junctions")
    return path


def download(name, destination, expected=None):
    with urllib.request.urlopen(BASE_URL + name, timeout=30) as response:
        data = response.read(32 * 1024 * 1024 + 1)
    require(len(data) <= 32 * 1024 * 1024, "Official build input exceeds its size bound")
    digest = hashlib.sha256(data).hexdigest()
    require(expected is None or digest == expected, "Official Node build input SHA256 mismatch")
    destination.write_bytes(data)
    return digest


def build(args, report):
    require(os.name == "nt", "runtime-job.node must be built on native Windows")
    source = plain_path(args.source_dir)
    work = plain_path(args.work_dir)
    output = plain_path(args.output)
    node = plain_path(args.node_executable)
    require(source.is_dir() and (source / "runtime_job.cc").is_file(), "Native source directory is incomplete")
    require(node.is_file() and sha256(node) == NODE_SHA256, "Expected official bundled Node22.23.2 x64 bytes")
    require(not work.exists(), "Native build work directory must be fresh and separate")
    require(not output.exists(), "Native build output must not overwrite an existing artifact")
    require(source not in work.parents and work not in source.parents and source != work,
            "Native build work directory must be separate from source")
    work.mkdir(parents=True)
    (work / "owner.txt").write_text("Marlin runtime-job native build only\n", encoding="utf-8")
    report["sourceFiles"] = []
    for item in sorted(source.rglob("*")):
        plain_path(item)
        if item.is_file():
            report["sourceFiles"].append({"path": item.relative_to(source).as_posix(), "size": item.stat().st_size, "sha256": sha256(item)})
    shutil.copyfile(source / "runtime_job.cc", work / "runtime_job.cc")
    runner_path = Path(__file__).with_name("windows-job.py")
    spec = importlib.util.spec_from_file_location("marlin_runtime_job_build_owner", runner_path)
    owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner)
    report["ownedRunnerSha256"] = sha256(runner_path)
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "COMSPEC", "PROGRAMDATA", "ALLUSERSPROFILE"}}
    # Setup Configuration resolves installed C++ tools through ProgramData.
    # The outer builder deliberately supplies a small environment, so obtain
    # this OS-owned folder through its public API when it was omitted.
    common_data = ctypes.create_unicode_buffer(260)
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.SHGetFolderPathW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_wchar_p]
    shell.SHGetFolderPathW.restype = ctypes.c_long
    require(shell.SHGetFolderPathW(None, 0x23, None, 0, common_data) == 0, "Cannot locate the OS ProgramData folder for C++ tools discovery")
    env["ProgramData"] = common_data.value
    env["ALLUSERSPROFILE"] = common_data.value
    env["PATH"] = str(Path(env["SYSTEMROOT"]) / "System32")
    commands = report["commands"] = []

    def run(command, name, timeout=60):
        record = {"argv": [str(value) for value in command], "log": str(work / f"{name}.log"), "exitCode": None}
        commands.append(record)
        result = owner.run_owned(command, work, env, timeout, record["log"])
        record["exitCode"] = result.returncode
        require(result.returncode == 0, f"Native build command {name} exited {result.returncode}; see its owned log")
        return result.stdout

    node_info = json.loads(run([node, "-p", "JSON.stringify({platform:process.platform,arch:process.arch,versions:process.versions})"], "node-identity"))
    require(node_info["platform"] == "win32" and node_info["arch"] == "x64" and node_info["versions"]["node"] == NODE_VERSION,
            "Actual bundled Node version/platform does not match the native build")
    report["nodeExecutable"] = {"path": str(node), "sha256": NODE_SHA256, **node_info}
    shasums = work / "SHASUMS256.txt"
    manifest_sha = download("SHASUMS256.txt", shasums, SHASUMS_SHA256)
    rows = {line.split()[1]: line.split()[0] for line in shasums.read_text(encoding="utf-8").splitlines()}
    header_name = f"node-v{NODE_VERSION}-headers.tar.gz"
    require(rows.get(header_name) == HEADERS_SHA256 and rows.get("win-x64/node.lib") == NODE_LIB_SHA256 and rows.get("win-x64/node.exe") == NODE_SHA256,
            "Official Node release SHASUMS does not match pinned native build inputs")
    archive = work / header_name
    library = work / "node.lib"
    download(header_name, archive, HEADERS_SHA256)
    download("win-x64/node.lib", library, NODE_LIB_SHA256)
    include = work / "node-headers"
    include.mkdir()
    required = {"node_api.h", "node_api_types.h", "js_native_api.h", "js_native_api_types.h"}
    with tarfile.open(archive, "r:gz") as package:
        for filename in sorted(required):
            members = [member for member in package.getmembers() if member.name == f"node-v{NODE_VERSION}/include/node/{filename}"]
            require(len(members) == 1 and members[0].isfile() and members[0].size < 1024 * 1024,
                    "Official Node-API header is missing or invalid")
            with package.extractfile(members[0]) as stream:
                (include / filename).write_bytes(stream.read())
    report["inputs"] = {"releaseUrl": BASE_URL, "headersArchiveSha256": HEADERS_SHA256,
                        "nodeLibSha256": NODE_LIB_SHA256, "shasumsSha256": manifest_sha,
                        "headers": [{"path": name, "sha256": sha256(include / name)} for name in sorted(required)]}
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
    require(vswhere.is_file(), "Visual Studio Build Tools with x64 C++ compiler are required for packaging")
    installations = json.loads(run([vswhere, "-all", "-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-format", "json", "-utf8"], "vswhere"))
    require(len(installations) == 1, "No supported C++ build tools installation was found")
    installation = Path(installations[0]["installationPath"])
    vc_version = (installation / "VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt").read_text(encoding="utf-8").strip()
    vc = installation / "VC/Tools/MSVC" / vc_version
    compiler = vc / "bin/Hostx64/x64/cl.exe"
    dumpbin = compiler.with_name("dumpbin.exe")
    sdk_root = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits/10"
    versions = [item.name for item in (sdk_root / "Include").iterdir()
                if re.fullmatch(r"10\.[0-9]+\.[0-9]+\.[0-9]+", item.name)
                and (item / "um/Windows.h").is_file() and (sdk_root / "Lib" / item.name / "um/x64/kernel32.lib").is_file()]
    require(versions, "Windows SDK x64 headers and libraries are required")
    sdk_version = max(versions, key=lambda value: tuple(map(int, value.split("."))))
    sdk_include = sdk_root / "Include" / sdk_version
    sdk_lib = sdk_root / "Lib" / sdk_version
    require(compiler.is_file() and dumpbin.is_file(), "The selected x64 C++ tools are incomplete")
    env["PATH"] = str(compiler.parent) + os.pathsep + env["PATH"]
    env["INCLUDE"] = os.pathsep.join(str(item) for item in (vc / "include", sdk_include / "ucrt", sdk_include / "shared", sdk_include / "um"))
    env["LIB"] = os.pathsep.join(str(item) for item in (vc / "lib/x64", sdk_lib / "ucrt/x64", sdk_lib / "um/x64"))
    report["compiler"] = {"path": str(compiler), "sha256": sha256(compiler), "msvcVersion": vc_version,
                          "windowsSdkVersion": sdk_version, "installationComplete": installations[0].get("isComplete")}
    target = work / "runtime-job.node"
    command = [compiler, "/nologo", "/LD", "/MT", "/O2", "/W4", "/WX", "/EHsc", "/std:c++17", "/utf-8",
               "/DNAPI_VERSION=8", "/DBUILDING_NODE_EXTENSION", "/D_WIN32_WINNT=0x0602", f"/I{include}",
               work / "runtime_job.cc", f"/Fo{work / 'runtime_job.obj'}", "/link", f"/OUT:{target}",
               "/MACHINE:X64", "/DELAYLOAD:node.exe", library, "kernel32.lib", "delayimp.lib", "/INCREMENTAL:NO"]
    run(command, "compile", 120)
    inspection = run([dumpbin, "/DEPENDENTS", target], "imports")
    imports = [line.strip() for line in inspection.splitlines() if re.fullmatch(r"\s*[a-zA-Z0-9_.-]+\.(?:dll|exe)\s*", line, re.I)]
    require(imports and all(name.casefold() in {"kernel32.dll", "node.exe"} for name in imports),
            "Native adapter unexpectedly requires a non-system runtime DLL")
    report["imports"] = imports
    smoke = work / "smoke.cjs"
    smoke.write_text("const native=require(process.argv[2]); const id=native.currentIdentity(); if(id.pid!==process.pid || typeof id.createdAt!=='string' || !/^[1-9][0-9]*$/.test(id.createdAt)) throw Error('Native identity smoke failed'); console.log(JSON.stringify(id));\n", encoding="utf-8")
    report["identitySmoke"] = json.loads(run([node, smoke, target], "identity-smoke"))
    require(report["identitySmoke"]["executable"].casefold() == str(node).casefold(), "Native identity image differs from bundled Node")
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(target, output)
    report["artifact"] = {"path": str(output), "size": output.stat().st_size, "sha256": sha256(output)}
    require(report["artifact"]["sha256"] == sha256(target), "Native output bytes changed while copying")
    require(all(sha256(source / entry["path"]) == entry["sha256"] for entry in report["sourceFiles"]), "Native build source changed during compilation")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-dir", "work-dir", "node-executable", "output", "report"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    report_path = plain_path(args.report)
    require(not report_path.exists(), "Native build report must not overwrite a previous result")
    report = {"schemaVersion": 1, "target": {"platform": "win32", "arch": "x64", "napiVersion": 8, "nodeVersion": NODE_VERSION}, "actualExitCode": 1}
    try:
        build(args, report)
        report["actualExitCode"] = 0
    except Exception as error:
        report["error"] = str(error)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"actualExitCode": report["actualExitCode"], "artifact": report.get("artifact"), "error": report.get("error")}, ensure_ascii=False))
    return report["actualExitCode"]


if __name__ == "__main__":
    sys.exit(main())
