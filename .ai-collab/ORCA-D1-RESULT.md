# ORCA-D1 交付报告（用户数据目录分离）

- Task: MARLIN-D1（Orca Task `task_3eec37f60d3e` / Dispatch `ctx_522070980665` / Run `run_c0d51a93432f`）
- 执行者: Orca ZCode（term_f8c9c557-bdc5-4749-bddb-0f9f0820bc28）；协调者 Codex 仅协调/验收
- workspace: /home/liuxuedeng/orca/workspaces/Django-Agent/marlin；branch: prep-desktop-commercial-release
- 开始与结束时 HEAD `afa7e0138f9fbad80e80aa4ead6f1d80af0145da`（未变；未提交/推送/合并/发布）
- 环境: Python 3.12.2（anaconda3），Django 5.2.15，filelock 3.13.1
- 以本次 Task 设计为准；未执行旧设计文档中 D1 的 SECRET_KEY 全局生成/持久化段（协调者 msg_2fdf638813d6 明确不做）

## 1. 交付总清单（新增/修改/删除全量）

| # | 文件 | 变更 | SHA256（结束态） |
|---|---|---|---|
| 1 | config/runtime_paths.py | **新增** | `a1151c1cffeec0bc455f5e9af0b9d0d890d74f4de497f921ff2920fefdd6a381` |
| 2 | config/settings.py | 修改（APP_DATA_DIR / DB / MEDIA / STATIC） | `f7dba13b049d085f799e0464ebe916ff3d0d50e2fd94a9e215d9e9b0583fe51a` |
| 3 | personal_knowledge_base/model_rate_limit.py | 修改（1 处缓存根引用） | `79587ff3f7b0ca57896de1366f5b81750367d5358006517891b4ef1e84571ea9` |
| 4 | personal_knowledge_base/eval_dataset_registry.py | 修改（cache_path 引用） | `16024d82793abd1ff85cf720d2be5b6a7325afa55c3e8ec3c292e36c3a3b4325` |
| 5 | personal_knowledge_base/eval_reports.py | 修改（1 处目录引用） | `50385be7afde12a498091f9dbde7a63892d3df5e95510f99990bc6196a446037` |
| 6 | personal_knowledge_base/tasks.py | 修改（仅两处 checkpoint 路径） | `a58039b32f25221e1565e03690b0d925a379b6a6fd50a051864903e6439c70f4` |
| 7 | scripts/local_services.py | 修改（仅 Langfuse 状态目录） | `a07158cbf552682d19cf2c01c61999258f06ec7f3c0aeb7547178adf530cb212` |
| 8 | .env.example | 修改（仅新增 APP_DATA_DIR 注释说明段） | `6a8b0dd902335610006b482c730fb26c3991daf1f17036bb55e6e602dcd89a6d` |
| 9 | personal_knowledge_base/test_runtime_paths.py | **新增**（22 项测试） | `bf30492d150fd0bd35ec3c6e0ca1c370d2a456065c8accf7eae74e9c8c25e4ec` |
| 10 | .ai-collab/ORCA-D1-RESULT.md | **新增**（本文件，临时文件+rename 原子写入） | 不自记（文件自身） |

- 删除文件：无。（工作树中其余 M/D 状态属 P02A/R1/CLEANUP 等已验收他人任务，本 Task 未触碰。）
- P01 保护四文件核验（结束态 sha256 与 P02A 报告记录逐字一致）：accounts/views.py `a6c24118…`、requirements.txt `b5432b4f…`、accounts/test_auto_setup_portability.py `cef757cd…`、accounts/test_auto_setup_processes.py `b1259968…` ✓
- `git diff --check` 退出码 0（无空白错误）。

## 2. 实现要点

**config/runtime_paths.py（新增，纯 stdlib 模块）**
- `resolve_data_directory(base, value)`：value 为 None/空/纯空白 → 回落 `base`（既有行为）；显式值 `expanduser().resolve()` 解析为绝对路径（含空格路径可用）；不改 chdir。settings 与非 Django 的 local_services 共用。
- `app_data_root()`：函数体内懒加载 `django.conf`，**调用期**读取 `settings.BASE_DIR` + `settings.APP_DATA_DIR`（None=未指定→回落当时 BASE_DIR），保证 `override_settings(BASE_DIR=…)` 隔离测试继续生效，旧根不在导入期冻结。
- `runtime_cache_dir(*parts)`：`app_data_root()/.cache/<parts>`，五类缓存统一收敛点。

**config/settings.py**
- `APP_DATA_DIR`：env 未设置/空白 → `None`；显式 → 经 `resolve_data_directory` 解析绝对路径。SECRET_KEY failclosed、DEBUG 默认、ALLOW_AUTO_SETUP 默认 false 全部未动（子进程探针有断言）。
- `_DATA_ROOT = APP_DATA_DIR or BASE_DIR`（settings 装载期快照）：`DATABASES.default.NAME` = `DJANGO_DB_PATH` 优先 → 其次 `_DATA_ROOT/db.sqlite3`；`STATIC_ROOT=_DATA_ROOT/staticfiles`；`MEDIA_ROOT=_DATA_ROOT/media`。
- 源码资源不变：TEMPLATES DIRS、STATICFILES_DIRS（前端 dist/assets）、.env 加载仍在源码 BASE_DIR。导入期无 mkdir、无密钥生成。

