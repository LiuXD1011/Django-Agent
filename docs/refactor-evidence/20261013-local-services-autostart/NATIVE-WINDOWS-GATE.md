# Native Windows gate — not executed

Run from this exact source iteration's `packages/core` directory using the project-supported native Node and installed native SQLite binding. Do not reuse the historical frozen package as a claim of this new capability.

```powershell
npm run typecheck
npm run build
node --import tsx --test test/local-services.test.ts test/local-services-owner.test.ts test/local-services-process-output.test.ts
$env:MARLIN_LOCAL_SERVICES_COMPILED_TEST = '1'
node --test test/local-services-compiled.test.ts
Remove-Item Env:MARLIN_LOCAL_SERVICES_COMPILED_TEST
```

Capture each real `$LASTEXITCODE`, stdout/stderr, source bindings and native process terminal observations separately. Do not aggregate a failed check into a later command's exit. The service fixture runs the actual bundled/default Node executable through the production Windows supervisor/Job Object; it never launches Docker. Cross-process tests exercise actual SQLite locks with a killed holder and a later successful holder.

The POSIX shebang-based dev subprocess checks explicitly skip on Windows; their Linux PASS is not native Windows dev-entry evidence. Native Windows compiled Owner acceptance runs without a loader. Root must additionally run the actual development CLI and controlled Docker/Langfuse acceptance on the intended target using an isolated project, sourceRoot/dataRoot and synthetic env. If a short success-fixture budget expires during native Job Object setup, record the observed timeout and timing rather than claiming success or enlarging production work budgets.

Root also coordinates the new Windows package/source-input iteration and installed-desktop zero-autostart check. No Windows result is claimed by this artifact.
