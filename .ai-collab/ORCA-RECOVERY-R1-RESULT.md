# ORCA-RECOVERY-R1-RESULT — 任务恢复租约与取消写入竞争最小修复（r1 + r2）

- r1: task_8590df29493c / ctx_16e0a24ebf0f（已 completed，Codex 验收 changes_requested）
- r2（本报告新增）: task_36bf3dea2cfa / ctx_e51dfc4c29db，2026-09-30
- 基线: prep-desktop-commercial-release @ afa7e0138f9fbad80e80aa4ead6f1d80af0145da（全程未变；r1/r2 均为工作树改动，未提交）
- r2 边界遵守: 仅修改 `personal_knowledge_base/tasks.py`、`personal_knowledge_base/test_task_recovery.py`、`personal_knowledge_base/test_open_rag_runs.py`（仅补夹具，未改产品校验）、本报告（原子更新）；未触 P02A/R1 他人文件、依赖、前端、锁文件、配置；无真实外部 API/业务库/工作区 cache 写入；未提交/推送；graphify 由 Codex 整波统一更新。

---

## r1 内容（历史存档，含 r2 更正标注）

### 代码变更（tasks.py，r1 共 5 处）
1. 新增 `_claimed_task_records(task_id, worker_token)`（属主匹配 + id + status="running"）；`_owned_task_records` 委托之并加 cancel 排除。
2. 取消请求分支改为属主守卫 update，成功才 return。
3. `OpenRagEvaluationCancelled`/已取消异常分支：属主守卫 update，仅成功才写 cancelled cache。
4. 通用恢复 reset CAS 扩为 `{id,status,claimed_by,lease_expires_at,payload}`。**[r2 更正] r1 报告此处宣称可拦截"续租（lease/updated_at 变）"，其中 updated_at 部分系夸大：r1 的 CAS 并未包含 updated_at/attempt_count 快照守卫，legacy `lease=None` 仅触碰 updated_at 的活跃续租仍会被重置或误判 failed（Codex 探针 1/2 正是重现）。已由 r2 修复 1 补齐。**
5. `cache.delete` 移入 reset 成功守卫之后。
6. `_mark_recovery_failed` 增补 claimed_by/lease 快照守卫。**[r2 更正] 同上，updated_at-only 续租仍会误判 failed，已由 r2 修复 1 补齐。**

### r1 测试与命令（历史证据，保留）
- 基线 46 tests OK（与 Codex 独立基线一致）；red 7 新测试 5 失败（'pending'!='running'×2、'failed'!='running'、'cancelled'!='running'、'cancelled'!='completed'）；修复后 54 tests OK；test_knowledge_cleanup 26 OK；`git diff --check` 洁净。
- **[r2 更正] r1 报告将 open_rag_runs 的 422!=202 "推定归因"于 P02A 在改文件 open_rag_benchmark.py 的合约校验链——该归因无证据且错误。r2 实证：`git diff` 显示 test_open_rag_runs.py 无任何未提交改动（夹具不完整在 HEAD 即存在，与 P02A/R1 无关）；产品校验在 `eval_views.py:477`（vector/hybrid 需可用 embedding 模型，否则 422 `embedding_model_required`）与 `eval_views.py:480`（rerank_enabled 需可用 Rerank 模型，否则 `rerank_model_required`）；该 v2 成功用例只建了 answer/judge 两个 KnowledgeQA 模型，未建 embedding/rerank。422 是产品校验对不完整夹具的正确拒绝。**

---

## r2 修复内容（本轮）

### 修复 1：恢复 CAS 补齐快照 updated_at + attempt_count（tasks.py 3 处）
- `_mark_recovery_failed`（tasks.py:1656）：filter 增补 `updated_at=record.updated_at`、`attempt_count=record.attempt_count`，保留 r1 的 claimed_by/lease/payload/status 守卫。legacy `lease=None` 只触碰 updated_at 的活跃续租：SELECT（updated_at 过期）→ resolve 检查点续租 → CAS 因 updated_at 不匹配 0 行 → 不判 failed、不写 cache、不计 discarded。
- 通用 reset（tasks.py:1796）：同样增补两字段。pending→running→pending ABA（新行与快照在 owner/lease/payload/status 全同、但 updated_at/attempt_count 不同）→ 0 行 → 不重置、不删 cache、不 enqueue、不计 recovered。
- process_knowledge `kept` 一致性快照刷新（tasks.py:1750）：`refresh_from_db(fields=("status","payload"))` 扩为含 `updated_at/attempt_count/claimed_by/lease_expires_at`，使后续 `_mark_recovery_failed` 的 CAS 用一致快照，不因局部刷新放大会误判 0 行；process_knowledge 专用 stale 分支（tasks.py:1695-1710）按约未改动（其已有 `updated_at__lt=stale_before` 守卫天然拦截续租）。

