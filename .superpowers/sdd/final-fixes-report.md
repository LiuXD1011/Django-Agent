# Final review fix wave report

Date: 2026-07-12 (Asia/Shanghai)

## Scope and outcome

Implemented all three Important findings from the final review on local `main` without modifying any reference project:

1. Duplicate cleanup now accepts only exactly 64 hexadecimal SHA-256 characters, normalizes valid hashes to lowercase for grouping and snapshot comparison, and revalidates the same boundary immediately before destructive work. Mixed-case hashes match only inside the same tenant and knowledge base.
2. Startup recovery now marks unsupported pending/running task types failed with the stable reason `unsupported task type: <task_type>`. `cleanup_knowledge_artifacts` records are explicitly excluded because the cleanup command owns their retry lifecycle. Existing `process_knowledge` lease, fencing, reconciliation, and enqueue behavior remains intact.
3. Recovery scheduling now recognizes both retained `python -m django ...` argument lists and Python's actual `django/__main__.py` argv form. All management commands are suppressed; `runserver` schedules only when `RUN_MAIN=true`; gunicorn and uvicorn remain enabled.

The approved design document now records the user-approved fresh-running-over-earliest recovery exception, the process-local 300-second VLM capability observation, and cleanup artifact manifest ownership.

## TDD evidence

### Initial focused RED

Command:

```text
python manage.py test personal_knowledge_base.test_knowledge_cleanup.KnowledgeCleanupTests.test_plan_rejects_invalid_sha256_duplicate_boundaries personal_knowledge_base.test_knowledge_cleanup.KnowledgeCleanupTests.test_plan_normalizes_sha256_case_within_knowledge_base_only personal_knowledge_base.test_knowledge_cleanup.KnowledgeCleanupTests.test_execute_revalidates_normalized_sha256_and_rejects_invalid_change personal_knowledge_base.test_task_recovery.TaskRecoveryTests.test_recovery_fails_unknown_pending_and_running_task_types personal_knowledge_base.test_task_recovery.TaskRecoveryTests.test_recovery_excludes_cleanup_artifact_manifests personal_knowledge_base.test_task_recovery.TaskRecoveryTests.test_python_module_django_management_commands_do_not_schedule_recovery
```

Result: exit 1, 6 tests run, 9 assertion failures. Failures demonstrated invalid hashes entering cleanup candidates, mixed-case valid hashes not grouping, unknown records remaining pending/running, and module-form Django management commands scheduling recovery.

### Initial focused GREEN

The same command completed with exit 0: `Ran 6 tests ... OK`.

### Actual `django/__main__.py` RED/GREEN

Command:

```text
python manage.py test personal_knowledge_base.test_task_recovery.TaskRecoveryTests.test_django_main_module_argv_does_not_schedule_management_recovery
```

Before implementation: exit 1, one test with six subtest failures. After recognizing paths ending in `/django/__main__.py`, the command passed as part of the three-test command below:

```text
python manage.py test personal_knowledge_base.test_task_recovery.TaskRecoveryTests.test_django_main_module_argv_does_not_schedule_management_recovery personal_knowledge_base.test_task_recovery.TaskRecoveryTests.test_python_module_django_management_commands_do_not_schedule_recovery personal_knowledge_base.test_task_recovery.TaskRecoveryTests.test_runserver_child_and_non_management_services_keep_scheduling_behavior
```

Result: exit 0, `Ran 3 tests ... OK`.

### Focused module regression

```text
python manage.py test personal_knowledge_base.test_knowledge_cleanup personal_knowledge_base.test_task_recovery
```

Result: exit 0, `Ran 55 tests ... OK`.

## Final verification evidence

### Full backend suite

```text
python manage.py test
```

Result: exit 0, `Ran 134 tests in 10.730s`, `OK`; Django system check reported no issues. Expected warning/error log fixtures appeared but caused no test failures.

### Migration drift

```text
python manage.py makemigrations --check --dry-run
```

Result: exit 0, `No changes detected`.

### Diff integrity and scope

```text
git diff --check
git diff --name-only
```

Result: exit 0 with no whitespace errors. The pre-commit implementation diff contained only:

- `.superpowers/sdd/final-fixes-report.md` (this required report; added after the captured name-only check)
- `docs/superpowers/specs/2026-07-12-vlm-task-recovery-cleanup-design.md`
- `personal_knowledge_base/knowledge_cleanup.py`
- `personal_knowledge_base/tasks.py`
- `personal_knowledge_base/test_knowledge_cleanup.py`
- `personal_knowledge_base/test_task_recovery.py`

No `MiMo-Code`, `open-webui`, `WeKnora`, or `xiaolinnote_ai` paths were touched.

## Concerns

No known functional concerns or migration requirements. Artifact manifests intentionally remain pending/running until the cleanup command retries them; startup recovery must continue excluding that task type.
