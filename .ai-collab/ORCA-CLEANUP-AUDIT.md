# ORCA-CLEANUP-AUDIT — 只读清理/许可/构建证据报告

- task_id: `task_5d4b003df557` / dispatch_id: `ctx_b96df5398740`
- 执行: 审计 worker（term_db08c892-566d-4233-8314-3ad01577385f），2026-09-30
- 仓库基线: HEAD `afa7e0138f9fbad80e80aa4ead6f1d80af0145da`，分支 `prep-desktop-commercial-release`，跟踪文件 352 个
- 工作区脏文件（其他执行者的活跃改动，本报告不将其列为清理候选、也不属于本 worker 改动）：
  - `accounts/views.py`、`personal_knowledge_base/model_rate_limit.py`、`personal_knowledge_base/open_rag_benchmark.py`、`requirements.txt`（+`filelock>=3.13,<4`）、`scripts/local_services.py`（已修改）
  - 未跟踪：`.ai-collab/`、`accounts/test_auto_setup_portability.py`、`accounts/test_auto_setup_processes.py`、`personal_knowledge_base/test_runtime_lock_portability.py`
- 约束遵守：未运行任何测试（本文所有测试均标 `not_run`）；未安装依赖/导入 Django/启动服务；未读取 `.env`/凭据文件（仅读取 `.env.example`、`.env.langfuse.example` 模板）；未执行 `frontend/dsh-recon.mjs`。
- 方法：先 `graphify query`（graphify-out/graph.json 存在、wiki/index.md 不存在；返回 262 节点子图，显示被截断，退出码未单独捕获）；随后以多途径交叉验证引用（文件名 grep + 内容 grep + git log --follow + 测试编排清单核对），未以单次 rg 无结果下结论。

> **勘误（2026-09-30，MARLIN-CLEANUP-01，task_b0a290393112/ctx_6a6066f47fa3）**：原第一组候选 1 中"商用交付需二选一：轮换该令牌，或重写历史"表述不准确，已更正为"历史仍保留该值，本轮不检查有效性/不处理凭据或历史，需后续核验"；流程披露中"建议轮换"同步更正为后续核验口径。本地终端一次性打印的过程说明如实保留，未夸大为对外泄露。同日 MARLIN-CLEANUP-01 已将该文件以工作树删除方式移除（未 stage、未重写历史）。

---

## 第一组：无引用/无构建用途文件候选（逐项证据）

判定标准：① 全仓内容引用为零（排除自身自引用）；② 不在任何测试编排/构建入口中；③ git 历史显示为一次性产物。三项均满足才列为候选。

### 候选 1（最高优先级，敏感）：`frontend/dsh-recon.mjs`
- 证据：
  - 全仓 grep `dsh-recon` 零命中（排除 .git/node_modules/graphify-out/.ai-collab，grep 退出码 1）。
  - git 历史仅一条：`347e7c6`（2026-09-05 "Add session trajectory and knowledge base improvements"，31 文件 +2885 行的混合提交）一次性带入。
  - 内容为针对 `http://127.0.0.1:3099` 的单次 UI 侦察脚本（playwright 截图到 /tmp/dsh-analysis）。
  - **敏感值**：第 4 行硬编码本地访问令牌（类型：URL query `?token=` 参数），HEAD blob 与工作树均在第 4 行（仅核实行号，本文不打印值）。已随 347e7c6 入库。
- 误删风险：无构建/测试用途；删除不破坏任何入口。
- 可逆删除条件：`git rm` 即可恢复（文件在历史中）。历史仍保留该值，本轮不检查有效性/不处理凭据或历史，需后续核验。
- ⚠️ 流程披露：本审计在读取该文件时，屏蔽第 3 行（实为空行）后第 4 行令牌值被一次性打印到本 worker 终端输出（本地终端输出，非对外渠道）。该令牌的后续处置需后续核验，本轮不检查其有效性、不处理凭据或历史。

### 候选 2：`tests/debug_current_graph_rag_reason.py`、`tests/debug_hello_latency.py`、`tests/debug_memory_timeout_reason.py`
- 证据：
  - 精确 grep 三个文件名：仅各自文件内部自引用（如 docstring 中的运行命令），无任何外部 import/引用（退出码核验过）。
  - 不在 `tests/run_full_project_tests.py` 的 COMMANDS 清单中（该清单 7 项已逐条核对）；仓库无任何 CI 配置（`git ls-files` 中无 .github/workflows/Jenkinsfile/Makefile/tox.ini 等，grep 退出码 1）。
  - 三文件同在 `b95f8be`（2026-08-19 "chore: reorganize local references and clean project artifacts"）加入，属一次性诊断产物。
  - 内含硬编码绝对路径 `/home/liuxuedeng/anaconda3/envs/django-agent/bin/python`，不具可移植性。
