# 共享浏览器账号交接修复

范围为 CD-15：同 Cookie jar 中的一个 tab 登录或注册时，旧 tab 立即失效并离开原私有页面；成功后两个 tab 必须进入新的私有空间。原三项规格与其 spec:83、5000ms URL 断言全部保持。历史[2PASS/1FAIL](AUTH-E2E-PROTOCOL-ACCEPTANCE.md)及其冻结资料不改写。

选择一次性的 tab-local 导航交接。跨 tab logout 导航前，用 sessionStorage 保留该 document 已观察的 identity 事件值（仅服务/账号/空间标识与随机 nonce）；新 document 先安装实时 storage listener，再消费交接记录、比较持久 identity 事件值。只有已经产生新的成功身份事件且 cookie 会话 marker 存在，才请求受保护的 platform 路由；现有 router guard 仍以真实服务端 me 判断登录。记录不含密码、凭据或授权证明，不能直接标记 authenticated。

保留 authenticate 在第一个 await 前的失效、所有 generation/epoch、Cookie origin lock、refresh 不确定性及敏感操作前置证明。普通主动打开 login 没有交接记录，继续允许切换账号/注册；失败登录、真正退出或撤销没有有效的新会话，不恢复旧 A。sessionStorage 不可用时保持退出及失效，不能伪造恢复。先消费 marker，避免循环导航；后续 logout 清掉 cookie marker，优先于旧成功事件。显式登录即使复用同一账号也应发布成功 identity 事件，防止其他 tab 只收到 logout。

备选方案：直接在所有 login 页面自动 restore 会阻止原规格在第二个 tab 注册 B，也可能在 B 尚未提交时恢复 A；省去提前 logout 广播会留下旧页面私有内容和待完成请求，改变安全边界。因此不采用。

执行计划：

- [x] 用真实生产 transport 的跨 document 单元回归取得 RED；以独立 4180/8180 的事件白名单观察核查真实失效与导航时序。
- [x] 最小修复 production transport，保留 router/Login/store 原行为；取得回归 GREEN。
- [x] 执行前端全部 unit、相关严格类型、未改的原三项真实 E2E；确认独立进程、随机 data/cache 清理及 Root Source 未触碰。
- [x] 保存精确命令、结果、边界、链接、来源哈希和临时脚本清理记录。本次程序化测试不代替 Orca 或安装版验收，不标 Goal 完成。

## 实测根因

独立真实 TS Core + Chromium 中，只暂停 A 新 document 的 `auth-transport.mjs` 加载，直到 B 注册成功；不 mock 后端或修改产品延迟。预加载的只读 observer 在 A 的新 document 记录到了 identity storage 事件：6934.732ms 时 Cookie mode 已存在，但 transport 模块响应到 6959.725ms 才完成，A 到 7137.829ms 仍停在 login。此前同一 A 先收到 logout、旧私有缓存失效并导航 login。这直接观测了事件在业务监听安装前丢失，补足原历史 trace 的推断。[白名单事件](../refactor-evidence/20261013-shared-tab-auth-fix/diagnostic-public-events.json)、[命令/真实退出0](../refactor-evidence/20261013-shared-tab-auth-fix/diagnostic.json)。所有时间是该诊断命令内事件的相对位置，包含人为模块加载门控，不能作为产品延迟或性能改进。

新增单测执行完整生产 transport，跨 document 共用 localStorage 并保留本 tab sessionStorage，只有浏览器与 HTTP 边界用明确替身。实际 RED 为 6PASS/3FAIL：missed-event、已经提交但 logout handler 才开始执行的队列竞态，以及同账号显式重登录没有新 identity 事件；失败均为业务断言。修复后专项 9/9 GREEN。其余用例同时保护：commit 前不会恢复 A、主动打开 login 能继续注册、真实 logout/失败登录不恢复、后来的 logout 优先、tab storage 不可用安全失效及 marker 一次性消费。[RED](../refactor-evidence/20261013-shared-tab-auth-fix/red.stdout.log)、[GREEN](../refactor-evidence/20261013-shared-tab-auth-fix/green.stdout.log)。

## 最终验证

生产仅修改 transport：显式成功登录也广播 identity；logout 导航保留低敏交接；新 document 在装监听之后消费/对账。`auth.ts`、router、Login、client、HTTP/Core、依赖/lock、原 E2E spec/config/helper 均未修改。epoch、origin lock、sensitive intent、服务/用户/空间/设备核查和 uncertain-refresh 代码逐字保留；仅 persist 的成功事件条件增加 explicitLogin。当前 production SHA `f0fe75466a593c282c8b30d99c245a87b03e04093f4ad796dbd8a2d9fc59abfb`。[最小差异](../refactor-evidence/20261013-shared-tab-auth-fix/production-only.diff)、[最终绑定与边界检查](../refactor-evidence/20261013-shared-tab-auth-fix/validation.json)。

