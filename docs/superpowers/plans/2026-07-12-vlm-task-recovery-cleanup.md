# VLM 熔断、任务恢复与知识清理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 识别并熔断 VLM 权限错误，恢复服务重启前的文档任务，并安全清理同知识库重复知识及失效任务。

**Architecture:** 保留 Django 单体和 SQLite 顺序队列。模型层将 401/403 转为结构化不可重试异常，多模态层使用单文档熔断；任务表通过原子认领和 `updated_at` 心跳成为恢复源；独立清理服务与管理命令负责预览和不可逆执行。

**Tech Stack:** Django、SQLite、`requests`、Django cache、`unittest.mock`、Django TestCase/TransactionTestCase。

## Global Constraints

- 只修改 Django-Agent 主项目。
- 不修改 `MiMo-Code`、`open-webui`、`WeKnora`、`xiaolinnote_ai` 及其子目录。
- 直接在本地 `main` 分支实施，不创建分支或 worktree。
- 不引入 Redis、Celery、对象存储或额外常驻进程。
- 保留当前未提交的 Chunk 修复，不覆盖或回退用户工作区变更。
- 数据清理只合并同一租户、同一知识库、相同非空 SHA-256 的文件。

---

## File Structure

- Modify `personal_knowledge_base/model_providers.py`: 解析上游权限错误，维护短期 VLM 可用性状态。
- Modify `personal_knowledge_base/multimodal.py`: 实现单文档 VLM 熔断。
- Modify `personal_knowledge_base/document_parsing/__init__.py`: Parser 能力返回最近权限错误。
- Modify `personal_knowledge_base/tasks.py`: 原子任务认领、心跳、恢复、去重及启动调度。
- Modify `personal_knowledge_base/apps.py`: 在实际服务进程中安排一次恢复。
- Create `personal_knowledge_base/knowledge_cleanup.py`: 重复识别、完整清理与失效任务整理。
- Create `personal_knowledge_base/management/commands/cleanup_knowledge_state.py`: dry-run/`--confirm` 命令。
- Modify `personal_knowledge_base/test_multimodal_processing.py`: VLM 熔断回归测试。
- Modify `personal_knowledge_base/test_multimodal_api.py`: VLM 能力状态测试。
- Create `personal_knowledge_base/test_task_recovery.py`: 任务租约与恢复测试。
- Create `personal_knowledge_base/test_knowledge_cleanup.py`: 重复知识和失效任务清理测试。

---

### Task 0: 固化已验证的 Chunk 修复基线

**Files:**
- Modify: `personal_knowledge_base/document_processing.py`
- Modify: `personal_knowledge_base/test_multimodal_processing.py`

**Interfaces:**
- Preserves: 已完成的 PDF 连续文本块合并、短尾合并和短图表标签并入前一 Chunk 行为。
- Produces: 干净的提交基线，避免后续 Task 1 修改同一测试文件时混入未归属变更。

- [ ] **Step 1: 重新运行 Chunk 定向测试**

Run:

```bash
python manage.py test \
  personal_knowledge_base.test_multimodal_processing.MultimodalProcessingTests.test_pdf_layout_blocks_are_merged_before_chunking \
  personal_knowledge_base.test_multimodal_processing.MultimodalProcessingTests.test_split_text_does_not_emit_overlap_only_short_tail \
  personal_knowledge_base.test_multimodal_processing.MultimodalProcessingTests.test_short_pdf_labels_after_an_image_join_the_previous_chunk \
  personal_knowledge_base.test_multimodal_processing.MultimodalProcessingTests.test_markdown_image_chunks_attach_to_preceding_text_chunk
```

Expected: 4 tests PASS。

- [ ] **Step 2: 提交现有 Chunk 修复**

```bash
git add personal_knowledge_base/document_processing.py personal_knowledge_base/test_multimodal_processing.py
git commit -m "fix: merge short PDF layout chunks"
```

---

### Task 1: 结构化 VLM 权限错误与单文档熔断

**Files:**
- Modify: `personal_knowledge_base/model_providers.py`
- Modify: `personal_knowledge_base/multimodal.py`
- Modify: `personal_knowledge_base/document_parsing/__init__.py`
- Test: `personal_knowledge_base/test_multimodal_processing.py`
- Test: `personal_knowledge_base/test_multimodal_api.py`

