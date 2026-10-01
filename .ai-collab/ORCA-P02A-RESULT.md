# ORCA-P02A 交付报告（round 2 主体；round 1 原文自「历史存档」起逐字保留）

- r2 Task: MARLIN-P02A round 2（Orca Task `task_849586d20efa` / Dispatch `ctx_afb1b54dfa95` / Run `run_c0d51a93432f`）；round 1 Task `task_c88afbb1710f` / Dispatch `ctx_e3d54d183f92` 已 completed、验收 changes_requested，r2 仅修复其指明缺口，不重审已验收项
- r2 执行者: Orca ZCode（term_f8c9c557-bdc5-4749-bddb-0f9f0820bc28）；协调者 Codex 仅协调/验收
- workspace: /home/liuxuedeng/orca/workspaces/Django-Agent/marlin；branch: prep-desktop-commercial-release
- r2 开始与结束时 HEAD `afa7e0138f9fbad80e80aa4ead6f1d80af0145da`（未变；未提交/推送/合并/发布）
- 环境: Python 3.12.2（anaconda3），filelock 3.13.1（requirements 声明 `filelock>=3.13,<4`），Django 5.2.15

## R2-A. r2 交付总清单（整个 P02A 的新增/修改/删除全量）

| # | 文件 | 轮次 | 变更概要 | SHA256（r2 结束态） |
|---|---|---|---|---|
| 1 | personal_knowledge_base/model_rate_limit.py | r1 修改；r2 未动 | 删模块级 fcntl；`_bucket_lock` 改 filelock（详见 §1） | `fbed2185c5d11c6b50d33a8421148343b1b1c6f7f7f1c069717706438132da54`（与 r1 一致） |
| 2 | personal_knowledge_base/open_rag_benchmark.py | r1 修改；r2 未动 | `open_rag_prepare_lock` 改 FileLock acquire/Timeout 语义（详见 §1） | `f334ab9ce7651ce63627fa34cd2baabcf93f8cc866a870fcd71cd6f7e5708f39`（与 r1 一致） |
| 3 | scripts/local_services.py | r1 修改；r2 修改（R1） | r2：严格剩余 deadline，见 R2-B | `6598cf98cf688b4d8a90571612404b6e87183949043dad0819992de51cb67fdb` |
| 4 | personal_knowledge_base/test_runtime_lock_portability.py | r1 新增；r2 修改（R1/R2） | r2：确定性时钟×3 + 屏障/进程卫生 + 真实争用探针，17→20 项，见 R2-B | `cb01cc0b64765f578a1aa535a8cb53732d85315df1d7205bdaa2205032d23122` |
| 5 | .ai-collab/ORCA-P02A-RESULT.md | r1 新增；r2 原子替换（R4） | 本文件（同目录临时文件 + rename 原子替换） | 不自记（文件自身） |

- 删除文件：整个 P02A 无删除项。（工作树中其余 D/M 状态属 MARLIN-CLEANUP-01 等他人任务，不在本 Task 范围；r2 期间工作树新出现的未跟踪 frontend/src/router/auth-guard.test.mjs 与 frontend/src/views/Login.behavior.test.mjs 亦非本 worker 产出，未触碰。）
- model_rate_limit.py / open_rag_benchmark.py：r2 判定无必要锁语义修复，零改动。

P01 保护四文件核验（r2 结束时 sha256sum，与历史 TASK/REVIEW 记录逐字一致）：
- accounts/views.py `a6c241180c83a7afa2493e7827ae85aff177eb0b99c8a041856eab364558632f` ✓
- requirements.txt `b5432b4fb55a9b79463a53d0fea21d32b8776f91a684f670cb5b69465ebbd0c3` ✓
- accounts/test_auto_setup_portability.py `cef757cd9bcb49a2879d377a31530507dd7d18d5ad408620f5f2fa80c7fd3e65` ✓
- accounts/test_auto_setup_processes.py `b12599687f0c42279bff88835d170720429c6be34b15ac8794bd214318a8fadf` ✓

