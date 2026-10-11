# 首次文档发布的有界插入与预分配邻接

2026-10-11，依据 Goal II.3/4/5 与主任务的文件归属授权实施。基线为 `database.ts` SHA-256 `b03e9a96bf9681ff915defeb32db90a573657b33c559853ad1c9f4efb5cb0447`、`pipeline.ts` SHA-256 `a37b7b0c0193515cf7615c5cbf40618196f4c9e276d0df8a3b77659c6d6f4d1b`。已完整阅读这两个文件、实际 BetterSqlite3 类型与字段清单。

## 问题与设计

当前首次 `publish_local` 对每个父/子块执行 `insert` 后 `SELECT *` 回读；随后对每个可检索子块单独更新 pre/next。调用方已经拥有分块内容与范围，仅需要新 ID。上一轮无模型大文本的 `publish_local` 仍为 8245 ms，缩短关键词召回并没有解决同步发布阻塞。

1. 新增 `CoreDatabase.insertMany(name, values): void`，与旧 `insert` 共用未知字段检查、默认值生成及 `encoded` 字段验证。旧 `insert` 继续回读并返回解码后的 Row。新接口仅接收清单中的业务表和绑定参数，连续同列形状的行按最多 900 个参数形成多 VALUES 语句；自动主键显式/省略的行保持原顺序，不按形状重新排序。
2. 整个批量调用使用同一连接的同步事务；在发布事务内只是嵌套 savepoint。后续批次字段错误、SQLite 触发器/约束失败或外层提交失败必须回滚已写批次。一次仅编码一个有限批次，不保存跨请求数据或改变 SQL statement LRU。
3. 首次发布保留原短块去重阈值、digest(trim) 与顺序。去重完成后预分配 UUID，父块先插入，子块的 context_parent_id 对应原父索引，chunk_index 连续。可检索子块的 pre/next 直接绑定进 INSERT；元数据、Unicode 范围、title/tag、source_generation 与 parser_version 使用原字段。
4. 原发布 fence、owner/权限/current pointer 检查及外层同步原子事务不变：旧索引删除、新 chunks/images、正文和 FTS 同进同退。首次改为直接 `indexKeywords`，仍在发布时读取当前 KB keyword 策略；多模态增量 `relinkAndIndex` 保留。

## 验证边界

先保存实际 RED，再最小实现。新增测试验证同字段/default/64 位整数、混合自动主键、900 参数操作数量、后批 SQLite 故障和字段验证回滚、外层提交回滚，以及真实 SQLite 文档发布的父子/去重/邻接、标题与来源元数据、失败重解析保留旧正文/FTS/ID、晚到取消/撤权/current pointer fence。运行相关核心测试、`npm run typecheck` 与差异/链接检查。

本任务不再运行 40000 行入库或 CPU profile，不访问用户运行中的数据库/GUI，不调用真实模型。操作数量证明与离线回归不是最终响应性验收；主任务在冻结后统一执行大文件流水线及 IPC/GUI 测量。

## 证据

唯一汇总：[20261011-review-initial-publication-evidence.json](../refactor-evidence/20261011-review-initial-publication-evidence.json)，包含 RED/GREEN、完整命令、最终源码 SHA 与未验证限制。

## 实际结果

- [有效 RED](../refactor-evidence/20261011-review-initial-publication-red.tap)：12 项中 6 失败、6 通过、0 取消；缺少 `insertMany` 与首次 91 条 INSERT（预期 3 条）均实际复现。初轮取消夹具错误、首轮 GREEN 关键词夹具错误和补充提交故障夹具错误也分别保留在汇总中，未删除失败证据。
- [最终相关 GREEN](../refactor-evidence/20261011-review-initial-publication-related-green.tap)：139/139 通过，0 失败/取消/跳过，完整 TAP 命令总耗时 42608.088854 ms。包含新增 14 项、存储/default/statement reuse、真实 Python 文档格式、实际本地 HTTP 协议夹具、发布回滚/权限/队列及关键词来源回归。显式排除了 40000 行长入库用例。
- 操作数量：实际 SQLite 发布 46 父块 + 45 去重后子块，3 条 INSERT，最大 899 参数，0 逐块 SELECT 回读、0 首次邻接 UPDATE、0 模型调用。独立 125 行存储回归为 5 条 INSERT（899/899/899/899/29 参数），同样 0 回读。没有通过跳过字段验证/安全检查减少操作。
- 两类实际故障均通过：第 2 批触发器失败回滚先前批次；新 FTS 写入完成后，引用真实业务表的 deferred FK 导致外层 COMMIT 失败，旧 chunks/正文/source_generation/FTS 与无外键违例状态完整保留。取消、撤权、current pointer 和 ownerToken 晚到变化均拒绝发布。
- [最终 typecheck](../refactor-evidence/20261011-review-initial-publication-typecheck-final.txt) 退出 0；`git diff --check` 退出 0。冻结 `search-index.ts`、`internal.ts` 的 SHA 与输入完全相同；多模态增量 relink、写连接和 statement cache 未更改。

对应实现与回归：[database.ts](../../packages/core/src/storage/database.ts)、[pipeline.ts](../../packages/core/src/documents/pipeline.ts)、[database-bulk-insert.test.ts](../../packages/core/test/database-bulk-insert.test.ts)、[document-bulk-publication.test.ts](../../packages/core/test/document-bulk-publication.test.ts)。完整 SHA、每次命令/退出状态和链接检查见唯一汇总。

上述 42.608 秒是多个相关测试文件的 TAP 总耗时，并非 `publish_local` 阶段耗时。没有新的 40000 行整体数据、event-loop/IPC/health p95 或 Windows GUI 延迟测量；同步原子发布仍在核心线程。主任务集成纯分块 worker 后应统一测量实际发布阶段和界面响应，不能把减少 SQL 操作等同最终性能通过。
