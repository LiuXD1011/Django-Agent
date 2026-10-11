# 纯分块 Worker 设计与实施计划

日期：2026-10-11。Goal II.3/4/5 与父任务已批准该独立优化，记录设计后连续实施；不提交、不推送。本文件不表示安装版或真实页面性能已经通过。

## 问题与选择

已有隔离四万行流程中，非语义分块计算占用核心事件循环 3650ms，同步数据库发布另占 8245ms。Electron renderer 已是独立进程，但核心 IPC/HTTP、取消和心跳仍与计算共用事件循环。

选择独占纯计算 Worker，不修改分块算法。合作式主线程分片需要重写多个同步循环；统一数据库写服务涉及全部业务写入；两者均超出本任务。Worker 不解决数据库发布和长关键词召回的同步阻塞。

## 模块和接口

- 新增 packages/core/src/documents/chunking-workers.ts：受限排队、独占 Worker、nonce 协议、取消/超时/关闭、结果形状检查。
- 新增 packages/core/src/documents/chunking-worker.ts：只运行既有 splitDocument，发送真实开始/结果/错误，关闭消息端口。
- 原 chunker.ts 算法保留。pipeline、storage、desktop/build、主验收资料归根代理所有，本任务不编辑。

    new ChunkingWorkers({ concurrency?: number, maxQueued?: number, timeoutMs?: number, workerUrl?: URL })
    split(parsed: ParsedDocument, rawConfig: unknown,
          options: ChunkerOptions & { onProgress?: (event: { stage: 'chunking'; progress: number }) => void }): Promise<ChunkingResult>
    close(): Promise<void>

concurrency 默认 1，合法 1..4；maxQueued 默认 16，合法非负整数。workerUrl 只供可信内核实例/真实协议夹具使用，不能由 renderer 控制。每个非语义任务创建自己的 Worker，完成和中止均等待实际 exit/terminate，之后才释放并发位置。排队中取消直接移除，不创建 Worker。

semantic 或自定义 tokenCounter 仍直接调用 splitDocument，保留回调和原语义；不能结构化克隆函数。此路径的模型取消/关闭仍由调用方的原 job signal 和 handler 生命周期管理，close 只拥有新计算 Worker。关闭后所有新请求均拒绝。

timeoutMs 是可选的显式 Worker 执行期限，从实际创建 Worker 前开始，包含启动；排队不计入执行期限。省略时不引入独立分块超时。原来没有 chunk deadline，不能把 IPC 的 120s 误当成既有分块预算。不添加输入大小或堆大小限制，不截断原合法正文；现有解析协议限制仍由原桥接层处理。

## 数据与安全边界

消息只包含协议版本、计算 nonce、可信 ParsedDocument、已校验的已知分块配置、标题。模型配置、函数、数据库连接和认证上下文不传给 Worker。Worker env 为空，避免继承环境凭据；Node Worker 不是系统沙箱，仍具有 Node 的文件/系统权限。本实现及其计算导入链不读取业务数据库、文件、凭据或网络，不声称剥夺这些权限。

Worker 开始消息先于真实计算。调用方 onProgress 在核心线程运行，不传入 Worker。中止先使结果失效，再 terminate；完成直到实际 Worker 退出前仍检查 signal/关闭状态，晚结果不能变成成功。第一个取消、关闭或超时原因保留，合法的 null AbortSignal 原因也按原语义拒绝。任何 protocol/nonce/结果形状不合法、启动失败、线程错误、提前退出均明确拒绝，不能假造空成功或悄悄回退主线程。

返回值保留全部父/子片段、Unicode code point offsets、来源 metadata、fallback 和统计诊断。桥接只做线性结构检查，不在核心线程再次进行全文切片/分块验证。原 worker 中的 chunker 继续验证内容覆盖和范围。

## 路径与集成

模块用 import.meta.url 决定同目录的 chunking-worker.ts 或 chunking-worker.js。两种入口的 execArgv 都为空。源码入口先由实际 Node 22.23.2 加载只含类型导入的 TS bootstrap，再调用已安装 tsx/esm/api 的 register，之后动态导入 chunker.js。直接设置 Worker --import tsx 的初版真实执行无法解析该源码 .js 导入，因此不能照猜测的 loader 方式启动。编译 JS 分支不解析或导入 tsx，不需要开发包。TypeScript NodeNext 将两个模块输出到 dist/documents；产品入口无 eval、cwd 相对路径或 renderer 指定路径。

根代理已让 DocumentWorkflow 持有一个 ChunkingWorkers，将原 splitDocument 调用改为该实例的 split，保持 stage 和原 provider callback，并由开始事件持久化 chunking.progress；发布前仍执行当前权限、job pointer、attempt/owner/lease fence。工作流先触发原 job 取消，再 await chunker.close，并等待所有原 handlers/scheduled。本代理不编辑或验收这些集成文件；最终类型检查时基线已包含根代理集成。应用原 close 顺序仍归根代理复核。

