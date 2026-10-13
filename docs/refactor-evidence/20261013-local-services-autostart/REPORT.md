# Langfuse development autostart migration — code complete, deployment gates pending

2026-10-13. Root selected and authorized the single CoreOwner design in [AUTOSTART-GAP.md](../20261013-legacy-retirement-prepare/AUTOSTART-GAP.md). Implementation and controlled Linux protocol acceptance are complete. This report does **not** claim actual Docker/Langfuse deployment, Orca settings acceptance, native Windows acceptance or legacy retirement.

## Result and scope

The development CLI now calls the private Owner startup method after Owner ready and before HTTP listen. It applies the same Owner's persisted global integration settings. Desktop never calls it: an actual desktop subprocess with saved autostart=true and environment true recorded zero CLI calls and no startup cache.

Seven production files changed: `application.ts`, `runtime/owner-contracts.ts`, `runtime/owner-client.ts`, `runtime/owner-host.ts`, `tools/dev-server.ts`, new `integrations/local-services.ts`, and the narrowly approved `jobs/owned-process.ts` extension. Root explicitly authorized that last extension after inspection: optional `discardOutput` drains pipes without storing output or applying the capture limit; default capture, limits, supervisors, timeout/cancel and ownership remain unchanged. Seven new test/fixture files complete the 14-file code scope.

[Reviewable code diff](code-complete.diff), [exact scoped source SHA](source-bindings.json), [323-file Core source snapshot](core-source-inputs.json), [delta against the earlier 315-file validation](core-source-delta.json). The delta is exactly 6 modified existing files and 8 added files; no removed files or unexpected modifications in that baseline. New service SHA256: `3bcf20483cb30e203c54ad62aae5e36a3b15d7a25dd0ab6cf2eef200c32eee18`.

No commit/stage/Git mutation, dependency or lockfile change, schema change, frontend/desktop source edit, main reporting document edit, old-file removal, actual Key/account/device/document modification, actual .env read or Docker command occurred. All integration accounts/passwords and configuration files used by tests are synthetic and disposable. Existing port 8000 and 5173 services were not touched.

## Preserved behavior and lifecycle

- Default-off and external API return without CLI execution or startup cache creation. Tracing enabled and UI URL do not gate startup. Boolean environment values accept true/1/yes/on with whitespace/case normalization.
- Nonempty environment wins. API precedence is BASE_URL, saved base_url, HOST, then localhost default. Timeout is decimal float, invalid/nonfinite fallback 45, clamped 1–120; JavaScript-only hexadecimal syntax is rejected to retain float parsing semantics.
- The private OwnerCall contains only operation and absolute sourceRoot. Trusted dev `--source-root` optionally selects a separate source directory; by default it uses the repository root derived from the tool's location. It does not change the required explicit data-root.
- A dedicated `dataRoot/.cache/langfuse/startup-lock.sqlite3`, timeout:0, BEGIN IMMEDIATE connection holds a real OS lock across the startup. Rollback/close releases it; actual killed holder process tests demonstrate crash release. No business transaction is held across await and no marker-file lock is used.
- One performance.now deadline covers directory/lock wait, executable resolution, config, up and health. Grant never resets it; every next step checks remaining budget. CLI timeout uses that remainder. Native GET health uses the API base, bypasses proxies, follows no redirect, caps each probe at min(2s, remainder), and accepts only real HTTP200.
- Two fixed shell-free compose argv use sourceRoot .env/compose and cwd. A config failure prevents up. The resolver checks only Docker/docker.exe on absolute deployment PATH entries; missing candidates are docker_unavailable, access/isolation failures are startup_failed. Raw stderr, command output and credentials never enter state/logs.
- Fixed results: disabled, external, healthy, missing_server_configuration, docker_unavailable, compose_failed, startup_timeout, startup_failed, cancelled. Non-early diagnostics atomically replace startup.json under dataRoot, including lock waiter timeout. Environment configuration must be a regular readable file.
- Signal guards are installed before the optional long startup. Cancellation and app.close abort pending lock/network/CLI work and await the owned process tree's terminal state. Work budget is never enlarged to accommodate cleanup; the existing supervisor's bounded terminal cleanup can follow budget expiration. No compose down, volume deletion, port/name-based process kill or external-service cleanup exists.
- Nonfatal service states still allow business HTTP startup; an actual occupied HTTP port still correctly exits 1. A renderer invoke startup path gets 404, a malformed direct invoke gets 400, forged private extra argv gets invalid_owner_call, and an ordinary user saving global settings gets 403.

## Actual verification

Commands ran in `packages/core`; every underlying exit was saved separately, and counts below come from terminal TAP summaries. [Machine results](validation-results.json).

