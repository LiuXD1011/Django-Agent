# 旧 Django 实现退役执行计划

> 执行者按本计划逐项核对。Root 单一协调源码解冻、共享接口、数据库迁移和最终集成；本轮子代理只准备清单与独立证据，不实施生产删除。

**目标：** 删除被替代的旧运行入口、依赖声明和源码，保留业务、真实数据、兼容导入、回归依据及许可证。

**架构：** Electron / TypeScript Core / Vue 是当前运行路径，Python 仅解析和评测。旧源码以逐字节 `.txt` 快照作为不可运行历史资料；当前 importer、密码、AES-GCM、租户/渠道等继续在原位置运行。

**技术：** 现有 Node/TypeScript、SQLite、Electron、Python workers；不改变依赖版本或锁文件。日期 2026-10-13。

## 当前状态：第一批暂缓，发现真实自动启动缺口

Root 的原正式Windows `package-only` 已actual0且原HANDLE/Job终态active0；本轮再次实际计算 `build_windows.source_inputs(ROOT)` 为468项并逐项匹配 `dd5b9d2f…` 冻结，10项均不在构建集合。删除前15项只读门禁actual0，301源码/归档及174source-map/保留SHA一致。

但完整重读发现旧 `manage.py runserver` → `scripts/local_services.ensure_langfuse` 实际承担显式opt-in Langfuse Docker autostart，当前UI仍有开关及“下次开发启动生效”的说明，而TS dev入口无启动调用。原准备中的“未发现业务遗漏”范围判断需更正。Root赞同该缺口，已明确**暂缓整个10项group**，不是仅保留3个路径。所有301项仍存在，`entrypoints_retired=false`、`full_retirement_executed=false`；本轮未执行unlink、服务、Docker、模型或业务suite。

[独立AUTOSTART-GAP设计](../refactor-evidence/20261013-legacy-retirement-prepare/AUTOSTART-GAP.md)记录旧键/环境优先级、锁/单调截止时刻、失败降级、desktop排除、Neo4j没有同类自动启动，以及最小TS owner落点/真实验收方案。Root协调共享owner入口的下一源码迭代与验证，不重复向用户请求普通迁移批准。原Windows构建manifest及非运行归档不改；原两份准备文档字节已保存，下面的准备阶段数字/结果保留其历史口径，不能当作当前退役完成证明。

## 授权、来源与本轮事实

Goal §2.1 已批准清理替代的 Django 代码、依赖、脚本和过时文档；§2.2 禁止以删除源码掩盖业务遗漏。当前 Windows 正式 prepare 冻结源码，本计划及证据不解除该冻结。所有 `implemented` / `retirement_executed` 均为 **false**。没有生产、测试、依赖或真实数据修改，没有服务、GUI、模型调用、stage、commit、reset 或发布。

[清单](../refactor-evidence/20261013-legacy-retirement-prepare/candidates.json)给出每个路径的 SHA-256、字节数、Git 状态、归属边界、动作、精确归档、新能力落点及引用索引；[可读表](../refactor-evidence/20261013-legacy-retirement-prepare/RETIREMENT-FILES.md)和[完整拟删除差异](../refactor-evidence/20261013-legacy-retirement-prepare/prospective-deletion.diff.txt)供审阅，尚未应用。归属表示“原有 tracked 文件，准备者只读”，不推断作者。

