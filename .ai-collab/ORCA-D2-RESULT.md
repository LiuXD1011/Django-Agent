# ORCA-D2-RESULT — MARLIN-D2 最小 Windows 桌面运行入口（retry dispatch）

- Task: `task_3eaaedeb24fd` / Dispatch: `ctx_d84c89eb85bf`（同 Task retry；前一 worker 被系统 Killed，业务草稿按指示保留并在此之上修复）
- 日期: 2026-10-01
- 运行平台: Linux (WSL2, python3.12)。**Windows native 未由本 worker 运行**，由 Codex 按原计划独立验收。

## 实现范围（恢复清单 8 项全部闭环）

### scripts/start_desktop.py（桌面入口，本 dispatch 修复项）

1. `stop_group`：单项 `_stop_process` 抛错仍逐一回收其余 child，最后重抛首个错误；`run_desktop` 的 `finally` 捕获清理错误并保证实例锁必定释放（嵌套 try/finally）。
2. `run_migrations`：`communicate` 遇 `KeyboardInterrupt`/`SystemExit`（BaseException）先 `_stop_process` 回收自己持有的 migrate child 再上抛；`TimeoutExpired` 路径保持原有 stop+DesktopError(EXIT_MIGRATE)。
3. `probe_health`：HTTP 超时 = 真实剩余预算 `min(2.0, remaining)`，删除 0.1s 下限（不再越过 deadline）；仍禁系统代理 + `X-Marlin-Desktop-Instance` 头比对。
4. `wait_healthy`：每轮先 poll 所有 children，任一早退立即失败（打印 `exited early (code N) during startup`），不再等满 deadline；sleep 取 `min(0.25, remaining)`。
5. `ensure_secret`：改用 `os.open(O_WRONLY|O_CREAT|O_EXCL, 0o600)` + `os.fdopen`，密钥从首字节即 0600（不再 open 0644 写完再 chmod）；原子 `os.replace`，空文件拒绝替换、不打印密钥等行为不变。
6. `run_desktop`：`--data-dir` 经 expanduser 后立刻 `os.path.abspath` 绝对化，env/锁/secret/DB 及子进程（cwd=源码根）共用同一绝对路径，相对路径不再因子进程 cwd 漂移。
7. `_run_migrate_mode`：在 `django.setup()` **之前**设 `sys.argv=["manage.py","migrate"]`（`APP_TASKS_SYNC="test" in sys.argv`，恢复定时器不再被拉起进入迁移）；在创建 MigrationExecutor **之前**记录既有 DB 存在性（executor 的 migration_plan 会在 fresh 时制造空 sqlite 文件），仅 `db_existed AND pending` 才经 SQLite backup API 写 `data/backups/pre-migrate-*.sqlite3`，fresh 不备空库，无待迁移不重复备份。

### config/desktop_wsgi.py

- `_same_origin` 改为有效端口正规化：http 隐式 `:80` 与显式 `:80` 等价，且必须同时等于请求 Host 端口与绑定端口 `MARLIN_DESKTOP_PORT`；`null`/外站/错端口/`https`/ftp 拒绝不变；新增显式拒绝 userinfo（`evil@127.0.0.1`）与畸形端口（urlsplit ValueError 捕获）。
- WhiteNoise 仅服务源码根 `frontend/dist/assets` → `/assets/`、SPA 深链/health/API/files 鉴权走 Django、auth 响应 no-store、auto-setup 仅 POST、实例响应头：均保持草稿已实现行为（Codex smoke 已验，未重做）。

### personal_knowledge_base/test_desktop_runtime.py

