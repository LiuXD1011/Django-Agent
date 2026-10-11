# Final Windows builder independent review — 2026-10-10

Read-only review by parser_worker. No unresolved defect was reproduced in the frozen files below. Production code, product tests, QA data and GUI were not modified or exercised. No vendor/model requests were made.

## Frozen identities

All five files were completely read; SHA-256 matched before verification and again afterward.

| File | SHA-256 |
| --- | --- |
| `scripts/build_windows.py` | `b214f24751c83a49007979d89bccfac6059e783da201a2e6e40e6d37d7a44d05` |
| `scripts/test_build_windows.py` | `9c66dc4c76e29803f86350ca3ccbc9b44f9df568c5fcbd81154822b2131e2f8b` |
| `scripts/desktop/windows-gates.py` | `95c9006091e359e83ff24e14aad3eaa6b113d2640797fb89d91b59bca6238729` |
| `scripts/desktop/windows-job.py` | `8d1ab8c4e54d8dd47715fd3110ee3614c6958ac272db32d30b1bfb7dbf94bd73` |
| `scripts/desktop/audit-asar.cjs` | `3dcaccf0b1c6cdf8f93d4490d75abdaccc8a37b1bf6ffa1a7fa98c52ebec1fae` |

Installed `@electron/asar` 3.4.1 and its actual `lib/asar.d.ts` were read. Desktop package/runtime contracts were checked without launching the application.

## Verified boundaries

- Prepared authorization requires the formal `marlin-windows-build-gates-v1` schema, verified state and `frozen_source` scope. Unknown/failed/artifact-only/partial results, invalid TAP counts/durations, missing/changed referenced evidence and rehashed reports with invalid native/Python/window facts are rejected. Report SHA alone is insufficient. GUI, vendor and installer claims must remain false in this controlled gate.
- Source inventory includes newly added source files, build scripts and worker modules; before/after equality is required. Prepared reuse checks full payload bytes and lock inputs. Refresh runs fresh source builds/gates rather than treating an existing artifact report as a fresh-source result.
- Electron package version, `path.txt`, distribution version and the complete distribution file map bind the gate/prepared record. Changed, added, deleted or version-mismatched distribution files are rejected. Payload inventory likewise rejects additions, deletions and changes, including nested worker files.
- Actual Windows junction fixtures are rejected before resolving/descending. POSIX parent links and ownership-marker links are also rejected. These fixtures did not access user data.
- The native Windows helper starts suspended, assigns the exact child to a kill-on-close JobObject before resume and cleans the owned Job on timeout and early parent exit. Its observed descendants were dead at return; a separately owned unrelated fixture process stayed alive. Membership and process handles protect the descendant cleanup from PID reuse. No port/name/global process cleanup was used.
- Actual installed ASAR creation/extraction accepted the ten real desktop asset bytes plus all eighteen production document/evaluation worker files. Five independent nested-file/manifest mutations were rejected. This checks inspection behavior on a controlled archive; it does not establish a new installer build.

## Actual verification

Linux targeted command: `python -B -m unittest -v scripts.test_build_windows.PackageTests.<name> ...` with the seventeen exact case names below. Exit 0, 17/17, 2.016 s, no skips. The orchestration tests use controlled build-tool fixtures; their success is not Windows NSIS/Electron application acceptance.