- 原评审 265 个候选当前全部存在，逐文件 SHA 与原评审相同，候选 Git 状态为空。本轮补齐 36 个根测试/旧诊断/runner，共 **301** 个精确路径；不能删除整个 `tests/`。
- 已在本轮独立证据目录保存 **301** 份精确字节历史副本，不是生产改动，也不是用户数据备份。每个副本末尾追加 `.txt`，不被 Python、Django 或默认测试 discovery 当作模块。没有运行其中代码。
- 原 AST 312 文件/1048 条旧绝对导入照旧保留。本轮扫描 tracked Python 314 文件、1054 条含旧服务第三方包的导入，解析错误 0；按原包口径比较，原 1048 条没有缺失，新扫描另包括 `manage.py` 的 3 条导入；另外 3 条属于本轮增加的第三方包识别范围。这是扫描口径差异，不能声称旧源码改动。独立 workers 的旧业务导入仍为 0。[完整 AST](../refactor-evidence/20261013-legacy-retirement-prepare/python-import-inventory.json)。
- 当前 tracked UTF-8 源码及文档（候选、冻结证据目录之外）共 187 条疑似旧引用，逐行保存在[references.json](../refactor-evidence/20261013-legacy-retirement-prepare/references.json)。引用是审查候选，不能将字符串命中当作运行依赖。
- 只读 HEAD 为 `dd5a356a3afdd67492d82a3b3e0e89dafffe2174`；逻辑 index 按 `git ls-files --stage` 原始输出计算，绑定见[audit.json](../refactor-evidence/20261013-legacy-retirement-prepare/audit.json)。不改写外部已有提交，不依赖 `.git/index` 的 stat-cache 字节稳定。

## 保留能力的当前落点

以下是代码落点，不是整组 GUI/安装验收通过声明。每个候选的细分归属见清单；跨域 `views.py`/`urls.py` 须同时核相邻路由域，不能只按表中的主域认定全部功能迁移。

| 旧能力/目录 | 当前能力及必要检查 |
| --- | --- |
| accounts、权限、个人空间 | `packages/core/src/auth/`、`storage/schema.ts`、`legacy/tenants.ts`；注册/初始化/refresh/设备/改密码、空间及成员过滤。原 OIDC 三方法实际返回 disabled/空地址/not configured，不伪称可用 OIDC 被迁移。 |
| 旧 migrations、models、凭据 | `storage/legacy.ts/schema.ts/migrations.ts/files.ts/credentials.ts`；旧 `django_migrations` 只读版本识别、bigint、媒体、备份、重复导入、失败回滚。不得重放旧有破坏性 migrations。 |
| 文档/图片/表格/Office | `workers/document/parser/` + Core `documents/workflow.ts/pipeline.ts`；TS 编排模型、索引、摘要、图谱、Wiki。`chat/image_context.py` 对应 `chat/attachments.ts` 的真实 VLM 图片上下文；旧名 ImageGenerationTests 实际不是生成图片功能。 |
| 分块/父子/语义缓存 | `documents/chunker.ts/chunking-workers.ts`、`knowledge/chunks.ts`、`retrieval/parent-context.ts`；不能删除编辑、启停、来源坐标、图片屏障和检索后刷新。 |
| 检索、RRF/Rerank、问答/引用 | `retrieval/service.ts/search-index.ts`、`chat/index.ts/retrieval.ts`、`adapters/chat-routes.ts`；验证过滤、修改/删除后检索、早停及历史恢复。 |
| Agent、工具、子任务、上下文 | `agents/index.ts/tools.ts/application-hooks.ts`、`chat/`；实际 Graph/WebFetch/read_skill hooks 已接线，业务技能目录与 Codex 技能分离，不制造不存在的业务技能。 |
| Wiki/图谱/旧图 | `wiki/index.ts`、`graph/index.ts/legacy-templates.ts`、`integrations/neo4j-http.ts`；旧图源与索引不可清除，外部 Neo4j 未配置不算可用图谱通过。 |
| 记忆/历史投影 | `memory/index.ts`、`chat/`；保留用户/空间与开关语义、引用隔离。根旧真实库诊断脚本退为历史资料，不在默认检查读取原库。 |
| 任务、事件、恢复/停止 | `jobs/queue.ts/journal.ts/streams.ts`、`runtime/owner-worker.ts`；窗口退出归 `desktop/owned-runtime.cjs`/bootstrap/native Job，不能以删旧 task 代码证明新包退出已验收。 |
| 四模型、设置、用量、观测 | `models/runtime.ts/thinking.ts`、`settings/`、`observability/`、`integrations/trace.ts`、`desktop/langfuse.cjs`；凭据空白保留、显式清除、厂商错误与思考参数继续。 |
| MCP/联网搜索 | `integrations/index.ts/search.ts`、`agents/application-hooks.ts`；保留官方 TS MCP SDK 及真实协议调用，不要求 Docker 才有基础桌面业务。 |
| 评测、人工审核、策略、公共资料 | `evaluation/` + `workers/evaluation/worker.py`；至少5题、版本/来源新鲜度、取消/恢复、真实报告；保留完整公共 registry 和旧报告兼容。 |
| 旧租户/资源/公开 embed/IM渠道 | `legacy/channels.ts/tenants.ts`、`adapters/legacy-routes.ts`；这是当前业务，不能退役 `packages/core/src/legacy/`。旧邀请/分享/IM QR callback/admin-promote 的 generic 占位响应不能算真实已实现或静默删掉产品能力；保存旧路由与设计依据，必要的新增产品语义由 Root 单独确认。 |
| 浏览器/PWA/Electron | 当前 frontend、HTTP/SSE、preload/IPC/正式资源继续保留。没有发现 frontend 静态单测读取旧 Python 源；例如 model-presets 的后端来源现在是 `packages/core/src/settings/startup.ts`。 |

