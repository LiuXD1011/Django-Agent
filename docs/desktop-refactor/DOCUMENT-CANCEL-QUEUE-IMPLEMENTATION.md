# Document queue cancellation implementation

This independently owned implementation follows [the reviewed commit design](DOCUMENT-CANCEL-COMMIT-DESIGN.md). It covers the queue, workflow, publication and real batch boundaries; coordinator/Query/HTTP/IPC authorization and Windows delivery remain root-owned acceptance work.

## Contract and boundaries

Every real `process_knowledge` claim receives an independent eight-byte shared BigUint64 control word. The low byte is `AttemptState`, the upper 56 bits a monotonically increasing local commit ordinal. The trusted bridge registers the complete job/attempt/owner/tenant/job-user/document/KB tuple after the claim transaction returns. A queued identity has no fabricated token: `previousAttempt` identifies the queued row with null claim, or exactly its immediate next running claim. It never targets a later retry.

`register` must ACK before the handler starts. The third synchronous `JobQueue.register` initializer may only install the terminal `onOutcome` callback; it cannot publish or execute models. This supplies terminal telemetry even when registry ACK fails. No bridge is required for existing in-process callers. `cancelClaim` awaits actual execution/helper cleanup and returns the persisted status, including completion when final commit won. Its optional synchronous queued callback updates document/task telemetry in the same queued cancellation transaction.

Nested publications share an owned outer transaction and ordinal. A standalone entry inside an unrelated transaction is rejected. SearchIndex preserves the existing transaction behavior for ordinary publication callbacks; an internal WeakSet capability delegates only a trusted attempt publication's outer transaction to Queue. Checkpoints occur before and after actual insert/FTS batches without changing validation, parameters, rowid precision, context or recall. Single SQLite statements cannot be interrupted.

A local gate is acquired at the end of the outer callback. Actual driver COMMIT success advances the ordinal. Cancellation before permission causes complete rollback; cancellation after local permission preserves the committed body/FTS and stops subsequent work. The publisher returns normally first so pipeline artifact ownership is recorded accurately. A final gate commits document/task/root/progress/job/result/events together. The synchronous outcome publisher is registered once; its failed COMMIT rolls back its first invocation and Queue then publishes the failure outcome in a separate owned transaction. Terminal audits match job ID and queue attempt.

## Verification scope

The initial real Python-parser/SQLite regression fails because a fully completed workflow is overwritten with `cancelled`. Raw RED is [the initial log](../refactor-evidence/20261012-document-cancel-late-red.tap); it is a business assertion, not a missing-module failure. Additional deterministic Worker/SQLite barriers verify real transactions, queued/actual claim matching, ACK ordering, callback and COMMIT faults, rollback, helper cleanup and precise late cancellation. No live data, model vendors, GUI or large profiling runs are used. Raw failures from temporary script working-directory mistakes or syntax errors are retained but are not counted as business RED.

Shared cancellation is a volatile request, not a durable success. Durable cancellation ACK follows rollback or successful local commit, owner terminal transaction and helper cleanup. A killed owner before ACK provides no durable cancellation promise. Exact IPC/HTTP authority, registry deadlines/capacity, persisted recovery and native platform checks require the coordinated final acceptance.

## Final independent verification

| Source-bound check | Result | Evidence |
| --- | --- | --- |
| Shared control, precise queued/claim race, native chunks/FTS/local/final barriers, terminal faults, actual helper cleanup, real batch checkpoints | 21/21, exit 0 | [raw TAP](../refactor-evidence/20261012-document-cancel-final-focused.tap), [command, timing and six-source hashes](../refactor-evidence/20261012-document-cancel-final-focused.json) |
| Existing jobs, bulk replacement, startup recovery, bulk validation, keyword batch/64-bit/old-vector/publication/retrieval options | 60/60, exit 0 | [raw TAP](../refactor-evidence/20261012-document-cancel-final-related.tap), [command and hashes](../refactor-evidence/20261012-document-cancel-final-related.json) |
| Actual Python descendant exit, unknown local HTTP results, authority revocation, safe/manual recovery and image COMMIT rollback | 6/6, exit 0 | [raw TAP](../refactor-evidence/20261012-document-cancel-final-workflow.tap), [command and hashes](../refactor-evidence/20261012-document-cancel-final-workflow.json) |
| Core typecheck | exit 0 | [raw output](../refactor-evidence/20261012-document-cancel-final-typecheck.tap), [command and hashes](../refactor-evidence/20261012-document-cancel-final-typecheck.json) |

These commands bind the same six owned product-source SHA values before/after execution. They do not freeze unrelated root-owned Runtime code or claim compiled/Windows/UI acceptance. An earlier wider small-workflow run also passed 26/26, excluding the 40000-line and migrated-size cases; it preceded the last minor terminal refinements and is [historical evidence](../refactor-evidence/20261012-document-cancel-workflow-related.tap).

The second genuine RED is [a real SQLite terminal-write failure](../refactor-evidence/20261012-document-cancel-terminal-fault-red.tap): both completion and failure transactions are rejected, but the old queue returns a running job without an explicit rejection. The fixed behavior is `503 job_outcome_failed`, `INVALID` control, no durable terminal event and no successful unregister. The last accepted local body remains intact. This unconfirmed slot needs owner recovery/restart; it is never a successful cancellation ACK. A final completion COMMIT fault whose subsequent failure transaction succeeds instead produces a durable failed document/task/root/job, preserving the already committed local generation.

Intermediate failures remain unchanged: a malformed trusted-publication closing parenthesis (implementation error); a working-directory failure in a temporary edit command; illegal `fixed` strategy/64 child-size fixture; a fixture CAS success comparison against the wrong value; a native SQLite function attempting a forbidden reentrant query; a final-barrier assertion expecting the old generation despite prior local COMMIT; and an introduced extra ordinary SearchIndex transaction caught by the existing batch test. They are not business RED and none is hidden by weakening content/rowid assertions.

The Node-only test observers are WeakMap capabilities registered once with an explicit disposer. They expose no renderer/configuration/JSON route. Observer exceptions/thenables trigger the normal rollback/failure path. Fixtures pause actual native INSERT or actual FTS batches/commit gates, do not replace parser/workflow/database/index behavior, and release barriers/dispose observers during cleanup. The chunks trigger passes its real `NEW.id`; it performs no reentrant SQL. Readonly WAL checks use a true ReadDatabase, never a second writer.

Cancellation samples in these small fixture diagnostics include the parent polling interval and are not UI latency or P95 measurements. Synchronous SQL itself remains indivisible. Root still owns registry/preflight/authority/transport saturation and crash acceptance, packaged JavaScript and target Windows/native GUI checks. Shared buffers stay inside Node worker threads; no JSON fork or renderer receives them. No model vendor, live QA data, large upload/profile or package build was invoked here.

Full source/test/evidence hashes and temporary script cleanup are recorded in [the independent freeze manifest](../refactor-evidence/20261012-document-cancel-queue-freeze.json).
