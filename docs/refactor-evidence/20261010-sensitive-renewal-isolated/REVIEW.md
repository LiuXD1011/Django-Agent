# Sensitive session renewal isolated patch review

Only the marked external copy was modified. Main workspace and formal stage remain frozen; no patch was applied, no dependency/TTL/permissions/core change, no commit, and no real GUI/Windows/DB/application API/model operation.

Artifacts: [patch](sensitive-session-renewal.patch), [original/new SHA manifest](sha256-manifest.json), [stable red/green evidence](evidence.json), [related test log](related-final.txt), [full unit log](unit-final.txt). All eight original main source/test SHA values remain unchanged. Only the eight manifest paths differ in the copy; Settings/Login/package/lock unchanged.

Production scope: auth-transport.mjs, stores/auth.ts, DeviceSessions.vue, and explicitly approved one-line client.ts request fence. Four existing test files contain the regressions. client response/401/retry/navigation behavior is unchanged.

`authenticatedSessionOperation(generation, work)` captures private service/user/cached tenant/selected tenant/stable device intent, acquires the one origin Cookie lock (or a same-page private IPC/Bearer queue), proves service and me, privately rotates only after definite me401, and proves the original selected tenant again before first mutation. The callback retains skipAuthRefresh and generation, sends mutation once, then checks before success cleanup. No renderer context or arbitrary skip-lock option exists. Ordinary refresh joins its queue then rechecks me, avoiding a redundant rotation; prepared work never awaits a refresh queued behind itself.

`assertSensitiveSession()` is a no-argument check called by Axios after CSRF await and before returning request config. With no sensitive operation active it is a no-op. Actual Axios microtask user/tenant/service/device changes without storage events now result in mutationCount=0; the five RED cases previously sent one mutation.

Refresh uncertainty contains only service/user/device IDs. A sent refresh with unknown result, or confirmed consumption before final identity proof/persistence, records the fence; automatic old-refresh reuse is then refused under the queue, including another Cookie tab. Same-device normal me does not remove it. Confirmed explicit login/registration/setup, a new stable device, local logout/clearStorage, or confirmed rotation plus successful final proof/persist/check clear it. Login passes explicitLogin only after server success and generation check, within its existing origin lock. New device renewal has an explicit passing regression.

Legacy rotated access is used only by a private final me call; the primary tenant is not substituted for the original selected tenant. New credentials are persisted only after identity proof, and win over public me metadata during merge. A coordinator-proven legacy rotation can update a queued same-identity intent; arbitrary changed storage tokens cannot. Core HTTP compatibility/routing is outside this patch and is not claimed verified against a real server.

Tests: related 109/109; full `npm run test:unit` 294/294, all with an independent no-network preload. Initial expiry RED: three mutations × real serialized non-reentrant WebLocks/fallback all failed. Unknown-refresh RED demonstrated three automatic rotation attempts instead of one. Independent review found four issues; all received RED→GREEN regressions: legacy expired access proof, IPC/Bearer double renewal, cached-CSRF Axios await window, and consumed rotation with lost final me. Independent reviewer reports 73/73 and no remaining Critical/Important issues; reviewed hashes match the final manifest.

Reproduce from the isolated frontend directory:

```sh
NODE_OPTIONS='--import=/tmp/marlin-auth_core-renewal-20261010-jy2e_w46/no-network.mjs' node --test src/api/client.behavior.test.mjs src/api/auth-transport.test.mjs src/router/auth-guard.test.mjs src/views/settings/device-sessions.test.mjs src/views/Settings.behavior.test.mjs src/stores/auth-storage.test.mjs
NODE_OPTIONS='--import=/tmp/marlin-auth_core-renewal-20261010-jy2e_w46/no-network.mjs' npm run test:unit
```

The copied startup.ts is byte-identical context for a pre-existing static-read unit test, not part of this patch or a runtime/database test. The initial old device test fixture lacked fake fetch and failed on fixture.invalid; all later validation forbids unmocked fetch. No real service was contacted. No real Windows/Orca regression is claimed: root owns integration and retest. Same-page fallback ordering remains the existing boundary when Web Locks are unavailable.
