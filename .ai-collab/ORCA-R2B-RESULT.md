# ORCA-R2B-RESULT — 持续任务恢复（常驻有界恢复 loop + worker 恢复范围）

- 任务: task_a225951b0d82 ｜ 本轮 Dispatch: ctx_7202552dc69a（旧轮次草稿续作，未完审查 msg_2b0f2ffda27c/msg_a7308222121b 已处理并 ack）
- 分支: prep-desktop-commercial-release（未提交）｜ 更新: 2026-10-01
- 范围遵守: 仅改 `personal_knowledge_base/tasks.py`（恢复过滤/调度部分）、`personal_knowledge_base/management/commands/run_task_worker.py`、`personal_knowledge_base/test_task_recovery.py`；新增 `personal_knowledge_base/task_recovery.py`、`personal_knowledge_base/test_task_worker_lifecycle.py`、本报告。未触 D2 桌面文件、R2A ownership 围栏、依赖/前端/配置/迁移。

---

## 结论

旧实现 `schedule_startup_recovery` 只有 0.1s/90.1s 两个一次性 Timer、`run_task_worker` 只查 pending：约 90 秒后崩溃 worker 的租约永远无人恢复。R2B 落地为每进程唯一的有界常驻恢复 loop（`task_recovery.TaskRecoveryLoop`：daemon 线程 + stop Event、固定 30s 可注入间隔、首轮保留 0.1s 启动延迟、失败记简短日志等下一间隔、每轮前后 `close_old_connections`），web 恢复原有全部队列，worker 命令恢复其 `--queue` 队列且独立线程扫描（同步长任务/繁忙期间照常扫描），`recover_incomplete_tasks` 新增作用于全部四分支的 `queue_names` 过滤（默认 None=全队列，R1 snapshot CAS 与 pending→eval 交 worker 消费语义不变）。终验合并 142 项 OK exit 0（含 R2A ownership 30 项与真实双进程互斥），Codex 探针 `marlin_codex_r2b_probes` 4/4 OK exit 0（修复前 3 失败），真实跨进程崩溃→租约过期→后继 --once 恰好认领一次由独立验收测试证明。

## 实现要点

### 1. `task_recovery.py`（新增，常驻有界 loop）
- `TaskRecoveryLoop`：`run()` = 首轮等待 `initial_delay_seconds`（保留旧 `STARTUP_RECOVERY_DELAY=0.1`）→ 首轮恢复 + 向量重建启动检查（仅初始化一次，不随周期重复触发全量重建；worker 可 `include_startup_reindex_check=False` 关闭）→ `while not stop_event.wait(interval)` 周期恢复直到停止。等待全部事件驱动，无 tight spin、无重复 Timer。
- `_round`：`close_old_connections` 前后包裹；`OperationalError/ProgrammingError` 记 warning，其他异常记**简短** warning（类型名+消息，无堆栈），均等待下一间隔。
- 进程级单例 `start_recovery_loop`/`stop_recovery_loop`（按审查修复）：存活且**同契约**（`(queue_names, include_startup_reindex_check)` 键）→ 幂等复用；契约不同 → `RuntimeError`，绝不静默换契约；**stopping 且线程仍活**（join 超时窗口）→ `RuntimeError`，既不返回 stopping 实例也不开第二个线程；`stop_recovery_loop` 仅在 join 成功后清除单例，超时保留 stopping 状态。
- `stop(timeout)`：置位 stop_event + 有限时间 join；docstring 如实声明——恢复轮阻塞在卡死回调上时 join 超时到期即放行，daemon 线程随进程硬终止，绝不阻塞 shutdown（有界停止的已知限制）。
- web 退出兜底：`start_recovery_loop` 注册一次性 `atexit` stop/join（同一有界限制）。
- `run_recovery_round(queue_names)`：单次有界恢复轮（worker `--once` 的确定性恢复步骤），失败返回 None 不抛出。