**Interfaces:**
- Produces: `ModelAccessDeniedError(status_code, upstream_code, message)`。
- Produces: `vlm_access_state(tenant) -> dict | None`、`mark_vlm_access_denied(tenant, exc)`、`clear_vlm_access_denied(tenant)`。
- Changes: `analyze_image(...) -> tuple[str, str, list[str], str]`，最后一项为空或熔断原因。
- Consumes: `process_document_images()` 使用上述熔断原因停止当前文档后续 VLM 调用。

- [ ] **Step 1: 写权限异常和熔断失败测试**

在 `test_multimodal_processing.py` 增加两个测试。第一个构造两张不同哈希图片，Mock 第一次 OCR 抛出 `ModelAccessDeniedError(403, "AllocationQuota.FreeTierOnly", "free quota exhausted")`，断言 `vision_completion` 总调用次数为 1、两张 `KnowledgeImage` 都失败且错误包含上游错误码。第二个测试先处理失败文档，再处理新文档并让 Mock 返回 OCR/Caption，断言新文档重新调用两次，证明熔断不跨文档。

在 `test_multimodal_api.py` 增加测试：向 cache 写入当前租户 VLM 拒绝状态后，请求 Parser Engine API，断言 `vlm_available` 为 `false`，并返回 `vlm_unavailable_reason.code == "AllocationQuota.FreeTierOnly"`，且响应中不包含 API Key。

- [ ] **Step 2: 运行测试确认 RED**

Run:

```bash
python manage.py test \
  personal_knowledge_base.test_multimodal_processing.MultimodalProcessingTests.test_vlm_403_stops_remaining_image_calls \
  personal_knowledge_base.test_multimodal_processing.MultimodalProcessingTests.test_vlm_circuit_resets_for_next_document \
  personal_knowledge_base.test_multimodal_api.MultimodalApiTests.test_parser_capabilities_reports_recent_vlm_access_denial
```

Expected: FAIL，原因分别为异常类、熔断行为和能力状态接口尚不存在。

- [ ] **Step 3: 实现结构化访问拒绝异常**

在 `model_providers.py` 中增加：

```python
class ModelAccessDeniedError(ModelConfigurationError):
    def __init__(self, status_code: int, upstream_code: str, message: str):
        self.status_code = status_code
        self.upstream_code = upstream_code
        self.safe_message = message
        super().__init__(f"{upstream_code or 'model_access_denied'}: {message}")


def _raise_for_model_status(response):
    if response.status_code not in {401, 403}:
        response.raise_for_status()
        return
    try:
        error = (response.json() or {}).get("error") or {}
    except ValueError:
        error = {}
    raise ModelAccessDeniedError(
        response.status_code,
        str(error.get("code") or "model_access_denied"),
        str(error.get("message") or "Model access was denied"),
    )
```

让 `openai_compatible_chat_raw()` 调用 `_raise_for_model_status(resp)`。使用 Django cache 保存五分钟安全状态：key 为 `vlm:access-denied:{tenant.id}`，值只包含 `status_code/code/message`；`vision_completion()` 成功时清除，捕获 `ModelAccessDeniedError` 时写入后重新抛出。

- [ ] **Step 4: 实现多模态单文档熔断**

修改 `analyze_image()`：OCR 遇到 `ModelAccessDeniedError` 时立即返回空 OCR、空 Caption、错误列表和熔断原因，不再调用 Caption；Caption 遇到该异常时保留已成功 OCR 并返回熔断原因。普通异常继续允许另一种视觉能力尝试。

修改 `process_document_images()`：维护局部变量 `circuit_error = ""`。熔断后，后续图片不调用 `analyze_image()`，直接写入相同错误；仍创建 `KnowledgeImage`，按已有结果设置 `partial/failed`。

- [ ] **Step 5: 能力接口读取最近拒绝状态**

`parser_capabilities(tenant)` 在配置可用后读取 `vlm_access_state(tenant)`。存在拒绝状态时设置：

```python
result["vlm_available"] = False
result["vlm_unavailable_reason"] = denied_state
```

无拒绝状态时保持现有兼容响应。

- [ ] **Step 6: 运行 Task 1 测试确认 GREEN**

Run: Step 2 相同命令。

Expected: 3 tests PASS，并确认 Mock 第一次 403 后没有多余请求。

