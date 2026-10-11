# Sensitive session renewal approved implementation plan

Goal: prepare identity-bound authentication under one origin lock before the first sensitive mutation.
Constraints: only the three approved production files and their tests; no core/TTL/dependency/client behavior changes; no real GUI/API/DB/model actions; no commits.

- [x] Write actual-client expiry regression using queued non-reentrant Web Locks and fallback. Expect RED: mutation 401 logs out instead of renewing.
- [x] Add closure-private intent checks, lock-held low-level me/capabilities preflight and necessary refresh; keep mutation skipAuthRefresh and one send.
- [x] Adapt store changePassword and DeviceSessions revoke/logoutAll to authenticatedSessionOperation(generation, work). No public skip-lock option.
- [x] Verify queue rechecks, refresh principal and selected-tenant proof, stable device, late/unknown no retry, CSRF and existing generation barriers.
- [x] Run relevant tests then npm run test:unit in this isolated copy; record RED/GREEN outputs.
- [x] Generate patch and SHA manifest; verify original approved files unchanged.
