# Runtime 接入独立审查

最新二次结论：对 Runtime SHA `1ae591f2a876fc4c38a996049c3b85fd0596bf0f86565b60e529812cb01cbb83`，spec compliance 在本次源码接入范围符合，code quality approve；初审P2已修复并独立复验，未发现其他重要遗漏。此范围不包含 Windows native/双 loader/整树或最终包的交付批准，详见末节。

以下初审 request changes 与原 RED 按旧版本保留；[初审原文副本](initial-request-changes-report.source.md)字节未改。

Spec compliance：需修复一项 generation 隔离遗漏。已读的身份 gate、原 Job/ChildProcess 生命周期、30秒 graceful + 单调5秒观察及 main 对 stop rejection 的消费方向符合批准设计，但 fork 同步失败的旧 startup timer 可以停止后续 generation。Windows native、双 loader、嵌套 Job、整树及最终打包门禁仍由指定负责人执行，本报告不将其记为通过。

Code quality：request changes，1项 P2。该结论针对[Root 送审的7份源码绑定](../20261013-root-runtime-integration/source-revision-for-review.json)，其中 `desktop/runtime.cjs` SHA `a499caf736cef2d70ab002a342602e183569c23127ad5fdf5b2242fe67c52927`、`owned-runtime.cjs` SHA `eeddc9f54625f4b4879b3acf5e0d49dd6f621b53176edfd55072788ca31dc0c5`。不是对随后可能修改版本的批准。

## 具体发现

P2 — 同步 fork 失败遗留 startup timer，旧失败代次会停止新代次。位置：[runtime.cjs:169](/home/liuxuedeng/Django-Agent/desktop/runtime.cjs:169)、[timer/fork:173](/home/liuxuedeng/Django-Agent/desktop/runtime.cjs:173)。`start()` 在 fork 前注册30秒timer，fork没有自己的 try/catch；fork 同步抛错时 Promise executor 自动 reject，但 `settled` 仍为 false，timer没有清掉。因为尚未赋值 child/lifetime，同一 Runtime 此后允许重新 start。旧timer触发 `finish(error)`，该闭包调用当前 `this.stop()`，因此发 shutdown 给新 child 并把新 Runtime 置为 stopping。

新增只读复验完整求值当前 Runtime 和 RuntimeLifetime，明确将 fork/native/时钟替换为 VM 单元边界，未启动任何 OS/Core/HTTP/模型。先让第一 fork 同步 throw，再让下一代成功完成真实产品代码的 owned-bootstrap/ready 分支，最后触发前代timer。实际结果为 1项0PASS/1FAIL/0skip，工具 chunk `0ddec7` exit1：旧失败后仍有1个startup timer；新代次 `stopping:false/receivedShutdown:false` 变为 `true/true`。证据为[实际观察](old-startup-timer-observation.json)、[完整 RED 工具输出](red-execution.json)、[归档脚本](old-startup-timer-red.source.cjs.txt)。没有通过重跑既有27项来掩盖此遗漏。

本机安装的 Node22 `fork` 参数验证和 `ChildProcess.prototype.spawn` 对部分非列举 errno 有同步抛错路径；已只读取其实际函数实现作为调用边界依据。[本地公开 API 实现投影](node22-public-fork-spawn.source.txt)。这不是在 Windows 上注入资源故障或制造 PID 复用的实验，也不声称普通 ENOENT/EMFILE 必然同步抛错；所读代码恰将常见五类运行错误转为异步 error。当前 main 每次新启动使用一个新 Runtime，正常失败后会退出，所以最直接影响范围是同一 Runtime 对象在同步失败后的重试；设计明确承诺后续 generation 不受旧回调影响，因此应在集成前补齐。

建议捕获 fork 同步异常并一次性 settle/清 startup timer；让 startup finish 的清理目标固定为本次 child/lifetime/generation，不能重新解析当前 `this.lifetime`。补正式回归，至少断言同步 fork 失败立即没有旧timer、下一代 ready 后触发旧回调不会收到shutdown。不要删30秒期限、禁止正常重启或弱化跨代断言来绕过。

## 已核的其他边界