`git diff --check` 退出码 0（无空白错误）。

## R2-B. r2 代码变更内容

**scripts/local_services.py（R1）**：`ensure_langfuse` 锁等待改为先计算剩余、`remaining <= 0` 直接 `startup_timeout`，否则 `lock.acquire(timeout=remaining)`（删除 `max(.05, …)` 预算放大）；获得锁后每条 docker 命令前重查剩余、耗尽即返回 `startup_timeout` 不执行后续命令，`subprocess.run(timeout=remaining)`（删除 `max(.1, …)`）；HTTP 探针 `timeout=min(2, remaining)` 且剩余≤0 即止（删除 `max(.1, …)`，覆盖协调者补充要求）；disabled/external/missing_server_configuration/docker_unavailable/compose_failed/healthy/startup_failed/startup_timeout 映射全部保留；同一 monotonic deadline，获得锁后不重置预算。

**test_runtime_lock_portability.py（R1+R2）**：
- R1：新增 `_ScriptedClock`（注入 `scripts.local_services.time` 的确定性时钟）与三个确定性测试（见 R2-D）。
- R2 屏障：跨进程测试改显式 held/attempting/blocked/release 屏障——同 key 与 blocking prepare 用例中，contender 先对同一路径做一次**真实失败的 acquire**（`FileLock.acquire(timeout=0)` 抛 `Timeout` 且 `is_locked` 为 false，证明真实内核级争用而非仅启动顺序），此后才写 `B_blocked`/`C_blocked`；holder 等 blocked 标记（而非 attempting）才于 **unlock 前**写 release 注记（model `A_releasing`、prepare `P_released`）并解锁，contender 获锁后立即可见（消除 r1 unlock 后写标志与 contender 的竞争）；删除 holder `sleep(0.8/1.2)` 猜测式自释；非阻塞用例保持 `C_done` 屏障（holder 持锁直至 contender 在 with 体内写出该标记，尝试时锁必然被持）。
- R2 进程卫生：全部 Popen 创建自第一进程起在 try/finally 内（二次 spawn 失败亦回收首个）；`_wait_child` = communicate + 校验真实 exitcode + 空 stderr（kill 仅异常终止；crash 用例校验真实 exitcode=2）；`_wait_marker` 监视被观察子进程提前退出并立即携带 stderr 报错（不再空等 30s）；`_reap` 幂等化（重复回收为 no-op）。
- 保留：fcntl 阻断探针×3、模型锁语义/异常释放/0600（断言在持锁内，不假设 Windows 释放后保留锁文件）、独立 key 并行；框架仅 +3 测试与少量辅助。

## R2-C. r2 命令与退出码（按时间序，真实记录）

runner：/tmp/marlin-p02a/run_isolated_tests.py（r2 版）——os.environ 按白名单重建（不 setdefault 继承业务凭据）；DJANGO_DB_PATH → OS 临时 sqlite；`sys.argv=["manage.py","test",labels]` 于 django.setup 前设置（`should_schedule_recovery` 走 management-command 分支，不再调度 startup recovery）；`settings._setup()` 后于 django.setup **前**覆盖 `BASE_DIR`/`MEDIA_ROOT` → /tmp/marlin-p02a/base；labels/env 键白名单写入 final-run-manifest.json；shell 侧 `env -i` 白名单（PATH/HOME/LANG/LC_ALL/TMPDIR/SSL_CERT_FILE）。