- 误删风险：中低——丢失的是"延迟/内存超时排查方法论"记录，而非构建/测试能力。
- 可逆删除条件：均被 git 跟踪，`git rm` 后随时可从历史恢复；建议若采纳，把其中可复用的诊断思路摘要进 docs 或删除信息本身确认无用后再删。

### 候选 3：`tests/rebuild_current_graph_rag.py`
- 证据：精确 grep 仅自引用（其自身输出 JSON 中的 `"rebuilt_by"` 字段）；不在 run_full_project_tests.py；同批 b95f8be 加入。注意：候选 2 中三个 debug 脚本也**不引用**它（精确逐名 grep 确认），删除不产生悬空引用。
- 误删风险：低——一次性图谱重建工具，产物路径写死。
- 可逆删除条件：git 跟踪，可随时恢复。

### 候选 4：根 `package.json` 的 `devDependencies.@playwright/test` + 根 `pnpm-lock.yaml`
- 证据：
  - 根 package.json 三个脚本（dev/build 委托 `cd frontend && npm run …`、test=manage.py、start:local=scripts/start_local.py）均不需要根级 node_modules。
  - `pnpm-lock.yaml`（lockfileVersion 9.0）importers 仅有 `.` 一项：`@playwright/test 1.61.1`（外加 playwright-core、fsevents[darwin-only]），与根 devDep 一致但与实际构建路径无关——前端 e2e 的 node 侧 specs 由 `frontend/package.json` 自带的 `@playwright/test` 提供（frontend/playwright.config.ts 在 frontend/ 内运行）；Python 侧 e2e 用的是 Python `playwright` 包（见第三组缺口）。
  - 全仓 grep（*.json/*.md/*.ts/*.mjs，排除 frontend/）对 playwright 的引用仅 package.json:11 一处；scripts/*.py 无 npx/pnpm playwright 调用。
- 误删风险：低。风险点是若开发者习惯从仓库根跑 `npx playwright` 会失去依赖来源；`packageManager: pnpm@11.9.0` 字段与 pnpm-lock 同生，若只删 lock 不删字段会留下工具链声明不一致（或反之）。
- 可逆删除条件：确认团队无人从根目录调用 playwright/pnpm 后，一并移除 devDep+pnpm-lock（可选：同时移除 packageManager 字段或改声明 npm）；git 可恢复。

### 候选 5：`scripts/verify_langfuse_settings.py`
- 证据：全仓 grep `verify_langfuse`（含 *.md、*.yml、*.py）零命中（退出码 1）；未被 run_full_project_tests.py 引用。疑似被 `manage.py langfuse_check`（`personal_knowledge_base/management/commands/langfuse_check.py`，已跟踪）取代。
- 误删风险：低-中——无法确认仓库外（个人 shell 历史/笔记）是否仍引用它。
- 可逆删除条件：与用户确认其被 langfuse_check 完全取代后删除；git 可恢复。

### 候选 6（文档类，中低优先级）：docs/ 历史计划/报告 6 件 + 180 文档 2 件
- 历史计划/报告（仅在 docs/ 内部互相引用，无代码引用）：
  - `docs/langfuse-goal-implementation-plan.md`、`docs/langfuse-implementation-report.md`、`docs/langfuse-settings-thinking-implementation.md`、`docs/langfuse-settings-thinking-level-plan.md`、`docs/evaluation-workbench-business-logic-fix-plan.md`、`docs/session-tree-refactor-plan.md`
  - 证据：对 `tool-error-handling|evaluation-workbench-business-logic|session-tree-refactor` 的引用仅存在于 docs/ 内部（排除 docs/ 后 grep 退出码 1）；对应功能均已落地（提交 afa7e01、819221b 等）。
  - **特殊风险**：`docs/langfuse-implementation-report.md:213-215` 是全仓唯一记录前端 19 个 `*.test.mjs` 运行命令（`node --test …`）的文档（另一处在 .ai-collab/REVIEW.md:34，非交付物）。删除前应先把该命令固化为 `frontend/package.json` 的 test script 或写入 README。
  - `docs/tool-error-handling.md` 同样零外部引用，但属行为说明文档，建议保留或归档而非删除。
- `docs/open-rag-benchmark-180-documents.md` + `.csv`（143 行清单）：
  - 证据：代码仅引用数据集 id `open_rag_benchmark_180`（eval_views.py:48,347、eval_dataset_registry.py:15,18），不引用这两份文档；文档互相引用（md→csv）。
  - 风险：它是 180 子集的推导依据与 qrels 泄漏警示（md 首部明确警告该子集不能作严格基准），且涉及第二组的 NC 许可溯源。**建议在许可决策完成前保留**。

### 明确排除的"疑似候选"（已验证有用，防止误删）
| 文件 | 引用证据 |
|---|---|
| `frontend/src/assets/knowledge-workspace.svg` | `frontend/src/styles/app.css:132`（url() 引用） |
| `personal_knowledge_base/testdata/legacy/{sample.doc,sample.ppt,sample.xls}` + README | `personal_knowledge_base/test_document_parsing.py`（测试夹具，README:42 LibreOffice 依赖） |
| `tests/eval/{eval_config.yaml,datasets/django_agent_multiactor_eval.json}` | `tests/test_local_agent_eval.py:33-34`（且该测试在 run_full_project_tests.py 编排内） |
| `docs/trajectory-event-sourcing.md` | `personal_knowledge_base/event_log.py:3`、`models.py:373`、`tests/test_session_trajectory.py:3` |
| `docs/langfuse-operations.md` | `docs/langfuse-settings-thinking-level-plan.md:417`、goal plan:614 引用；运维文档 |
| `.env.example` / `.env.langfuse.example` | README:62、docker-compose.langfuse.yml:6、docs/langfuse-operations.md:16 |
| `docker-compose.langfuse.yml` | `requirements.txt:49` 注释固定配套；operations 文档引用 |
| `scripts/` 其余 5 个 .py | start_local（package.json:6）、local_services（manage.py）、bench_langfuse_overhead（docs+test_submission_regressions.py）、benchmark_open_rag_runtime（scripts/test_benchmark_open_rag_runtime.py 导入）、test_benchmark 本体（unittest 可独立运行） |

> 局限声明：以上"零引用"基于仓库内文本 grep + 编排清单核对 + git 历史；无法排除仓库外引用（个人脚本、CI 外部系统、IDE 配置）。所有候选均为 git 跟踪文件，删除后可经 git 恢复（dsh-recon 的令牌问题例外，见上）。

---

## 第二组：许可/依赖来源盘点与桌面商用交付缺口（仅事实，非法律结论）

### 许可声明
- 源码许可：根 `LICENSE` = MIT（Copyright (c) 2026 LiuXD1011，21 行）；README:219 声明 MIT。README:223-224 致谢 Tencent/WeKnora、XiaomiMiMo/MiMo-Code；`frontend/src/styles/weknora-redesign.test.mjs` 文件名显示 UI 参考 WeKnora 重设计，但仓库未记录 WeKnora/MiMo-Code 的许可条款与借鉴范围（仅致谢链接）。
- 评测数据：
  - `personal_knowledge_base/eval_datasets/open_rag_benchmark.manifest.json`：`license: CC-BY-NC-4.0`，来源 `https://huggingface.co/datasets/vectara/open_ragbench`，固定 revision `63f6b052ff83508b08e242db42263ee708815c26`，pdf_urls.json 带 sha256。**非商业许可**，语料在运行时下载至 `.cache/`（.gitignore:92 忽略，不入库）。
  - 派生子集 `open_rag_benchmark_180.manifest.json`：**无 license 字段**（grep 全部 eval_datasets/*.json 仅主 manifest 含 "license"）。docs/open-rag-benchmark-180-documents.md 声明其来自同一上游 qrels 推导（180 题/142 篇）。
  - 内部数据集 chunking_v1 / retrieval_v1 / retrieval_v2：占位符数据（README:190 明确"deliberately unverified"），无 license 字段（自产，风险低但未声明）。
- 依赖清单（声明来源，未做合规核验、未联网）：
  - Python：`requirements.txt` 全部精确/范围固定（Django 5.2.15、DRF 3.14.0、litellm、ragas==0.4.3、langfuse==3.15.0 等）；无锁文件（无 pip-tools/conda-lock/poetry.lock）。
  - Node：`frontend/package.json`（10 运行时依赖 + @playwright/test）由 `frontend/package-lock.json` 固定；根 package.json 仅 @playwright/test 由 pnpm-lock 固定。各 npm 包的 LICENSE 文件不在仓库内。
  - 可选服务（docker-compose.langfuse.yml，全部镜像已固定版本）：langfuse/langfuse:3.225.8、langfuse-worker:3.225.8、clickhouse 25.3.2.39-alpine、minio RELEASE.2024-12-18T13-15-44Z、redis 7.4.2-alpine、postgres 16.6-alpine。requirements.txt:49 声明 langfuse 客户端与服务端 3.225.8 配套。另有可选 Neo4j 5-community（README:74）。

### 桌面商用交付缺口（事实清单）
1. **NC 许可数据集内嵌产品评测工作台**：CC-BY-NC-4.0 的 Open RAG Bench 通过 `eval_views.py`/`eval_dataset_registry.py` 成为一等数据集选项（含 180 派生子集），MIT 源码 + NC 数据在"商用"场景存在许可方向冲突（此处仅记录事实，不给结论）。
2. **入库的本地令牌**：`frontend/dsh-recon.mjs:4`（见第一组候选 1；历史提交 347e7c6 已含）。
3. **静态资源 DEBUG 门控**：`config/urls.py:30-33` 仅 `settings.DEBUG` 时挂载 `/assets/`（指向 frontend/dist/assets）与媒体路由；`frontend/dist/` 被 .gitignore:40 忽略、未构建。README 快速开始只有 runserver+dev 模式。
4. **数据路径在仓库根**：`config/settings.py:102`（db.sqlite3，DJANGO_DB_PATH 可覆盖）、`settings.py:120`（MEDIA_ROOT=BASE_DIR/media）。无用户目录重定向。
5. **无 Windows 打包工程**：`git ls-files` 无 .bat/.ps1/pyinstaller/nsis/electron 配置；README:39-42 前置条件含 LibreOffice（soffice）用于旧版 .doc/.ppt（testdata/legacy 夹具依赖它）。
6. **gunicorn**（requirements.txt:30 "生产部署"）：上游不支持 Windows 原生（公知上游事实，本次未联网复核）。
7. **原生/平台敏感依赖未验证**：`CairoSVG`（requirements.txt:21，需原生 Cairo）、`sqlite-vec==0.1.9`（原生扩展）的 Windows 可安装性未验证（not_run，未联网）。
8. **测试依赖未声明**：`tests/test_frontend_playwright_e2e.py:153` 导入 Python `playwright.sync_api`，requirements.txt 无此项（详见第三组）。
9. **README 断链**：README:16 引用 `docs/images/wiki-graph-preview.png`，`docs/images/` 目录不存在（ls 退出码 2，跟踪清单亦无）。仓库含 `tests/test_readme_links.py` 但本次未运行，无法确认该测试是否覆盖图片引用。
10. **前端 UI 溯源仅致谢**：WeKnora/MiMo-Code 借鉴范围与许可条款未在仓库记录（weknora-redesign 样式测试文件名为唯一线索）。

---

## 第三组：构建/测试最小复现命令与锁漂移（全部 not_run）

### 声明的入口（来源：README + 两个 package.json + run_full_project_tests.py）
| 层 | 命令 | 声明处 |
|---|---|---|
| 后端安装 | `pip install -r requirements.txt` | README:52（注意：工作树版含未提交的 filelock 行，HEAD 无） |
| 后端迁移/启动 | `python manage.py migrate`；`python manage.py runserver` | README:78,81 |
| 任务 worker | `python manage.py run_task_worker --queue documents` / `--queue evaluation` | README:201-202 |
| 前端安装/构建 | `cd frontend && npm install`；`npm run build`（vite build） | README:55；frontend/package.json:8 |
| 前端开发/预览 | `npm run dev` / `npm run preview`（--host 0.0.0.0） | frontend/package.json:7,9 |
| 根委托 | `npm run dev`/`npm run build`（=cd frontend && npm run …）；`npm test`（=python manage.py test）；`npm run start:local`（=python scripts/start_local.py） | 根 package.json:3-6 |
| 后端测试（全量编排） | `python tests/run_full_project_tests.py`（7 项：backend_agent、chat_feature_objective、frontend_contracts、local_agent_eval、`npm --prefix frontend run build`、playwright e2e、compileall） | tests/run_full_project_tests.py:12-56 |
| 前端单测（*.test.mjs，共 19 个） | `node --test <文件…>` — **无 npm script 封装**，唯一文档化命令在 docs/langfuse-implementation-report.md:213-215 | 同左 |
| 前端 node e2e（*.spec.ts，共 7 个） | playwright（frontend/playwright.config.ts：testDir ./tests、webServer=`npm run dev --port 4173`、chromium desktop/mobile-390 两 project）；**frontend/package.json 无 test script，运行命令未声明** | frontend/playwright.config.ts |
| Python e2e | `python tests/test_frontend_playwright_e2e.py` | 文件自身 docstring:570 |

以上命令本轮全部未执行（not_run，任务禁止跑全仓测试）。

### 锁文件状态
- `frontend/package-lock.json`：lockfileVersion 3，148 个包；其根块 dependencies 与 `frontend/package.json` 的 10 项 specifier 逐字一致、version 同为 0.6.2-django（程序化比对）。表面同步；深层解析一致性未验证（not_run）。
- `pnpm-lock.yaml`：lockfileVersion 9.0，仅覆盖根 `@playwright/test@1.61.1`（+playwright-core、fsevents），与根 package.json 一致，但与实际前端构建路径无关（见第一组候选 4）。
- 工具链不一致（非经典漂移）：根声明 `packageManager: pnpm@11.9.0`（package.json:9），而 README:55 与全部构建脚本走 npm + frontend/package-lock.json；两套包管理器/锁并存。
- Python：requirements.txt 为唯一清单、无锁；工作树新增 `filelock>=3.13,<4`（accounts 初始化跨进程锁，Windows 友好方向）尚未提交。
- requirements.txt 与已装环境是否一致：未验证（not_run，禁止改环境）。

### 复现缺口（对照上表）
1. Python `playwright` 包被 e2e 依赖但未在 requirements.txt 声明（tests/test_frontend_playwright_e2e.py:153）——新环境按 README 装完依赖无法直接跑该项。
2. 19 个 `*.test.mjs` 与 7 个 `*.spec.ts` 均无 package.json script 入口，运行方式只散落在历史报告文档。
3. 无 CI 配置文件，全部入口依赖本地记忆/文档。
4. README 快速开始不含构建产物运行路径（runserver 在 DEBUG=false 下无 /assets/，见第二组缺口 3）。

---

## 本轮命令与退出码台账（摘要）
1. `git rev-parse HEAD && git branch --show-current && git status --porcelain | head -50 && git ls-files | wc -l` — 退出码 0（HEAD afa7e013、352 文件）。
2. `ls graphify-out/graph.json graphify-out/wiki/index.md` — 退出码 2（graph.json 存在、wiki 不存在）。
3. `graphify query "frontend build pipeline…"` — 正常返回 262 节点子图（显示截断），退出码未捕获。
4. dsh-recon 引用 grep（全仓，排除 .git/node_modules/graphify-out/.ai-collab）— 退出码 1（零命中）；`git log --follow` — 1 条（347e7c6）。
5. debug/rebuild/svg/180-docs/testdata/tests-eval 引用 grep（分批）— 退出码 0，命中明细已录入上文；`tests/eval` 初查过宽，已用精确路径复核（test_local_agent_eval.py:33-34）。
6. pnpm-lock/package-lock 结构提取（python3 json 解析 + head/grep）— 退出码 0。
7. eval manifests 许可字段提取 — 退出码 0（仅主 manifest 含 license）。
8. `ls docs/images` — 退出码 2（不存在）；`git ls-files | grep -iE "\.github|makefile|tox\.ini…"` — 退出码 1（无 CI）。
9. `git show 347e7c6 --no-patch/--stat`、`git log --follow`（候选文件历史）— 退出码 0。
10. `git diff requirements.txt` — 退出码 0（确认 +filelock 为工作树新增）。
11. `git show HEAD:frontend/dsh-recon.mjs | grep -n "token=" | cut -d: -f1` — 退出码 0，仅输出行号 4（无值）。
12. ⚠️ 例外：读取 dsh-recon.mjs 内容时第 4 行令牌值被一次性打印（awk 屏蔽行号错位所致，详见第一组候选 1 流程披露）。
13. 测试执行：无（not_run）。未安装任何包、未导入 Django、未启动服务。

## 收尾核对（报告写入后回填）
- [x] 本文件为 `.ai-collab/` 内新增第 7 个文件，未覆盖既有 6 文件（DECISIONS.md、ORCA-P02A-RESULT.md、RESULT.md、REVIEW.md、STATUS.json、TASK.md）
- [x] 写入方式：同目录临时文件 `.ORCA-CLEANUP-AUDIT.md.tmp` → `mv` 原子替换
- [x] 除本报告外无任何文件被本 worker 修改/删除
- [x] 勘误：2026-09-30 MARLIN-CLEANUP-01 按协调者指示修正候选 1 处置表述（见文首勘误块），原子替换写入
