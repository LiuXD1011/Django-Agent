# WIN-ASAR-BOOTSTRAP-001 packaging implementation

2026-10-13, Linux implementation and related verification. This report covers the eight explicitly assigned build/gate/test paths only. It does not claim target Windows, installer, renderer, normal startup, or full Goal acceptance. The earlier installed normal launch FAIL and probe48236 result remain unchanged.

## Result and source

The builder now copies `desktop/runtime-bootstrap.cjs` byte-for-byte to payload `owned-runtime/runtime-bootstrap.cjs`, in both fresh staging and eligible refresh. The manifest requires this resource and binds its SHA to source; inventory, startup preflight and actual ASAR audit reject missing, changed and rehashed replacement bytes. The existing 12 ASAR assets, versions, dependency policy and physical staging IPC gate remain in place. Existing stages without the required resource are rejected; none were patched by this agent.

`DESKTOP_GATE_FILES` explicitly freezes the new `desktop/packaged-bootstrap.test.cjs`. Official native Windows gates execute its two actual ASAR/external Node regression cases through a reviewed fixed-path adaptation, preserving every assertion and test count. The report labels their native/Core unit doubles. The temporary adapted executable is precisely deleted after its owned runner completes; its review archive and full log remain in `controlled-gates`.

The new build-only `scripts/desktop/verify-packaged-runtime.cjs` executes under the prepared locked official Electron 44.7.0 in main mode, with a new isolated profile and synthetic data. It requires Runtime from the actual output `app.asar`, uses actual `resources/runtime`, external bundled Node22.23.2, actual compiled Core and native Job authorization, then verifies ready, capabilities, clean stop and zero model-usage rows using readonly product SQLite. It creates no renderer window and reports no GUI/installer verdict. Ordinary Node and RunAsNode are rejected before Core.

`package_only` and full packaging invoke this gate after actual ASAR audit and before installer copying. The native Windows build-only Job runner retains the exact process tree, bounds execution at 120 seconds, establishes its terminal state and cleans its owned fixture. The report binds archive, archived Runtime, physical bootstrap, native addon, compiled Core entry, product Node, manifest, frozen source, official Electron and runner SHA. The builder records the observed runner exit code, rejects missing or invalid reports, and rechecks source and prepared gates before publishing the local output. Nonzero/timeout/missing-report unit cases preserve an unrelated sentinel and refuse stale success.

Complete starting bytes are archived in [before](before/). [Before SHA](before-sha256.json), [final scope SHA](after-sha256.json), [complete diff including new script](code-complete.diff), [Runtime and installed API bindings](source-and-api-binding.json) and [metrics](metrics.json) are independently reviewable. Only the assigned eight production/test paths were edited; Runtime and its regression belong to Root/Runtime owners.

The external Runtime bindings are `desktop/runtime.cjs` SHA `fb2b569bbb94c4237608b515d97f78914cc996322116405c1d009244414b9112` and cleanup-reviewed `desktop/packaged-bootstrap.test.cjs` SHA `46cdd96a9b4b625d0478a209b627204dc7bb8845981645695130c945cf939272`. The earlier regression SHA184 and 31-pass result are historical. Root separately reported the revised actual Node22 regression 2/2 pass, no skip, exit 0; this agent did not replay that suite. Its current fixed-path adaptation was checked after reading the complete revised file: [receipt](post-runtime-cleanup-adaptation.txt).

## Related terminal verification

| Command / scope | Actual exit | Total | Pass | Fail | Skip | Evidence |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `python -m unittest scripts.test_build_windows` | 0 | 49 | 47 | 0 | 2 | [full log](GREEN-python-verified.log), PTY 57605 terminal 0 |
| `node --test scripts/desktop/startup.test.cjs` | 0 | 135 | 130 | 0 | 5 | [full log](GREEN-startup-final.log), PTY 53003 terminal 0 |
| Four necessary final cases after readonly SQLite/helper cleanup changes | 0 | 4 | 4 | 0 | 0 | [log](GREEN-final-targeted.log) |
| Final strict integer/boolean report case | 0 | 1 | 1 | 0 | 0 | [log](GREEN-report-integer-types.log) |

The Python skips are actual Windows junction and native Win32 Job tree checks; startup's five skips are actual Windows API/supervisor cases. They remain conditional skips, not Windows PASS. Python verification includes real locked ASAR 3.4.1/FileMatcher resource copying, actual native SQLite/FTS/vec and actual compiled-Core capabilities IPC on Linux with disposable data. Its pipeline/Electron/Windows report projections are explicitly synthetic, not target execution. Node counts are the final runner totals; they are not inferred from top-level subtest labels. Repeated related samples above are not summed into a new test total.

Before production changes, [resource Python RED](RED-resource-python.log) showed two failures and [startup RED](RED-resource-node.log) showed two failures: missing/rehashed physical scripts reached the old child-launch attempt. [gate RED](RED-packaged-gate.log) showed the missing main-mode gate and official path adaptation; [report RED](RED-packaged-report.log) showed the missing strict validator. The final [integer-type RED](RED-report-integer-types.log) rejected neither false exit nor boolean protocol until strict integer checks were added; its GREEN appears above. Positive intermediate [resource Python](GREEN-resource-python.log), [resource Node](GREEN-resource-node.log), [gate](GREEN-packaged-gate.log) and [report](GREEN-packaged-report.log) receipts remain separate.

One intermediate cleanup-test run failed three synthetic outcomes because its Windows environment omitted `SystemRoot`; [failure log](INTERMEDIATE-python-cleanup-fixture-failure.log) is retained. The fixture was corrected to the existing trusted build environment; production code and assertions were not loosened. The complete corrected 49-case run exited 0.

`node --check` on the new gate, AST parsing of the affected Python files, and scope `git diff --check` exited 0. No Core full suite, Frontend full suite, Windows, Docker, GUI, Source QA DB, private auth or model invocation was run here. No Git mutation, version/dependency edit or old artifact modification occurred. Test data/helpers were self-owned; test temporary directories cleaned themselves, and no standalone temporary executable remains from this implementation turn.

## Remaining target execution and handoff

From native Windows x64 Python3.13 with the official build-host Node/npm, use a fresh owned local stage, for example:

```powershell
python scripts/build_windows.py --work-dir "D:\MarlinBuild-ASAR-Fix" --prepare-only
python scripts/build_windows.py --work-dir "D:\MarlinBuild-ASAR-Fix" --package-only --output-dir "D:\MarlinArtifacts-ASAR-Fix"
```

The first command must establish the frozen-source native/physical gates, including the new labelled ASAR/Node regression. The second performs NSIS, static actual-ASAR inventory audit, then the new actual Electron→ASAR Runtime→bundled Node→real Core/native Job dynamic gate. Success requires `PACKAGED_RUNTIME_GATE_EXIT=0` and a strictly validated `packaged-runtime.json`; archived installer companion reports include it. Both commands are examples for the authorized Windows worker, not actions executed by this agent. An old prepared payload missing the new resource must not be repaired in place to masquerade as this fresh source.

After a successful current-source build, the authorized Windows worker/Root still need isolated installation and true normal launch/login/page/tray/quit acceptance. The build-only gate does not replace those UI checks. Original normal startup remains FAIL until that independent current installer is actually tested. Cancelling or timing out this dynamic gate uses only the retained Job tree and deletes only the marker-owned fixture; existing services, original installer bytes, QA and earlier prepared autostart fixtures are outside its scope.
