# 纯知识查询抽取实施记录

日期：2026-10-12。依据 [Query Worker 设计](CORE-READ-WORKER-DESIGN.md)，root 已授权实施 A 批知识查询抽取，暂不实现 Query Worker/B 设置。独占知识 domain/service/bases/routes、index state 提取、workflow stages 提取及独立测试/证据，不改 storage/Auth/runtime/Application。

接口已与 root 和 image_parse_review 冻结：DatabaseReader 的 path/dataRoot、get/all/read(id:BindValue)；AuthReader 的原认证/assertCan签名。纯 KnowledgeReadDomain 使用这两个接口及纯 IndexStateReader，写 KnowledgeDomain 继承读逻辑并保留真实 CoreDatabase/AuthService/SearchIndex/jobs。KnowledgeQueries、KnowledgeBaseQueries 共享 DTO/分页/过滤；写 service 用薄委托复用，不复制查询实现。

ReadRouteContext={auth,params,query}；ReadRouteRegistrar.route('GET',path,同步JSON handler)。registerKnowledgeReadRoutes复用13条现有知识GET，owner不再另注册同一GET；registerDocumentReadRoutes(registrar,domain,{parserEnabled})追加stages，保留原503与items/spans。root另注册2条账户GET形成16条A manifest。下载/图片与任何写仍owner。

TDD先用真实Native SQLite readonly后端执行现有KnowledgeService，断言构造/页面查询不发DDL且投影保持等价；当前SearchIndex构造会发DDL，应真实失败。测试不以缺模块、ReadDatabase/AuthReader协作者尚未完成的scaffold错误作为RED。抽取后同一断言改用已批准的纯Queries入口，并增加真正ReadDatabase/AuthReader、namespace/撤权、parent/disabled/64位seq/Unicode正文、工作流状态、tags、分页、stages与精确GET注册回归。

只运行新测试、knowledge/domain相关与检索/stages相关核心测试和core typecheck；不fullsuite/build/live/GUI，不访问外部模型或真实密钥。测试与源码哈希、RED/GREEN原日志保存独立证据；临时脚本删除。查询Worker快照与auth epoch/同步发布响应性由root集成验收，本抽取不宣称已解决这些问题。

实现入口：`knowledge/read-domain.ts` 的 `KnowledgeReadDomain`、`knowledge/read-queries.ts` 的 `KnowledgeQueries`/`KnowledgeBaseQueries`、`knowledge/read-routes.ts` 的纯同步注册器。`retrieval/index-state.ts` 仅抽取原 state SQL；`documents/stages-query.ts` 仅抽取原轨迹投影及 GET 注册，owner 原入口委托复用。没有新增检索初始化、工作流恢复、凭据解密或数据库写入。

ReadDispatcher 可在自己的同步快照内构造这几个对象，并将重新认证的上下文传给 handler：

```ts
const domain = new KnowledgeReadDomain(reader, authReader);
registerKnowledgeReadRoutes(registrar, new KnowledgeQueries(domain));
registerDocumentReadRoutes(registrar, domain, { parserEnabled });
```

实际验证：原入口的 [RED](../refactor-evidence/20261012-knowledge-read-queries-red.tap) 在 DTO/64 位序号断言均通过后，因 SearchIndex 构造发出 `CREATE ... IF NOT EXISTS` 而失败（exit 1）。批准的抽取入口保留同一断言，替换测试消费者为纯 Queries 后 [初始 GREEN](../refactor-evidence/20261012-knowledge-read-queries-green-initial.tap) 为 1/1；补充真实 ReadDatabase/AuthReader 测试后 [最终新测试](../refactor-evidence/20261012-knowledge-read-queries-green-final.tap) 为 6/6。覆盖 Unicode 完整正文、秘密投影、父子块/停用计数、64 位序号和存储大小、状态/分页/标签、当前 membership 撤销、租户/知识库/块命名空间、索引状态及精确 14 GET/stages/503。

[知识/知识计数/应用知识/检索相关回归](../refactor-evidence/20261012-knowledge-read-queries-related.tap) 73/73，通过写入、编辑、删除和索引等既有行为；[解析工作流定向回归](../refactor-evidence/20261012-knowledge-read-stages-related.tap) 6/6。该工作流命令仅选择六项已有用例，未运行 40K 长文或外部付费模型；其中 HTTP 模型是测试自行启动的本地受控夹具。最后只清理新抽取文件缩进和未使用的 type import，再运行 6/6 新测试。TAP 底部 `duration_ms` 为该进程 TAP 总耗时，不是产品页面延迟。

共享 core typecheck 初次 exit 2：亲读 [原日志](../refactor-evidence/20261012-read-auth-typecheck.tap) 和 [命令/退出记录](../refactor-evidence/20261012-read-auth-typecheck.json)，七项诊断均在 root 同时集成的 owner-client/owner-worker epoch/session/bootstrap 字段，知识/存储/Auth 抽取没有诊断。root 已确认由主任务在阶段二整合后执行最终 typecheck/build，当前不重复编译过渡中的同一协议，本记录不将当前整体检查记为通过。

[独立证据与完整源码 SHA](../refactor-evidence/20261012-knowledge-read-extraction-evidence.json) 保留改动前已有文件哈希、RED/GREEN 命令和原日志、最终产品/测试/依赖哈希。只读源码抽取不验证 Worker admission/auth epoch 回复 fencing、实际页面响应性、同步发布阻塞或 Windows 运行；这些由 root 集成验收。
