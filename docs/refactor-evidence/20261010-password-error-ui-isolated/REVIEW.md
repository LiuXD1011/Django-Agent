# Isolated password/login Chinese message patch

This copy belongs to /root/ui_baseline. It is outside the frozen repository; no patch has been applied to the main workspace, Windows stage, or installation.

Only Settings.vue catch maps old_password_mismatch and invalid_password, and ordinary Login.vue submit catch maps invalid_credentials. Each original fallback remains intact. Authentication, refresh, generation fences, credentials, registration, initialization, retry and success behavior are unchanged.

Actual checks in this copy (Node22.23.2/npm10.9.8 on Linux/WSL):

- RED:26 tests,23 pass,3 expected failures,0skip,1.307s; three original English messages reproduced.
- GREEN related:63/63,0fail/skip,1.423s.
- Unmodified frontend npm run test:unit:244/244,0fail/skip,54.137s.
- git apply --check against original copies:exit0.
- Main workspace all361 approved frozen source SHA unchanged; only4 of109 copied inputs changed. The other105 copied inputs, including the lock file and package configuration, are unchanged.

The new regressions execute the real compiled Vue SFC setup and original reactive state using existing auth/API boundaries as fixtures. No real credentials, Core/API service, paid model, visible GUI, installation or build was used. Existing full-unit headless browser/local fixture tests ran only as unit tests. These results do not prove native GUI or installer acceptance.

## Review artifacts

[Four-file patch](password-login-chinese-errors.patch), [verification JSON](verification.json), [original/new hashes](file-changes.json), [complete frozen source before](source-before.json), [source fence after](source-after.json), [RED TAP](red-targeted.tap), [related GREEN TAP](green-related.tap), [full unit TAP](green-full-unit.tap). Original files remain in ../original; changed files remain at ../frontend/src/views.

| File | Original SHA256 | New SHA256 |
| --- | --- | --- |
| frontend/src/views/Settings.vue | `d65a2ff9262be9dd5a7ca9ebd624ddbf13f7a5f88c7e7f082edce770ac869390` | `f0ff4bcfda194cac75315c53f9fea3f4dab2528e4a8793edf6b7a8e6706f058c` |
| frontend/src/views/Settings.behavior.test.mjs | `8b6165f2447085aad178d6bba865d3b76a098d22f51adbbd8b64fd7901600748` | `6a96ef3e6dfafab91f92bb8e7cc1e4b9cd0321447fc25793f9f3e44b156c81f3` |
| frontend/src/views/Login.vue | `39f0d8fb04fa6aa6485b1d918f449f6187062b5fb2cc6549788f5a6a6be5e7cd` | `8b36b8b15a90154c820086cd6ecff9d17b9a84fd4267a57d354059a03f20ac7a` |
| frontend/src/views/Login.behavior.test.mjs | `35eda79b93f4490bf1107efee24b1aefb5bc96a76964d557ba91d9d596d3186a` | `92fd2d55565cabd728d2ba0d89cd1124777d614c69dc4fd7b7068d5ddbf5e167` |

Only the parent may integrate the patch after releasing the installation/source freeze. The first password submission401 and sensitive-operation refresh diagnosis remain outside this patch.