### 2. `tasks.py`（恢复过滤/调度部分）
- `recover_incomplete_tasks(now=None, queue_names=None)`：`queue_filter` 应用于**全部四分支**——unsupported、process_knowledge stale、process_knowledge 分组、generic（prepare_open_rag_dataset/open_rag_evaluation/rebuild_vector_index）。`None`（默认）= 全队列，web 行为不变；R1 快照 CAS（含 updated_at/attempt_count 指纹）原样保留；evaluation 队列记录恢复后仍只重置为 pending 交 worker 消费，web 不直接运行。
- `schedule_startup_recovery()`：`should_schedule_recovery`（管理命令/test/migrate/autoreload-parent 过滤）不变；通过后委托 `start_recovery_loop(interval_seconds=RECOVERY_INTERVAL_SECONDS=30.0, initial_delay_seconds=STARTUP_RECOVERY_DELAY=0.1)`，双 Timer 删除。

### 3. `run_task_worker.py`
- 正常模式：`start_recovery_loop(queue_names=queues, include_startup_reindex_check=False)`（只恢复自己服务的队列；启动向量重建检查属 web 职责）+ 轮询 drain；恢复扫描在独立 daemon 线程，**同步执行长任务或队列持续繁忙时照常扫描**；`finally: loop.stop()`（命令异常/退出有限时间停自身 loop）。
- `--once`：既有 drain 语义——一次确定性恢复（`run_recovery_round`）后处理可用 pending 直至空并退出，不留 daemon；**恢复轮失败（返回 None）→ `CommandError` 非零退出**，不照常 drain（审查项 3）。
- `--poll-interval`：NaN/inf/≤0/非数字 → `CommandError` 清楚拒绝；正值过小下界 0.1s，不无限忙等。
- CLI 表面不变（`--queue` 仍 required+choices，desktop `start_desktop.py` 兼容）。

## 审查响应（msg_2b0f2ffda27c + msg_a7308222121b，均已实现并 ack）