| 检查 | 实际结果 |
| --- | --- |
| 最终前端 `npm run test:unit` | session75096 exit0，370/370，0失败/取消/skip；TAP47183.435182ms，命令47299.313329ms |
| 相关 strict/noEmit | 原三项 E2E spec + 逐字提取的生产 DOM 交接块，工具chunk1192f4对应命令exit0，718.010966ms；这是明确范围的严格类型检查，不是全前端 TS 项目检查 |
| 最终原三项真实 E2E | session33670 exit0，3/3，命令19493.446987ms，Playwright日志19.0秒；原 spec SHA仍 `4ca3836fa53313a8edab826284bd006ce877ec4c5df1ef23036dd5f50e0d10a9`，未放宽 spec:83或等待 |
| 同一加载竞态的修复后真实复验 | session12707 exit0；A在业务module加载前再次收到identity，随后进platform，真实me200且服务端账号与B相同 |

[最终完整单测](../refactor-evidence/20261013-shared-tab-auth-fix/frontend-unit-final.json)、[最终严格类型](../refactor-evidence/20261013-shared-tab-auth-fix/types-final.json)、[类型范围与来源](../refactor-evidence/20261013-shared-tab-auth-fix/type-source-final.json)、[最终原规格](../refactor-evidence/20261013-shared-tab-auth-fix/e2e-final.json)、[修复后白名单时序](../refactor-evidence/20261013-shared-tab-auth-fix/diagnostic-green-public-events.json)。原三项保留并通过全部断言：两独立 Cookie jars、390px 上下文、共享库/撤销 A 不影响 B；同 jar 换为 B、服务端身份、A私有内容消失及低敏缓存更新；移除 access 后用 HttpOnly refresh 恢复，Cookie 不进 JS/localStorage。依然不是整组 A 的全部业务、Orca 自然过期或 Windows 正式 IPC 验收。

首次 strict 检查发现 `.includes(event.key)` 不能窄化 StorageEvent 的 `string | null`；原 diagnostic完整保留，生产改为两个等值条件后复验 exit0。为使结果对应最终源码，再跑完整370及原三项，先前绿色结果仍保留。初次 strict 和最终实际 DOM 来源都公开绑定，没有靠关闭 strict 或弱化断言变绿。[首次类型诊断](../refactor-evidence/20261013-shared-tab-auth-fix/types.stdout.log)。Playwright 两次 stderr 只有现有 FORCE_COLOR/NO_COLOR 环境警告，未隐藏。

第一条 RED harness 在执行测试前因旧 Source `/proc/3833788/stat` 已不存在而安全拒绝，此为环境变化，不能计为产品 RED。Root 另核 session72606已无句柄、8000/5173无监听并确认 Source 已停止；本轮没有恢复、发 signal 或调用 Source。随后只启动自己的 4180/8180，四次独立数据/cache均由实际 helper 在 Core close0后删除，所有准确 helper/Core PID已消失、两端口无监听。两次手动 diagnostic 另取得 helper实际close0；两次 Playwright只直接取得外层exit0及Core close0，不推断未单独观察的helper退出码。[首次工具拒绝](../refactor-evidence/20261013-shared-tab-auth-fix/environment-readonly-rejection.json)、[生命周期](../refactor-evidence/20261013-shared-tab-auth-fix/lifecycle.json)。

没有 Orca/native GUI、真实管理员/模型配置、API Key 或付费请求；合成账号只存在于已删除的随机数据目录。未 stage/commit/reset，既有 staged helper index及旧失败证据保持。临时测试/类型助手精确归档删除，私有 Playwright cache 的本轮无秘密结果仅记录清理，不复制 trace/headers/body。[脚本清理](../refactor-evidence/20261013-shared-tab-auth-fix/consumed-script-cleanup.json)、[冻结](../refactor-evidence/20261013-shared-tab-auth-fix/freeze.json)。本源码修改尚不包含在 Root 正复验的历史6e安装包内，需要最终集成与重新打包；Goal 保持 active。

初次证据收尾在检查稍后才生成的 validation.json 链接时实际退出1；生命周期、旧证据保护和8份临时助手清理已完成。此为证据工具顺序缺陷，产品和测试未受影响；新恢复助手只完成剩余链接/diff/绑定/冻结并归档删除自身，没有重放测试或清理。[实际工具失败](../refactor-evidence/20261013-shared-tab-auth-fix/finalize-initial-tool-output.json)、[恢复助手清理](../refactor-evidence/20261013-shared-tab-auth-fix/resume-script-cleanup.json)。