- 垃圾库测试改写：垃圾字节写**真实** `data_dir/db.sqlite3`（旧稿经 base_env 传 `DJANGO_DB_PATH` 被 `build_desktop_env` 覆盖导致正常启动并卡住）；断言 `EXIT_MIGRATE`、端口拒绝、锁可复得。
- 迁移备份测试改用**真实反向迁移**（`manage.py migrate sessions zero`，真 DROP）制造"既有库+待迁移"，替代删除 `django_migrations` 行的伪回滚——后者重放迁移必撞 `table django_session already exists`（本次实测复现后修正）；新增备份=回滚前真实恢复点的行级校验（备份无 sessions 行、live 库重放后有）。
- 所有 `stdout.readline` 改为 reader 线程 + `queue.Queue` 有界等待（`_readline_bounded`、E2E `_pump_output`），不再有无界阻塞；FileLock 均保持对象引用。
- E2E `finally`：先关 stdin + 有界等待优雅退出（launcher 自行回收其 children 并释放锁），超界才 terminate→kill 兜底；reader join + 队列排空后取全部输出断言；不按端口/进程名泛杀。
- worker 早退断言改为 `worker exited (early|unexpectedly)` 正则（web 先就绪与否两条真实路径都接受）；`_http` 捕获 `HTTPError` 返回错误状态码（401/403 断言可达）。
- 新增 `test_same_origin_http_port_normalization` 钉住恢复项 4 的端口语义。

### package.json / requirements.txt / README.md / docs/desktop.md

- `package.json`：~~恢复草稿超范围删除的 `packageManager` 与 `devDependencies`~~（**Round2 勘误：此断言错误，见文末 Round2 段**——该删除是已批准 CLEANUP，Round2 已重新移除），现 diff 仅剩 `start:desktop` 一行新增。**〔历史状态标注：此句描述的是 Round1 当时的临时 diff 状态；当前 diff 含已批准 CLEANUP 的删除（根 packageManager/devDependencies 不在根 package.json），以 Round2 段为准。〕**
- `requirements.txt`：waitress>=3.0,<4 与 whitenoise>=6.12,<7 已在（草稿写入）；`filelock>=3.13,<4` 为并行任务（R2A/锁可移植）的工作区改动，未触碰。
- `README.md` 桌面启动/首次初始化说明、`docs/desktop.md` 全量说明已由草稿写入，逐条核对与最终行为一致（127.0.0.1、实例锁、密钥 0600、备份生命周期、evaluation 队列、实例头健康探测、优雅停止、"本地源码运行交付基础、非签名安装包"、临时密码自行保存、Neo4j/Langfuse 默认关）；README 中 Node 版本/`npm ci`/图片移除等非桌面段为派发前已保留的其他工作流草稿，未动。

## 测试证据（真实退出码，日志无管道）

| 命令 | exit | 结果 |
| --- | --- | --- |
| `python3 /tmp/marlin_codex_d2_probes.py` | **0** | 5/5 OK（修复前 5/5 FAIL，见 /tmp/marlin-codex-d2-probes-before.log；修复后 /tmp/marlin-d2-probes-after.log） |
| `python3 manage.py test personal_knowledge_base.test_desktop_runtime.DesktopWsgiBoundaryTests DesktopEntryUnitTests DesktopSettingsContractTests` | 0 | 21 OK |
| `... DesktopOrchestrationTests` | 0 | 6 OK（真实 migrate 子进程/备份/垃圾库/占口/诱饵健康/worker 早退/启动超时） |
| `... DesktopEndToEndTests` | 0 | 1 OK（真实迁移+Waitress+worker+HTTP：资产 MIME/深链/no-store/files 401/异站 403 零残留/合法 POST 建号 201/登录/stdin-EOF 优雅退出 exit 0/仓库树不变） |
| `python3 manage.py test personal_knowledge_base.test_desktop_runtime`（最终验收） | **0** | **29 OK in ~22s**（/tmp/marlin-d2-final.log） |

## 未运行 / 边界声明

