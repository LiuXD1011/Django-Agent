# ORCA-CLEANUP-RESULT — 清理实施结果报告

- task_id: `task_b0a290393112` / dispatch_id: `ctx_6a6066f47fa3`
- 执行: 清理 worker（term_db08c892-566d-4233-8314-3ad01577385f），2026-09-30
- 基线: HEAD `afa7e013`（本轮全程未变），分支 `prep-desktop-commercial-release`；开工前核对 10 个目标文件均无未提交改动
- 环境: Linux WSL2，node v22.23.2 / npm 10.9.8
- 边界遵守: 删除仅为工作树操作（未 stage/git rm/commit/重写历史）；未触碰 P02A（accounts/scripts/local_services/lock tests）与 R1（tasks/test_task_recovery）文件；未装 Python 包、未改 requirements/数据集/后端；未使用/验证/轮换令牌；dsh-recon 内容与删除正文零输出（检视仅 --name-status/--stat）；无内置子代理。
- Round2: task_id `task_9765eb989516` / dispatch_id `ctx_662ec1d04775`（清理 worker term_0740ef7f-610c-4f37-966f-45a74fb8890c），2026-10-01；仅改 `frontend/package.json` 之 `test:unit` 与本文件（原子 mv）。**含对 Round1 一处错误表述的勘误，见"〇"节。**

## 〇、Round2 勘误与 test:unit 修复（2026-10-01）

### 勘误（针对 Round1 §三.3，原文保留未删）

Round1 §三.3 声称 glob 形态 `node --test "src/**/*.test.mjs"` "在 node v20.19+（vite engines 下限）/v22.23.2 **实测**覆盖 19 文件"。**该表述与证据矛盾，予以更正：**

- Round1 实际只在 Node v22.23.2 上运行过 glob 形态；Node 20.19 属**未实测的推断**，被误写为"实测"。
- Codex 独立复测（round2 派发前）：`npm_config_cache=/tmp/marlin-review-npm-cache npm exec --yes --package=node@20.19.0 -- node --test 'src/**/*.test.mjs'`（cwd `frontend`）→ **exit 1**，报错 `Could not find '/home/liuxuedeng/orca/workspaces/Django-Agent/marlin/frontend/src/**/*.test.mjs'`。Node 20.x 的测试运行器不展开位置参数 glob，按字面路径查找，必然失败；glob 形态仅 Node 22 实测可用。日志：`/tmp/marlin-codex-node20-unit.log`。
- 同句"Windows 兼容（引号内 glob 由 Node 解析）"同为推断，Windows 原生从未实跑，亦不应表述为已验证。

### 修复（最小方案，无新增依赖/脚本）

`frontend/package.json` 的 `test:unit` 由 `node --test "src/**/*.test.mjs"` 改为 **`cd src && node --test`**——无参运行时 Node 测试运行器从 cwd 递归发现 `*.test.mjs`，Node 20 与 22 均支持该行为。`test:e2e`、esbuild 及其余文件零改动；README 未动（前轮 README engines `^20.19.0 || >=22.12.0` 的支持范围在修复后才真正被 `test:unit` 满足，此前 glob 形态在 20.19 不可用，本轮不改 README 掩盖任何问题）。

### Round2 命令与退出码台账（本 worker 实测，cwd 除注明外为 `frontend/`）