- [ ] **Step 7: 提交 Task 1**

```bash
git add personal_knowledge_base/model_providers.py personal_knowledge_base/multimodal.py personal_knowledge_base/document_parsing/__init__.py personal_knowledge_base/test_multimodal_processing.py personal_knowledge_base/test_multimodal_api.py
git commit -m "fix: stop VLM calls after access denial"
```

---

### Task 2: 原子任务认领、心跳与启动恢复

**Files:**
- Modify: `personal_knowledge_base/tasks.py`
- Modify: `personal_knowledge_base/apps.py`
- Create: `personal_knowledge_base/test_task_recovery.py`

**Interfaces:**
- Produces: `resolve_task_callable(record: TaskRecord) -> Callable | None`。
- Produces: `recover_incomplete_tasks(now=None) -> dict`。
- Produces: `should_schedule_recovery(argv=None, environ=None) -> bool`。
- Changes: `_run_task(task_id, fn)` 只执行原子认领成功的 pending 任务。

- [ ] **Step 1: 写原子认领和恢复失败测试**

使用 `TransactionTestCase` 创建 Tenant、KnowledgeBase、Knowledge 和 TaskRecord，覆盖：

```python
def test_run_task_claims_pending_record_only_once(self): ...
def test_recovery_enqueues_pending_process_knowledge(self): ...
def test_recovery_resets_running_task_with_expired_lease(self): ...
def test_recovery_keeps_running_task_with_fresh_lease(self): ...
def test_recovery_merges_duplicate_unfinished_tasks(self): ...
def test_recovery_discards_task_for_soft_deleted_knowledge(self): ...
def test_management_commands_do_not_schedule_recovery(self): ...
```

Mock `_enqueue_sequential` 和实际处理函数，断言恢复顺序、状态更新和重复任务错误信息。原子认领测试连续调用 `_run_task()` 两次，断言函数只执行一次。

- [ ] **Step 2: 运行测试确认 RED**

Run:

```bash
python manage.py test personal_knowledge_base.test_task_recovery
```

Expected: FAIL，因为恢复、租约和启动判断接口不存在，且当前 `_run_task` 会重复执行。

- [ ] **Step 3: 实现任务函数注册与原子认领**

在 `tasks.py` 中迟延导入文档处理函数：

```python
def resolve_task_callable(record):
    if record.task_type != "process_knowledge":
        return None
    knowledge_id = str((record.payload or {}).get("knowledge_id") or "")
    if not knowledge_id:
        return None
    from .document_processing import process_knowledge
    return lambda: (process_knowledge(knowledge_id), {"knowledge_id": knowledge_id})[1]
```

`_run_task()` 开头使用：

```python
claimed = TaskRecord.objects.filter(id=task_id, status="pending").update(
    status="running", progress=0.1, updated_at=timezone.now()
)
if not claimed:
    return
```

随后重新读取 record。APP_TASKS_SYNC 和普通新任务继续从 pending 开始，因此兼容原路径。

- [ ] **Step 4: 实现 15 秒任务心跳**

新增 `_heartbeat_task(task_id, stop_event)`，使用 `stop_event.wait(15)` 循环更新仍为 running 的 TaskRecord `updated_at`，每次循环前后调用 `close_old_connections()`。`_run_task()` 在认领后启动 daemon Thread，并在 `finally` 中 set + join，确保成功、失败和异常都停止。

- [ ] **Step 5: 实现恢复、任务去重和队列防重复**

`recover_incomplete_tasks(now=None)`：

1. 将 `status=running, updated_at < now-90秒` 改为 pending。
2. 遍历 pending/running 的 `process_knowledge`，验证 Knowledge 存在、未软删除且未取消。
3. 按 knowledge_id 分组，每组保留最早任务；其他 pending/running 更新为 failed，错误为 `superseded by recoverable task {kept_task_id}`。
4. 对保留的 pending 任务解析 callable 并调用 `_enqueue_sequential()`。
5. 返回 `recovered/stale_reset/superseded/discarded` 计数。

维护 `_queued_task_ids` 集合：入队时去重，出队时移除，防止同进程重复恢复。

- [ ] **Step 6: 实现安全启动调度**

`should_schedule_recovery()` 对 `test/migrate/makemigrations/shell/collectstatic` 返回 false；运行 `runserver` 时仅当 `RUN_MAIN=true` 返回 true；其他 WSGI/ASGI 启动返回 true。