1. 新模块单跑（迭代验证，屏障加强前）：`python3 run_isolated_tests.py personal_knowledge_base.test_runtime_lock_portability` → **20 tests, OK, exit 0, 5.9s**（日志 r2-portability-iter1.log；"startup recovery" 警告 0 条）。
2. R3 最终合并（一次运行；不重跑已知基线——Codex 日志 /tmp/marlin-codex-p02a-r1-review.log 已证明旧 108 项 7.362s 通过）：五模块 labels（test_llm_providers、test_open_rag_benchmark、test_settings_thinking.LocalStartupTests、test_langfuse_access_regressions.LangfuseConfigurationRegressions、test_runtime_lock_portability）→ **111 tests（=91 旧四模块 + 20 新模块）, OK, exit 0, 6.7s**（日志 r2-final-merged.log；退出码存 r2-final-merged.exit；此运行先于 R2-B 屏障加强）。
3. 屏障加强后定向重跑（按协调者 msg_90428bd4eec5 仅定向，不重复广泛回归）：`python3 run_isolated_tests.py personal_knowledge_base.test_runtime_lock_portability` → **20 tests, OK, exit 0, 5.8s**（日志 r2-portability-final.log，结束态 hash cb01cc0b…）。
4. 协调者转达的 Codex 独立验证（msg_90428bd4eec5，日志时间戳 2026-10-01 09:24）：Linux 合并 111 tests OK（/tmp/marlin-codex-p02a-r2-review.log）；Windows native 锁模块 20 tests = 19 pass + 1 skip, exit 0（/tmp/marlin-codex-p02a-r2-windows.log；skip 为 POSIX 权限位用例，符合设计）。
5. 隔离有效性：r2 运行后仓库根无 `.cache/`；/tmp/marlin-p02a/base/.cache 出现 model-rate-limits/eval-datasets/eval-reports（与 r1 污染结构一致，证明运行副作用落在隔离目录）；r2 三份本 worker 日志 "startup recovery" 均 0 条（r1 iso-regression.log 首行该警告已消除，见 E-3）。

未运行：全仓测试、迁移、前端 Playwright、真实 Docker/HTTP。**Windows native execution: not_run** —— 延续 r1 结论：本机 Windows 解释器未装项目依赖，本轮本 worker 未装工具链（Codex 侧已按其自身环境完成 Windows native 锁模块验证，见上第 4 条）；r1 的限制表述仍成立："未准备项目依赖环境"，而非"没有 Windows 实机"。

## R2-D. R1 确定性复现（无需真实 Docker/HTTP）

- `test_deadline_spent_on_lock_grant_stops_before_docker`：包装类先调真实 `FileLock.acquire`（真实成功），再令注入的脚本化 monotonic 超过既定 deadline → 断言 `startup_timeout` 且 `subprocess.run`/`build_opener` 均 0 调用。Codex r1 审查在该场景实测旧代码 docker 被调 2 次；本测试以 0 次断言固化修复（对应 Codex r2 探针 late_lock，已 exit 0）。
- `test_first_compose_consuming_budget_skips_second_command`：首个 compose 返回时耗尽剩余预算 → 第二命令不调用（`run.call_count==1`、首调用命令含 `config`），状态 `startup_timeout`（对应 Codex r2 探针 first_compose_exhausts_budget，已 exit 0）。
- `test_health_probe_timeout_uses_remaining_budget_only`：第二个 compose 后仅剩 ~0.05s → 探针 timeout=剩余（断言 `0 < timeout < 0.1`；r1 的 `max(.1,…)` 会给 0.1s），探针失败耗尽预算后 `startup_timeout`、open 恰 1 次。

## R2-E. 勘误（对 r1 报告的更正；r1 原文按历史保留，不改写）

