# Frozen startup fixes: independent recheck — 2026-10-10

Read-only parser_worker review. The three earlier reproduced gaps no longer reproduce in the frozen revision. No new unresolved defect was reproduced. This report preserves the original RED review at [final-startup-review](20261010-final-startup-review.md); it does not overwrite that history.

## Scope and identities

Complete reads: launcher, startup tests, fixed Windows PowerShell supervisor, actual desktop runtime, root package commands and the updated startup plan. Builder formal gate/distribution fields had just been independently reviewed in [Windows builder review](20261010-final-windows-builder-review.md).

| File | SHA-256 |
| --- | --- |
| `package.json` | `7ebaa45c538eb88b4222bd53372116a53a7333fd6077e290960150061856baca` |
| `scripts/desktop/start-desktop.cjs` | `ee576cb58d9385fadb1600f183164f8e541b9284d8a3aed17ff4c6cc919c7078` |
| `scripts/desktop/startup.test.cjs` | `69c5d09ce3ee2c9d370c49a10e2b79190851732ac6fcf92e6a988e08e34f6da1` |
| `scripts/desktop/windows-launch-supervisor.ps1` | `f647757e1310962feb1a89879433989a1ba03cf03ee7c88e5490169c49f0084e` |

Hashes matched the owner freeze and were checked again before this report. No production/test/package changes were made.

## Fresh minimal reproduction

```text
node --test --test-name-pattern='formal gate semantics reject rebound SHA: (unknown-format|artifact-only)|Electron full distribution rejects executable-bytes|POSIX cancellation' scripts/desktop/startup.test.cjs
```

Exit 0: 4 tests, 4 pass, 0 fail, 0 skip, 2861.446824 ms. Synthetic formal gate fixtures exercise actual production preflight and assert zero spawn on invalid reports/Electron changes; they are not assertions that native gates ran. The POSIX case actually starts an owned group with a TERM-resistant descendant, then cancels after its readiness handshake. The launcher waits for the force cleanup after the leader exits, returns 143, confirms the descendant is no longer active and preserves a separate unrelated fixture child. Normal CLI still refuses POSIX, so this is a cancellation regression on the test-injected runtime, not Windows Electron acceptance.

```text
TAP version 13
# Subtest: formal gate semantics reject rebound SHA: unknown-format
ok 1 - formal gate semantics reject rebound SHA: unknown-format
  ---
  duration_ms: 83.38606
  type: 'test'
  ...
# Subtest: formal gate semantics reject rebound SHA: artifact-only
ok 2 - formal gate semantics reject rebound SHA: artifact-only
  ---
  duration_ms: 59.005374
  type: 'test'
  ...
# Subtest: Electron full distribution rejects executable-bytes before spawn
ok 3 - Electron full distribution rejects executable-bytes before spawn
  ---
  duration_ms: 52.175235
  type: 'test'
  ...
# Subtest: POSIX cancellation retains owned group cleanup after the leader exits while an unrelated child survives
ok 4 - POSIX cancellation retains owned group cleanup after the leader exits while an unrelated child survives
  ---
  duration_ms: 2499.087979
  type: 'test'
  ...
1..4
# tests 4
# suites 0
# pass 4
# fail 0
# cancelled 0
# skipped 0
# todo 0
# duration_ms 2861.446824
```

The launcher now checks formal verified/frozen_source/report semantics and all referenced native/Python/Langfuse facts after hashes, plus source/desktop/output bindings. Actual full Electron distribution bytes must equal both gate and prepared distribution maps. Unknown/failed/artifact-only and incomplete evidence cannot authorize spawn merely by rebinding a report hash.

## Windows evidence and supervisor structure

Independently read the complete [original Windows five-case TAP](20261010-startup-review-fix-windows-green.tap) and [typed evidence summary](20261010-startup-review-fix-summary.json). Recomputed every raw report SHA-256 and byte size: red, gate_green, facts_green, windows_red, linux_green and windows_green all match. The existing Windows TAP records 5/5, zero skips, 9755.4347 ms. This recheck did not rerun those five tests.

Recorded actual Windows facts, with their original scope retained:

- Native private Job cancellation returns 143; owned leader and TERM-resistant descendant dead, separate unrelated child alive; cleanup observed 41 ms.
- Native leader early exit returns 7; owned descendant dead, unrelated child alive; cleanup observed 26 ms.
- Literal Chinese/space/shell/quote argv, stdout, stderr and exit code are preserved; fixture poison environment fields and ambient PATH are absent.
- Only isolated helper copies inject real Win32 CreateJob/Assign failures. Both return 125 and do not execute the suspended child's marker.

Complete PS source inspection confirms a fixed private stdin protocol and Electron location, bounded argv/environment, CREATE_SUSPENDED then JobObject assignment before ResumeThread, no breakaway, KILL_ON_JOB_CLOSE and retained exact process/thread handles. CANCEL or stdin EOF and parent early exit all finish the same Job and wait for active count zero. Failure cleanup never resumes an unassigned child. No PID-name/port search or unrelated process kill is used. The Node supervisor cleanup timer produces an error rather than claiming successful cleanup if its deadline expires. General arbitrary-command or platform-bypass CLI options were not added.

The Windows evidence uses an isolated official Node fixture copied to the Electron location; it proves native process ownership/rollback, not Electron GUI or product latency. Its original RED proves absent helper tests, not an old Windows taskkill failure. No private QA data, protected existing Windows PIDs, GUI or vendor service was touched in this review.

## Remaining acceptance boundary and cleanup

Fresh-source prepare, actual Electron smoke, NSIS installation/uninstallation and real GUI/vendor acceptance remain separately owned stages. Local SHA/report schemas provide consistency, not signatures against an actor able to rewrite all local source/evidence. No full startup ninety-case suite or complete product suite was repeated here.

The own temporary minimal TAP was removed after inclusion in this report. No fixture scripts/processes were left by this review. No production edits, commits or pushes.
