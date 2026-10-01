# ORCA-FIRST-RUN-RESULT — 首次使用可靠性修复（MARLIN-DESKTOP-D3）

- task_id: `task_7312466bd6b5` / dispatch_id: `ctx_a6038010d6cb`，执行：清理 worker（term_0740ef7f-610c-4f37-966f-45a74fb8890c），2026-10-01
- 环境: Linux WSL2，node v22.23.2 / npm 10.9.8（依赖沿用 cleanup 轮 `npm ci` 产物，未安装任何新包）
- 边界: 仅改下述 6 个授权文件；未 commit/push；未动样式主题、后端、依赖/lock/package 脚本及其他 worker 文件；graphify 由 Codex 统一（协调者 msg_1d12b5d3c0b6）

## 一、变更清单（全部实际路径）

修改（3）：
- `frontend/src/router/index.ts` — 守卫改为具名导出 `authGuard` 并注册：无 token 访问受保护页直接回 `/login`，**不再调用 autoSetup**（消除静默建号导致随机管理员密码丢失）；有 token 与 public 路由原流程不变
- `frontend/src/stores/auth.ts` — `autoSetup` 继续只 persist 已知认证字段（persist 未动，temp_password 从不入 storage），新增 `return res.data` 供调用方一次性展示；`login`/`logout` 未动
- `frontend/src/views/Login.vue` — `quickStart` 与 `submit` 双双加 loading 防重入（Enter 与初始化并发，协调者 msg_1d12b5d3c0b6 补充项）；quickStart 补 try/catch/finally（失败/未知错误 loading 必复位）；错误码映射：`setup_busy`→请稍后重试、`auto_setup_disabled`→本环境未开启、`setup_already_completed`→用已有账号登录（disabled 与 completed 文案互斥）、网络/未知→"自动初始化失败，请稍后重试或使用已有账号登录"；成功留在当前页，组件内存 ref 展示后端返回的账号/临时密码（Vue 插值转义），文案为"建议保存并尽快在设置中修改"（不称服务端强制）；用户点击"已保存登录信息，进入工作台"后才导航并释放内存；无返回 temp_password 时显示"已完成、未返回初始密码、请用已有账号登录"，不伪造、不自动再次初始化

新增（3）：
- `frontend/src/views/Login.behavior.test.mjs` — 10 用例：成功留页+展示凭据+确认后才导航、pending 双击仅一次调用、busy 提示可恢复重试、disabled/completed 文案互斥且不伪造凭据、网络/未知错 fallback、无 temp_password 完成态不伪造不再初始化、全程零 storage 写入、旧错误在新尝试前清空、普通登录成功导航/失败不导航、submit 防重入
- `frontend/src/router/auth-guard.test.mjs` — 5 用例：真实 store+守卫；无 token 不调 autoSetup、public/有 token 直通、autoSetup 返回 data 含 temp_password 且 storage 全量写入对账无泄漏（含独立 key 检查）、无 temp 仍 persist 已知字段、普通 login 契约不变
- `.ai-collab/ORCA-FIRST-RUN-RESULT.md`（本文件，临时文件+原子 mv）

## 二、命令与退出码台账

| # | 命令（cwd=frontend，除注明外） | exit | 结果 |
|---|---|---|---|
| 1 | `node --test src/views/Login.behavior.test.mjs src/router/auth-guard.test.mjs`（**修复前 red**） | 1 | 15 测试 13 fail / 2 pass（两条"保持性"用例绿）/ 0 cancelled，失败全部对准缺失行为（无 finally loading 卡死、立即导航、双击两次调用、无错误处理、无返回值、守卫静默建号、store 丢数据）（`/tmp/marlin-d3-red-canonical.log`） |
| 2 | 同命令（**修复后**） | 0 | 15/15（`/tmp/marlin-d3-green3.log`） |
| 3 | `npm --prefix frontend run test:unit` | 0 | **45 tests / 45 pass / 0 fail** = 既有 30 + 新增 15（`/tmp/marlin-d3-testunit.log`） |
| 4 | `npm --prefix frontend run build` | 0 | 21.88s 构建成功；仅既有 >500kB chunk advisory（index 1.46MB），无新增告警（`/tmp/marlin-d3-build.log`） |

Codex 独立验收（msg_ff4fe11fa2fe，非本 worker 复跑）：Linux test:unit 45/45 exit0、build exit0、Windows 真实 npm 脚本 45/45 exit0；Playwright 隔离真实后端全行为链通过（三类错误提示、无 token 不建号、一次 POST 初始化后留页展示、storage 无密码泄漏、确认后跳转、错误密码后正常登录、390px 无溢出）；日志 `/tmp/marlin-codex-d3-{unit,build,browser,windows-unit}.log`。**Windows 与浏览器端到端证据归属 Codex，本 worker 未实跑**。

not_run 及理由：`tests/test_frontend_contracts.py`（grep 全文无 Login/auth/router/auto-setup/quickStart 相关断言，与本次改动面零交集，判"不必要"）；Windows 原生/浏览器实跑（前端逻辑测试 + build 已覆盖可覆盖面，原生未跑 **not_run**，不声称）；后端任何测试（未触碰）；graphify（Codex 统一）。

测试方法（无新框架）：esbuild `transformSync` TS→CJS + `node:vm` 沙箱执行**真实** `auth.ts`/`router/index.ts`；`@vue/compiler-sfc`（锁内 3.5.38）`parse+compileScript` 编译 Login.vue 真实 `<script setup>` 后直接驱动 `setup()` 返回的绑定；store/api/router/localStorage 为边界 stub；固定假凭据 fixture（`fixture-tmp-9137-not-real`）。red 阶段曾出现装置问题并当场修正后才记录 canonical red：测试文件相对路径 ENOENT、旧代码无守卫致双 await 挂起毒化队列（改为同步记录调用数+先 resolve 再 `allSettled`+timeout 兜底）、vm 跨 realm 对象 `deepStrictEqual` 原型不等（宿主侧 spread 后比较）、store 新契约（返回 `res.data`）下 stub 形态对齐。

## 三、遗留

1. 本 worker 侧 Windows 原生 / 浏览器端到端未实跑（not_run）；该面已由 Codex 独立验收覆盖（见上）。
2. README 未声明 auto-setup 行为变更（本任务未授权改 README；现有 README 对自动初始化的描述与本实现无冲突）。
3. 桌面 D1（数据根/SECRET_KEY）、D2（启动器/waitress/静态接线）仍待派发。
