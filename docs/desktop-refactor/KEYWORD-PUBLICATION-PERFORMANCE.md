# 关键词原子发布批处理

目标是减少长文档本地发布的同步 CPU 开销。缓存后四万行测试用例跨度仍需 23479.8ms（完整 TAP 命令 25406.6ms），不能据此宣布界面响应、心跳和取消性能通过。

## 已授权设计

Goal II.3/4 和父任务已授权记录设计后自主实施。本次仅修改 `retrieval/search-index.ts`、实际发布所在的 `documents/pipeline.ts` 和相关测试；不改数据库连接缓存、队列恢复或运行中的用户数据。

旧缓存前 CPU profile 中 `relinkAndIndex` 包含约 35038ms，`indexKeyword` 包含 29536ms，其中 `#scopeRecord` 15263ms、`#rowid` 7396ms。这些是调用树包含时间，不相加；旧 profile 不能充当缓存后的阶段测量。输入与摘要见 [旧 profile 摘要](../refactor-evidence/20261011-review-keyword-old-profile-summary.json)。

选择在原有单写连接和同步原子事务内批处理：

1. 新增 `indexKeywords(scope, ids, publish)`，单片段 API 委托给它；每批最多 64 个去重 ID，连同最多 900 个知识库范围参数仍低于 999 个参数。
2. 每批只读取授权片段的索引所需列，通过原来的租户、文档、知识库及有效状态条件判断可检索性，不读取或反复解析完整来源 JSON。保留片段数值范围校验。
3. 每个序号继续使用精确 bigint；保留全局片段 seq_id 冲突、登记 rowid 冲突、旧序号清理及失效片段向量删除。不把安全检查替换为局部集合假设。
4. 每批批量删除/插入 FTS，整个调用只有一个写事务。发布回调仍同步且恰好调用一次；任何冲突、取消或失败都回滚整次调用。
5. 邻接关系改用带租户、知识库、文档条件的直接更新，避免读取没有消费者的整行返回值。原来的队列 owner/cancel fence 与外层发布事务保持不变。

不改变解析正文、source range、片段元数据、向量指纹或跨网络调用边界。没有跨连接结果缓存，也不新增第二写者。同步批处理仍可能阻塞事件循环；它是否足够必须由阶段耗时及实际响应再判断。

## 验证计划

- [x] 先跑 RED：批次事务/读取预算、精确序号、范围和失效片段、跨批冲突回滚、同步发布取消与提交失败。
- [x] 最小实现后运行相关检索与文档测试及 core typecheck。
- [x] 只进行一次不含模型的四万行 CPU profile，同时输出各阶段耗时和完整来源/末行检索断言。
- [x] 保存命令、RED/GREEN、阶段证据、剩余同步阻塞判断，删除临时分析脚本。

自审：批大小的参数上限覆盖最大范围；批处理中继续逐项全局冲突检查；回调并未变成异步，也没有拆分外层原子发布。

## 第一次实测后修正查询计划

唯一一次四万行 CPU profile 的完整来源与末行检索断言通过，但本地发布仍 12870ms；批次查询 `all` 自身占 4133ms。隔离 2000 片段的实际 `EXPLAIN QUERY PLAN` 确认 `c.id IN (...)` 被 SQLite 选成 `chunks_space_library(tenant_id,knowledge_base_id)` 扫描，每批遍历整个知识库。

改用最多 64 行的 `wanted(id) VALUES` 和 `CROSS JOIN chunks c` 固定所选 ID 优先，再用 `c.id=wanted.id` 及全部原权限条件过滤。实查选择 `SEARCH c ... (id=?)`，无需硬编码 SQLite 自动索引名。先增加查询计划 RED，再改 SQL 并复测；第一次慢结果保留，不再运行第二次 CPU profile。最终源码若有变化，需一次无 profile 的四万行完整验证。

## 最终本地测量与限制

最终源码无 profiler 的四万行流程完整通过：3,200,000 字节正文、1600 个父片段、11200 个子片段，末行 `039999` 可检索，模型使用记录 0。该 subtest 跨度 19892.0ms，完整 TAP 命令 21949.1ms，文档流程根跨度 15135ms。这三个计时范围不同。约减少 15.3% 比较的是同一 subtest 的缓存后 23479.8ms 与本轮 19892.0ms，包含夹具及末行检索；它不是完整命令或纯入库跨度的降幅，也不是尾延迟或真实 GUI 性能验收。

| 阶段 | 最终跨度耗时 |
| --- | ---: |
| docreader | 1292ms |
| chunking | 3650ms |
| publish_local | 8245ms |
| multimodal | 50ms |
| embedding（跳过，无模型） | 362ms |
| postprocess（跳过，无模型） | 37ms |
| graph（跳过） | 382ms |
| wiki（跳过） | 332ms |

最大本地阶段仍是 8245ms 的同步原子发布。未进行 live health/HTTP/IPC/GUI 响应或取消延迟观察，不能宣布响应问题修复。纯 chunking worker 可把 3650ms 计算移出主线程，但不能解决数据库发布；后续需保持单写者、原子可见性、权限和可取消 fence 的独立写执行设计，不能拆事务后展示半个新来源。

另一个剩余热点是末行关键词召回：第一次新 profile 的 `keyword()` 初始 SQL `all` 自身 2926ms，完整调用约 3492ms；实际 `records()` SQL 154ms。这与索引发布不同，本次只记录，不扩大到召回排序与权限过滤修改。

主要证据：[首次 RED](../refactor-evidence/20261011-review-keyword-batch-red.tap)、[查询计划 RED](../refactor-evidence/20261011-review-keyword-batch-key-plan-red.tap)、[48 项检索绿色](../refactor-evidence/20261011-review-keyword-batch-key-plan-related-green.tap)、[第一次四万行 profile TAP](../refactor-evidence/20261011-review-keyword-batch-large-local-profile.tap)、[profile 摘要](../refactor-evidence/20261011-review-keyword-batch-new-profile-summary.json)、[最终四万行 TAP](../refactor-evidence/20261011-review-keyword-batch-large-local-final.tap)、[SQL 计划](../refactor-evidence/20261011-review-keyword-batch-sql-plan.json)。

首次实现复测的 7 通过 / 1 失败源于新增 vec0 夹具用 `number` 绑定 rowid；实际扩展要求整数绑定，已改成 `40n`，保留 [该失败记录](../refactor-evidence/20261011-review-keyword-batch-first-fixture-error.tap)。它不作为产品缺陷或预期 RED。

最终相关测试 85/85 通过，0 失败/跳过/取消，38840.3ms；最终 `npm run typecheck` 退出 0。四万行仅在独立性能测量中执行，相关套件使用实际 Node `--test-skip-pattern` 排除它，未通过重复长测耗尽预算。完整命令、源码 SHA、文档链接检查和边界见 [唯一汇总证据](../refactor-evidence/20261011-review-keyword-batch-evidence.json)；测试记录见 [最终相关测试](../refactor-evidence/20261011-review-keyword-batch-final-related-v2.tap) 与 [最终类型检查](../refactor-evidence/20261011-review-keyword-batch-final-typecheck.log)。