**五类 .cache 引用迁移（全部运行写入 → 用户数据根，运行期解析）**
1. model_rate_limit.py `_bucket_lock` → `runtime_cache_dir("model-rate-limits")`（filelock 语义/0600 不变；顺删未用的 `Path` 导入）。
2. eval_dataset_registry.py `cache_path` → `runtime_cache_dir("eval-datasets", id, version)`；manifest 仍在源码 `personal_knowledge_base/eval_datasets/`。
3. eval_reports.py `_open_report_directory` → `runtime_cache_dir("eval-reports", tenant.id)`。
4. tasks.py 仅两处：`_open_rag_checkpoint_path`（创建/读写根）与 `_cleanup_open_rag_checkpoints`（清理根）→ `runtime_cache_dir("open-rag-runs", …)`。
5. scripts/local_services.py 仅 Langfuse 状态目录：`resolve_data_directory(root, env.get("APP_DATA_DIR"))/.cache/langfuse`（APP_DATA_DIR 来自已解析 local_env，未设置/空白回落 root 既有行为）；`.env.langfuse`/`docker-compose.langfuse.yml` 仍读源码根；startup lock/健康检查语义零改动。该模块仍不进 Django 导入链（`config/__init__.py` 为空 + runtime_paths 纯 stdlib，有探针断言）。

**明确不做**：不自动迁移/复制/删除旧用户数据；不在 import 时 mkdir/生成 secret；不改 DEBUG/SECRET_KEY failclosed/ALLOW_AUTO_SETUP 默认；不做全局 SECRET_KEY 生成（设计报告该段未执行，桌面 launcher 下阶段独立管理）；graphify 本波由 Codex 统一更新。

**范围外备注**：scripts/verify_langfuse_settings.py:112 会写 `.cache/settings-ui-cleanup`（Playwright 截图，人工验证脚本，不在允许文件清单）——未改，仅备忘。

## 3. 测试命令与退出码（按时间序，真实记录）

runner：/tmp/marlin-d1/run_isolated_tests.py——os.environ 按白名单重建（不继承业务凭据，APP_DATA_DIR 亦不在白名单）；DJANGO_DB_PATH → OS 临时 sqlite；`sys.argv=["manage.py","test",labels]` 于 django.setup 前设置（不调度 startup recovery）；`settings._setup()` 后于 django.setup 前覆盖 BASE_DIR/MEDIA_ROOT → /tmp/marlin-d1/base。

1. 新模块单跑（迭代验证）：`python3 run_isolated_tests.py personal_knowledge_base.test_runtime_paths` → **22 tests, OK, exit 0**。
2. 合并定向回归第一次（9 labels：test_runtime_paths、test_runtime_lock_portability、test_task_recovery、test_open_rag_runs、test_eval_reports、test_eval_dataset_sources、test_open_rag_benchmark、test_llm_providers、test_settings_thinking）→ 230 tests，**5 errors**：均为 `test_settings_thinking.LangfuseAccessTests` 的 `DisallowedHost('127.0.0.1:8000')`——runner 白名单 env 未列 127.0.0.1（P02A runner 当时只跑该模块的 LocalStartupTests 故未暴露）。按协调者 msg_684c46852acf：仅调整临时 runner 白名单 `DJANGO_ALLOWED_HOSTS=testserver,localhost,127.0.0.1`，**业务 Host 限制零改动**。
3. 合并定向回归最终重跑（同 9 labels 一次运行）→ **230 tests, OK (skipped=1), exit 0**（skipped 为 test_settings_thinking.py:280 “opt-in real local Langfuse session contract” 自跳过，与本波无关）；日志 /tmp/marlin-d1/d1-final-merged.log。

隔离有效性：新模块单跑日志无 “startup recovery” 行；最终合并日志仅 1 条 “startup recovery” INFO，来自 test_task_recovery 自身在隔离 scratch DB 上主动驱动恢复流（`recovered: 0`），非调度泄漏；运行后仓库根无 `.cache/`，副作用落 /tmp/marlin-d1/base/.cache（eval-datasets/eval-reports/model-rate-limits 结构与 P02A 隔离证明一致）。

新模块覆盖面（22 项，全部真实路径 helper + 真实临时写入）：resolve_data_directory 单元（None/空/空白回落、expanduser、绝对化、空格路径）；runtime_paths 与 local_services 导入不带入 django；helpers 调用期跟随 override_settings(BASE_DIR/APP_DATA_DIR)；user root 真实写入（model-rate-limits 真 filelock 争用+0600、open-rag-runs checkpoint 写/读/过期清理且源码根同路径文件不被清理、eval-reports 目录写入、eval-datasets cache_path 随根而 manifests 留源码）；TEMPLATES/前端 dist 源码锚定；ensure_langfuse 经 env APP_DATA_DIR 重定向 startup.json 且未设置/空串回落源码根；子进程 settings 探针（DJANGO_DB_PATH 显式优先；APP_DATA_DIR 含空格路径路由 DB/MEDIA/STATIC 且解析绝对；未设置保持历史缺省；纯空白=未指定；DEBUG=false+无 secret 仍拒绝（含契约报错文案）；ALLOW_AUTO_SETUP 缺省 false）。子进程探针白名单重建 env、不调用 django.setup（无恢复定时器、不触真实 DB/API）。

未运行：全仓测试、迁移、前端 Playwright、真实 Docker/HTTP。**Windows native execution: not_run** —— 本机未备 Windows 项目依赖环境（延续 P02A 结论）；Codex 将用已备 Windows venv 独立验收，重点可核：`resolve_data_directory` 的盘符大小写/绝对化行为、含空格与 `~`（Windows USERPROFILE）展开、filelock 用户根路径锁、`.env` 中 APP_DATA_DIR 读取。