- **E-1（§3.2 "5 项失败全部为 fcntl 阻断暴露" 不成立）**：exposure4.log 五项失败中仅 3 项是 fcntl 证据（langfuse/model/prepare 探针，日志含 `ModuleNotFoundError: No module named 'fcntl'`）。第 4 项 `test_lock_error_blocks_critical_section` 失败为 "AssertionError: OSError not raised"——该测试断言的是新 FileLock 实现的 seam（mock `filelock.FileLock.acquire` 抛 OSError），旧 fcntl 实现不经过该路径，属**新 FileLock 实现约束**，不是 fcntl 阻断证据；第 5 项 `test_blocking_waits_for_release_then_acquires` 仅为 `P_acquired_after_release` 标记 20s 未出现，日志中无 contender fcntl 崩溃证据（当时子进程 prefix 未安装 blocker），r1 归因 "contender 在函数内 import fcntl 崩溃" 属臆测，撤回。
- **E-2（exposure2 定性）**：exposure2.log 为测试草稿缺陷——`ModuleNotFoundError: No module named 'config'`（config 路径错误）与 `NameError: name '_bucket_lock' is not defined` / `name 'open_rag_prepare_lock' is not defined` 等，不是业务 fcntl 暴露。
- **E-3（r1 隔离结论过强）**：r1 iso-regression.log 首行为 `WARNING … tasks Task startup recovery skipped: no such table: task_records`，说明该次正式运行的 runner 副作用隔离未完全满足（startup recovery 曾被调度并触到空库），不能宣称"全部正式隔离已满足"。r2 runner 已消除（argv 分类 + setup 前覆盖 BASE_DIR/MEDIA_ROOT），r2 日志该警告 0 条。r1 §4 所记 .cache 污染隔离失误与处置维持原记录。
- **E-4（§6 graphify 退出码）**：r1 所记 "`graphify update .` exit 0" 的 0 取自管道 tail 的 `$?`，非 graphify 实际返回码，该数值撤回。r2 本 worker 未运行 graphify update（按协调者消息 msg_14325e4f36b3 由 Codex 统一更新），故 r2 无可记录的 graphify 实际返回码。
- **E-5（exposure3 补充定性）**：exposure3.log 中 `test_lock_file_enforces_0600` 的 ERROR 为草稿期在锁释放后 stat 锁文件（`FileNotFoundError`，filelock 释放即删锁文件），属测试草稿缺陷，非业务暴露；r1 定稿已改为持锁内断言。

## R2-F. 未做与遗留

- 未做：提交/推送/合并/发布、Windows 依赖安装、真实 Docker/网络/凭据、全仓测试、graphify update（由 Codex 统一更新）、model_rate_limit.py / open_rag_benchmark.py 改动（r2 无必要锁语义修复）、任何未授权文件改动。
- 遗留（超出本 Task，维持 r1 §6 记录）：`os` 在 model_rate_limit.py 仍被 `_bucket_lock` 的 chmod 使用（保留正确）；open_rag_benchmark 其余 urlopen 下载路径平台行为未验证；Langfuse 健康检查真实联网路径仅 mock 验证。
- 附属产物（OS 临时，不入仓库）：/tmp/marlin-p02a/{run_isolated_tests.py(r2 版)、r2-portability-iter1.log、r2-final-merged.log、r2-final-merged.exit、r2-portability-final.log、final-run-manifest.json、base/}。

---

# 以下为 round 1 历史存档（原文逐字保留，其中被 R2-E 勘误的表述以勘误为准）

# ORCA-P02A 交付报告（Orca implementation round 1）

- task_id: MARLIN-P02A（Orca Task `task_c88afbb1710f` / Dispatch `ctx_e3d54d183f92` / Run `run_c0d51a93432f`）
- 执行者: Orca ZCode（term_127438bb-773e-4db1-af73-f14d5fbf47ef）；协调者 Codex 仅协调/验收
- workspace: /home/liuxuedeng/orca/workspaces/Django-Agent/marlin
- branch: prep-desktop-commercial-release；开始时 HEAD afa7e0138f9fbad80e80aa4ead6f1d80af0145da（未变，未提交/推送/合并）
- 环境: Python 3.12.2（anaconda3），filelock 3.13.1（requirements 声明 `filelock>=3.13,<4`），Django 5.2.15
- 授权来源: 当前 Orca Task/Dispatch；旧 .ai-collab TASK/STATUS 仅作历史证据，未恢复文件派发轮询

## 1. 变更清单（业务 3 + 测试 1，均在允许范围内）

