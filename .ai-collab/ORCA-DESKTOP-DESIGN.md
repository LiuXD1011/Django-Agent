# ORCA-DESKTOP-DESIGN — Windows 首发最小交付设计（只读调查报告）

- task_id: task_2d3568b62474
- dispatch_id: ctx_e0db7292e3b8
- 日期: 2026-09-30
- 基线: prep-desktop-commercial-release @ afa7e0138f9fbad80e80aa4ead6f1d80af0145da（分析期间 P01 accounts / P02A 文件锁在其他终端并行修改，涉及行号以其落定后为准；本文所引为读取时点状态）
- 范围: 只读。除本文件外零写入；未安装依赖、未运行服务器/测试/迁移、未联网、未读真实 .env。
- 验证状态: 所有测试与 Windows 原生步骤均 **not_run**（本机为 WSL，Windows 侧仅有 C:\Python313\python.exe 3.13.3 且未装项目依赖）。

---

## 1. 现状盘点：已有能力 vs 缺口

### 1.1 源代码与用户数据分离

| 数据 | 现状 | 证据 | 结论 |
| --- | --- | --- | --- |
| SQLite 主库（含 FTS5/vec0 虚拟表，向量与全文索引都在库内） | `DJANGO_DB_PATH` env 可重定向，缺省 `BASE_DIR/db.sqlite3`；WAL + busy_timeout 30s | config/settings.py:98-108；personal_knowledge_base/search.py:59,73 | ✅ 已支持单文件搬家 |
| media 上传 | `MEDIA_ROOT = BASE_DIR / "media"` 硬编码，无 env | config/settings.py:119-121 | ❌ 缺口 G1 |
| `.cache/` 群（评测报告、OpenRAG 数据集与 checkpoint、限流锁、langfuse 状态） | 全部 `BASE_DIR/.cache` 相对路径 | personal_knowledge_base/eval_reports.py:112；tasks.py:436；open_rag_benchmark.py:56-75；model_rate_limit.py:24-26；scripts/local_services.py:43 | ❌ 缺口 G1（装进 Program Files 类只读目录即不可写） |
| SECRET_KEY | DEBUG 态每次启动随机（会话/CSRF 失效）；生产态必须 env 提供，无持久化机制 | config/settings.py:35-41 | ❌ 缺口 G2 |
| LLM API Key | env 或 DB ModelConfig（随库持久化） | config/settings.py:140-154 | ✅ |

### 1.2 首次初始化

- 开关：`ALLOW_AUTO_SETUP` env，**默认 False**（config/settings.py:47）。
- 端点：`auth_auto_setup`（accounts/views.py:152-177），带 SQLite 跨进程 FileLock 闸门（accounts/views.py:100-131）、503/setup_busy 熔断、临时密码下发。功能完整（P01 另有可移植性测试 accounts/test_auto_setup_portability.py:106-313）。
- **缺口 G3**：`.env.example` 无 `ALLOW_AUTO_SETUP` 键（grep 验证），用户复制模板后「自动初始化」按钮收到 401/auto_setup_disabled；README.md:87 却宣称「首次访问自动创建默认账号」——文档与默认值矛盾。
- **缺口 G4**：首启无自动 migrate。全仓只有 scripts/verify_langfuse_settings.py:30 调用 migrate；auto-setup 前提是 User 表已建（accounts/views.py:158）。README.md:78 要求手动 migrate。桌面路径需要启动器先迁移。

### 1.3 生产静态资源与 SPA

- SPA 服务端回退：catch-all `TemplateView index.html`（config/urls.py:32-34，不受 DEBUG 影响）✅；模板目录含 `frontend/dist`（config/settings.py:84）。
- **缺口 G5**：`/assets/` 与 media 仅在 `settings.DEBUG` 时挂 `static()`（config/urls.py:28-30）。`DEBUG=false` 且已 `npm run build` 时，`/assets/*` 无任何 URL 服务 → 首屏白屏。`STATIC_ROOT=staticfiles`（settings.py:116）同样无服务 URL，requirements 无 whitenoise/waitress（requirements.txt:29-33 只有 Windows 不支持的 gunicorn）。
- 前端同源请求：axios `baseURL: ''`（frontend/src/api/client.ts:3-6）✅ 同源部署零配置；开发态 vite 代理 5173→8000（frontend/vite.config.ts:6-12）。
- loopback：`ALLOWED_HOSTS` 缺省 `localhost,127.0.0.1`（config/settings.py:50）✅；绑定地址由启动命令决定（runserver 默认 127.0.0.1:8000）。

