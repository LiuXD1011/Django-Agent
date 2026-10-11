# 2026-10-10 核心集成只读审查

审查基线为当前未提交工作区；未把 HEAD 当作本轮基线。完整读取 AGENTS.md、desktop-refactor/SPEC.md、PLAN.md 和 requesting-code-review 指令。没有修改生产代码、已有测试、Git index、HEAD 或分支。仅新增本报告；复现脚本及独立测试数据写入 /tmp，使用完毕删除。没有访问真实用户数据、真实模型厂商、Windows QA 数据或 GUI。

## 范围与已确认的实现

完整审查 application.ts、HTTP/legacy route adapters、legacy channel/tenant 服务、AuthService、channel-principal、graph-legacy、GraphService 和 IntegrationService；沿调用链检查 chat 的授权/关闭、Agent 工具与 actor 委派、source fingerprint、credential projection 及 SQLite 绑定。核查当前安装的 better-sqlite3 和 Neo4j driver 类型定义。

- 十条公开 embed 路径由固定注册集合限定，IPC 返回 404；HTTP 仍执行 Host/Origin 和 CSRF 策略，renderer body 不能选择 transport 或 AuthContext。
- grant 按 digest 存储，绑定 origin、TTL、渠道版本、访客、会话与冻结 KB 集合；公共工具与 actor 使用同一 KB scope，账户历史、SQL/MCP、技能文件和联网工具不在默认访客选择中。
- 渠道、tenant、API-key rotation、成员撤销使用同一个 AuthService 和业务数据库。普通读取及 IPC rotation 不返回原始 API key/token；显式 HTTP rotation 保留授权的旧协议。
- application shutdown 先拒绝新请求并取消已登记 controller，关闭业务服务并等待登记工作，最后关闭数据库。
- 原图导出采用 WeakMap 内部 ticket、固定只读模板、原导入归档和配置验证、分页双读及异步后的授权/来源检查；本地发布在同步 SQLite 事务中完成。

## 已修复 Important / P2：旧图迁移遗漏导入前的分块来源元数据比较

以下记录初次审查版本的问题与复现，修复后的独立复核结果见文末。

位置：`packages/core/src/storage/graph-legacy.ts:92`、`:96`、`:101`。

原归档 SELECT 读取 content/type/hash 和关联数组，却不读取 metadata；计划只比较这些字段，然后用**当前** metadata 计算新 ticket 的 source fingerprint。因此正常分块 metadata 更新使旧图不再可见后，再执行旧图迁移仍会把旧图发布到新的 provenance 上。该行为违反 SPEC 中来源变化需要失效的约束，并能产生错误的原文引用；不是跨账户授权漏洞。

使用当前 `test/graph-legacy.test.ts` 中的 fixture 建立全新独立 SQLite 导入副本及受控本地 HTTP 原图服务，在 /tmp 脚本通过真实 `KnowledgeService.updateChunk` 执行：

1. 首次 migration.import 和 graph.overview：2 节点。
2. 更新 first chunk 的 `metadata.source_refs`，保留正文不变，将 source_ref 改成 `edited-page:99`。
3. graph.overview：0 节点，来源失效符合预期。
4. 再次 migration.import：未报 `legacy_graph_source_changed`，仍成功发布 2 节点。
5. 旧 Orca 实体重新可见，引用已经变成 `edited-page:99`。

运行命令：`cd packages/core && node --import tsx /tmp/marlin-final-core-review.mts`。独立复现退出码 0；输出：

```json
{"scenario":"source_metadata_api_edit_then_legacy_import","before_nodes":2,"after_edit_nodes":0,"migration_code":"success","import_nodes":2,"visible_nodes":2,"edited_provenance_bound_to_old_entity":["edited-page:99"]}
```

最小修复：原归档 SELECT 增加 metadata，使用与 sourceFingerprint/sourceHash 相同的来源元数据投影，排除 graph_relation_chunks 和 graph_indirect_relation_chunks 两个派生字段后比较归档与当前值；差异返回 `legacy_graph_source_changed`，不能将已变更来源当成原图导出的新起点。回归应覆盖正常 API 更新 source_refs 后拒绝重导，并确认两个派生关联字段的变化不会阻止合法重复导入。

## 独立 60-bit 正向验证