### 修复 2：_run_task 失主即停（tasks.py:255-266）
- fn 正常 return 后，finalize CAS 与 cancel CAS 均为 0 行时立即 `return`：不重试 fn（r1 代码会重跑满 MAX_RETRIES=3 次并以 `failed: None` 记日志）、不写新 owner 的状态或 cache。真实 database-is-locked 的有限重试路径（异常分支）保持不变。

### 修复 3：test_open_rag_runs 夹具补全（不改产品校验）
- `test_unified_run_accepts_v2_contract_and_separates_models`：按产品管线校验实际需要补 tenant 默认 `Embedding` 与 `Rerank` 模型（type canonical、status="active"、source="openai"、parameters 含 base_url——`_db_model_config` 对空 base_url 返回 None）；hybrid/answer+judge 分离断言原样保留，校验零 mock。
- 新增拒绝用例 2 个（证明校验未被消音）：`test_unified_run_requires_embedding_model_for_hybrid`（422 `embedding_model_required`，enqueue 未被调用）、`test_unified_run_requires_rerank_model_when_enabled`（422 `rerank_model_required`）。既有 `test_soft_deleted_or_inactive_models_are_rejected`（400 invalid_configuration）原样保留。

### 测试补强（test_task_recovery.py，+3 用例 +1 断言）
- `test_generic_reset_skips_legacy_updated_at_only_renewal`：legacy 续租后断言仍 running、counts 全 0、cache sentinel 完整、不 enqueue。
- `test_resolver_failure_after_legacy_renewal_does_not_mark_failed`：续租后 resolver 抛错，断言不判 failed、cache 未被改写。
- `test_generic_reset_survives_pending_running_pending_aba`：ABA 后断言行保持 T2 updated_at/attempt_count=1、counts 全 0、不 enqueue。
- `test_expired_owner_cannot_finalize_after_recovery_reclaims_task`：补 `owner_a_calls` 计数断言（失主后 fn 必须恰执行 1 次；r1 代码下该断言为 3 次，红）。

## r2 命令与真实结果（runner：/tmp/marlin-codex-review-runner.py，白名单 env + 临时 DB + BASE_DIR/MEDIA_ROOT 重定向 + sys.argv 管理命令在 django.setup 前；未触真实外部服务）

| 步骤 | 命令 | 结果 | 退出码 |
| --- | --- | --- | --- |
| r2 red 证据（历史） | Codex 探针 `/tmp/marlin_recovery_review_probes.py`（r1 代码） | 3 失败：'pending'!='running'（续租被重置）、'failed'!='running'（误判 failed）、fn.call_count 3!=1；日志 /tmp/marlin-codex-recovery-probes.log。另 Codex 独立 93 tests 有 1 个 422 | 1 |
| 修复1+2 验证 | `python /tmp/marlin-codex-review-runner.py marlin_recovery_review_probes` | 3 tests OK（探针全绿） | 0 |
| 修复3 验证 | `... personal_knowledge_base.test_open_rag_runs` | 15 tests OK（含 2 个新拒绝用例的 422 追踪行，均为预期） | 0 |
| 合并终验 | `... personal_knowledge_base.test_task_recovery personal_knowledge_base.test_open_rag_runs personal_knowledge_base.test_knowledge_cleanup marlin_recovery_review_probes` | **Ran 101 tests in 3.825s OK**（= Codex 基线 93 + r2 新增 5 + 探针 3；REVIEW_422 ×3 均为故意拒绝用例：embedding/rerank/dataset_not_published） | 0 |

not_run：Windows 原生、真实模型/网络/服务、多进程真实并发（竞争以确定性单线程交错注入模拟）；graphify update（Codex 整波统一）。

## 变更文件清单（r2）

- 修改：`personal_knowledge_base/tasks.py`（6 处：r1 5 处 + r2 修复 1/2）
- 修改：`personal_knowledge_base/test_task_recovery.py`（r1 8 新 + r2 3 新 1 断言）
- 修改：`personal_knowledge_base/test_open_rag_runs.py`（夹具 +2 模型 +2 拒绝用例）
- 原子更新：`.ai-collab/ORCA-RECOVERY-R1-RESULT.md`（本文件）

## 残余与边界（不得过度声称）

- `_update_open_rag_runtime`（tasks.py:646-676）仍仅按 `{id,status="running"}` 更新，被抢占旧属主可跨属主写 progress/payload/result；新旧属主共享同一 checkpoint 文件路径——待后续批次（r1 已记录，r2 未扩大范围）。
- 本修复不构成全链路 exactly-once，不适用多主机 HA；SQLite 单机语义。
- `_mark_recovery_failed` 的 CAS 精确到快照等值：合法场景下若行在 SELECT 与 CAS 之间被任意字段更新（含 progress 心跳写），恢复动作放弃——这是设计语义（宁漏不抢），非缺陷。