### 1.4 web + 任务 worker 启动/健康/退出

- `scripts/start_local.py` = `os.execv` 转 `manage.py runserver`（scripts/start_local.py:6-9）；manage.py 外层进程先 `ensure_langfuse`（manage.py:9-15，docker 不可用时优雅降级 `docker_unavailable`，scripts/local_services.py:89-94，有 LocalStartupTests 覆盖 personal_knowledge_base/test_settings_thinking.py:287-317）。
- **缺口 G6**：evaluation 队列任务入队后仅置 pending 等外部 worker（personal_knowledge_base/tasks.py:77-80）；`run_task_worker` 是手动命令，无任何脚本拉起它。桌面若只开 web，评估任务永久 pending。
- 健康检查：`/health` 返回 ok（personal_knowledge_base/views.py:416-417；config/urls.py:15）✅，可作为启动器就绪探针。
- 退出：runserver/worker 均无进程编排（无 PID 管理/优雅终止），启动器需自管子进程。
- `os.execv` 在 Windows 上不替换进程、退出行为不可靠 → 启动器应改用 `subprocess` + 信号/任务kill。

### 1.5 可选重依赖与 Windows 安装风险（均 not_run，待原生验证）

- 评估栈 ragas/datasets/langchain-*：仅评估功能用，首发的最小路径可不装（裁剪为可选 extras 的候选）。
- CairoSVG：document_parsing 引用（personal_knowledge_base/document_parsing/images.py、__init__.py），Windows 需 Cairo/Pango DLL，安装失败率高 → 应可降级。
- neo4j 驱动：函数内懒加载（graph_rag.py:137、memory.py:183）+ `neo4j_configured` 守卫，默认关闭（config/settings.py:250）✅ 不装也能跑主路径。
- LibreOffice/soffice：仅旧版 .doc/.ppt 需要，缺失时优雅报错（document_parsing/legacy_office.py:17-56）✅。
- sqlite-vec 0.1.9 / PyMuPDF / tiktoken 的 cp313-win_amd64 wheel、官方 CPython 3.13 的 FTS5 编译项（personal_knowledge_base/startup.py:44-49 会硬失败）→ 原生验证顺序见 §5。
- Django 5.2.15 + DRF 3.14.0 组合（requirements.txt:2-3）：3.14 官方支持矩阵未覆盖 Django 5.2，本仓未在本机装过 → **not_run，原生安装时若报 import/兼容错，需升 DRF ≥3.16**（不改代码，仅依赖行）。

### 1.6 已确认不需改的项

- SSE 已有 `StreamState`/`StreamEventRecord` 数据库持久化（personal_knowledge_base/models.py:299,317），不按单进程内存假设处理。
- Langfuse 默认关（config/settings.py:170），桌面阶段 1 可完全不带 docker。
- CACHES locmem（config/settings.py:127-132）对单机桌面足够，不动。

---

## 2. 方案对比与推荐阶段

| 维度 | A. 最小本地启动器（推荐先做） | B. Electron/Tauri 完整打包 |
| --- | --- | --- |
| 交付物 | `scripts/start_desktop.py` + 少量 settings/urls 改动 + 前端小修 | 外壳工程、打包管线、自动更新、签名 |
| 复用 | 直接复用 manage.py/run_task_worker/health/自动初始化全套 | 需把上述全部封装进外壳生命周期 |
| 风险 | 低；全部改动可测试可回滚 | 高；引入新栈与构建链，与本仓 Vue/Django 结构正交 |
| 用户体感 | 命令/快捷方式启动 → 打开浏览器 | 双击图标、托盘、离线安装包 |
| 结论 | **阶段 1（本设计三批次）** | 阶段 2：待 A 的数据分离与生产服务路径稳定后，再评估 Tauri（体积/权限更小）包住 A 的启动器，不重复实现服务编排 |