原准备阶段没有经真实业务运行确认的新业务遗漏；后续删除前源码核对已经确认当前UI的Langfuse autostart缺少TS落点，按上述当前状态暂缓。UI-BASELINE 的 105 API/69 UI、主矩阵38组及 Windows 验收仍由 Root 判定；未完成的图谱、评测、模型、安装行为不能靠清理旧目录消失。

## 默认检查与 E2E 的实际边界

根 `package.json` 的 `npm test` 顺序运行 core/frontend/desktop/startup；没有旧 Python runner、manage.py 或旧服务启动。根 README 当前已说明 TS local/desktop、两个 worker requirements；AGENTS 的 Django check 条件是“若仍修改旧实现”，保留原规则即可。正式 builder 以明确名单复制 core/frontend/workers/desktop；Python builder 明确拒绝 Django/DRF/Gunicorn/Waitress/WhiteNoise。[当前绑定与静态检查](../refactor-evidence/20261013-legacy-retirement-prepare/verification.json)。

PBKDF2 默认认证测试已使用可追溯 Django 黄金向量与独立 HMAC oracle；保留 `auth.test.ts`、fixture、原 Django 生成收据与 `auth/passwords.ts`，不再要求 Python Django。AES-GCM 双向兼容测试仍实际执行 Python `cryptography`，这个必要测试环境与旧根 requirements 的退役分开；删除根 requirements 不等于卸载系统 Python 包。命令可通过 `MARLIN_CRYPTO_TEST_PYTHON` 指定已验证的独立 cryptography 解释器。

认证 E2E config/helper 当前只启动真实 TS Core + Vite，独立空数据目录、不复用旧服务。初版 AUTH-E2E-TS-ENTRY 的 3FAIL 是历史，不能当当前阻断：后续[共享tab修复](SHARED-TAB-AUTH-FIX.md)最终原三项实际 **3/3、exit0/session33670**，frontend **370/370**，源 transport `f0fe7546…`、原 spec `4ca3836f…` 与当前 SHA 匹配；[最终原始E2E日志](../refactor-evidence/20261013-shared-tab-auth-fix/e2e-final.stdout.log)、[107绑定Root审查](../refactor-evidence/20261013-root-sidebar-auth-review/review.json)及[自然Orca交接](SHARED-TAB-ORCA-ACCEPTANCE.md)均保留。只读重新核证，不重跑suite、不把历史结果记为本轮新测试。它们不证明最新 Windows IPC、自然过期和完整A组通过。

通用 `frontend/playwright.config.ts` 只启动4173 Vite，默认包含全部spec；多数其他spec有明确 `page.route` 替身，而真实auth spec需要Core。现有Vite proxy指8000，因此直接 `npm run test:e2e` 不是自含的全部真实业务入口，需要调用者另起隔离TS Core或选明确auth配置。mobile配置也只启动preview。三者均不启动Django；不能把通用前端替身规格或“只起Vite”当完整真实E2E通过。Root下一来源迭代可整理通用testMatch/说明，但本轮不改配置，不占用8000或复用现有服务。