| # | 要求 | 落地 |
| --- | --- | --- |
| 1 | stop join 超时不得提前清空全局实例；旧线程活着不得开第二线程；不得把 stopping 实例当正常实例返回 | `stop_recovery_loop` 仅 join 成功清单例；`start_recovery_loop` 对 stopping-alive 抛 `RuntimeError`。Codex probe `test_stopping_live_loop_prevents_a_second_loop` 由红转绿 |
| 2 | alive 实例不同 queue/reindex 契约不得静默复用，同契约才幂等 | `contract` 键比较，不同抛 `RuntimeError`；同契约幂等返回。probe `test_live_loop_does_not_silently_change_queue_contract` 由红转绿 |
| 3 | `run_recovery_round` 失败（None）时 `--once` 必须 `CommandError` 非零；常驻 loop 下一周期重试 | handle 检查 None → `CommandError`（probe `test_once_failure_is_not_reported_as_success` 由红转绿）；loop 失败续扫有专测 |
| 4 | web 退出加小型 atexit stop/join，并如实说明阻塞回调下 join 超时限制 | `_register_atexit_stop`（一次性注册）；限制已写入 `_stop_loop_at_exit`/`stop` docstring 与本报告 |
| 5 | 3 轮（0.1/30.1/60.1s）未过旧 90.1s 窗口，注释/断言不成立 | `test_rounds_continue_on_fixed_interval_until_stop` 改为 5 轮可控 wait = 0.1/30.1/60.1/**90.1/120.1**s，明确越过窗口后仍恢复，无真实长 sleep |

## 命令与 exitcode（runner=/tmp/marlin-codex-review-runner.py：白名单 env + 临时 DB + BASE_DIR/MEDIA_ROOT 重定向 + sys.argv 在 django.setup 前置为 manage.py test）

| 命令 | 结果 | exit |
| --- | --- | --- |
| `python /tmp/marlin-codex-review-runner.py personal_knowledge_base.test_task_recovery`（queue 过滤+loop 契约批次） | 62 tests OK | 0 |
| `python /tmp/marlin-codex-review-runner.py personal_knowledge_base.test_task_worker_lifecycle`（首轮） | 21 tests：2 failures（**测试夹具缺陷**：fresh/expired/busy 任务共用同一 knowledge_id，触发恢复合并语义判 superseded——非产品缺陷；改为每场景独立 knowledge 后全绿） | 1 → 修复后 0 |
| `PYTHONPATH=/tmp python /tmp/marlin-codex-review-runner.py marlin_codex_r2b_probes`（Codex 探针；修复前 3 失败见 /tmp/marlin-codex-r2b-blocked-probes.log） | **4 tests OK**（4 项审查行为全部由红转绿） | 0 |
| `python /tmp/marlin-codex-review-runner.py personal_knowledge_base.test_task_worker_lifecycle personal_knowledge_base.test_task_recovery`（审查修复后） | 86 tests OK | 0 |
| `python /tmp/marlin-codex-review-runner.py personal_knowledge_base.test_task_recovery personal_knowledge_base.test_task_worker_lifecycle personal_knowledge_base.test_task_ownership personal_knowledge_base.test_knowledge_cleanup`（终验合并） | **142 tests OK**（含 R2A 真实双进程互斥 + R2B 真实跨进程崩溃恢复） | 0 |
| `python /tmp/marlin-codex-review-runner.py`（system check 冒烟） | NATIVE_URL_IMPORT_OK 17 VEC v0.1.9 | 0 |

## 验收映射（简报逐条）

- **超过原 90 秒窗口仍扫描**：5 轮可控 wait（0.1→120.1s 等价），无真实长 sleep。
- **繁忙 worker 期间仍扫描**：`test_recovery_loop_scans_while_worker_busy`——真实 loop 线程 + 真实 `recover_incomplete_tasks`，worker 线程阻塞在长任务 fn 期间过期租约被重置并 enqueue（事件等待，非时序猜测）。
- **正确 queue 边界**：`queue_names` 过滤 3 分支测试（unsupported/stale/generic）+ `--once` 不碰其他队列 + web loop `queue_names=None` 专测。
- **异常后下一周期可用**：瞬态错误/DB 错误后第 3 轮仍执行（简短日志断言无堆栈）。
- **启动幂等 / stop 不遗留线程**：单例幂等（同实例、单线程、daemon）、stop join 后 `threading.enumerate()` 无 `task-recovery-loop`；join 超时的 stopping 守卫另测。
- **--once drain 并退出**：恢复→drain 顺序断言、多任务 drain 至空、其他队列不动、退出后无 daemon 线程、恢复失败非零退出。
- **真实跨进程崩溃→恢复→只认领一次**：`test_crashed_holder_lease_is_recovered_and_claimed_exactly_once`——holder 子进程经生产 `_run_task` 认领（真实 token/租约/心跳）后被 SIGKILL（无 finally、无心跳停止，`returncode≠0` 断言）；测试进程经独立子进程把租约/updated_at 直接写进过去（时间压缩=简报允许的"缩短间隔"，避免 90s sleep）；后继子进程跑**真实** `run_task_worker --queue evaluation --once`（真实恢复轮 + 真实 drain，stub resolve 免模型调用）。断言：崩溃后行仍 running 且 claimed_by=holder；终态 completed、claimed_by 空、`attempt_count==2`（holder 1 + 后继恰好 1）、`successor_calls==1`、runs.jsonl 恰 ["holder","successor"] 两行。屏障文件 + 有界收割 + exitcode 断言，沿用 R1/R2A 机制。
- **合并测试**：`test_sync_sequential_cancel_and_lease_regression_combined`——同步顺序队列按入队序执行并完成、持有中取消 → cancelled+租约清空、fresh 租约不重置 + 过期租约恰好重置一次（二次扫描 stale_reset==0）。
- **不重置活跃续租者 / R1 CAS 保持**：R1 原测试（legacy updated_at-only 续租、ABA、heartbeat 竞速等）与 R2A ownership 30 项原样全绿，产品 CAS 谓词未动。
- **pending→eval 交 worker、web 不直接运行**：evaluation 队列恢复仍只重置为 pending（原测试绿）；worker 经 drain 消费。

## 变更文件清单（worker_done CSV 同此）

| 文件 | 类型 | 内容 |
| --- | --- | --- |
| `personal_knowledge_base/tasks.py` | 修改 | ①`RECOVERY_INTERVAL_SECONDS=30.0` 常量；②`recover_incomplete_tasks(now, queue_names)` 四分支 queue 过滤；③`schedule_startup_recovery` 重写为常驻 loop 委托（双 Timer 删除）。恢复相关 CAS/取消/终态逻辑零改动。 |
| `personal_knowledge_base/task_recovery.py` | 新增 | TaskRecoveryLoop（固定间隔/事件驱动/首轮启动延迟/单次向量检查/简短错误/连接卫生）、进程级幂等单例（契约守卫 + stopping 守卫）、atexit 兜底、`run_recovery_round`。 |
| `personal_knowledge_base/management/commands/run_task_worker.py` | 修改 | 正常模式恢复 loop（queue 限定、无向量检查、finally stop）、--once 先恢复（失败 CommandError）后 drain、poll-interval 校验/下界。 |
| `personal_knowledge_base/test_task_recovery.py` | 修改 | 双 Timer 契约测试重写为 loop 契约（单例启动、DB 错续扫、向量检查仅一次、无权限返回 None）+ queue 过滤 4 项；既有恢复语义测试（R1 全部）零弱化。 |
| `personal_knowledge_base/test_task_worker_lifecycle.py` | 新增 | 25 项：loop 契约（可控 wait）、单例/stopping/契约守卫、worker 命令生命周期（--once×4、poll 校验、繁忙扫描、finally stop）、合并回归（顺序/取消/租约）、真实 loop 繁忙扫描、真实跨进程崩溃恢复。 |
| `.ai-collab/ORCA-R2B-RESULT.md` | 新增 | 本报告。 |

## not_run / 边界（如实声明）

- **Windows 原生未跑**（本环境 WSL2/Linux；跨进程测试用 subprocess+SIGKILL，POSIX 语义）。`stop()`/join 路径无平台特定调用。
- **无真实模型调用/网络**：恢复与 worker 生命周期全部以 stub resolve/注入 fn 驱动；跨进程测试同样 stub。
- **时间语义**：租约窗口用"可控 wait（单元）/ DB 直接写过期时间（跨进程）"压缩，未真实等待 90s；生产最坏恢复延迟 ≈ 租约 90s + 最多一个 30s 扫描周期。
- **不宣称**高 QPS、多节点 HA、exactly-once：SQLite 单机语义、每进程单 loop 线程；恢复是 at-least-once 归位（R1 CAS 保证不重置活跃者），执行恰好一次由租约认领 CAS 保证到"认领"粒度，fn 幂等性仍由业务层负责。
- `--once` 恢复失败即非零退出、不 drain（保守语义：宁可worker退出由守护方重启，也不在未恢复状态下报成功）。
- atexit 停机在恢复轮阻塞于卡死回调时受 join 超时限制：到期放行退出，daemon 线程随进程硬终止（已如实注明）。
- 未重跑 P01/P02A 锁、D1 runtime_paths 等已验收基线（本轮未触碰其文件）；graphify 由 Codex 统一更新。
- 旧轮次遗留：首轮 lifecycle 测试 2 失败系测试夹具共用 knowledge_id 触发恢复合并语义（测试缺陷，已修），非产品缺陷；已在上表如实记录。
