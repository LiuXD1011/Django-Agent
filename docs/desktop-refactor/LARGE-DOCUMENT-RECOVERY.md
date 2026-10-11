# 大文档中断恢复修复设计与实施计划

状态：主代理已授权在当前 Goal 中实施；不提交、不触碰实际应用数据或模型凭据。

问题是启动恢复只执行一次。崩溃后在旧租约到期前重启，队列仍为 `running`，文档、阶段、聊天 Actor 和评估会继续显示执行中。当前启动测试统一使用 `leaseUntil=1`，没有覆盖快速重启。另外，文档恢复在事务外读取队列状态，另一写入连接可以在取得写入锁前认领新尝试，旧恢复随后覆盖新任务的状态。

## 已授权设计

采用应用生命周期拥有的延迟恢复定时器。在初始化服务时记录启动遗留的 `running` 任务 ID，保留立即恢复，再等待剩余遗留任务的最近租约期限。每次到期调用现有队列和文档恢复，再投影 Actor 状态；重新读取租约，持续续租的其他核心不会被抢占。启动后创建的任务不加入定时器跟踪集合。`close()` 开始时取消定时器，回调同时检查关闭标记。

定时器使用应用已有的 `options.now` 时钟与全局 `setTimeout`，不增加依赖。评估 DTO 已读取队列状态，保留手动继续与未知付费请求确认。普通聊天流已有终态投影。文档恢复将状态和尝试次数读取移入 `BEGIN IMMEDIATE` 的事务内，并保留租户、知识库、当前工作流 ID、来源正文及 generation 检查。

已排除强制清除所有租约的方案，因为可能抢占仍在运行的核心；也排除永久固定间隔扫描，因为会重复调度排队文档。定时器只在存在启动遗留任务时运行。

## 实施计划

使用 TypeScript、Node.js 22 `node:test` MockTimers、真实 SQLite 和现有队列。测试只生成隔离临时数据库，不调用模型。

- [x] 新增 `packages/core/test/application-startup-lease-recovery.test.ts`：快速重启时不抢活租约；到期后自动恢复手动文档、Actor 与评估；租约续期后等待新的期限；退出后不再访问数据库；启动后新任务不加入监听；独立 SQLite 连接认领新尝试后旧恢复不得覆盖文档、任务和阶段。
- [x] 运行新增测试，完整 RED 为 4 项中 3 项预期失败、1 项通过。
- [x] 修改 `packages/core/src/application.ts`：保存启动遗留 ID 和时钟；完成立即恢复后按最近到期时间安排一次检查；移除已终结遗留 ID；应用关闭时取消检查。
- [x] 修改 `packages/core/src/documents/workflow.ts`：将当前 status/attempt 复核移到每个恢复事务内，跳过新认领或新尝试。
- [x] 运行新增测试及文档启动恢复、队列、Actor、评估相关测试，99/99 通过；运行 `npm run typecheck`，退出码 0。
- [x] 检查本次文件差异和文档链接，向主代理报告实际结果与限制。无提交步骤。

## 验证证据与限制

[完整 RED](../refactor-evidence/20261011-review-startup-lease-red-confirmed.tap) 中快速重启、续租后到期、独立连接认领三个断言均失败于产品状态错误。[初次 RED](../refactor-evidence/20261011-review-startup-lease-red.tap) 因测试清理过早释放等待器而挂起，仅精确匹配的本次隔离测试 runner/child 被停止；清理逻辑修正后完整重跑，没有修改实际核心服务。

[首次 GREEN](../refactor-evidence/20261011-review-startup-lease-green.tap) 为 8/8，包含新增四项与原启动四项。[最终相关 GREEN](../refactor-evidence/20261011-review-startup-lease-related-green.tap) 为 99/99，失败、取消、跳过均为 0，总耗时 103433.490084 ms；范围是启动恢复、文档工作流、队列、Actor、评估报告保留和四个应用集成文件。新增恢复测试不调用解析器或模型，既有套件使用隔离 Python 子进程及 localhost 协议 fixture。

实际命令为 `node --import tsx --test --test-name-pattern='^(?!a real 40000-line local upload)' test/application-startup-lease-recovery.test.ts test/document-startup-recovery.test.ts test/document-workflow.test.ts test/jobs.test.ts test/agents.test.ts test/evaluation-retention.test.ts test/application-knowledge.test.ts test/application-agent-observability.test.ts test/application-chat-graph.test.ts test/application-evaluation-graph.test.ts`。该负向模式实际未排除 40000 行测试；它也通过，单项耗时 52239.408382 ms。该耗时是并行回归环境的离线测量，不代表桌面或浏览器健康端点延迟通过。

[最终类型检查](../refactor-evidence/20261011-review-startup-lease-final-typecheck.log) 使用 `npm run typecheck`，退出码 0。本次修复尚需主代理集成后的实际重启和最终目标平台验证。

设计文档的 5 个本地链接均有效，指定文件的 `git diff --check` 退出码 0。首次挂起测试遗留的单个临时数据库目录已在核查专用用户名、知识库名、文档标题及零模型用量后清理；验证临时脚本使用后删除。源文件 SHA 已保存至 `20261011-review-startup-lease-diff-and-links.json`。
