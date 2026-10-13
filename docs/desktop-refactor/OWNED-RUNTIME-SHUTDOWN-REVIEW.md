# 顶层桌面 Runtime 的自有进程退出审查

本次仅做调查、独立 synthetic RED 和设计，不修改产品或既有测试。当前 `desktop/runtime.cjs` SHA `2822eae450a9e2daf910e03eb0757575ec978bd588717131273cfd8289b3b691` 与实际6e安装包中的同文件一致。原 PID25268 的未知终态和死因不归因于本路径；[此前独立数据复核](SIDEBAR-POSTCLOSE-AUDIT.md)及其169d冻结保持不变。

## 已核现状

完整阅读当前 Runtime、runtime.test、main、CoreOwner、QueryClient、desktop-process、OwnedProcessRegistry、Windows supervisor，以及 jobs / desktop-process / parser-lifecycle 对应测试。当前 Runtime 使用 `fork` 的真实 ChildProcess、私有 JSON IPC和 bundled Node；核心业务和数据库在 CoreOwner worker 中，耗时任务另有注册的 supervisor/Job。

`Runtime.stop()` 保持同一个 Promise，发送 `shutdown`，给核心30秒正常退出时间。超时后 Windows 创建 `taskkill.exe /PID captured_child.pid /T /F`。核心 `exit` 清 timer并立即 resolve；已经创建的 taskkill 没有被等待或撤回，仅监听其 `error`，未处理非零 `exit`。创建绑定、表数量和既有测试范围见[源绑定](../refactor-evidence/20261013-owned-runtime-shutdown-review/source-bindings-before.json)。

