# Ragas bytecode inventory regression — 2026-10-10

The frozen bridge can mutate a strict packaged runtime inventory by creating Python bytecode caches. This was reproduced without model requests, user data, GUI, or writes to a formal stage. Product sources and official tests remain unchanged pending root's explicit source-update timing.

Reviewed complete `src/evaluation/ragas.ts`, `src/tools/python-env.ts`, the actual evaluation tests, worker and worker boundary tests. Frozen Ragas source SHA-256: `1817938751761881c7c2786f64495708195a2836488a32551c0f3a08d12d0705`; environment helper: `0d5cf252430da1cc817474784a12927f4fda44a5b5c03a8b6317f1d3cb5f277f`.

`RagasBridge` uses `['-u', workerPath]`. The sanitized environment has no bytecode-disable setting. The worker's audit hook prohibits business DB files/SQLite, direct network and subprocesses; it does not prohibit `.pyc`. A normal writable dependency import can therefore add a cache file. Existing precompiled caches can hide this until an uncached import occurs. Launcher strict inventory should continue rejecting mutations; do not allowlist/delete caches to conceal the defect.

Actual controlled evidence:

| Platform / path | Frozen launch | Only CLI `-B` changed |
|---|---|---|
| Linux, actual frozen TS `RagasBridge`, CPython 3.8.10 executable and complete stdlib copied into owned `/dev/shm` tree | Protocol completed, `dont_write_bytecode=false`; added `__pycache__/owned_fixture_module.cpython-38.pyc`; unchanged-inventory assertion **RED** | Real same helper/module import completed, `dont_write_bytecode=true`; no files added; assertion **GREEN** |
| Native Windows, 3.13.16 embeddable executable/DLL/stdlib zip/`_pth` copied into independent owned temporary tree; exact frozen Python CLI shape, private JobObject | `isolated=1`, `ignore_environment=1`, `dont_write_bytecode=false`; added `__pycache__/owned_fixture_module.cpython-313.pyc`; unchanged-inventory assertion **RED** | `dont_write_bytecode=true`, same isolated flags; no files added; assertion **GREEN** |

Linux command: `node --import <core>/node_modules/tsx/dist/loader.mjs --test /tmp/marlin-ragas-bytecode-regression-20261010.mjs`. Two cases: one RED and one candidate GREEN, exit `1`. [Facts](20261010-ragas-bytecode-parser-worker-linux.json), [raw TAP](20261010-ragas-bytecode-parser-worker-linux.tap).

Windows command: `C:\Python313\python.exe -I -B <owned UNC temporary probe> <repository UNC>`. The host probe copies only runtime binaries/zip/`_pth`, executes exclusively the owned copy under `windows-job.run_owned` with 15-second bounds and no inherited provider credentials, and removes the copied tree after use. Two inventory regression assertions: one RED and one candidate GREEN, exit `1`; three concrete CLI observations including an environment-only diagnostic are retained in [native facts and raw unittest result](20261010-ragas-bytecode-parser-worker-windows.json). This proves the interpreter/CLI boundary, not an additional compiled Windows `RagasBridge` or real Ragas scoring run.

An initial diagnostic assumed `_pth`'s `ignore_environment=1` would suppress `PYTHONDONTWRITEBYTECODE=1`; that assertion failed. Actual 3.13.16 accepted the variable and suppressed writes. The diagnostic was corrected to record this observed behavior; the final evidence does not claim environment-only suppression is ineffective. Explicit `-B` remains the smallest unambiguous launch-local fix without changing the shared environment helper.

Proposed production edit, once root authorizes a new source snapshot: change only the Ragas spawn arguments to `['-B', '-u', this.options.workerPath]`. Preserve protocol, timeout, cancellation, owned supervision and environment. An independent new test template is `/tmp/marlin-evaluation-bytecode-test-20261010.ts` for later placement at `packages/core/test/evaluation-bytecode.test.ts`: it performs an actual Python module import with Chinese/non-BMP text, compares the complete worker file path/hash inventory before/after, and asserts `sys.dont_write_bytecode` is true. Windows acceptance must supply an independent owned helper via `MARLIN_TEST_PYTHON`; it must not execute against a frozen packaged runtime before the fix.

All model calls in this investigation: `0`. Linux and native temporary helper/worker trees were removed by test cleanup; standalone handoff scripts will be deleted after root consumes the candidate test template. No formal source/inventory, user QA, passwords or credentials were changed or read.