| # | 命令 | exit | 结果 |
|---|---|---|---|
| 1 | `npm --prefix frontend run test:unit`（Round1 glob 脚本，**对照**，Node v22.23.2） | 0 | 30 tests / 30 pass / 0 fail（日志 `/tmp/marlin-r2-node22-control-glob.log`） |
| 2 | `cd frontend/src && node --test`（候选方案，Node v22.23.2） | 0 | 30 tests / 30 pass（`/tmp/marlin-r2-node22-candidate-from-src.log`） |
| 3 | `cd frontend/src && npm_config_cache=/tmp/marlin-review-npm-cache npm exec --yes --package=node@20.19.0 -- node --test` | 0 | `v20.19.0`，30 tests / 30 pass（`/tmp/marlin-r2-node20-candidate-from-src.log`） |
| 4 | `find frontend（除 node_modules）`全部测试模式文件核查 | 0 | 命中恰为 src 下 19 个 `.test.mjs`，无 src 外文件，无发现漂移 |
| 5 | Node22 逐文件仲裁：19 文件逐个 `node --test <file>`（cwd src） | 0（19/19） | 逐文件用例和 = 30 == 套件 30（`/tmp/marlin-r2-arbitration/node22/`） |
| 6 | Node20.19 逐文件仲裁：19 文件逐个 `npm exec --package=node@20.19.0 -- node --test <file>`（cwd src） | 0（19/19） | 逐文件用例和 = 30 == 套件 30（`/tmp/marlin-r2-arbitration/node20/`） |
| 7 | 改 `frontend/package.json` 仅 `test:unit` 一行 | — | `cd src && node --test` |
| 8 | `npm --prefix frontend run test:unit`（最终脚本，Node v22.23.2） | 0 | 30 tests / 30 pass / 0 fail（`/tmp/marlin-r2-final-node22-script.log`） |
| 9 | `npm exec --yes --package=node@20.19.0 -- npm run test:unit`（最终脚本） | 0 | 30 tests / 30 pass / 0 fail（`/tmp/marlin-r2-final-node20-script.log`） |
| 10 | 版本内证：`npm exec --yes --package=node@20.19.0 -- sh -c 'echo $(node --version) && npm run test:unit'` | 0 | 同一 PATH 下先打印 `v20.19.0` 再跑脚本 30/30，排除解释器歧义（`/tmp/marlin-r2-final-node20-script-versioned.log`） |

Codex 独立验收（协调者转述，非本 worker 复跑）：round2 派发前 Node22 test:unit 30 tests / exit 0、`build` exit 0、README links exit 0、Node20.19 glob 复测 exit 1（命令与日志见上勘误节）；本 worker 提交修复后，Codex 对**当前** `test:unit` 复验——Linux Node22 与 Node20.19 各 30/30 exit 0，且 **Windows 原生**（临时副本，实际 `npm run test:unit`）30/30 exit 0（msg_384d91d6ab12）。**Windows 证据归属 Codex 独立验收，本 worker 未实跑 Windows。**

**not_run（本 worker）**：`build`（派发指示：无业务变化不必重跑）；`test:e2e`（需浏览器）；Windows 原生运行（**本 worker 未实跑，不声称 Windows 实测为我所做；Windows 30/30 见上，归 Codex 验收**）；后端任何测试；`graphify update .`（由 Codex 统一执行，本 worker 不并发运行）。

### Round2 验收结论

- [x] Node v20.19.0：19 文件 30 用例全覆盖、全过、exit 0（套件运行 + 逐文件仲裁双口径）
- [x] Node v22.23.2：19 文件 30 用例全覆盖、全过、exit 0；对照（Round1 glob 脚本）30/30 未回归
- [x] Windows 原生 30/30 exit 0：Codex 独立验收（msg_384d91d6ab12，临时副本 + 实际 `npm run test:unit`），本 worker 未实跑、未冒称
- [x] 勘误显式入档（本节 + §三.3 原文旁标注），未删改 Round1 历史
- [x] 本轮改动仅 `frontend/package.json`（1 行）与本文件；未 commit/push，未触碰后端、README 及其他 worker 文件

## 一、变更清单（全部实际路径）

删除（6，工作树 D，可从 HEAD 恢复）：
- `frontend/dsh-recon.mjs`
- `tests/debug_current_graph_rag_reason.py`
- `tests/debug_hello_latency.py`
- `tests/debug_memory_timeout_reason.py`
- `tests/rebuild_current_graph_rag.py`
- `pnpm-lock.yaml`