推荐理由：A 是 B 的严格子集与前置——B 的任何外壳最终都要调用「migrate → waitress → worker → health → 浏览器」这套编排，先把它做成可测试的 Python 入口，外壳只替换图标与进程包装。

---

## 3. 三个可派发小批次

### 批次 D1：用户数据根目录分离 + 桌面默认配置

- 范围/文件：`config/settings.py`、`.env.example`、`README.md`、新增 `tests/test_desktop_paths.py`（或并入 personal_knowledge_base/test_settings_thinking.py 的 LocalStartupTests 风格）。
- 行为：
  1. 新增 `APP_DATA_DIR` env（缺省 `BASE_DIR`，完全向后兼容）：`MEDIA_ROOT = APP_DATA_DIR/media`；各处 `BASE_DIR/".cache"` 改引用 `settings` 上的统一常量（eval_reports.py:112、tasks.py:436、open_rag_benchmark.py cache_path、model_rate_limit.py:24、scripts/local_services.py:43）。
  2. SECRET_KEY 持久化：`APP_DATA_DIR/secret_key` 文件，权限 0600；读取顺序 env > 文件 > 生成并落盘（仅 `DJANGO_DEBUG=false` 时落盘要求；DEBUG 态保持现行为不变，settings.py:35-41）。
  3. `.env.example` 补 `ALLOW_AUTO_SETUP=true`（桌面段注释说明）与 `DJANGO_DB_PATH` 示例；README.md:87 与默认值矛盾处改为指向开关。
- 推荐方案（无用户选项）：env 名沿用现有 `DJANGO_*` 风格，取 `APP_DATA_DIR`，缺省不迁移旧数据。
- 验收：`python manage.py test tests.test_desktop_paths -v 2`（新增：设 `APP_DATA_DIR` 后 MEDIA_ROOT/.cache/secret_key 全部落新根、缺省行为与现状逐字节一致、DEBUG=false 无 env 时 secret_key 文件生成且二次启动复用）；`python manage.py test accounts.test_auto_setup_portability -v 2`（P01 落定后回归，not_run）。
- 风险：`.cache` 路径散点多（5 处），漏改一处即写回源码目录——用单一 `settings` 常量收敛；旧数据不自动搬迁（文档说明）。
- not_run：全部测试、Windows 真机路径（`os.fspath`/`realpath` 在 Windows 盘符大小写下的行为由 P01 锁路径测试模式覆盖）。

### 批次 D2：生产静态服务 + 桌面启动器（web+worker+health+退出）

- 范围/文件：`requirements.txt`、`config/urls.py`、新增 `scripts/start_desktop.py`、扩展 `personal_knowledge_base/test_settings_thinking.py`（或新增 `tests/test_start_desktop.py`）。
- 行为：
  1. `requirements.txt` 增加 `waitress>=3.0`（纯 Python、Windows 一等支持；gunicorn 保留给 Linux 部署，requirements.txt:30 不删）。
  2. `config/urls.py`：`DEBUG=false` 时也服务 `/assets/`（document_root 指向 `frontend/dist/assets` 或 `STATIC_ROOT`，与 urls.py:30 对称），media 用 `serve_file` 现有视图（urls.py:23）不变；不改 urls.py:32-34 的 SPA 回退。
  3. `scripts/start_desktop.py`（仅标准库 + 现有依赖）：
     - 解析 `--data-dir`（写 `APP_DATA_DIR`/`DJANGO_DB_PATH` env）；
     - 子进程 1：`manage.py migrate`（前台，失败即退出并打印）；
     - 子进程 2：`waitress-serve --listen=127.0.0.1:8000 config.wsgi:application`（`DJANGO_DEBUG=false`、`ALLOW_AUTO_SETUP=true`、`DJANGO_SECRET_KEY` 由 D1 机制注入）；
     - 子进程 3：`manage.py run_task_worker --queue documents`（消除 G6；evaluation 队列桌面阶段不启动，任务留在 pending 并在 UI 展示——与现状一致）；
     - 轮询 `http://127.0.0.1:8000/health`（views.py:416）直至 200（超时 60s）→ `webbrowser.open`；
     - Ctrl+C/控制台关闭：按创建逆序 `terminate()`+`wait(timeout)` 兜底 `kill()`（Windows 用 taskkill /T 兜底）。
