# Iteration 2 — independent review R1/R2 fixes

Root authorized a second scoped iteration after [independent review](../../20261013-local-services-autostart-review/REPORT.md). The review facts were verified against the actual source, installed fs types and a controlled Python float oracle. Only `packages/core/src/integrations/local-services.ts` changed in production; one regression test file was added. OwnedProcessRegistry, supervisor, Owner wiring, desktop/frontend, legacy files and dependencies were not changed in this iteration. No commit/stage occurred.

## R1: resolver deadline and cancellation

The resolver now receives the existing `remaining()` closure, which owns the original performance.now deadline and signal. It checks before each PATH candidate, after stat, after access, in the error branch before classifying missing/denied candidates, and before final classification. A late ENOENT/EACCES cannot override timeout/cancellation. The cutoff is never reset and no subsequent candidate starts once it has expired or the signal is aborted.

Installed `fs.promises.stat/access` have no abort signal API. The current request is awaited to its terminal result; after it finishes, cancellation or deadline wins immediately and traversal stops. This is a single in-flight filesystem request limitation, not a fresh budget or continued PATH search. Deterministic 160ms request latency yields 7 attempts and about 1125–1129ms for the 1s total budget; the final pending request accounts for the overrun. A 40ms cancellation/close yields 1 attempt and about 162ms, versus the original 10 attempts/about 1612ms. No executable is spawned in these injected boundary cases.

## R2: Python float finite syntax

Finite strings preserve Unicode decimal digits, underscores only between digits, decimal fraction/exponent, and the legacy whitespace set. Decimal Unicode codepoints are converted by their ordered digit block; mathematical styles with adjoining ten-digit blocks retain values via modulo ten. After validating Python's decimal/underscore grammar, underscores are removed and the normalized number is parsed. Invalid underscore placement, hexadecimal, nonfinite values and unsupported text still fall back to 45; finite values retain the 1–120 clamp. Saved number configuration is unchanged.

A real, standalone Python float oracle verified `1_0`→10, `1_2.5`→12.5, `١.٢٥`/full-width/mathematical digits→1.25, exponent/clamp and illegal underscore positions. It also identified U+0085/Unicode spacing versus invalid BOM/control prefix behavior. [Oracle](python-float-oracle.json) records Python/Unicode versions. Runtime core and its tests do not require Python; only the archived independent-review replay invokes its original standalone oracle, without Django.

## Actual checks and source binding

[Review-only delta](review-fixes.diff), [current complete migration diff](code-complete.diff), [current 15-file SHA bindings](source-bindings.json), [324-file source snapshot](core-source-inputs.json), [delta from earlier 315](core-source-delta.json), [machine results](validation-results.json).

- New targeted regressions: actual RED exit1, 0/6, then GREEN exit0, 6/6. Cases include valid float forms, candidate stat/access deadline, caller cancellation and close. [RED](regressions-red.log), [GREEN](regressions-green.log).
- Reviewer's archived original script replayed unchanged: actual exit0, 3/3. [Replay](independent-review-replay.log). The original reviewer RED artifacts remain untouched.
- Related service/Owner/dev/output plus new regression cases: actual exit0, 28/28, zero skipped. [Focused](focused-green.log). This reruns real SQLite cross-process lock/release/crash, fixed CLI/health, nonfatal HTTP, actual desktop zero CLI, cancellation/tree cleanup and output behavior.
- Core typecheck actual exit0 and fresh build actual exit0. [Typecheck](typecheck.log), [build](build.log).
- Fresh plain Node compiled Owner/dev acceptance: actual exit0, 2/2, zero skipped. [Compiled](compiled-green.log).

Counts overlap: the targeted 6 are included in 28; the reviewer replay also exercises the same fixes. These checks are not additive unique totals. The original 62/18/RED and 315-source full suite prove their earlier iterations and do not cover R1/R2. No full suite rerun occurred.

The source snapshot now contains 324 files: six existing baseline files remain modified and nine files have been added across the whole migration. Since iteration 1, only local-services.ts changed and the review regression file was added. Before source copies/hashes and original RED history are preserved. Current service SHA is recorded in source-bindings.json rather than overwriting the original historical SHA report.

All slow filesystem injection is clearly scoped to Docker candidate stat/access and restored in finally. SQLite locks, selected synthetic source files and state writes stay real; tests do not substitute mock Docker success. Disposable review/replay source/data directories are removed after terminal completion; the original independent-review script was run from a repository-external temporary copy and removed. [Final checks](final-checks.json) verify bindings, whitespace, links and no matching task helper or temp directory remains.

Independent reviewer re-review is pending Root coordination. Actual Docker/Langfuse, Orca settings/restart, native Windows/Job/lock and the new Windows source/package iteration remain Root's separate gates. No Docker, existing services/ports, browser, real credentials or old 10 files were touched.

## Review package correction — evidence only

The first iteration-2 `code-complete.diff` was incomplete: it had only the 9 added paths and omitted the six existing modified application/registry/Owner/dev-entry paths. Its generator used the unstaged `git diff` view; the six paths were already in the index at this observation. No staging action or author is inferred. This was an evidence packaging error, not a production/source change. The omitted package is preserved byte-for-byte as [incomplete-previous-code-complete.diff](incomplete-previous-code-complete.diff).

The corrected [complete diff](code-complete.diff) uses baseline content verified independently of the index. Current HEAD is `dd5a356a3afdd67492d82a3b3e0e89dafffe2174`; the bytes of all six existing scoped files in that HEAD match both the frozen 315-file task-before source SHA and the original scoped before binding. Each of the nine additions has an empty preimage. Thus this fixed scope uses the actual task-before source bytes even though worktree/index status differs.

[Exact path manifest and reconstruction proof](code-complete-path-manifest.json) records 15 headers, 6 modified + 9 added paths, the before/current SHA of every path, and reconstruction of each patch to the currently bound 15 files. Corrected package SHA256: `d8f48869f3bc7363e5ec5198239d0f477f50f96ef2cf8bff4351c2d241f22ffa`. The manifest check actual aggregate exit is 0. Index SHA before and after the read-only repair is identical. Production/test/dependency bytes and current source bindings were unchanged; review-fixes.diff and all RED/GREEN history were untouched. No tests were rerun for this evidence-only correction.