修改（6，Round1）：
- `package.json` — 移除 `devDependencies.@playwright/test` 与 `packageManager: pnpm@11.9.0`；4 个委托脚本原样保留；根无 lock，统一 npm
- `frontend/package.json` — 新增 `"test:unit": "node --test \"src/**/*.test.mjs\""` 与 `"test:e2e": "playwright test"`；devDependencies 显式加入既有锁内版本 `"esbuild": "0.27.7"`（`src/services/langfuse.test.mjs:5` 直接 import，原仅靠 vite 传递提升）；其余依赖零变更。**【Round2 更新：`test:unit` 已改为 `cd src && node --test`，见"〇"节】**
- `frontend/package-lock.json` — 仅根块 devDeps 同步（3 行 diff），依赖树保持 148 包、esbuild 0.27.7 不变
- `README.md` — 移除断链图片 `docs/images/wiki-graph-preview.png`（目录不存在）；Node 要求改为锁内 engines 实测值 `^20.19.0 || >=22.12.0`（vite 7.3.5 与 @vitejs/plugin-vue 6.0.6 一致，弃用设计报告的 Node18 猜测）；前端安装 `npm install`→`npm ci`；新增"开发与测试"段（test:unit/test:e2e/build 三入口，如实标注 e2e 需浏览器、dist 被 git 忽略）
- `frontend/src/styles/weknora-redesign.test.mjs` — 仅第 18 行：断言与说明 `新对话`→`对话`（Codex msg_5898410b5963 批准范围；其余断言与 Platform.vue 未动）
- `.ai-collab/ORCA-CLEANUP-AUDIT.md` — 勘误（原子替换）：候选 1 "轮换或历史重写二选一"更正为"历史仍保留该值，本轮不检查有效性/不处理凭据或历史，需后续核验"；流程披露保留本地终端一次性打印事实，未夸大为对外泄露

新增（1）：
- `.ai-collab/ORCA-CLEANUP-RESULT.md`（本文件，临时文件+原子 mv；Round2 为同路径整体重写，Round1 原文全量保留）

Round2 新增修改（1）：
- `frontend/package.json` — 仅 `test:unit` 一行（见"〇"节）

## 二、命令与退出码台账（Round1，2026-09-30，原样保留）

| # | 命令 | exit | 结果 |
|---|---|---|---|
| 1 | `git status --porcelain -- <10个目标文件>` | 0（空输出） | 目标全部干净 |
| 2 | `rm` 6 文件；`git diff --name-status`/`--stat` 核验 | 0 | 6 D，共 -1142 行，无正文输出 |
| 3 | `npm install --package-lock-only`（frontend） | 0 | 锁仅 +devDeps.esbuild 根条目，树 148 包不变 |
| 4 | `npm ci`（frontend） | 0 | 干净安装成功；npm 输出既有 audit 通告（锁内旧版，按约不升级） |
| 5 | `npm --prefix frontend run test:unit`（首版脚本 `node --test src/`） | 1 | **根因**：Node22 把位置参数目录当模块加载（MODULE_NOT_FOUND），0 文件执行 |
| 6 | `node --test "src/**/*.test.mjs"`（glob 实证） | 1 | 30 用例 29 过 1 败 → 单跑定位 `weknora-redesign.test.mjs:18` |
| 7 | 漂移溯源 `git log -S "新对话" -- Platform.vue` | 0 | 347e7c6(2026-09-05) 改标签未同步 3bf5f25(2026-07-22) 契约；两文件工作树干净＝**HEAD 既有失败，与本轮清理无关** |
| 8 | 只读探针（内存替换标签后整文件断言） | 0 | "WeKnora redesign contract assertions passed"→一行修复充分 |
| 9 | Orca ask → Codex 批准该一行修正；check 清空 2 条 Delivery | — | 另获知 graphify 由 Codex 统一更新（msg_634361203267） |
| 10 | 修 `weknora-redesign.test.mjs:18` + 修 test:unit 脚本为 glob 形式 | — | 首次复跑仍 1 败系脚本未更新之疏漏，改后通过 |
| 11 | `npm --prefix frontend run test:unit`（最终） | 0 | **30 用例 30 过 0 败** |
| 12 | `npm --prefix frontend run build` | 0 | 14.83s 构建成功；仅 chunk>500kB 建议（index 1.45MB，advisory）；产出仅被忽略的 `frontend/dist/`，**不宣称安装包完成** |
| 13 | `python -B tests/test_readme_links.py` | 0 | "test_readme_links: OK" |
| 14 | 悬空引用检索（py/mjs/ts/json/vue/css/html/md，排除 docs/.ai-collab/graphify-out/node_modules） | 0 | 唯一命中 `docs/langfuse-goal-implementation-plan.md:583` 提及 pnpm-lock.yaml——历史计划文档按约保留，非源码悬空引用；`.zcodeignore` 的 `.pnpm-debug.log*` 为忽略模式，无害 |
| 15 | 覆盖率仲裁：19 文件逐个单独运行求和 | 0 | **逐文件和=30 == 套件 30**；且 langfuse 用例名出现在套件 spec 输出 → 19 文件全覆盖 |