结构化克隆完整解析正文和返回结果、核心线程中的线性结构检查仍有成本。队列限制的是任务个数而非字节数，未通过增加输入/堆限制缩小原合法输入范围。每任务独占 Worker 有启动成本。主线程 heartbeat 测试只证明实际计算期间可以执行回调，不表示所有 HTTP/IPC 请求满足特定延迟预算，也不解决同步数据库发布阻塞。

## TDD 实施与验收

- [x] 先编写真实 Worker 测试：算法结果 parity、Unicode/父子、空输入、fallback、主线程真实计算期间响应、并发/排队、已取消/排队取消、运行取消和晚结果、关闭、显式超时、协议错误/崩溃和恢复。新模块不存在时以明确 assertion 失败，不能以 import typo 作为 RED。
- [x] 保存 RED 后实现最小桥接/Worker，检查 GREEN，修复真实缺陷。
- [x] 用独立临时编译目录和不带 tsx 的 Linux、实际 Windows Node 22.23.2 子进程验证 JS Worker 路径，临时目录名称含中文和空格，结束删除。
- [x] 运行 core typecheck 与相关 parser/分块测试；未重复四万行完整入库/profile，未执行完整核心测试。
- [x] 记录稳定证据、命令、耗时、源码 hash、临时目录清理和边界。以下隔离 smoke 仍不替代安装版或真实页面测试。

主要命令在 packages/core 中执行：

    node --import tsx --test test/chunking-workers.test.ts
    node --import tsx --test test/chunking-workers-compiled.test.ts
    npm run typecheck

源码 freeze 后才进行最终相关检查，不在其它代理重型 profile 期间执行测试。根代理负责实际 pipeline 调用、HTTP/IPC 页面响应、发布阻塞及安装验收。

## 实测结果与证据

| 检查 | 结果 | 原始证据与耗时 |
| --- | --- | --- |
| 实现前真实 Worker 用例 | 21/21 预期 FAIL，模块缺失的明确 assertion | [RED](../refactor-evidence/20261011-chunking-workers-red.tap)，750.427848ms |
| 源码入口真实 loader 修复后 | 20/20 PASS | [源码 GREEN](../refactor-evidence/20261011-chunking-workers-loader-green.tap)，9777.782311ms |
| 取消后紧接关闭与 null 取消原因 | 先 2/2 FAIL，再 2/2 PASS | [RED](../refactor-evidence/20261011-chunking-workers-cancel-close-null-red.tap)、[GREEN](../refactor-evidence/20261011-chunking-workers-cancel-close-green.tap)，1702.809934 / 1679.848088ms |
| 最终 24 项分块 Worker 与 12 项真实 parser 桥接 | 36/36 PASS，无取消或跳过 | [最终 TAP](../refactor-evidence/20261011-chunking-workers-final.tap)，16115.360932ms；[命令回执](../refactor-evidence/20261011-chunking-workers-final-command.json) 16185.755ms |
| 最终核心类型检查 | exit 0 | [日志](../refactor-evidence/20261011-chunking-workers-typecheck-final.log)、[命令回执](../refactor-evidence/20261011-chunking-workers-typecheck-final-command.json)，17446.316ms |
| 最终纯计算编译 JS，中文空格临时目录 | 1/1 PASS；Linux 和 win32 均 Node v22.23.2、父片段 1 / 子片段 6 / 实际开始 1 | [编译与平台 TAP](../refactor-evidence/20261011-chunking-workers-compiled-final.tap)，6499.341627ms；[命令回执](../refactor-evidence/20261011-chunking-workers-compiled-final-command.json) 6572.277ms |

初始测试夹具在模块缺失断言前创建了无关 Worker，退出时留下线程；仅终止该次测试所属进程，调整创建顺序后重跑真实 RED。保留[初始夹具失败](../refactor-evidence/20261011-chunking-workers-first-fixture-cleanup-error.tap)。初版源码 loader 的[失败日志](../refactor-evidence/20261011-chunking-workers-first-green.tap)和[真实 Worker 诊断](../refactor-evidence/20261011-chunking-workers-loader-diagnostic.log)均保留。

首次编译夹具扩大到完整核心 emit 后失败，未记录子进程失败属性，因此不能把它断言为超时，保留[原日志](../refactor-evidence/20261011-chunking-workers-compiled-first.tap)。后续仅编译纯计算导入链的临时 tsconfig，仍发生实际 FAIL，原文件名虽然含 green 也不改写结果：[原日志](../refactor-evidence/20261011-chunking-workers-compiled-green.tap)。[诊断重跑](../refactor-evidence/20261011-chunking-workers-compiled-diagnostic.tap)证实 code 2、非信号终止、非 killed，且报 TS2688：临时配置在 core 目录外找不到已有 Node 类型。夹具显式指定已安装 node_modules/@types 后[首次通过](../refactor-evidence/20261011-chunking-workers-compiled-fixed.tap)；产品 tsconfig 和依赖未改。

最终证据索引、源码/编译文件 SHA、诊断临时脚本归档及清理记录见[冻结记录](../refactor-evidence/20261011-chunking-workers-review.json)。本代理模型调用为 0，未访问实时用户数据库、凭据、GUI 或安装 payload 文件内容；仅调用父任务允许的现成 Windows Node 可执行文件进行隔离计算。
