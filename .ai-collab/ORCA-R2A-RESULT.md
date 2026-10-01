# ORCA-R2A-RESULT — 评测进度/检查点属主保护与状态一致性

Round 1: task_0940d993e9ab / ctx_58790f1fbfa7（已正式完成）｜ Round 2（定向返工）: task_4d324a6ff347 / ctx_a0466644ac33 ｜ 分支: prep-desktop-commercial-release（未提交）｜ 更新: 2026-10-01

---

## Round 2（Codex changes_requested 定向返工）— 当前状态

### 结论

三项代码证据阻断全部修复，且按"测试先暴露缺陷再修"执行：暴露批次 14 项 5 failures + 6 errors（三项缺陷均被捕获），修复后 ownership 套件 30 项、Codex 独立探针 7 项、D1 模块 + ownership 合跑 52 项全部 exit 0。Codex 核心套件 Linux 148 / Windows 87 已独立通过（/tmp/marlin-codex-r2-round2-linux.log 及 -windows.log）。

### 修复 1 — 原始 claim 身份上下文绑定（防冒用新 owner token）

- `_WORKER_IDENTITY: ContextVar`（tasks.py 模块头）；`_run_task` 在每次 fn() 调用外 `_WORKER_IDENTITY.set((task_id, worker_token))`、finally reset——异常/返回后上下文复原，重试保持同一 token。
- 新增 `_evaluation_worker_identity(task_id, payload, claimed_by)`：有上下文时原始身份永远优先且 task_id 必须匹配（不匹配抛 RuntimeError，禁止跨 task 串用）；无上下文（离线测试/legacy 直调的明确兼容边界）回落 record 自身 token/claimed_by。两个 evaluation 入口（原 876/1432 行）全部改走 resolver，不再从再次读取的 fresh DB 取身份。
- 确定性测试：`WorkerIdentityBindingTests`（6 项）——`_run_task` 绑定/复原/重试同 token；跨 task 抛错；无上下文回落边界；**claim 后、入口读取前 preemptive reclaim 的真实入口交错测试（open 与 tenant 各一项，走真实 `run_open_rag_evaluation_task`/`run_tenant_evaluation_task` + 真实 DB + 真实 fenced 写）**：旧执行保持 owner-a 身份，check_cancelled 即停，检索 mock 未被调用，新 owner 行/payload/result/checkpoint/cache 分毫未动。修复前该交错会让旧 fn 冒用 owner-b 身份写 DB+checkpoint（暴露批次已证实）。

### 修复 2 — `_cleanup_open_rag_checkpoints` 保守守卫 + 互斥边界

- 只清理"已终结记录 + 确认仍过期"的文件：pending/running 一律保留；未知/无记录保守跳过（不引入分布式锁）。
- 新增 `_cleanup_expired_open_rag_checkpoint`：事务内以观测终态为谓词的 guarded CAS UPDATE（与 fenced 发布/认领共用同一 SQLite 写锁边界），边界内重新判断行状态（等锁期间被 resume/重置为活动态 → 0 行放弃）与文件 mtime（等锁期间被重新发布 → 放弃）；不用 exists 检查假装互斥。
- 测试 `CheckpointCleanupGuardTests`（5 项）：running/pending/无记录 8 天旧文件保留；completed/partial/failed/cancelled 过期文件清理；fresh 文件保留；边界内 resume→running 拒删；边界内 republish（mtime 变新）拒删。唯一 tmp 异常回收由 round-1 既有测试继续覆盖。Codex probe7（running 8 天 checkpoint 被删）修复前红、修复后绿。

### 修复 3 — `task_status` 运行态展平字段构建自最新 DB result

- 读路径彻底不读 locmem cache：status/progress/终态/not_found 仍以主键查询为准；`status=="running"` 且 `result` 为 dict 时，展平 runtime 字段（stage/stage_progress/completed_stages/partial_metrics/completed_questions/total_questions/failed_questions/valid_coverage）直接取自最新 DB result（剔除 status/progress/result/error_message 键避免覆盖权威值）。
- 测试：`test_running_runtime_fields_come_from_latest_db_result`——DB stage=judge / cache stage=retrieval → 输出 judge + DB partial_metrics + DB progress（即 Codex probe6，修复前红）；`test_terminal_states_...` 增加"DB 无 result 时 cache stage 不得外泄"断言；终态/not_found/cancelled/progress 断言全部保留。

### D1 测试夹具最小适配（Codex msg_9ff9f3211b3b + ask 批准）