当前 runtime 专项最终29相关测试及 native/packaging检查见[当前实现](OWNED-RUNTIME-SHUTDOWN-IMPLEMENTATION.md)。原准备时Root正在正式Windows prepare；后续原builder package-only已actual0，新包实际GUI/安装业务仍另验，不能把静态扫描或历史6e/aabd安装结果替代新包门禁。

## 黄金资料、许可证和历史链接

[保留核对表](../refactor-evidence/20261013-legacy-retirement-prepare/preservation.json)绑定所有原字节与新位置：

- 根/两个 worker 的 MIT、Apache POI DOC/PPT 来源说明和 Apache-2.0、MT19937 许可保留原位置。DOC/PPT 新旧 SHA 完全相同；新 parser fixture manifest 全部文件 SHA 核对。现有 PyMuPDF AGPL/commercial/native 第三方安排不被 MIT 覆盖或更改。
- 公共数据的180题ID、3045全集、revision、files、corpus OID、CC-BY-NC-4.0、两个原 manifest SHA 与当前 registry逐项核对。原 manifest 原样归档，当前 registry/算法/licence不改。没有下载或读公共缓存/已付费向量。
- `chunking_v1.json`、`retrieval_v1.json`、`retrieval_v2.json` 的实际内容是含 placeholder 的未验证模板；原样归档，不将它们包装成有效黄金答案或悄悄变更内容。`eval_dataset_manifest.json` 原样保留关联公开注册信息。根 `tests/eval/datasets/django_agent_multiactor_eval.json`、`eval_config.yaml` 保留当前原字节。
- `sample.xls` 原SHA `3f8cde41…` 与新原创 `records.xls` 的 `b6b51ea2…` 不等价；旧 README 未声明该 xls 来源。保留旧 xls 的精确归档，不附会 Apache POI 许可、不将“新副本等价”写成true。当前原创 xls 已有项目fixture manifest来源说明。tracked 源中没有独立 `.xml` 文件；Office ZIP内部 XML 的解析代码/fixture/测试保留，不把 XML公共内容或网络WebFetch XML支持当成旧Django应删项。
- **174** 条基线链接来自 DATA-BASELINE(129)/PARSER-BASELINE(45)，涉及100个目标。[逐条source-map](../refactor-evidence/20261013-legacy-retirement-prepare/HISTORICAL-SOURCE-MAP.md)每条绑定原文档:行号、旧路径、归档与SHA。冻结文档/收据不改；归档不是将当前 TS代码伪装成旧源。移除旧路径后旧直接链接将需要通过本 addendum 解引用，不能声称直接链接仍正常，也不能为了静态链接检查保留可运行旧后台或创建旧Python模块symlink。其他旧文档引用仍通过301项总表定位。

不批量删除 `docs/`；langfuse-operations、trajectory、跨设备/旧重构等是历史实现说明，保留其字节并由本计划标明旧运行命令已退役。`workers/document/README.md` 中“旧后端文件未修改”是提取当时的历史说明，后续Root仅在非冻结的新版本说明追加退役链接；不据此删除来源或许可证。

## 分步执行与退出条件

### 1. 解冻前只读门禁

- [x] 原265/AST/174链接地图及当前来源已核对；301精确字节副本/source-map完成。
- [x] 当前密码、AES-GCM、公开资料、许可证、渠道、默认tests/E2E边界核对；检查退出0详见 verification。
- [x] Root已完成原正式Windows prepare/package来源绑定；删除前再核468项/dd5冻结一致。下一autostart实现必须形成新源码迭代，不能改历史构建manifest洗掉差异。
- [ ] Root 根据真实矩阵决定本次删哪些域；存在重要业务遗漏时保留对应旧源/归档，不把旧服务继续引入正常入口。

### 2. 最小第一批：精确10个旧入口/依赖/脚本

仅在Root确认源码解冻且清单SHA/候选Git状态仍一致后执行：

