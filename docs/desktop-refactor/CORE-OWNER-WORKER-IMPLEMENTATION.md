# Complete core owner Worker: stage 1 implementation

This implements the approved [coordinated plan](CORE-OWNER-WORKER-PLAN.md), using the writing-plans and test-driven-development workflows. Goal II.5 authorizes continuation after design review; no commit is authorized.

The sole `CoreApplication` and `CoreIpcAdapter` live in a Node 22 Worker. Their existing synchronous transactions, authentication epoch, recovery, callbacks, parser supervision and shutdown stay unchanged. The coordinator owns transport only; importing response constructors never opens a database. Worker threads are trusted application code, not an operating-system sandbox.

`CoreOwner.start({dataRoot, allowAutoSetup?, parser?, evaluation?})` accepts serializable configuration only. Parser options keep their existing timeout/limit semantics; evaluation excludes its callable `answer` override and runtime validation rejects functions, exotic objects and unknown configuration fields. `dispatch`, `invoke`, `openStream` and `nativeLangfuse` retain their existing DTOs. `startupLog` and `httpTransport` are asynchronous. The latter returns the internal CSRF key, dispatch function and scoped upload preflight; none is a renderer capability.

Messages use a private correlation UUID distinct from business request IDs. The bridge allows at most 64 active calls and 64 queued calls. A stream occupies a slot until its iterator ends or is released. Only one frame can be awaiting acknowledgment; the consumer acknowledges the previous frame when it requests the next one. Return, abort and close unblock the acknowledgment, abort the owned request and return its source iterator. Invalid events and frames above the existing 2 MiB limit fail safely. Binary values are cloned as exact Uint8Array views without detaching caller-owned buffers. HTTP auth changes, cookies and native Langfuse plans use internal messages only; ordinary invoke exposes the existing public response.

Shutdown stops admission, aborts all lifetimes, rejects queued calls, closes the actual application and waits for owned executions and Worker exit. Unexpected Worker exit rejects pending calls and streams with fixed safe errors. No error message, request payload, credential, cookie or arbitrary exception is logged. Source entry uses the project's existing Node 22 type-only bootstrap, registering tsx inside the Worker before loading application modules; compiled JavaScript loads no development loader. Worker environment remains the normal copied environment so existing startup overrides and parser environment policy are preserved.

Implementation and verification sequence:

1. Create typed contracts and an explicit unimplemented client. Test actual desired startup, private session persistence and real SQLite/FTS/vec diagnostics; observe failures from the unimplemented contract, not module resolution.
2. Implement one owner and its request/response bridge. Verify source startup, scoped upload preflight, credentials remaining private, exact binary transport, safe startup failure and session restart.
3. Add stream regressions before implementing frame transfer. Exercise real no-model chat error streams, one unacknowledged frame, ordered replay, return, abort, close and bounded admission. No provider or model calls are required.
4. Run the related tests, core typecheck and build. Run the same small actual application smoke against compiled JavaScript. Record raw output, command times and source hashes in independent evidence. Remove temporary command scripts.

Verification at the frozen owner source:

| Check | Result | Command wall time | Raw evidence |
| --- | --- | --- | --- |
| Initial desired owner behavior against an explicit unimplemented contract | 2 failed, as intended | 0.657 s | [RED](../refactor-evidence/20261012-core-owner-red.tap) |
| Desired frame transfer against an explicit unimplemented stream delegate | 3 failed, as intended | 12.991 s | [stream RED](../refactor-evidence/20261012-core-owner-stream-red.tap) |
| Final real source owner, native SQLite/FTS/vec, scoped authentication, binary/private transport, bounded streams and actual subprocess lifecycle | 16 passed | 29.285 s | [source GREEN](../refactor-evidence/20261012-core-owner-source-all-frozen.tap) |
| Plain Node compiled JavaScript, native database, no-model streams, real Python and nested compiled chunk Worker | 2 passed | 12.375 s | [compiled GREEN](../refactor-evidence/20261012-core-owner-compiled-frozen.tap) |
| Existing IPC, HTTP and system diagnostics regressions before root transport integration | 14 passed | 9.946 s | [related GREEN](../refactor-evidence/20261012-core-owner-related.tap) |
| Core TypeScript typecheck | Exit 0 | 17.179 s | [typecheck](../refactor-evidence/20261012-core-owner-typecheck-final.tap) |
| Core TypeScript build | Exit 0 | 21.346 s | [build](../refactor-evidence/20261012-core-owner-build-final.tap) |

These are command durations, including loader and test setup, not business latency, percentiles or performance acceptance. The [manifest](../refactor-evidence/20261012-core-owner-freeze.json) records command output hashes, the three frozen runtime source hashes, tests, compiled artifacts and temporary-script cleanup. No dependency or lockfile was changed.

The small actual text fixture completes real Python parsing, nested pure chunk computation and keyword publication with no configured models and zero usage calls. The lifecycle fixtures also start an actual Python helper and descendant, then exercise abort, configured timeout and owner close. After cancellation or timeout, the supervisor is reaped and the helper/descendant no longer run; close waits for actual owner exit. A Linux descendant can briefly remain a zombie, which is distinguished from a running process. Unexpected-thread-exit coverage uses an open stream with no running subprocess; it does not prove subprocess cleanup after forced termination or an operating-system crash.

Two preserved failed diagnostics were fixture mistakes, not additional product RED evidence: [parser-first](../refactor-evidence/20261012-core-owner-parser-first.tap) used a nonexistent usage field before changing it to `total.calls`; [parser-lifecycle](../refactor-evidence/20261012-core-owner-parser-lifecycle.tap) put a signal in `IpcOptions` before using the actual third argument. Their [parser](../refactor-evidence/20261012-core-owner-parser-green.tap) and [lifecycle](../refactor-evidence/20261012-core-owner-parser-lifecycle-corrected.tap) follow-ups pass. No assertions were weakened.

The source and compiled checks run on Linux with the project's Node 22 runtime. The compiled checks start real `.js` Workers using plain Node without tsx in parent or Worker and parse a small document through the compiled nested Worker. They do not substitute for a Windows package or installation check. Temporary data roots and helper scripts are removed by each test's `finally`; only isolated test passwords and synthetic cookie values are used.

Stage 1 does not implement read-only WAL routing or shared atomic cancellation. An owner blocked inside synchronous publication cannot process its normal cancellation message until the batch returns. It also cannot service business reads during publication. Moving health outside that Worker is not evidence that this defect is fixed. Windows packaging, desktop integration and live response tests remain root-owned acceptance work.
