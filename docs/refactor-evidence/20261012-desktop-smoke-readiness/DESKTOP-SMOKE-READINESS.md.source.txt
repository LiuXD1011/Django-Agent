# Desktop smoke 页面就绪设计与计划

真实安装版隐藏 smoke 截图只有背景：`desktop/main.cjs` 的 renderer Promise 在 `#app` 有子节点时即结束。`App.vue` 会先挂载 app-frame/PwaStatus，而初始路由的 authGuard 仍等待 auth.restore，router-view 可能尚空。因此 mounted 只能证明挂载，不能证明登录页或工作台已显示。原 3231.9168ms receipt 与失败记录均保留，不改成成功。

本次按 Goal II.3–4 已授权的修复范围继续，不要求重复审批或提交。选择在现有 executeJavaScript 模板内检查真实 DOM：`/login` 要有可见 login-page/login-panel、可用邮箱/密码输入与按钮；`/platform/*` 要有 shell/workspace 下的可见业务 main 与至少一个可用业务控件。路径与节点需要同时匹配。PwaStatus、侧栏按钮、空 router-view、隐藏/禁用/inert 控件都不能提前满足。

MutationObserver 监听结构、属性和样式变化，requestAnimationFrame 复核布局；15 秒截止返回 pageReady=false，host 的 ok 同时要求 mounted、pageReady、Node 隔离与 preload protocol/transport。正常结束或超时均清理 observer/timer/frame。不增加模块、依赖、桥接信号或 ASAR 白名单，不以固定 sleep 等待。另一方案是新增 Vue/router 就绪事件，但会扩大前端与 preload 改动；仅等待 DOMContentLoaded 或固定时长无法解决异步路由。

renderer 内分别记录首次观察到 mounted、pageReady 及总等待时间，均相对于本次 renderer probe 开始。startup_ms 明确计量从 runtime.start 前至 renderer 就绪/超时结果、截屏前；不表示所有业务请求完成、人工 GUI 通过或 P95。

实施文件只有 desktop/main.cjs、desktop/smoke-readiness.test.cjs、本文及独立证据目录。步骤：先让新测试提取实际 main.cjs 模板和实际 host JSON 表达式，在已安装 Playwright 1.61.1 的隔离真实 Chromium DOM 中验证延迟路由空壳、登录页、登录后工作台、永久空壳超时、控件不可用及隔离字段；实际运行 RED 后修改内联等待；再运行 GREEN、node --check desktop/main.cjs 与相关 desktop 边界测试。使用 Clock 的 install/pauseAt/runFor 加速真实 15 秒 deadline，不修改生产 timeout 或复制另一份实现。明确 HTML fixture 模拟路由阶段，测试不声称运行了真实 authGuard/用户会话。

不操作 Windows 应用、Orca、Vite、core server 或任何模型；不改原安装/continue harness、receipt、frontend、runtime/IPC、依赖/锁文件和共享报告。无需本轮重新打包或重跑前端全套；root 将在后续冻结包中进行真实 Windows smoke 与可见页面验收。

验证已实际完成：[RED](../refactor-evidence/20261012-desktop-smoke-readiness/red.tap) 为 6/6 功能断言失败、exit 1，其中空路由/PWA 壳立即 resolve 的 true !== false 直接重现原缺陷；同一测试源码在修复后 [GREEN](../refactor-evidence/20261012-desktop-smoke-readiness/green.tap) 6/6、exit 0。随后 [相关检查](../refactor-evidence/20261012-desktop-smoke-readiness/related.tap) 覆盖上述 6 项及既有 IPC/协议 5 项，11/11、exit 0；node --check desktop/main.cjs 与差异检查 exit 0。

测试运行生产模板和生产 JSON 表达式，fixture 只提供真实 Chromium DOM 的不同路由阶段。Playwright Clock 以真实 callback 顺序跑到生产 15000ms timeout，不缩短生产参数；TDesign 已安装输入类型定义与 input.mjs 实际把 autocomplete/email、type/password 等属性投影到原生 input。未重跑前端全套、core、Windows 包或付费模型。Chromium 行为回归证明了 readiness 条件，不能替代下一版 Electron/Windows 的截图与正常退出验收，也不承诺所有业务数据/接口已加载。