```text
manage.py
requirements.txt
desktop/requirements-windows.lock
scripts/start_local.py
scripts/start_desktop.py
scripts/local_services.py
scripts/benchmark_open_rag_runtime.py
scripts/test_benchmark_open_rag_runtime.py
scripts/bench_langfuse_overhead.py
scripts/verify_langfuse_settings.py
```

这些均不在当前运行/构建名单；新 `scripts/desktop/`、worker requirements、native locks及 `scripts/test_build_windows.py` 保留。builder测试中的旧文件名是“拒绝打包”夹具，不删除负断言。不要卸载全局Python包。具体操作脚本见[可执行runbook源码](../refactor-evidence/20261013-legacy-retirement-prepare/execution-runbook.source.py.txt)，默认只核对；Root选择 `--remove-group entrypoints --source-unlocked` 才会准确 unlink 这10个路径。脚本先一次性核所有目标/副本/状态，出现变化即退出，不自动扩大范围，不清目录。

**此group当前暂缓。** 即使上述文件不在当前TS运行/构建名单，也必须先迁移仍由UI承诺的旧autostart能力并由Root重新协调执行；本轮原10项执行授权已被该具体暂缓指令收回，没有运行删除分支。

### 3. 剩余旧运行源码与36个旧检查

在各对应能力完成Root真实验收后，按301清单去除剩余291个路径，精确文件删除，不用 `rm -rf` 清树；用户DB/WAL/SHM/media/.settings/.secrets/.env、缓存、旧图库、私有452快照、安装及备份均不在脚本允许集合中，也不读取它们。没有源码 symlink。所有旧文件先已字节归档，空旧目录可由Root另查后精确 `rmdir`；非空目录不动。

根36个额外旧检查包括32个导入Django/旧业务的测试，旧 full runner，以及三个漏于绝对import扫描的检查：migration graph源扫描（旧目录删除后会vacantly PASS）、真实旧 `db.sqlite3` 诊断、旧 `.env`/Neo4j网络诊断。全部归档后退役，不能将它们当当前默认安全验证。保留根 `test_readme_links.py`、`test_frontend_contracts.py`、eval fixtures。静态frontend脚本第188行的“旧Django Playwright覆盖”说明应在Root后续小补丁中改为当前 `frontend/tests/cross-device-auth.spec.ts` 并标明认证范围，保留4个原断言；本轮不编辑它。

全体执行命令为 `--remove-group all-after-acceptance --source-unlocked --capabilities-accepted`；两个显式参数由Root在实际门禁成立时给出，不是向用户请求重复授权。脚本中字段只表示此次文件动作，不能改变Goal或主矩阵状态。

### 4. 改动后的必要验证

Root按改动范围运行并存真实日志；本轮没有执行以下测试、构建或GUI：

```bash
python tests/test_readme_links.py
git diff --check
npm --prefix packages/core run typecheck
cd packages/core
MARLIN_CRYPTO_TEST_PYTHON=/path/to/verified-cryptography-python node --import tsx --test test/auth.test.ts test/credentials.test.ts test/migration.test.ts test/graph-legacy.test.ts test/legacy-routes.test.ts test/channel-routes.test.ts
cd ../../frontend
npm run test:unit
npx playwright test --config playwright.auth.config.ts
cd ..
npm --prefix desktop test
npm run test:startup
python -m unittest scripts.test_build_windows
```

`/path/to/verified-cryptography-python` 必须换为Root实际核过的独立解释器，不凭空假设。只删旧代码不需要重放Django check/migrations；若Root另修仍运行的旧Django代码，AGENTS旧检查条件继续适用。相关测试通过后不重复full suite；若后续改依赖/构建输入，执行必要新build及正式Windows source_inputs/native/loader/IPC/worker/installer门禁。不能在冻结prepare过程中运行并发写build/dist。

历史source-map归档SHA与冻结文档SHA另用runbook默认核对；删除之后使用 `--verify-retired-group entrypoints` 或 `all-after-acceptance` 核准确不存在及保留SHA。这是只读退出0核对，不等于运行验收。文档本轮检查链接指向现存原文与归档、差异和归档字节；旧直接链接未来移除状态显式记载。
