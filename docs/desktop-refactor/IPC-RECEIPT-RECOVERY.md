# Durable IPC authentication receipts

Goal II.3–5 authorizes this focused correction. Root owns the owner protocol and its acceptance point; this work owns only `adapters/ipc.ts`, independent receipt tests and this evidence. Public/private adapter method signatures remain unchanged.

The owner adapter currently saves a newly issued session to `desktop_meta` before adding its delivery receipt to an in-memory map. Abrupt termination after the save but before response delivery loses the map; a fresh adapter restores the undisclosed device. Normal close explicitly discards the map and therefore does not reproduce this crash defect.

The chosen implementation stores a versioned receipt journal inside the existing Vault-encrypted `token` envelope under `ipc.receipts`. Pending issues, predecessor sessions and refresh undo values never enter public replies or logs. A replacement session and its journal are written in the same synchronous SQLite transaction. Acceptance removes the receipt durably; rejection conditionally discards the issued credential, rebases dependent provisional predecessors, and persists the session and journal in one transaction. Empty journals are removed. Constructor recovery validates/decrypts both complete records before any mutation and atomically rejects all remaining receipts. Decryption/shape/inconsistent-pair failure stops initialization without replacing either record or the key.

Alternatives were retaining only memory receipts, which cannot recover after termination, and always logging out after recovery, which loses a previously accepted desktop device. Neither satisfies the required behavior. This design retains the existing single SQLite writer and schema.

A refresh replaces credentials within one stable device family and consumes the prior refresh token. Before a retained refresh, the adapter captures only the exact previous access/expiry/last-seen fields and consumed state of its refresh row. Rejection restores those fields only when the device still has the rejected access digest and has not been externally revoked/deleted. It first uses the trusted `discardIssue` contract, then conditionally undoes that same generation inside the same transaction. It removes an unused rejected refresh row; consumed rows retain existing replay semantics. Rebasing a dependent same-family refresh also carries the earlier undo forward. A later accepted generation, manual revocation, password/family revocation, disabled principals or deletion cannot be undone by cleanup.

The defined coordinator acceptance point is unchanged: confirmation is enqueued and the caller resolved together in one coordinator message turn. A confirmation processed by the owner is durable; termination before that processing remains unconfirmed and recovery rejects it. This does not claim a cross-thread/disk atomic transaction with renderer Promise resolution.

The earlier issuance-to-journal window remains explicit: `CoreApplication.dispatch()` returns a Promise, while `AuthService` commits issuance before the adapter receives the issue. Making that earlier window atomic needs an application/authentication hook outside this task's frozen files. This correction covers the diagnosed saved-session-to-delivery crash window; it does not claim to prevent every orphaned unexposed device issuance.

Implementation and verification sequence:

- Add a real owner Worker response-barrier termination regression using actual CoreApplication, SQLite and Vault. First verify RED restores the wrong device.
- Add isolated SQLite regressions for two pending logins, persisted predecessor rebasing, a later accepted descendant, pending refresh chains, and external revocation priority. Never send private credentials to the Worker parent.
- Implement encrypted journal decoding, atomic session/journal persistence and conditional refresh undo in the existing adapter.
- Verify accepted restart, normal close, encrypted persistence, corruption/key failure preservation and actual transaction fault rollback.
- Run only focused receipt/IPC/Auth tests and core typecheck. Preserve transitional root runtime diagnostics if present; no full suite, build, live database, GUI, model, Windows or vendor request is part of this task.

Verification at the frozen IPC implementation:

| Check | Observed result | Command time | Original evidence |
| --- | --- | --- | --- |
| Actual owner response-barrier termination before delivery | 1 failed, incorrect new device restored (RED) | 14.370 s | [crash RED](../refactor-evidence/20261012-ipc-receipt-crash-red.tap) |
| Initial journal/chain/refresh/atomic contracts | 5 passed / 9 failed, including one Worker fixture logging-format mistake | 21.887 s | [expanded RED](../refactor-evidence/20261012-ipc-receipt-red-corrected.tap) |
| First implementation | 12 passed / 2 failed: refresh SQL incorrectly referenced a nonexistent device column | 25.580 s | [first follow-up](../refactor-evidence/20261012-ipc-receipt-first-green.tap) |
| Final actual SQLite/Vault/Worker recovery regressions | 20 passed | 49.236 s | [final GREEN](../refactor-evidence/20261012-ipc-receipt-final-green.tap) |
| Existing IPC, auth-path, owner-fence, trusted discard and shared authentication regressions | 19 passed | 38.479 s | [related GREEN](../refactor-evidence/20261012-ipc-receipt-related.tap) |
| `npm run typecheck` in `packages/core` | Exit 0 | 20.918 s | [typecheck](../refactor-evidence/20261012-ipc-receipt-typecheck.tap) |

The [first test run](../refactor-evidence/20261012-ipc-receipt-red.tap) and expanded RED keep the fixture mistake intact: the controlled acknowledgment marker initially used an unsupported log level/event format. The corrected crash-only RED reached the actual saved-before-delivery barrier and restored the wrong device. Neither a missing module nor that fixture error is counted as product RED. The first implementation's refresh failures were a concrete implementation mistake: `device_sessions` has no `deleted_at` column. The final query uses the actual schema, row existence and the shared authoritative `sessionIsActive` checks; soft-deleted/disabled principals remain governed by the original authentication implementation. No normal assertion was removed.

Final regressions also prove confirmation processed by the owner survives abrupt termination; two pending refreshes restore every original device field and the original usable refresh; a later accepted same-device generation remains valid; rejecting a refresh predecessor persists the correct undo rebase; and manual, password, family, membership and original-idle-expiry revocations win. A malformed later journal entry, mismatched saved session, unauthenticated plaintext journal, corrupt ciphertext or missing key causes explicit initialization failure before partial cleanup. Actual SQLite trigger faults prove session/journal creation and device-discard/journal-removal rollback together. Normal owner close and the existing post-save authority fences remain passing.

The [freeze manifest](../refactor-evidence/20261012-ipc-receipt-freeze.json) records all three owned-file SHA values, relevant dependency/runtime source hashes, every preserved command/log hash, whitespace/local-link verification and temporary script cleanup. Command times include real initialization and test work; they are not UI latency measurements. No build/full suite, live data, model/vendor request, GUI, Windows or commit was performed. Root owns compiled-Node/desktop consumer verification and visible acceptance.