新 cleanup 语义（未知记录跳过 + 需 DB 查询）与 D1 `test_runtime_paths.py::test_open_rag_checkpoint_write_read_cleanup_stay_in_user_root`（SimpleTestCase、断言无记录 stale 文件被删）不可兼得，225 项回归中唯一失败即此。经 ask 裁决批准方案 A：该用例拆为 `OpenRagCheckpointCleanupUserRootTests(TransactionTestCase)`，为 stale 文件创建终态 TaskRecord("stale", completed)；**全部 D1 路径断言原样保留**（用户根读写、源目录过期副本不删、fresh 保留、repo 根无写入），未改 runtime_paths 生产实现、未放宽 cleanup 保守规则。

### Round 2 diff 全清单

| 文件 | 类型 | 内容 |
| --- | --- | --- |
| `personal_knowledge_base/tasks.py` | 修改 | ①`import contextvars` + `_WORKER_IDENTITY` ContextVar；②`_run_task` fn() 外 set/finally reset；③`_evaluation_worker_identity` resolver；④两个 evaluation 入口身份捕获改走 resolver；⑤`_TERMINAL_TASK_STATUSES` + `_cleanup_open_rag_checkpoints` 保守化 + `_cleanup_expired_open_rag_checkpoint` 事务边界守卫；⑥`task_status` 运行态展平改自 DB result、读路径去 cache。 |
| `personal_knowledge_base/test_task_ownership.py` | 修改 | 新增 `WorkerIdentityBindingTests`（6，含两个真实入口 reclaim 交错）与 `CheckpointCleanupGuardTests`（5）；更新 `TaskStatusDbAuthorityTests` 两用例（stage 外泄/DB 展平）。round-1 其余 19 项未弱化。 |
| `personal_knowledge_base/test_runtime_paths.py` | 修改（Codex 批准夹具适配） | cleanup 用例拆为 TransactionTestCase 类 + 终态 TaskRecord 夹具；断言零删减、零放宽。 |
| `.ai-collab/ORCA-R2A-RESULT.md` | 原子更新 | 本报告。 |

未触碰：D2 桌面文件、依赖、前端、`config/runtime_paths.py`、R1 `_claimed_task_records`/`_owned_task_records` CAS 谓词、views、settings、迁移。

### Round 2 命令与 exitcode

worker 实跑（本终端 Linux/WSL2）：

| 命令 | 结果 | exit |
| --- | --- | --- |
| 暴露批：`python manage.py test personal_knowledge_base.test_task_ownership.WorkerIdentityBindingTests CheckpointCleanupGuardTests TaskStatusDbAuthorityTests --noinput --verbosity 1` | 14 tests：5 failures + 6 errors（三缺陷全部暴露：身份上下文缺失、cleanup 删活动文件、cache stage 遮盖 DB） | 1 |
| `python manage.py test personal_knowledge_base.test_task_ownership --noinput --verbosity 1` | 30 tests OK | 0 |
| `PYTHONPATH=/tmp python /tmp/marlin-codex-review-runner.py marlin_codex_r2_probes` | 7 tests OK（Codex 独立探针 7 项全绿） | 0 |
| `python manage.py test <12 模块 225 项回归>` | 225 tests：224 通过，唯一失败 = D1 夹具（语义冲突，已按批准适配） | 1 |
| `python manage.py test personal_knowledge_base.test_runtime_paths personal_knowledge_base.test_task_ownership --noinput --verbosity 1` | 52 tests OK（D1 22 + ownership 30） | 0 |
| `orca-ide orchestration ask`（D1 夹具冲突裁决） | Codex 批准方案 A（msg_9ff9f3211b3b） | — |

Codex 独立验证（其终端实跑，日志路径由 Codex 提供）：

| 范围 | 结果 | 证据 |
| --- | --- | --- |
| 核心套件 Linux 148 / Windows 原生 87 | 全部 exit 0（源码 hash 未变） | /tmp/marlin-codex-r2-round2-linux.log、/tmp/marlin-codex-r2-round2-windows.log |
| D1 模块补验（新 TransactionTestCase 夹具，原路径断言完整） | Linux 22 / 0.749s、Windows 原生 22 / 2.612s，exit 0 | /tmp/marlin-codex-r2-d1-linux.log、/tmp/marlin-codex-r2-d1-windows.log |
| Codex 探针（7 项，先 5 后 7 两批） | 修复前 5pass2fail exit 1（/tmp/marlin-codex-r2-r2-before.log）；修复后 7/7 exit 0 | /tmp/marlin_codex_r2_probes.py |

### Round 2 not_run / 边界（如实声明）

