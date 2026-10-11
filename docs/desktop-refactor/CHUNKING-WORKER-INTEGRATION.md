# 分块 Worker 与实际文档工作流集成

2026-10-11。依据已批准的 Goal II.3/4/5，根代理负责共享接口和最终集成。问题与纯计算模块设计见 [CHUNKING-WORKER.md](CHUNKING-WORKER.md)，数据库批量发布见 [INITIAL-PUBLICATION-BATCHING.md](INITIAL-PUBLICATION-BATCHING.md)。

DocumentWorkflow 持有一个默认并发为 1 的 ChunkingWorkers。原 chunking 阶段通过此实例 split，真实 Worker 开始后持久化 chunking.progress 事件；原语义模型回调、stage 完结和发布 fence 保留。关闭流程先取消原 job，再等待所拥有的 Worker 退出，最后等待 handlers/scheduled；数据库关闭仍由应用在服务结束后执行。

新增 [document-chunking-worker.test.ts](../../packages/core/test/document-chunking-worker.test.ts) 使用明确标注的解析器替身，后续 SQLite、JobQueue、Worker、发布和取消均为真实实现。4 项实际 [RED](../refactor-evidence/20261011-root-workflow-worker-red.tap) 都因工作流尚未持有 Worker 而失败，0 取消；集成后的 [GREEN](../refactor-evidence/20261011-root-workflow-worker-green-first.tap) 4/4 通过，TAP 命令总耗时 9722.549516 ms。

覆盖精确 Unicode 正文/FTS、真实计算开始后取消或关闭且禁止发布、取消后重新解析成功，以及分块服务不可用时明确失败而不发布空内容。[typecheck](../refactor-evidence/20261011-root-workflow-worker-typecheck.txt) 退出 0。

这些结果不是最终四万行流水线、并发 HTTP/IPC 或 Windows 安装版延迟。同步原子数据库发布仍在核心线程；完成源码冻结后统一测量整体与各阶段耗时，再复核实际窗口和安装版。