```text
test_source_inputs_include_all_build_sources_and_detect_new_files (scripts.test_build_windows.PackageTests.test_source_inputs_include_all_build_sources_and_detect_new_files) ... ok
test_payload_reuse_rejects_added_changed_and_deleted_files (scripts.test_build_windows.PackageTests.test_payload_reuse_rejects_added_changed_and_deleted_files) ... ok
test_gate_refuses_rehashed_invalid_native_python_window_and_duration_reports (scripts.test_build_windows.PackageTests.test_gate_refuses_rehashed_invalid_native_python_window_and_duration_reports) ... ok
test_electron_distribution_rejects_modified_added_deleted_and_wrong_version (scripts.test_build_windows.PackageTests.test_electron_distribution_rejects_modified_added_deleted_and_wrong_version) ... ok
test_gate_schema_rejects_unknown_failed_artifact_and_partial_success (scripts.test_build_windows.PackageTests.test_gate_schema_rejects_unknown_failed_artifact_and_partial_success) ... ok
test_refresh_reuse_checks_all_locks_and_complete_worker_source_set (scripts.test_build_windows.PackageTests.test_refresh_reuse_checks_all_locks_and_complete_worker_source_set) ... ok
test_prepared_gate_rejects_old_missing_evidence_and_changed_report (scripts.test_build_windows.PackageTests.test_prepared_gate_rejects_old_missing_evidence_and_changed_report) ... ok
test_refresh_rebuilds_fresh_source_and_reverifies_without_dependency_ci (scripts.test_build_windows.PackageTests.test_refresh_rebuilds_fresh_source_and_reverifies_without_dependency_ci) ... ok
test_artifact_only_evidence_cannot_authorize_prepared_build (scripts.test_build_windows.PackageTests.test_artifact_only_evidence_cannot_authorize_prepared_build) ... ok
test_tap_gate_refuses_failed_skipped_incomplete_or_too_small_suites (scripts.test_build_windows.PackageTests.test_tap_gate_refuses_failed_skipped_incomplete_or_too_small_suites) ... ok
test_windows_gate_checks_actual_private_window_facts_before_verified (scripts.test_build_windows.PackageTests.test_windows_gate_checks_actual_private_window_facts_before_verified) ... ok
test_runtime_fixture_keeps_all_original_assertions_and_refuses_changed_path_shape (scripts.test_build_windows.PackageTests.test_runtime_fixture_keeps_all_original_assertions_and_refuses_changed_path_shape) ... ok
test_actual_asar_audit_checks_ten_assets_bytes_and_added_runtime_files (scripts.test_build_windows.PackageTests.test_actual_asar_audit_checks_ten_assets_bytes_and_added_runtime_files) ... ok
test_job_guard_rejects_shell_search_relative_paths_and_unbounded_timeout (scripts.test_build_windows.PackageTests.test_job_guard_rejects_shell_search_relative_paths_and_unbounded_timeout) ... ok
test_source_and_reset_reject_symlink_ancestors (scripts.test_build_windows.PackageTests.test_source_and_reset_reject_symlink_ancestors) ... ok
test_ownership_marker_cannot_be_a_link_to_another_file (scripts.test_build_windows.PackageTests.test_ownership_marker_cannot_be_a_link_to_another_file) ... ok
test_pipeline_orders_real_builds_and_never_publishes_or_rewrites_locks (scripts.test_build_windows.PackageTests.test_pipeline_orders_real_builds_and_never_publishes_or_rewrites_locks) ... ok

----------------------------------------------------------------------
Ran 17 tests in 2.016s

OK
```

Native Windows command used `/mnt/c/Python313/python.exe -I -B -c ...`, imported this repository via its UNC path, cleared inherited environment except Windows OS/temp/profile essentials, and set `PATH=C:\Program Files\nodejs;C:\Windows\System32`. It selected exactly the two cases below using `unittest.TestSuite`; exit 0, 2/2, 1.250 s, no skips. Actual Win32 JobObject and `mklink` junction behavior was exercised. Fixture children and junctions were cleaned in test `finally` blocks. No GUI, installed QA app or protected existing processes were touched.

```text
test_windows_job_timeout_and_parent_exit_clean_owned_descendants_only (scripts.test_build_windows.PackageTests.test_windows_job_timeout_and_parent_exit_clean_owned_descendants_only) ... ok
test_windows_full_inventory_rejects_junction_before_descending (scripts.test_build_windows.PackageTests.test_windows_full_inventory_rejects_junction_before_descending) ... ok

----------------------------------------------------------------------
Ran 2 tests in 1.250s

OK
```

Independent ASAR command: `node /tmp/marlin-windows-builder-review-asar.cjs`. The temporary script copied the current ten desktop assets and recursively copied production worker modules/requirements/licenses/readmes, excluding tests/cache/bytecode. It generated a complete byte inventory, built a real archive with installed ASAR 3.4.1, invoked the frozen `auditAsar`, exercised the five mutations, restored bytes and verified again. Exit 0:

```text
changed nested document module: rejected
missing evaluation worker: rejected
added worker module: rejected
changed runtime manifest bytes: rejected
changed staged module despite equal runtime bytes: rejected
{"format":"controlled-asar-review-v1","installed_asar_version":"3.4.1","assets":10,"real_worker_files":18,"negative_cases_rejected":5,"final_state":"verified","installer_executed":false,"gui_started":false}
```

## Limits and cleanup

This review does not claim a fresh complete payload preparation, NSIS build/install/uninstall, manual GUI behavior, signed distribution, real external service access or Ragas scoring. Referenced native/Python/window gate contents were validated with controlled negative fixtures; their full producer suites were not rerun. General build-tool orchestration uses bounded `subprocess.run`; the actual owned-tree results above apply specifically to `windows-job.py` gates. Startup consumer was changing under separate ownership and was deliberately excluded from this frozen builder review.

Only this report was added. Own temporary ASAR script/logs were removed after recording results; its temporary archive tree was deleted in `finally`. No production edits, commits or pushes.