这里存在一个静态可行窗口：timer 创建独立 taskkill → 原核心退出、其 ChildProcess 的退出回调完成 → stop resolve → taskkill 稍后按整数 PID 查找目标。加一次 JS `exitCode` 检查只能缩小创建前的窗口，不能约束已经创建的外部动作。若整数 PID 随后被复用，动作缺少原创建身份和持有对象的约束。此判断是代码和 API 所支持的推断；本次没有在 Windows 上实际制造 PID 复用，也没有停止陌生进程。[taskkill 参数契约](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/taskkill)、[Windows 句柄与标识生命周期](https://learn.microsoft.com/en-us/windows/win32/procthread/process-handles-and-identifiers)。

还有两个独立问题：核心退出时 stop 不等待自己的 taskkill终态；taskkill 以非零码退出但没有触发 spawn `error` 时，核心仍活着，stop既不结束也没有下一项有界动作。main 的 before-quit 在等待此 Promise，因而可能持续停留在退出过程中。

## 公开 API 与现有归属机制

| 已持有对象 | 能证明的范围与限制 |
| --- | --- |
| Runtime 的 ChildProcess | 有公开 `send/kill/exitCode/signalCode/exit/close`；没有公开的 Win32 Job能力。`exit` 不等于所有 stdio已经关闭，`killed` 不等于实际结束。[Node22文档](https://nodejs.org/download/release/v22.23.2/docs/api/child_process.html) |
| Node 的 Windows ChildProcess.kill | 所核Node22与Node24上游实现最终使用已记录的 process HANDLE；可用公开API，不读取或传递 JS私有 `_handle`。只终止根进程不能作为完整后代树保证。[Node22 libuv](https://raw.githubusercontent.com/nodejs/node/v22.23.2/deps/uv/src/win/process.c)、[Node24 libuv](https://raw.githubusercontent.com/nodejs/node/v24.21.0/deps/uv/src/win/process.c) |
| CoreOwner / QueryClient 的 Worker对象 | 终止本实例线程，不能提供顶层fork的整棵OS进程树能力；正常close会等待自己的线程和业务关闭结果 |
| OwnedProcessRegistry 的每任务 supervisor | 在创建payload之前绑定自己的Windows Job，原 owner仍活着时确认pin；注册对象负责停止和等待任务树。该Job仅覆盖相应任务，不能当作整个桌面fork已有Job |
| DocumentParser的Python supervisor | 其Windows Job在worker创建前建立，保护该调用的worker/后代。正常取消等待close；它不能补出顶层 Runtime在突然结束时的整体归属能力 |
| Electron UtilityProcess | 当前44.7.0类型提供kill/postMessage/exit，但未承诺清理所有后代；同版本C++的Kill仍重新按pid打开对象，不能作为本次整树安全修复的直接替换。[44.7源码](https://raw.githubusercontent.com/electron/electron/v44.7.0/shell/browser/api/electron_api_utility_process.cc) |

本地 Core 的 Node类型是22.19.15、desktop的Node类型24.19.1、Electron类型44.7.0。Electron44.7.0发布源码[DEPS](https://raw.githubusercontent.com/electron/electron/v44.7.0/DEPS)指定Node24.21.0；bundled核心Node为22.23.2。父进程和子进程不同，不能用Node22实现推断父Electron二进制的全部行为；本次未运行Electron读取其 `process.versions`。API证据和限定结论保存在[primary-api-review.json](../refactor-evidence/20261013-owned-runtime-shutdown-review/primary-api-review.json)。

## 实际 synthetic RED

执行 `node --test /tmp/marlin-owned-runtime-shutdown-red-20261013.cjs`，Node22.23.2，actual exit1：4例，1PASS、3FAIL、0skip。测试将完整未修改的 Runtime在VM中求值，仅替换OS创建、时钟和明确标注的synthetic进程表；被测 Runtime的OS fork/taskkill调用0。不是实际OS PID复用实验，也不是产品通过数量。

| 用例 | 当前实际结果 |
| --- | --- |
| 正常IPC退出、重复stop同一Promise | PASS；正常exit后无PID helper、timer清理 |
| timeout helper创建后核心退出，再将synthetic PID映射换为另一generation | RED；迟到helper按裸PID选中 `synthetic-foreign-B` |
| 核心先退出，自己的timeout helper尚未结束 | RED；stop已经resolve，helper仍未终态 |
| timeout helper实际exit1且不发error，核心仍活着 | RED；stop pending，0后续终止动作、0活动deadline |

[完整脚本归档](../refactor-evidence/20261013-owned-runtime-shutdown-review/synthetic-red.source.cjs.txt)、[真实命令结果](../refactor-evidence/20261013-owned-runtime-shutdown-review/synthetic-red-execution.json)、[四例投影](../refactor-evidence/20261013-owned-runtime-shutdown-review/synthetic-observations.json)。55.93873毫秒是synthetic测试工作耗时，不能用于产品退出延迟。`node --check` actual exit0；产品尚未修复，不存在GREEN。

## 推荐的最小完整设计

保留现有fork、私有JSON业务协议、30秒graceful、所有任务与Python解析/OCR/评测能力。新增一个极小的Windows OS adapter和受控fork bootstrap；主业务仍为TypeScript，不新增正常启动Python依赖。

1. 用稳定Node-API封装Win32身份及unnamed Job，避免V8、libuv或JS私有句柄API。adapter只加载在可信Electron main / bundled Node bootstrap，任何HANDLE均为本模块持有的opaque对象，不通过renderer IPC传出，也不提供任意PID终止接口。选择并固定支持两种运行时的NAPI_VERSION；同一二进制的双加载仍需真实验证。[Node-API契约](https://nodejs.org/download/release/v24.21.0/docs/api/n-api.html)。
2. fork先进入极小bootstrap，尚不导入会创建业务数据库、任务或子进程的Core入口。bootstrap用native `GetCurrentProcess/GetProcessTimes`得到原child的pid和真实创建FILETIME，通过私有IPC发送严格限定的startup身份与generation。FILETIME采用十进制字符串或BigInt，不用会丢精度的JSON Number。[GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes)。
3. main的native adapter `OpenProcess`后，在同一真实HANDLE上核对child.pid、ACK的原creation FILETIME、预期bundled可执行路径及liveness，再Assign到新建的unnamed Job；先设置kill-on-close，不允许breakaway/handle继承。排队的旧generation ACK本身不能作绑定证明。creation不匹配、已退出或权限失败时，不Assign、不终止该可能陌生的对象；仅关闭新建空Job/观察HANDLE并用原ChildProcess公开对象处理自己未获授权的bootstrap。[Assign契约](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject)。
4. Job绑定成功后，main授权bootstrap导入原Core入口。只有此后才允许CoreOwner、数据库及解析/MCP/评测后代产生。以后所有观察和终止针对保留的Job/原root HANDLE；不重新按PID寻找终止目标。主进程异常退出时OS关闭本模块最后Job句柄，处理仍属于该Job的树。[Job生命周期](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)。
5. `stop()`仍先发原私有shutdown并保留30秒；成功或异常root退出后，都等待本代次root终态与Job active count0。graceful超时则对自有Job HANDLE进行forceClose并执行有界native等待；`TerminateJobObject`调用成功不是整树已经结束的充分条件。失败明确返回安全的shutdown失败信息，不能静默成功或转回裸PID/image/端口动作。[Job终止](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject)。
6. `Runtime`持有固定generation的生命周期对象；所有late回调引用该对象，不能换成后续 `this.child` 或新实例的Job。stop只在真实完整树结束后完成；统一清timer、回调和opaque HANDLE。单纯等待ChildProcess.close也不是全部后代保证。main需明确处理stop的安全失败，避免引入未处理Promise rejection。

建议协调接口：`OwnedRuntimeLifetime`持有原 `child`、`generation`、`ready`、`treeExited`；提供幂等 `forceClose(reason)` 和最后 `dispose()`。native Job对象提供同句柄identity、实际root终态及active-count投影，不向调用方暴露可重新寻址的句柄数字。root已退出但后代仍活时，也必须通过原Job完成清理。附加native清理等待预算由Root实现计划明确选定，不延长或删掉30秒graceful，也不把观察超时当真实退出。

该方案比将整个IPC迁到UtilityProcess小；不会将未知外部进程纳入Job，也不会为了避免问题而删掉timeout/后代清理。已有每任务Job及其取消语义继续保留。不采用简单FILETIME检查后再运行taskkill：检查与外部按PID解析仍不是同一原子能力。不使用Python做启动guard，也不直接读取ChildProcess `_handle`。

## 必要回归与目标平台门禁

Root实施前应把上述三项RED迁成正式desktop回归，并保留正常退出用例。随后至少补齐：

- 双实例分别绑定两个opaque Job；旧实例timer、错误和close回调不得影响新实例。
- bootstrap旧ACK、creation不匹配、在Open前/核验后/Assign前退出，均不能授权业务或对陌生对象执行Job/终止；全部用可控native adapter或synthetic fake验证，不在机器上制造陌生PID复用。
- native身份不匹配、Job创建/绑定失败、取消startup：数据库/任务/模型0，自己的bootstrap终态可核，HANDLE不泄漏。
- 实际Windows自有root、直接子进程及抗TERM孙进程，在root正常退出、突然退出、graceful超时和main退出时都以原Job证明active0；独立旁实例仍活。仅测小型自有fixtures，记录真实创建身份和同句柄观察。
- helper/native非零码、无法终止、QueryInformationJobObject失败、观察超时：无裸PID降级、无假成功、无退出Promise无界挂起。
- 同一`.node`在bundled Node22与父Electron44/Node24真实加载，Win x64、已有outer QA Job的嵌套Job、中文/空格安装路径和断电式退出；没有对应平台实测时不称通过。
- 原JSON字节、ACK背压、Langfuse、文件上传、早停与取消控制槽、解析/评测后代清理和付费请求重启不重放等相关现有测试继续通过。安装包内包含新bootstrap/native adapter并匹配manifest；基础启动不需要系统Node/Python或开发服务器。

## 本机编译条件与剩余不确定性

[只读工具链投影](../refactor-evidence/20261013-owned-runtime-shutdown-review/windows-toolchain-projection.json)：vswhere actual exit0，发现VS2019 BuildTools16.11.35931.194、MSVC14.29.30133的Hostx64/x64 cl.exe及WinSDK10.0.19041.0。此轮未运行编译器，不能据此宣称adapter能编译/加载。vswhere中文display字段发生工具字符集损失，路径和版本投影正常，保留为观察限制。

已查的Windows node-gyp缓存仅有22.15.0 headers；Linux缓存有22.23.2等headers。本机是否有足够的目标node.lib、Electron对应headers、合适NAPI版本和最终打包DLL依赖仍需Root下一阶段实际检查/构建；不能拿现有better-sqlite3构建成功替代新adapter验收。Windows的Job权限/嵌套和两种loader实测也尚未完成。

本次只形成可执行的修复设计和实际RED证据，不改变产品、依赖、版本、主报告或任何历史冻结；没有运行桌面、Core、HTTP或模型，也没有stage/commit。Root协调实施及最终Windows正式链路复验。
