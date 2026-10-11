# Approved password/login UI implementation plan

Goal: apply only the reviewed known-code Chinese messages in an isolated copy. Parent approved the design; no repository files, stage, GUI, real Core/API, credentials, locks, dependencies or authentication policy may change.

1. Preserve all 361 frozen source hashes and copy frontend source/public plus the static startup.ts fixture. Mark the owned copy; reuse node_modules only for reading.
2. Add Settings regression cases for old_password_mismatch, invalid_password and existing fallback order. Add Login invalid_credentials plus unknown-code and mode boundaries; execute actual compiled SFC setup.
3. Run `node --test src/views/Settings.behavior.test.mjs src/views/Login.behavior.test.mjs` before implementation; require the three known-code cases to fail with their original English messages. Archive raw RED output and command/exit/counts.
4. Change only the two catches: Settings exact old_password_mismatch/invalid_password mappings and its existing fallback; Login exact invalid_credentials mapping only for ordinary login and its existing fallback. No string matching, status-wide translation, retry, trims or auth changes.
5. Rerun the two suites and relevant auth/client regression suites; run unchanged `npm run test:unit` in copied frontend. Use owned TMPDIR for generated fixtures/profiles and archive full logs. Headless unit test boundaries do not count as GUI/vendor/Core/API validation.
6. Produce four-file unified patch, original/new SHA maps and safe verification JSON. Validate allowed-file diff and all 361 main-workspace hashes unchanged. Do not apply patch or commit.