| 文件 | 变更 | SHA256 |
|---|---|---|
| personal_knowledge_base/model_rate_limit.py | 删模块级 `import fcntl`；`_bucket_lock` 改 `filelock.FileLock(path, mode=0o600)` 阻塞 `acquire()`+finally `release()`，acquire 后 `os.chmod(0o600)` 保留权限意图；key/缓存目录/事务/补充速率/blocked_until 逻辑未动 | fbed2185c5d11c6b50d33a8421148343b1b1c6f7f7f1c069717706438132da54 |
| personal_knowledge_base/open_rag_benchmark.py | 顶部 `from filelock import FileLock, Timeout`；`open_rag_prepare_lock` 改 `acquire(timeout=None if blocking else 0)`，`Timeout`→yield False，finally 仅在 acquired 时 release；算法/语料下载未动 | f334ab9ce7651ce63627fa34cd2baabcf93f8cc866a870fcd71cd6f7e5708f39 |
| scripts/local_services.py | 顶部 `from filelock import FileLock, Timeout`；`ensure_langfuse` 锁段改单次 `acquire(timeout=剩余预算)`，`Timeout`→`startup_timeout`（不触 Docker），锁内 finally release；同一 monotonic deadline，获得锁后不重置预算；disabled/external/docker_unavailable/compose_failed/missing_server_configuration/healthy 状态映射保留 | 809705b7bcef08f9146b04b5170832f227d815837165413055b59bad5623d28d |
| personal_knowledge_base/test_runtime_lock_portability.py | 新增集中行为测试 17 项（fcntl 阻断探针×3、模型锁语义/跨进程×6、prepare 业务上下文×3、Langfuse×5） | 2739184c095a7e6c00122be8a114a143392ce3a87ef1c0ae1ff9eb93e677322a |

未动其它业务文件、迁移、前端、依赖/配置；未改旧协作 STATUS/RESULT/TASK/DECISIONS/REVIEW。

P01 保护四文件核验（sha256sum，与历史 TASK/REVIEW 记录逐字一致）：
- accounts/views.py `a6c241180c83a7afa2493e7827ae85aff177eb0b99c8a041856eab364558632f` ✓
- requirements.txt `b5432b4fb55a9b79463a53d0fea21d32b8776f91a684f670cb5b69465ebbd0c3` ✓
- accounts/test_auto_setup_portability.py `cef757cd9bcb49a2879d377a31530507dd7d18d5ad408620f5f2fa80c7fd3e65` ✓
- accounts/test_auto_setup_processes.py `b12599687f0c42279bff88835d170720429c6be34b15ac8794bd214318a8fadf` ✓

`git diff --check` 退出码 0（无空白错误）。

## 2. 验收证据（A1–A6）

- **A1（fcntl 不可导入仍进入业务锁路径）**：`test_runtime_lock_portability.BlockedFcntlImportContractTests` 三个探针在独立 Python 子进程以 import-system 级阻断 fcntl（MetaPathFinder；先装载 filelock POSIX 后端再弹出 `sys.modules["fcntl"]`，使"业务模块自身 import fcntl 必炸、filelock 内核锁照常"）。修复前三项全失败（见 §3），修复后全过：模型锁进入临界区写标记、prepare 锁 blocking=False 获得、ensure_langfuse 返回 missing_server_configuration。未用 SoftFileLock，POSIX 后端为真实 flock 内核锁。
- **A2（模型锁语义）**：`ModelBucketLockSemanticsTests`（0600 权限持锁内断言、锁错误阻止临界区、临界区异常后可重获）+ `ModelBucketLockCrossProcessTests`（同 key 真实双进程互斥：持锁者先进入，后继者仅在对方释放后进入；不同 key 双进程并行 rendezvous 无超时；持有进程 `os._exit` 后内核释放、后继可获取）。`acquire_model_tokens`/`defer_model_calls` 的事务、补充速率、blocked_until、OperationalError 重试未改；阻塞语义保持无超时；未引入分布式限流或新 API。
- **A3（Open RAG prepare lock）**：业务上下文用真实 `get_dataset_spec("open_rag_benchmark","arxiv-v1")` + 临时 cache_path（同既有测试做法）。跨进程：holder blocking=True 持锁写标记，contender blocking=False 及时 yield False（耗时 <0.8s）且不得误获得；blocking=True 等待 holder 释放后 yield True 且验证 holder 已写 released 标记；临界区异常后可重获；仍写 `.prepare.lock`。
- **A4（Langfuse 启动锁）**：`LangfuseStartupLockTests`——disabled/external 早退保留；docker_unavailable（FileNotFoundError→）与 compose_failed（rc=1→）保留；真实独立子进程持 startup.lock 时，1s 预算内争用超时返回 `startup_timeout` 且 `subprocess.run`/`build_opener` 均 assert_not_called（FileLock Timeout 不误映射 startup_failed）；holder 0.5s 释放后继续启动至 healthy（mock docker rc=0、HTTP 200，run 调用 2 次）；预算连续性：holder 占 0.8s/预算 1s/HTTP 永不健康 → startup_timeout 且总时长 <1.6s（若获得锁后重置预算则 ≥1.8s）。
- **A5（进程测试卫生）**：所有跨进程用例均为真实独立子进程；`_spawn_child` 每子进程独立 `DJANGO_DB_PATH`；`_reap` = kill + 两次有界 `communicate`（二次超时上抛不静默）+ 管道显式关闭，finally 兜底；锁均有 context/finally 保护；0600 断言置于持锁内（不假设释放后锁文件必须保留，Windows 后端可删除自身锁文件）；时间断言含 CI 容差（如 <0.8s/<1.6s/10-30s rendezvous 上限）；子进程 `django.setup()` 前 `sys.argv.append("unittest")` 命中 `should_schedule_recovery` 排除分支，禁用 startup recovery 定时器。未复制大段测试框架。
- **A6（先基线、暴露、后回归）**：见 §3 时序。fcntl 阻断探针不是 Windows 原生测试。