新增 `schedule_startup_recovery()`，通过短延迟 daemon Timer 调用恢复，捕获 `OperationalError/ProgrammingError` 并仅记录日志。`apps.py.ready()` 在现有 SQLite 检查和 executor 初始化后调用该函数。

- [ ] **Step 7: 运行 Task 2 测试确认 GREEN**

Run:

```bash
python manage.py test personal_knowledge_base.test_task_recovery
```

Expected: 全部 PASS，无后台线程遗留导致测试进程挂起。

- [ ] **Step 8: 提交 Task 2**

```bash
git add personal_knowledge_base/tasks.py personal_knowledge_base/apps.py personal_knowledge_base/test_task_recovery.py
git commit -m "fix: recover interrupted knowledge tasks"
```

---

### Task 3: 重复知识与失效任务清理服务

**Files:**
- Create: `personal_knowledge_base/knowledge_cleanup.py`
- Create: `personal_knowledge_base/management/commands/cleanup_knowledge_state.py`
- Create: `personal_knowledge_base/test_knowledge_cleanup.py`

**Interfaces:**
- Produces: `plan_knowledge_cleanup() -> CleanupPlan`。
- Produces: `execute_knowledge_cleanup(plan: CleanupPlan) -> dict`。
- Produces: management command `cleanup_knowledge_state [--confirm]`。

- [ ] **Step 1: 写重复识别和 dry-run 失败测试**

测试构造：同租户同 KB 两条相同 `file_hash`，一条软删除、一条有效；另一 KB 创建相同哈希；两个 Knowledge 可使用相同或不同 `file_path`。覆盖：

```python
def test_plan_keeps_active_duplicate_and_ignores_other_kb(self): ...
def test_command_without_confirm_does_not_write(self): ...
def test_confirm_deletes_duplicate_relations_and_unshared_files(self): ...
def test_confirm_preserves_shared_file_path(self): ...
def test_external_cleanup_failure_preserves_knowledge_for_retry(self): ...
def test_invalid_and_duplicate_tasks_are_reconciled(self): ...
```

Mock Neo4j、Wiki和索引清理边界，只在不可用外部依赖处使用 Mock；本地数据库、MEDIA_ROOT 文件和级联关系使用真实对象验证。

- [ ] **Step 2: 运行测试确认 RED**

Run:

```bash
python manage.py test personal_knowledge_base.test_knowledge_cleanup
```

Expected: FAIL，因为清理模块和命令不存在。

- [ ] **Step 3: 实现不可变清理计划**

在 `knowledge_cleanup.py` 定义 dataclass：

```python
@dataclass(frozen=True)
class CleanupPlan:
    keep_ids: tuple[str, ...]
    delete_ids: tuple[str, ...]
    invalid_task_ids: tuple[str, ...]
    superseded_task_ids: tuple[str, ...]
```

`plan_knowledge_cleanup()` 获取所有非空 file_hash 的文件 Knowledge，按 `(tenant_id, knowledge_base_id, file_hash)` 分组。排序 key 为 `(deleted_at is not None, parse_status != "completed", created_at, id)`，首项保留，其余删除。任务计划同时识别指向不存在/软删除 Knowledge 的任务，以及同一有效 Knowledge 多个未完成任务中的后续记录。

- [ ] **Step 4: 实现逐 Knowledge 完整清理**

实现 `_delete_one_knowledge(item)`，按以下顺序：

1. 调用 `cleanup_wiki_for_knowledge(item)` 和 `delete_knowledge_graph(item)`；任何异常立即抛出，Knowledge 保留。
2. 遍历 Chunk 调用 `delete_chunk_index()` 后删除 Chunk。
3. 删除 `storage_owned=True` 的 KnowledgeImage 文件，再删除图片记录。
4. 删除关联 TaskRecord、Span 和 Knowledge。
5. 若数据库中不再有其他 Knowledge 引用原 `file_path`，删除原文件。

每条 Knowledge 独立执行并收集 `deleted/errors`，一个失败不阻止其他重复组继续。

- [ ] **Step 5: 实现管理命令**

命令默认输出 keep/delete/invalid-task/superseded-task 数量和 ID，不执行写入。`--confirm` 调用执行函数并输出 JSON 风格汇总；存在清理错误时以 `CommandError` 结束并保留错误 Knowledge。