在另一组新 fixtures 将 owner tenant ID 设置为 `1152921504606846976`，随后创建的 outsider tenant ID 为相邻的 `1152921504606846977`；用真实 importLegacy 导入，执行 graph migration 与查询。两种 ID 保持精确字符串；owner 得到 2 节点，outsider 查询同 KB 得到 `knowledge_base_not_found`。

运行命令：`cd packages/core && node --import tsx /tmp/marlin-final-core-review-large.mts`。退出码 0；输出：

```json
{"scenario":"adjacent_60bit_tenant_import_and_scope","tenant_id":"1152921504606846976","other_tenant_id":"1152921504606846977","nodes":2,"visible_nodes":2,"foreign_code":"knowledge_base_not_found"}
```

## 初次审查基线哈希

application、http、legacy-routes、channels 和 tenants 与 `20261010-root-frozen-legacy-channel.json` 中 source_sha256 一致。其他本次审查版本：

| 文件 | SHA-256 |
| --- | --- |
| auth/channel-principal.ts | c486ec4ae53d37af76939d745d5d2f82c25466d4744f361a350bad6bdc8cb917 |
| auth/index.ts | 94720753c4d47edb4dde3bfa9f99467000b54c2a027e9c9f5f3b9777ef0d89ff |
| storage/graph-legacy.ts | 5a22d69874b383a3b997d80cf874388992cb968a2ce9641c3a7b004b4bca4a44 |
| graph/index.ts | 9ca3b6217375c02e7cb5877cf2560156cf7c68219d42b27f114a4b0684bf6a8f |
| integrations/index.ts | c03186a558d9dd15c87045eff0f32d3f431f5813d4ed59772fe93289dbd1a44a |

## 修复后独立复核

完整重读修复后的 graph-legacy.ts 和新增 graph-legacy 测试。当前 sourceMetadata 仅排除 graph_relation_chunks 与 graph_indirect_relation_chunks；原归档 SELECT 包含 metadata，原/当前来源投影通过 canonical SHA 比较；异步后的 sourceHash 使用同一来源投影。

另建新 /tmp fixtures，通过真实 importLegacy、KnowledgeService.updateChunk、受控本地 HTTP 原图读取及 SQLite 查询执行四项独立检查，没有重跑根代理的完整/相关套件。运行命令：`cd packages/core && node --import tsx /tmp/marlin-final-core-review-recheck.mts`，退出码 0，4 项通过，0 项失败。

| 独立场景 | 实际结果 |
| --- | --- |
| 正常 API 修改 source_refs | 409 legacy_graph_source_changed；旧图外部读取增量 0；graph_document 逐行不变；查询 0 节点；model_usage 0 |
| 正常 API 增加普通 parser_position 对象 | 同样 409；外部读取增量 0；publication 不变；查询 0 节点；model_usage 0 |
| 两个 graph 派生 metadata 字段都改为与原值不同的数组 | 重导 repeated=true；publication_sha256 与首导相同；查询 2 节点；Orca 引用仍 page:2；model_usage 0 |
| 外部读取过程中修改来源 metadata | 409 legacy_graph_source_changed；仅第一次外部读取发生；graph_document 发布数为 0 |

修复后核查哈希：

| 文件 | SHA-256 |
| --- | --- |
| packages/core/src/storage/graph-legacy.ts | 60fa92706333cecb9cfb1833f08bec23eddf809b940d0d846080c3d7a84c19ec |
| packages/core/dist/storage/graph-legacy.js | 5bbd575ce30094fcf986e216849f48697e2a39021354ede358c1729e12d08a72 |
| packages/core/test/graph-legacy.test.ts | aa42a8dec99db0aa30c4a4fc7469b84e99abbb4c597056bdb9760226c3b07888 |

临时复核脚本、stdout JSON 和四组自身 fixtures 使用完毕后删除；仅更新本报告，生产源码、现有测试、Git index、HEAD 与分支未改。

## 结论与边界

上述唯一确认的 Important/P2 已修复并通过独立复核，本审查范围无未解决的已确认缺陷。未确认其他权限越界、凭据回显或关闭时丢写缺陷。没有重跑完整测试套件；本报告的运行证据对应初次两项独立局部复现及修复后的四项局部检查，不能替代根代理的全套检查。没有验证真实 Neo4j 成功连接、真实厂商调用、Windows GUI、安装/升级/卸载、断电持久性或整个 Goal 的完成门槛；旧外部服务不可达已有环境失败证据，不据此宣称迁移或交付完成。