## 3. 测试命令与实际退出码（按时间序）

环境（全部运行一致）：`PYTHONDONTWRITEBYTECODE=1 LANGFUSE_ENABLED=false LANGFUSE_AUTOSTART=false NEO4J_ENABLE=false` + 临时 `DJANGO_DB_PATH`。

1. 修复前离线基线（业务代码未改，`python manage.py test personal_knowledge_base.test_llm_providers personal_knowledge_base.test_open_rag_benchmark personal_knowledge_base.test_settings_thinking.LocalStartupTests personal_knowledge_base.test_langfuse_access_regressions.LangfuseConfigurationRegressions --noinput --verbosity 1`）：**91 tests, OK, exit 0**。
2. 新测试修复前暴露（`python manage.py test personal_knowledge_base.test_runtime_lock_portability`，经 3 次草稿迭代修正测试自身缺陷后定稿）：**17 tests, 5 failures, exit 1, 26.6s**。5 项失败全部为 fcntl 阻断暴露【r2 勘误 E-1/E-2/E-5：该表述不成立，仅 3 项探针为 fcntl 证据】：
   - model 探针：`ModuleNotFoundError: No module named 'fcntl'`（原 model_rate_limit.py:8 模块级导入）
   - prepare 探针：`ModuleNotFoundError: No module named 'fcntl'`（原 open_rag_benchmark.py:72 函数内导入）
   - langfuse 探针：`unexpected startup state: startup_failed`（原 local_services.py ImportError 落入通用 except）
   - `test_lock_error_blocks_critical_section`：fcntl 实现下 FileLock.acquire 永不被调（语义切换后该项转绿）【r2 勘误 E-1：实为新 FileLock 实现约束】
   - `test_blocking_waits_for_release_then_acquires`：contender 子进程在函数内 `import fcntl` 崩溃【r2 勘误 E-1：日志无此证据，仅 marker 未出现，撤回臆测】