**Round1 not_run（原样保留）**：`test:e2e`（需浏览器）；Windows 原生运行；后端任何测试；`graphify update .`（Codex 本波统一执行，msg_634361203267，本 worker 不并发运行）。

## 三、关键结论与定位记录

1. **weknora-redesign.test.mjs:18 既有失败**（非本轮引入）：347e7c6 将 Platform.vue 桌面导航从"新对话"改为"对话"（goChat 语义：优先回最近会话，新建入口移至会话侧栏），3bf5f25 的契约断言未同步。Codex 独立核实 Platform.vue:20/25/31/114/158 后批准仅对齐该断言文案；实测仅改该行后全文件断言通过，Platform 产品逻辑零改动。
2. **Node --test 观测陷阱（值得留档）**：进程内执行的测试文件在 TAP/spec 输出中只显示用例名、不显示文件路径；按"文件路径 grep"核对覆盖率会误报 4 个文件（services/langfuse、stores/auth-storage、KnowledgeDetail.multimodal、settings-ui）失踪。仲裁标准应为"逐文件单独运行用例数之和 == 套件用例数"（Round1 30==30，Round2 两版本均 30==30）。
3. **glob 形态选择**：`node --test src/`（目录位置参数）在此 Node 版本按模块加载失败；`node --test "src/**/*.test.mjs"`（Node 自身展开 glob，无 shell globstar 依赖）在 node v20.19+（vite engines 下限）/v22.23.2 实测覆盖 19 文件，Windows 兼容（引号内 glob 由 Node 解析）。**【Round2 勘误：本条中"v20.19+ 实测"与"Windows 兼容"为错误表述——glob 形态在 Node 20.19 实测 exit 1（位置参数 glob 不展开、按字面查找，`/tmp/marlin-codex-node20-unit.log`），Round1 仅在 Node22 实测过，Windows 从未实跑；正确形态为 `cd src && node --test`，两版本实测均过（Windows 原生由 Codex 独立验收，msg_384d91d6ab12），详见"〇"节。原文保留如上。】**

## 四、存留问题（未处理，需后续决策/任务）

1. dsh-recon 令牌值仍在 git 历史（347e7c6）；本轮按约不检查有效性、不处理凭据或历史，**需后续核验**。
2. npm audit 通告为锁内既有旧版依赖的已知问题；本轮版本冻结不升级，商用前需专项评估。
3. vite 构建建议拆分 >500kB chunk（index 1.45MB）；非阻塞。
4. `docs/langfuse-goal-implementation-plan.md:583` 提及已删除的 pnpm-lock.yaml（历史文档按约保留，文字与现状不符）。
5. Python `playwright` 包仍未在 requirements.txt 声明（后端文件不在本任务范围）；`test:e2e` 运行命令已入 package.json 但浏览器实跑未验证（not_run）。
6. 审计报告候选 5/6（verify_langfuse_settings.py、docs/ 历史文档）本轮未获批执行，维持原状待决策。

## 五、收尾核对

- [x] 除上表 13 个路径外无其他新增/修改/删除；graphify-out 未动（待 Codex 统一更新）
- [x] 两份 .ai-collab 文件均为临时文件+原子 mv 写入；.ai-collab 内他人文件（DECISIONS/RESULT/REVIEW/STATUS/TASK/ORCA-P02A-RESULT/ORCA-DESKTOP-DESIGN）未触碰
- [x] 验收四项全绿：npm ci / test:unit(19 文件 30 用例) / build / test_readme_links（Round1 口径；Round2 复验 test:unit 双版本，build 按派发指示未重跑）
- [x] Round2：改动仅 `frontend/package.json`（test:unit 一行）与本文件；Node20.19/Node22 双版本 19 文件 30 用例实测通过（Windows 原生为 Codex 独立验收）；勘误显式入档；未 commit/push；不冒称 Windows 实测
