# 关键词召回查询与定向读取

本次在 Goal II.3/4 和父任务授权下，仅修复关键词召回的已测热点。发布阶段 8245ms 的同步阻塞仍未解决，不改 pipeline、数据库缓存、状态规则、运行中的核心或用户数据。

## 实查依据

上轮 profile 的 `keyword()` 初始 SQL `all` 自身 2926ms。新建并只使用一份隔离的 12000 片段库，现有完整关键词 API 查唯一末行 `011999`：初始 SQL 3909.2ms，完整调用 4433.7ms，返回 1 个结果却读取/解码 12000 个片段。这里只建片段和索引，不跑四万行入库、解析、模型或 profiler。

实际 SQLite `EXPLAIN QUERY PLAN` 先用 `chunks_space_library` 遍历授权 KB，再对每个 seq_id 执行 FTS `=M1`。仅把 FTS 放前面仍可能选择 KB 索引扫描；指定 SearchIndex 构造器已有的非唯一 `retrieval_chunk_sequence` 索引后，实际计划使用全局 MATCH `M1` 候选再按精确 `seq_id=?` 查片段。

## 设计与安全边界

1. MATCH 分支使用 `chunks_fts CROSS JOIN chunks c INDEXED BY retrieval_chunk_sequence`，其后连接文档、知识库和租户。保留相同 MATCH 表达式、`bm25(chunks_fts),c.id` 排序及精确 SQLite 64 位序号。
2. 同一 SELECT 的 WHERE 中保留全部租户/KB scope、文档启用、所有删除条件、租户有效性、c/d/b 命名空间一致性、片段启用和可检索类型。`LIMIT` 在这些条件之后，不能先截取全局候选再在 JavaScript 里过滤。
3. 没有至少三个 codepoint 的单词时保留现有 scope 优先 LIKE 查询。短中文、标点及 `%`、`_`、反斜线仍按字面转义；不让无法使用 trigram 的短查询改成全局 FTS 扫描。排序仍为 `c.chunk_index,c.id`。
4. 已完整读取 `retrieval/internal.ts`，父任务同意归属：扩展现有 `records` 的选择参数，string/undefined 行为保持原样；新 ID 集合每批 64 个，用 VALUES 与 CROSS JOIN 主键查找，仍在 hydration 前应用全部相同 scope/active 条件。仅解码最终选中的片段，每个来源文档 JSON 在一次调用中仍只读一次；不引入跨请求缓存。
5. 无匹配结果直接返回，不解码无关来源。按初始 SQL 顺序恢复 hit 的排名。片段、图片、来源元数据和 source range 保留。

## 验证

- [x] 新回归先 RED：真实 MATCH 查询计划、limit=1 的解码预算、跨批定向读取、空匹配不读来源。
- [x] MATCH/BM25 与旧合法参考 SQL 排名相同；外租户、未选 KB、停用/删除来源不能挤占 LIMIT；稳定并列顺序、短中文/标点 LIKE 字面匹配、64 位最大 rowid。
- [x] 最小修复后相关核心测试、typecheck、diff/link 与源码 SHA。
- [x] 同一隔离库只做一次 before/after API 测量，保留旧慢结果；不重复四万行入库或 profile，测后删除隔离库及临时脚本。

自审：索引名称由同一个 SearchIndex 构造器创建并维护，不硬编码 SQLite 自动索引；它是非唯一索引，仍由现有碰撞检查控制写入。权限与有效状态在排序和 LIMIT 前确定，后续定向 hydration 只做同样过滤的复核。

## 本地测量结果与限制

在同一份隔离 12000 片段库上，唯一末行 MATCH 的一次 before/after 测量：完整 `keyword()` 调用 4433.75ms → 15.26ms；其中初始召回 SQL 3909.20ms → 9.94ms；解码片段 12000 → 1，完整来源元数据读取仍各 1 次，精确 seq_id 均为 `1152921504606858975`。这是 API 调用时间，与 Node 启动/完整 shell 命令、测试 subtest 及 document processing span 不同。

初始 6 项 RED 的有效结果为 4 失败 / 2 通过；最小实现后 6/6 绿色。首次 RED 有一个新夹具误用重复 tenants.api_key，已修正并保留原记录，不算产品缺陷或预期 RED。

这些结果只支持该孤立唯一词查询的根因修复；未测高频词、跨大量租户、并发请求、P95/P99 或真实 GUI/health/cancel。短 LIKE 的排序和字面语义有回归覆盖，但没有新的大库延迟宣称。此前 `publish_local` 8245ms 的同步原子发布没有改变，响应性仍不通过。未重复四万行入库或运行新的 CPU profile。

证据：[before](../refactor-evidence/20261011-review-keyword-recall-before.json)、[after](../refactor-evidence/20261011-review-keyword-recall-after.json)、[SQL 查询计划](../refactor-evidence/20261011-review-keyword-recall-plan-before.json)、[有效 RED](../refactor-evidence/20261011-review-keyword-recall-red.tap)、[首次夹具错误](../refactor-evidence/20261011-review-keyword-recall-red-first-fixture-error.tap)、[6 项 GREEN](../refactor-evidence/20261011-review-keyword-recall-green.tap)。

最终相关测试 [107/107 通过](../refactor-evidence/20261011-review-keyword-recall-related-green.tap)，0 失败/跳过/取消，完整 TAP 命令耗时 39801.5ms。该值是多文件相关测试命令的总跨度，不是关键词 API 延迟。核心 [typecheck](../refactor-evidence/20261011-review-keyword-recall-typecheck.log) 退出 0。命令、源码 SHA、链接和限制保存于 [本轮汇总证据](../refactor-evidence/20261011-review-keyword-recall-evidence.json)。