| Check | Actual result | Evidence |
| --- | --- | --- |
| Existing real dev entry, saved opt-in | RED: HTTP200, 0 CLI, no state; expected 2 calls | [log](dev-red.log), [exit1](dev-red.exit) |
| New service before implementation | RED: 0/11, 11 expected missing-service failures | [log](service-red-fixed.log), [exit1](service-red-fixed.exit) |
| Trusted Owner method before wiring | RED: 0/1 | [log](owner-red.log), [exit1](owner-red.exit) |
| Dev/desktop protocol before wiring | RED: 0/3 | [log](dev-entry-red.log), [exit1](dev-entry-red.exit) |
| Config-directory, lock-waiter state, HTTP port error regressions | RED 0/3, GREEN 3/3 | [RED](edge-red.log), [GREEN](edge-green.log) |
| Large real stdout/stderr | RED 2 failures/1 baseline pass; GREEN 5/5 incl timeout/cancel tree | [RED](output-red.log), [GREEN](output-green.log) |
| Float hexadecimal rejection | RED 0/1; included in final service GREEN | [RED](float-parser-red.log), [final](service-owner-output-final.log) |
| Deadline-reset mutation in repository-external disposable copy | RED 0/1: mutant returns healthy after grant; production GREEN1/1 | [RED](lock-budget-mutation-red.log), [GREEN](lock-budget-production-green.log), [scope/cleanup](lock-budget-mutation.json) |
| Related Core regression set | exit0, 62/62, 0 skip | [log](focused-final.log), [exit](focused-final.exit) |
| Final service/Owner/output after float fix, added raw-call/nonadmin/grant assertions | exit0, 18/18, 0 skip | [log](service-owner-output-final.log), [exit](service-owner-output-final.exit) |
| Final Core typecheck | exit0 | [log](typecheck-code-complete.log), [exit](typecheck-code-complete.exit) |
| Final fresh Core build | exit0 | [log](build-code-complete.log), [exit](build-code-complete.exit) |
| Plain Node compiled acceptance, no tsx loader | prior dist RED0/2, fresh final dist GREEN2/2, exit0, 0 skip | [RED](compiled-red.log), [GREEN](compiled-code-complete.log), [exit](compiled-code-complete.exit) |

The 62-test command includes local-services tests, Owner/dev/output tests and existing owner, private transport, health, stream, shutdown-failure and jobs tests. The final 18-test run reruns affected service/Owner/output cases after the decimal parsing fix and adds the grant-budget case. These are overlapping checks, not additive unique pass counts. The earlier full 698-test result belongs to the prior source iteration and is not presented as validation of this change; the full suite was not repeated.

Real dev protocol acceptance observed config/up with exact argv/cwd, loopback health200 before HTTP200, explicit env false overriding saved true with no cache/CLI, compose/missing-config/missing-Docker states with HTTP200, desktop zero CLI, and SIGTERM during a long config helper canceling the owned CLI/descendant before HTTP listen. Compiled acceptance repeats Owner persistence/nonfatal HTTP and compiled real dev fixed CLI/health success.

Initial harness mistakes are retained, not counted as business evidence: the first service RED harness opened a health listener before checking module presence, then was terminated and corrected; source-file creation was twice attempted from the wrong cwd. `lock-grant-green.log` matched no individual test and is excluded; only `lock-grant-actual-green.log` and the later production/mutation runs count. Initial typecheck failures (mixed ||/?? syntax and decrypt return narrowing) were fixed before the canonical final checks.

## Cleanup and remaining gates

All CLI, bystander, dev, desktop and lock-holder children are created by these tests and stopped through their owned handles. Terminal exit is awaited before removing the exact temporary directory. Own helpers use `marlin-local*`, `marlin-dev-entry*`, `marlin-autostart-red*`, `marlin-lock-budget-mutation*` directories. The initial `/tmp/marlin-autostart-red.mts` and repository-external mutation sources were removed after use; no temporary directory with those prefixes or matching helper process remained at final observation. [Cleanup and artifact checks](final-review-checks.json).

The actual service tests execute controlled Node CLI protocol fixtures and real loopback HTTP servers. They do not prove Docker Compose compatibility, image pulls, pinned Langfuse services or persistence of containers/volumes. Root must run the isolated real project acceptance described in AUTOSTART-GAP, then the actual Orca administrator save/restart flow. Keep all old 10 files and the historical Windows/source freezes intact until those gates are satisfied.

[Native Windows gate](NATIVE-WINDOWS-GATE.md) is an executable acceptance procedure, not a Linux emulation or Windows PASS. SQLite process locks/crash release and actual Job Object helper startup/cancel/timeout must run on native Windows. This source iteration also requires a new Windows build/source-input iteration; the original dd5 package is unchanged and does not contain this feature.

## Iteration 2 addendum — independent review fixes supersede the first snapshot

The independent review reproduced R1 (PATH candidate work continued after deadline/cancel) and R2 (valid Python float underscores/Unicode decimal digits fell back to 45). Root authorized fixes within the existing service ownership. Current implementation adds resolver checks using the original remaining budget/signal and preserves finite Python decimal syntax. No other production file changed in this iteration.

[Iteration 2 report](iteration-2/REPORT.md), [review-fix delta](iteration-2/review-fixes.diff), [current full diff](iteration-2/code-complete.diff), [current source SHA](iteration-2/source-bindings.json) supersede the first code-complete snapshot above; its historical source bindings, failures and results remain untouched. Core source count is now 324, with 6 existing modified and 9 added files across the migration.

Actual new evidence: targeted RED0/6→GREEN6/6; original reviewer script replay GREEN3/3; related service/Owner/dev/output GREEN28/28; typecheck/build exit0; fresh plain compiled GREEN2/2. These are overlapping checks, not additive unique counts, and the old 62/18 results do not validate the two review fixes. Installed fs stat/access cannot abort the current request; the resolver stops traversal immediately when it completes, with no budget reset. Deployment/native gates remain pending and the old 10 files stay preserved.

The first iteration-2 complete diff was subsequently found to omit the six existing modified paths because its generator read only the unstaged view. It is preserved as [incomplete previous package](iteration-2/incomplete-previous-code-complete.diff). The [corrected complete package](iteration-2/code-complete.diff) now covers all 15 scoped paths, verified against task-before source SHA and current bindings with [per-path reconstruction proof](iteration-2/code-complete-path-manifest.json). This evidence-only correction changed no source, tests, dependencies or index and did not rerun tests.