- 七份送审 production/test 已全文读取，逐一校验当前哈希；原27项 actual exit0日志已读，未重复执行。4项 bootstrap 测试是真实子进程/JSON IPC，但 `currentIdentity` 为明确替身；11项 Windows race 是 VM/native 替身，不能当 Windows Job 验收。
- parent 在 native load后 fork bootstrap，严格验证 generation/pid/creation 字符串/额外字段；成功 bindRoot 后才发送 owned-start。bootstrap 在授权前不 import Core，错误授权/早期shutdown/断开会退出；恢复原 argv后直接 import 原入口。正常业务初始化安装 Core listeners 后才发送 ready，bootstrap在该信号上移除自身授权/断开处理，原 JSON消息没有重写。主子 native路径都是同一个 `nativePath` 及 bundled nodeExecutable，普通 main传入绝对资源root；最终文件落点/manifest由打包门禁继续核验。
- Runtime 的 wire 编码、上传base64与长度/字段核查、stream帧顺序与ACK、取消控制槽和Langfuse协议相对送审diff保持。stop 先 failRequests/拒绝新请求，消息接收在 stopping 时停止；整树终态来自原lifetime的 ChildProcess.exit 与原Job active count0，单独root exit不能resolve。本代次Job status/terminate异常会拒绝，失败时不把closed设真、不允许重新start、没有taskkill或PID降级。
- stop 两层都缓存同一 Promise；保留30秒 graceful，再用 perf_hooks.performance.now 的5秒期限轮询；失败callback的信号只引用原child且吞掉同步signal错误，仍保留有界清理。成功才 close 原Job/置closed，保持后代仍活时不会假成功。
- `finishDesktopQuit` 将关闭窗口与runtime.stop纳入同一Promise链，catch消费停止失败；诊断写入错误也被消费，随后 app.quit。该路径未向renderer暴露native能力或错误中的敏感内容。它保留 Langfuse.close 的既有等待语义，本次不将此组件已存在的整体等待时间推定为新5秒平台承诺。
- exit/message 回调已有 lifetime比较，旧已settled start 的 finish会直接返回；本次发现的具体遗漏在fork同步失败使旧 start 未settled的路径。没有观察真实未知PID25268的死因或终止陌生目标。

本轮只新增此审查目录及自有 RED/证据助手，没有修改产品、既有test、主文档、native源码或打包文件，没有 stage/commit。脚本将按实际消费精确归档删除，所有结论以[审查绑定与清理](validation.json)为准。Goal保持 active；修复与正式回归由 Root 协调，之后须对新源码重新核查本发现。

## 二次独立审查：P2 已关闭

Root 按发现补了两项正式回归，在旧产品上取得实际11PASS/2FAIL，再实现 fork try/catch→finish，并在 finish 的错误清理前检查本次 generation。新的[七源码送审版本](../20261013-root-runtime-integration/source-revision-after-startup-timer-fix.json)和[29项真实终态](../20261013-root-runtime-integration/final-startup-timer-related-tests-terminal.json)均已读取：session2956/chunk30df95 actual exit0，29PASS/0FAIL/0SKIP，TAP8122.288011ms；没有重复运行该套件。[正式 RED](../20261013-root-runtime-integration/synchronous-startup-timer-formal-red.json)保持原失败。

最新 Runtime 与新增两回归所在的完整 shutdown test 已重读，其 SHA 分别为 `1ae591f2a876fc4c38a996049c3b85fd0596bf0f86565b60e529812cb01cbb83`、`b50f801b368bac0f26236ba851867baae993f47920a6cfe00976443e7bbdebd3`。fork同步失败现在走一次性 finish，立即清掉30秒timer，并给出安全的启动错误；只有 `this.lifetime?.generation === generation` 才发起 stop，失败代次没有自己的child时不清理当前其他代次。本改动未变化已核的身份授权、原协议、ACK、控制槽、完整树状态与5秒单调期限。

同一独立小场景对最新 Runtime 实际1/1 GREEN，工具chunk6a0cf2 exit0。为了在timer已被正确清掉后仍观察迟到callback，harness保留所有曾注册timer，而不是只取活动Set，并接受新的安全启动错误消息；原两条“不得停止/发shutdown给下一代”业务断言逐字保持，还追加“失败时timer即时为0”。观察到旧callback强制触发后，新代次仍 `stopping:false/receivedShutdown:false`，所有虚拟timer结束为0。[harness边界适配](green-harness-adaptation.json)、[最新实际观察](fixed-startup-timer-observation.json)、[GREEN完整工具结果](green-execution.json)、[GREEN脚本](fixed-startup-timer-green.source.cjs.txt)。仍然没有OS fork/kill/native/Core/HTTP/GUI/模型动作。

初审收尾在Root开始补正式测试后，预置旧七哈希检查实际拒绝新 `runtime-shutdown.test.cjs`（chunkdf9f69 exit1），发生在脚本清理及其他证据写入之前。初审文字中的“逐一校验当前哈希”在该时点未完成；当时独立RED严格绑定了两份被执行产品文件，七份文件已全文读取。当前二次结果另以新七源码全量校验为准，不把并行版本变化误报产品缺陷、不重写旧结论。[实际初审收尾工具拒绝](initial-finalize-version-change.json)。

二次 spec compliance：本次 Runtime/bootstrap/lifetime/main 接入源码满足批准的身份 gate、协议保留、原对象清理、有界失败和代次隔离要求。二次 code quality：approve，本次发现P2关闭，未发现其他重要新缺陷。该结论仅覆盖以上绑定版本与范围，Windows真实Job/native、NAPI双加载、嵌套Job、实际整树退出及安装包门禁须由各负责人单独证明，不能从本结论推断整个Goal交付完成。最新七份绑定、27/29历史分层与自有临时助手归档/精确清理记录见[审查验证](validation.json)。