- 推荐方案：waitress 而非引入 uvicorn/daphne（全仓无 ASGI 消费，config/asgi.py 未接通道）；不引入 whitenoise（避免 Manifest 静态收集步骤，桌面直接服务 `dist/` 目录更少一步构建产物搬运）。
- 验收：`python -m pytest tests/test_start_desktop.py -v`（子进程编排用 fake command + mock Popen：migrate 失败即中止、health 就绪才开浏览器、退出逆序终止）；`python manage.py test personal_knowledge_base.test_settings_thinking -v 2`；手工 `DEBUG=false` 下 `curl /health`、浏览器深链 `/platform/settings` 刷新（SPA 回退）——全部 not_run。
- 风险：run_task_worker 与 web 同机并发写 SQLite——已有 WAL+busy_timeout 30s（config/settings.py:105）+ 前轮恢复分析的两级 CAS，风险可控；waitress 与 Django 5.2 组合 not_run。
- not_run：真实启动、健康轮询、浏览器打开。

### 批次 D3：前端首启健壮性（quickStart 失败恢复）

- 范围/文件：`frontend/src/views/Login.vue`、`frontend/src/views/Login.*.test.mjs`（新增，仿既有 `frontend/src/views/*.test.mjs` node 单测模式）、可选 `tests/test_frontend_playwright_e2e.py` 增 case。
- 行为：`quickStart()`（Login.vue:26-30）补 try/catch：失败时 `error.value` 显示后端错误码（401/auto_setup_disabled → 提示「已初始化过，请用账号登录或注册」；503/setup_busy → 提示稍后重试）、`loading` 复位、按钮可重试。路由守卫失败已回 /login（frontend/src/router/index.ts:36-47）✅ 不动。
- 推荐方案：仅错误处理与提示文案，不改 UI 风格、不加新页面。
- 验收：`node --test` 跑新增 Login 单测（mock api.autoSetup 抛错断言 error/loading/可重试）；现有 `frontend/src/views/*.test.mjs` 全量回归；可选 playwright case「autoSetup 401 → 停留登录页且显示提示」（复用 tests/test_frontend_playwright_e2e.py:148 的 StaticLiveServerTestCase 模式，not_run）。
- 风险：无（纯前端错误分支）；注意 `t-alert` 已在模板中（Login.vue:52）直接复用。

---

## 4. 批次间依赖

D1 → D2（启动器依赖 APP_DATA_DIR/secret_key 机制）；D3 独立可先行。三批均不改恢复方案、不触 P01/P02A 在改文件（accounts/views.py、scripts/local_services.py 引用处仅**读取**）。

## 5. Windows 依赖准备与原生验证顺序（均未执行，not_run）

1. `C:\Python313\python.exe -m venv .venv` → `.venv\Scripts\pip install -r requirements.txt`：记录 DRF/sqlite-vec/CairoSVG/tiktoken/PyMuPDF 任一失败项；CairoSVG 失败不阻塞（降级为无 SVG 解析，阶段 1 可接受），DRF 兼容错则升 `djangorestframework>=3.16`（仅依赖行）。
2. `.venv\Scripts\python -c "import sqlite3;print([r for r in sqlite3.connect(':memory:').execute('pragma compile_options') if 'FTS5' in r[0]])"`：验证 startup.py:44-49 的硬前提。
3. `python manage.py migrate`（指向 `APP_DATA_DIR` 内 DB）→ `python manage.py check --deploy`。
4. `cd frontend && npm ci && npm run build`（Node 18+，package.json:11-25 全为官方 win wheel 包，风险低）。
5. 按批次 D2 启动：`curl http://127.0.0.1:8000/health` → 浏览器自动初始化 → 深链刷新。
6. 回归：`manage.py test accounts personal_knowledge_base` + 前端 node 单测。

## 6. 明确不做

Electron/Tauri 外壳（阶段 2 评估）、evaluation worker 桌面自启、自动更新/签名、UI 风格改动、架构重写、SSE 改动（StreamState 持久化已存在）、恢复机制改动（前轮已交付）。
