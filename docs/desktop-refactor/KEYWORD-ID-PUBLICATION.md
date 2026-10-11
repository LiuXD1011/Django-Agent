# 关键词发布的全局序号读取优化

日期：2026-10-11。Goal II.3/4/5 与父任务授权调查并执行最小可证优化；本代理仅拥有 retrieval/search-index.ts、retrieval/internal.ts、独立相关测试和本文及证据。不提交，不修改根代理的 database/pipeline/workflow/desktop 或主报告。

## 根因与范围

根代理当前隔离 3.2MB / 四万行流程记录 publish_local 6584ms，但未定位到本方法的精确份额。当前 indexKeywords 已每 64 个 ID 使用明确列投影读取权限、有效状态、整数范围、标题、上下文和正文，不调用 records、不读取文档 metadata，不对完整正文 Array.from。因此“每批次重复解码 3.2MB 文档”的假设不成立，不能据此新增文档缓存。

仍存在可直接证明的重复调用：#rowid 对每个已选定块分别调用 db.get，读取全局 chunks 序号冲突、retrieval_chunk_ids 的目标 rowid 占用、该块旧 rowid，共 3 次。随后分配空序号、清理旧索引和登记关联按原顺序执行。它涉及全局精度与冲突，不能仅在当前租户或 KB 中检查，也不能以 scoped chunk 列表替代登记表。

## 选择与接口

选择用一个 SELECT 的三个标量子查询合并上述读取，仍针对每个块、按原输入顺序重新读取当前全局状态。4 个参数，所有原绑定继续使用 bigint 与 string，最大 SQLite 整数不转成不精确 number。返回列只含冲突块 ID、登记块 ID、旧 rowid；不传输来源 JSON。

保持 SearchIndex 的全部公开接口、#write 同步 owner publish 和同一外层事务。保留原全局冲突拒绝、null 序号分配、旧 FTS/向量清理、登记 UPSERT、有效块与数字范围校验。internal.ts 无必要改动。每次方法调用都通过原 scoped SQL 重新验证文档与块；没有跨请求、跨事务或跨块的 hydration 缓存。

备选方案是每 64 块预读全局占用并维护可变 Map，可进一步降低调用次数，但必须仿真逐块释放旧序号、拒绝跨批碰撞以及维持更新顺序，风险与代码更多。本轮选择单条查询的最小方案。增设数据库 Worker/第二写连接不属于本任务。

新增 SQL 4 个参数，低于 900。既有最多 900 KB scope 加 64 块与租户形成 965 参数的合法读取契约保持，不为优化收窄已有 scope。

旧采样文件的 #rowid get / run 有耗时，但它与当前源码及根代理最新结果不同，不能将旧数字解释为当前精确占比。降低调用次数不等于已经消除发布阻塞或满足页面延迟预算；本代理不再运行四万行入库或 CPU profile。

## 实施与验证计划

1. 新建小型独立 SQLite fixture，真实写入 130 个块，记录每次 indexKeywords 的全局关联读取次数、完整 metadata 传输及 JSON 解码次数。RED 要求原 390 次读取变为 130 次，且真实 FTS 与精确 seq 仍正确；观察现状，保留原始失败与诊断。
2. 仅合并 #rowid 三次读取，检查 GREEN。原清理和登记代码保持顺序。
3. 回归全局跨租户/KB 冲突、最大整数、旧序号变化及旧向量删除、先改序号再复用的顺序、空序号、inactive/删除/namespace、异步 publish 拒绝、失败外层事务回滚以及调用间最新文档状态。保留元数据精度和正文来源，检查实际查询计划。
4. 运行相关检索测试与 core typecheck，不运行完整核心或四万行测试；记录命令、退出码、耗时、基线与最终 SHA、差异/链接和临时文件清理。最终整体验收归根代理。

本设计已按目标、数据流、异常、原子性与边界复核；不新增依赖或兼容层，不改变语义分块/模型路径。

## 实际结果

- [真实 RED](../refactor-evidence/20261011-keyword-id-publication-red.tap)：5 项中 4 PASS / 1 FAIL；130 个块的关联读取实际为 390，期望 130。文档 metadata 传输和 JSON 解码均为 0，确认原热点假设不成立。TAP 2206.205469ms。
- [独立 GREEN](../refactor-evidence/20261011-keyword-id-publication-green.tap)：5/5 PASS，关联读取变为 130。标量子查询实际计划分别使用 retrieval_chunk_sequence、INTEGER PRIMARY KEY 和 chunk_id 的 UNIQUE covering index；只有 SCAN CONSTANT ROW，没有业务表扫描。TAP 2177.344342ms。
- [最终相关回归](../refactor-evidence/20261011-keyword-id-publication-related-final.tap)：61/61 PASS，无跳过或取消，含根代理 4 项真实 Workflow/queue/Worker 集成。TAP 11763.864931ms；[命令回执](../refactor-evidence/20261011-keyword-id-publication-related-final-command.json) 11853.523ms。
- [核心类型检查](../refactor-evidence/20261011-keyword-id-publication-typecheck-final.log)：exit 0；[命令回执](../refactor-evidence/20261011-keyword-id-publication-typecheck-final-command.json) 17272.504ms。

最终小 fixture 的实际 CoreDatabase 调用为 get 130 / all 3 / run 137；当前封装每次调用一次 Statement 的同名 native 方法。返回并经过 normalization 的顶层行共 260，数字表示返回行，未伪称统计 normalization 的全部递归调用。合并查询总会返回一个包含空子查询结果的行，因此不宣称 normalization 次数减少；本优化减少 native 调用边界。新增 SQL 4 个参数，权限读取与原 64-ID 批次继续保持。

新增回归验证最大整数的跨 KB/租户冲突、真实 sqlite-vec 旧向量删除、原顺序释放旧登记序号、反序输入回滚、下次调用读取新标题与 disabled 状态。原相关测试也验证 owner fence、异步 publish 拒绝、稍后批次冲突的完整回滚、元数据/来源范围和向量 generation。相关既有测试包含隔离本地 HTTP 协议夹具，没有调用已配置供应商或真实模型。

本轮仅修改 search-index.ts 的 #rowid 三次全局关联读取，保留同文件其它代理此前已冻结的批量发布及召回优化；未修改 internal.ts、database、pipeline、workflow、Worker 或 desktop。未运行完整核心、四万行入库/profile 或真实 GUI；根代理负责新版本剩余同步热点与整体验收。没有从微小 fixture 的 wall time 推导整体速度提升。

源码 SHA、基线可验证的最小差异、原始日志 SHA、命令、调用诊断及临时脚本清理见[冻结证据](../refactor-evidence/20261011-keyword-id-publication-review.json)。