- Windows native 由 Codex 侧独立补验通过（核心 87 项 + D1 22 项均 exit 0）；worker 本环境仅 Linux/WSL2。
- 未重复 225 全套（Codex 明示不必；最终代码与 225 运行时 tasks.py 完全一致，唯一失败项已修复并单独绿）。
- 事务边界互斥为 SQLite 写锁语义；PG 方言未实测。未知/无记录 checkpoint 不再被自动清理（磁盘由运维兜底）——保守语义的已知代价。
- `_run_task` 上下文绑定覆盖全部经 `_run_task` 的执行路径；直接调用 evaluation 入口的离线场景走 resolver 回落边界（有测试）。
- 无其他未解决项（Codex D1 补验通过后确认可汇总交付）。

---

## Round 1（历史，2026-10-01 完成）

### 结论

R2A 完成：runtime 进度、checkpoint 发布/删除、完成 unlink 全部改为 worker_token fenced CAS；`task_status` 以 DB 为权威；`_run_task` 在 database-is-locked 有界重试的前与后都复查属主，失主/取消即停。新增 19 项属主测试（含真实双进程 write×reclaim 互斥），相关回归 194 项 + P01/P02A 锁 20 项全绿。

### Diff 全清单（round 1，round 2 叠加于其上）

| 文件 | 类型 | 内容 |
| --- | --- | --- |
| `personal_knowledge_base/tasks.py` | 修改 | ①`_update_open_rag_runtime` 新增必填 `worker_token` kwarg；快照读与条件 UPDATE 均走 `_owned_task_records`，易主后 UPDATE 0 行、不写 cache。②`_write_open_rag_checkpoint` 保留为离线 unfenced helper（docstring 注明仅测试/导入工具），改用唯一 `mkstemp` 临时文件 + finally 回收；新增 `_atomic_checkpoint_publish`。③新增 `_write_fenced_open_rag_checkpoint`：serialize/临时文件在事务外，`transaction.atomic` 内 owned CAS UPDATE 取 SQLite 写锁后同目录原子 rename，0 行拒发并回收 tmp；新增 `_delete_fenced_open_rag_checkpoint`。④`run_open_rag_evaluation_task`/`run_tenant_evaluation_task`：`stop_unowned` 助手（fenced 失败→先 `check_cancelled` 保持取消语义，再按失主抛 `OpenRagEvaluationCancelled` 兜底停止）；全部回调显式传 `worker_token` 并在 0 行时停止；完成 unlink 改 fenced 删除。⑤`_run_task` locked 重试：`_retry_cancelled_out` 助手，sleep 前与 sleep 后各复查一次属主/取消。⑥`task_status` DB 权威（round 2 进一步去掉 cache 读路径）。 |
| `personal_knowledge_base/test_task_ownership.py` | 新增（round 1: 19 tests） | fenced runtime 写、快照防抢写、legacy 空 token/payload token 边界、fenced checkpoint 发布往返+0600、旧 owner 发布/删除被拒、tmp 异常回收、task_status 终态/删除权威、`_run_task` 失主不重跑/cancel 落地/bounded 重试/sleep 期间失主即停、tenant/open 回调 fenced 拒绝即停、真实双进程 write×reclaim 互斥（屏障文件 + 有界收割 + exitcode 断言）。 |
| `personal_knowledge_base/test_evaluation_examples.py` | 修改（2 行） | 仅 mock 契约适配（`_write_fenced_open_rag_checkpoint` + `_delete_fenced_open_rag_checkpoint`），断言未动。 |
| `.ai-collab/ORCA-R2A-RESULT.md` | 新增 | 本报告。 |

### Round 1 命令与 exitcode

- 双进程互斥单测：1 test OK，exit 0（4.4s）。
- Codex 探针（当时 5 项）：修复前 3 失败（before 日志）；修复后 5/5 OK，exit 0。
- 12 模块相关回归 194 tests OK，exit 0；`test_runtime_lock_portability` 20 tests OK，exit 0。

### Round 1 原子性边界（继续有效）

- checkpoint 发布 = 事务内 owned CAS（SQLite 写锁）→ 同目录唯一 tmp 原子 rename → 提交；与 claim/reset 互斥、可线性化；**不是**文件与 DB 的严格两阶段提交。
- 事务内只有本地 fs 操作；serialize、`save_open_evaluation_report`、langfuse 上报均在事务外；不复制海量 payload 进 DB、无 Redis/新缓存协调。
- 空 token 兼容仅命中 `claimed_by=""` 的实际无主 legacy 记录；外部副作用不宣称 exactly-once。
