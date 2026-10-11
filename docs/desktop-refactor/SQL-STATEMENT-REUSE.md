# 入库 SQL 编译复用计划

**目标：** 减少大文本原子发布中重复 SQL 编译，继续验证真实响应和取消能力。

**架构：** 保留单一核心写连接、同步事务和现有数据库公开接口。每个连接持有最多 128 个按 SQL 文本区分的 prepared statement；每次调用重新绑定参数，缓存不保存查询结果或凭据。最近使用的语句保留，关闭连接时清空。

**技术：** 现有 TypeScript、better-sqlite3 13.0.3、node:test；不修改依赖。

## 依据与选择

四万行页面重解析已完成，完整处理 109610ms，其中本地发布 42440ms，辅助模型请求合计 52952ms；120 秒只读健康观察仍有 29 次三秒超时。因此流程完成不等于性能通过。

不含模型和秘密的真实四万行本地流程 CPU profile 中，SQL `prepare` 自身合计约 16.4 秒，关键词逐片段处理占约 29.5 秒。当前 `CoreDatabase.get/all/run` 每次重新 `sqlite.prepare`。实际 SQL 计划确认单片段和序号查询均已使用索引，没有新的全表扫描依据。

先选择有界语句复用：比跨进程改造更小，保留原子发布语义；跨调用结果缓存会导致权限和正文过期，因此不用。若它仍不能让界面、心跳和取消及时响应，继续测量，再处理批量索引或耗时工作的进程边界，不把这一步单测记作性能完成。

## 实施与验证

- [x] 新增 `packages/core/test/database-statement-reuse.test.ts`：重复参数查询观察真实 prepare 数量先 RED，验证 get/all 共用但参数结果隔离、容量淘汰、DDL 后重新读取、事务失败后继续使用。
- [x] 完整读取实际 `BetterSqlite3.Statement` 类型，修改 `packages/core/src/storage/database.ts`，仅加入私有有界缓存。
- [x] 执行 `npm run typecheck` 及数据库/JSON/检索相关测试。
- [x] 再执行不含模型的四万行流程，比较本地阶段耗时；保留第一次 CPU profile 与真实健康超时失败。
- [ ] 仅在本地性能达到要求后重启实际核心并用页面重测，避免重复消费已经成功的三个模型请求。

Goal II.3/4 已授权设计记录后自主实施；不提交，不改变业务、凭据或发布范围。自审：缓存限于 SQL 编译，不缓存数据或改变参数绑定；关闭清理与事务回滚仍由原连接负责。

## 已执行结果

三项回归在旧实现均按预期失败；实现后数据库、JSON、检索及来源范围相关测试 46/46 通过，类型检查退出 0。无模型、真实 SQLite/Python 的四万行完整上传测试为 23479.775 ms，原同名测试为 50437.710 ms；两次独立执行条件不能用于计算 P95。本测试仍核对完整父子来源、末行事实检索和零模型请求，性能尚未通过，继续定位批量入库成本。

证据：[RED](../refactor-evidence/20261011-root-statement-reuse-red.tap)、[46 项 GREEN](../refactor-evidence/20261011-root-statement-reuse-related-green.tap)、[类型检查](../refactor-evidence/20261011-root-statement-reuse-typecheck.log)、[四万行结果](../refactor-evidence/20261011-root-statement-reuse-large-local.tap)。实际核心还未加载本次缓存修复，实际页面和最终安装包仍须复测。