3. 修复后新模块（manage.py 直跑）：**17 tests, OK, exit 0, 7.6s**。
4. 合并定向回归（manage.py 直跑，五模块同次，含任务要求命令的全部标签）：**108 tests, OK, exit 0**。
5. **隔离修正后的正式记录**（改用 OS 临时隔离 runner `/tmp/marlin-p02a/run_isolated_tests.py`：shell 白名单 env + 临时 `DJANGO_DB_PATH` + `django.setup()` 后 `settings.BASE_DIR=/tmp/marlin-p02a/base`）【r2 勘误 E-3：该 runner 的隔离未完全满足，见 iso-regression.log 首行 startup recovery 警告】：
   - 基线四模块：**91 tests, OK, exit 0**（注：业务代码已修复状态下复核；第 1 步为修复前代码基线，二者均 91/OK）
   - 新模块：**17 tests, OK, exit 0, 6.9s**
   - 合并回归：**108 tests, OK, exit 0, 7.0s**
   - 隔离有效性证据：运行后 `/tmp/marlin-p02a/base/.cache/` 出现与此前污染相同的 model-rate-limits/eval-datasets/eval-reports 结构，而仓库根无任何新增。

未运行：全仓测试、迁移、前端 Playwright；**Windows native execution: not_run** —— 本机存在 Windows 原生 `C:\Python313\python.exe`（3.13.3），但该解释器未安装项目依赖（Django/filelock/DRF/sqlite-vec/django-cors-headers/requests/httpx 等），本轮按授权不安装 Windows 工具链，故限制应表述为"未准备项目依赖环境"，而非"没有 Windows 实机"。

## 4. 隔离失误与处置（如实记录）

首轮基线与首轮合并回归的 runner 只隔离了 `DJANGO_DB_PATH`，未隔离 `BASE_DIR`，导致 `test_llm_providers` 真实 `_bucket_lock` 路径与 `test_open_rag_benchmark` 报告用例把 `.cache/`（model-rate-limits 3 锁、eval-datasets、eval-reports，共 7 文件，时间戳 21:34）写入仓库根。处置：经协调者消息指出后确认来源（派发前 git status 无该目录、无进程占用），整体移入 `/tmp/marlin-p02a/quarantine/cache-from-workspace-20260930` 保留（未删除），仓库根已无 `.cache`；随后所有运行改用隔离 runner 并验证仓库根零新增。此失误与处置如实计入本轮交付。

## 5. A0 勘误（对 task_6a5a296d43ba / ctx_39af9b44bdfd 审计报告的纠正）

1. SSE 表述错误：`personal_knowledge_base/stream_manager.py` 的 StreamManager 已有 StreamState/StreamEventRecord 持久化、`get_stream` 恢复与 `get_events`/`_refresh_stream` 刷新，不能宣称"SSE 仅单 web 进程有效"；真实缺口是**跨进程/崩溃语义待实测**。
2. 数据路径表述不完整：`config/settings.py` 已支持 `DJANGO_DB_PATH` 环境变量；正确缺口是**缺少统一的桌面可写用户目录约定，默认仍写源码目录**（BASE_DIR 下 db.sqlite3/media/.cache）。
3. 完成度表述：派发时工作树既有 4 项为**业务改动**（P01 已验收交付），另有 .ai-collab 协调文件；不应把"主要功能源码存在"表述为"功能完整验收"。

## 6. 附属产物与未验证项

- graphify：改码前 `graphify query` 三次（锁概念/并发恢复/引用方），改码后 `graphify update .` exit 0【r2 勘误 E-4：该 0 为管道 tail 的 $?，非 graphify 实际返回码，数值撤回】；**graphify-out/（graph.json、graph.html、GRAPH_REPORT.md、2026-09-30/ 等）为忽略产物，不计入交付变更**。
- OS 临时测试数据（不入仓库）：/tmp/marlin-p02a/*（隔离 runner、日志、隔离缓存）、/tmp/p02a-dbg*、/tmp/marlin-p02a/exposure*.log 等。
- 未做：提交/推送/合并、Windows 依赖安装、真实 Docker/网络/凭据、全仓测试、未授权文件改动。
- 遗留（超出本 Task 范围，仅记录）：`os` 在 model_rate_limit.py 仍被 `_bucket_lock` chmod 使用（保留导入正确）；`open_rag_benchmark` 其余 urlopen 下载路径的平台行为未验证；Langfuse 健康检查真实联网路径仅 mock 验证。