- **Windows native 未运行**（本 worker 仅 Linux/WSL2）；Windows venv 为 Codex 所备，未被本 worker 使用；`terminate()` 在 Windows 为强杀、不经 launcher finally 的差异由测试 finally 的 stdin 优先策略缓解，最终以 Codex Windows 验收为准。
- 未打包：无 Electron/Tauri/安装器/自动更新/签名；交付为本地源码运行入口。
- 未触碰：`tasks.py`/R2A 文件（并行 worker 独占）、`config/settings.py`、D1 `runtime_paths.py`、前端源码；graphify 按约定由 Codex 统一运行。
- 已知遗留：无新发现；历史敏感材料清理事项（含既往提及的 dsh-recon 相关材料）属其他工作流范围，本轮未操作、未读取、未验证任何历史凭据。

## Round2 定向返工（task_7c898801f949，Codex changes_requested 后新 Task）

### 勘误（更正 Round1 错误断言）

Round1 报告称 package.json 的 packageManager/devDependencies 删除是"草稿超范围误删"并予以恢复——**该断言错误**。此删除是**已批准的 CLEANUP Round1 内容**（`.ai-collab/ORCA-CLEANUP-RESULT.md`「修改（6，Round1）」：移除 `devDependencies.@playwright/test` 与 `packageManager: pnpm@11.9.0`；4 个委托脚本原样保留；根无 lock，统一 npm；Playwright 已直接声明于 frontend/package.json）。Round1 的"恢复"实际回退了已批准 cleanup，Round2 已重新移除根 packageManager/devDependencies，保持四原脚本 + `start:desktop`；HEAD 工作树不是当前批准基线，未重加根 lock。

### Round2 实际改动（仅 Task 允许的文件；scripts/start_desktop.py 未发现真实生产清理缺陷、未改）

1. `package.json`：重新移除根 `packageManager` 与 `devDependencies`（见勘误），scripts 保持 dev/build/test/start:local/start:desktop 五项，`private: true` 保留。
2. `config/desktop_wsgi.py`：`_same_origin` 补 hostname 相等——同端口下两个不同 loopback 名互不同源（`http://localhost:8899` 不能伪作 Host `127.0.0.1:8899`，反向亦然），hostname 大小写正规化；隐式 80==显式 80、必须等于绑定端口、拒绝 userinfo/null/外站/错端口 全部保留。
3. `personal_knowledge_base/test_desktop_runtime.py`：
   - 5 处 `with sqlite3.connect(...)` 改 `contextlib.closing(...)`（WinError 32 根因：with 只管事务不关连接，未关句柄在 Windows 锁住 db/backup 文件致 TemporaryDirectory 清理失败）；无 ignore_cleanup_errors、无跳过 Win。
   - env 契约断言改 `str(Path(...))` 比较（Windows 实际值为 `\data dir`），保留真实值语义未删断言。
   - worker 早退端口断言改 `_port_eventually_refuses`（3 秒上限有界条件轮询，保留最终断言；依据 Codex port-probe：退出后首查 False、约 100ms 后 True，CIM 证实无进程泄漏，属端口释放可观察性延迟）；未增 JobObject/泛杀。
   - 新增 `test_loopback_aliases_are_distinct_origins`（双向别名拒绝 + 大小写正规化放行）。
4. 本报告：追加了本段与勘误。

### Round2 验证（真实退出码）

| 命令 | exit | 结果 |
| --- | --- | --- |
| `python3 /tmp/marlin_codex_d2_probes.py`（改前复现） | **1** | 5 pass 1 fail（test_loopback_alias_is_still_a_distinct_origin，与 /tmp/marlin-codex-d2-origin-review.log 一致；/tmp/marlin-d2-probes-r2-before.log） |
| `python3 /tmp/marlin_codex_d2_probes.py`（改后） | **0** | 6/6 OK（/tmp/marlin-d2-probes-r2-after.log） |
| `python3 manage.py test personal_knowledge_base.test_desktop_runtime`（Linux 最终验收） | **0** | **30 tests OK in ~21.4s**（29 + 新 origin 用例；/tmp/marlin-d2-final-r2.log） |

### Round2 未跑项

- **Windows native 未由本 worker 运行**，由 Codex 用现有临时 native venv 再验。
- 除 desktop 模块与 6 探针外，未跑其他后端/前端套件（均为已验证项，不重测）。