- [ ] **Step 6: 运行 Task 3 测试确认 GREEN**

Run:

```bash
python manage.py test personal_knowledge_base.test_knowledge_cleanup
```

Expected: 全部 PASS，跨 KB 和共享路径数据保留。

- [ ] **Step 7: 提交 Task 3**

```bash
git add personal_knowledge_base/knowledge_cleanup.py personal_knowledge_base/management/commands/cleanup_knowledge_state.py personal_knowledge_base/test_knowledge_cleanup.py
git commit -m "feat: clean duplicate knowledge and stale tasks"
```

---

### Task 4: 清理当前数据并完成综合验证

**Files:**
- Modify only if verification exposes a regression in Task 1–3 files.
- Inspect: current SQLite database and local media storage.

**Interfaces:**
- Consumes: `cleanup_knowledge_state` command and startup recovery API。
- Produces: cleaned current data and verification evidence。

- [ ] **Step 1: 执行当前数据库 dry-run 并保存 ID 清单**

Run:

```bash
python manage.py cleanup_knowledge_state
```

Expected: 只列出同 KB 重复/软删除副本和失效任务；不得把跨 KB 的 Wu/EulerMormer 文件列为互相重复。

- [ ] **Step 2: 确认清单后执行不可逆清理**

Run:

```bash
python manage.py cleanup_knowledge_state --confirm
```

Expected: 删除计划中的重复副本、关联任务和无共享文件；保留每个知识库中的有效副本。

- [ ] **Step 3: 验证 VLM 外部状态和本地熔断**

不再次批量调用图片 API。读取当前 cache/能力接口，确认阿里云账户仍为 `AllocationQuota.FreeTierOnly` 时前端能力显示不可用。说明账户侧必须关闭“仅使用免费额度”或补充付费信息；代码熔断已经阻止同文档重复调用。

- [ ] **Step 4: 运行全部后端测试**

Run:

```bash
python manage.py test
```

Expected: 所有测试 PASS；允许既有测试主动产生的 400/404 和无模型日志，但不得有失败或错误。

- [ ] **Step 5: 验证迁移和代码质量**

Run:

```bash
python manage.py makemigrations --check --dry-run
git diff --check
```

Expected: `No changes detected`，`git diff --check` exit 0。

- [ ] **Step 6: 验证路径边界和运行状态**

Run:

```bash
git diff --name-only 526faa4..HEAD
git status --short
```

Expected: 不包含 `MiMo-Code/`、`open-webui/`、`WeKnora/`、`xiaolinnote_ai/`。记录仍存在的用户/先前 Chunk 工作区变更，不误提交或回退。

- [ ] **Step 7: 提交验证中必要的最小修正**

仅当 Step 4–6 暴露回归时，先在 `test_multimodal_processing.py`、`test_multimodal_api.py`、`test_task_recovery.py` 或 `test_knowledge_cleanup.py` 中新增能复现该回归的失败测试，再修改 Task 1–3 所列生产文件并仅暂存实际变化的文件：

```bash
git add personal_knowledge_base/model_providers.py personal_knowledge_base/multimodal.py personal_knowledge_base/document_parsing/__init__.py personal_knowledge_base/tasks.py personal_knowledge_base/apps.py personal_knowledge_base/knowledge_cleanup.py personal_knowledge_base/management/commands/cleanup_knowledge_state.py personal_knowledge_base/test_multimodal_processing.py personal_knowledge_base/test_multimodal_api.py personal_knowledge_base/test_task_recovery.py personal_knowledge_base/test_knowledge_cleanup.py
git commit -m "fix: address recovery verification regression"
```

无回归时不创建空提交。

---

## Plan Self-Review

- 设计中的 VLM 403 识别、当前图片停止、后续图片熔断、下文档重试和能力状态均由 Task 1 覆盖。
- pending 恢复、过期 running、心跳、原子认领、重复任务和启动命令隔离均由 Task 2 覆盖。
- 同租户同 KB 哈希判重、有效副本优先、完整派生数据清理、共享路径和外部失败可重试均由 Task 3 覆盖。
- 当前数据执行、全量测试、迁移检查和参考项目路径检查由 Task 4 覆盖。
- 不需要数据库迁移；任务租约复用 `updated_at`。
