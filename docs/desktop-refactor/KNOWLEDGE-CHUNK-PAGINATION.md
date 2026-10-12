# 分块分页只装载当前页

2026-10-12，Goal II.3–5 授权范围：仅 `knowledge/read-domain.ts`、`read-queries.ts`、新增独立回归和本说明/证据。root已提供真实GUI问题：分页返回20条，仍装载11429条完整分块，Query串行影响其他读。该观测不是P95，本任务不操作live/GUI或模型。

当前 `listChunks` 先读取完整文档，`domain.chunks` 又读取完整文档并为所有候选逐条解码完整块，随后类型过滤、DTO投影，最后paginate。问题在页外metadata/content和完整文档metadata的装载，分页本身仍需准确总数和既有排序。

最小方案先用仅id/tenant_id/knowledge_base_id/deleted_at的文档scope投影完成原权限检查，再查询 scoped、未删除块的id/chunk_type并保留 `ORDER BY chunk_index,id`。原JavaScript严格chunk_type比较和原paginate完全复用；只有页内id调用原read codec与chunkDto。通用chunks方法供其他非分页调用保留。doc和窄scope共享相同断言，其他doc DTO与写service保持原行为。

不采用SQL类型强制转换或独立分页规则：目前paginate有page_size/limit、page/offset、有限数fallback、截断和clamp的语义，chunk_type是严格相等并将假值视为不筛选。先保留窄候选数组避免改变这些规则。候选投影仍是O(总块数)，当前目标是避免O(总块数)大字段装载/DTO转换；不声称所有检索或本地发布响应性已解决。

TDD：真实CoreDatabase种子+native readonly ReadDatabase，在同一deferred snapshot内用AuthReader认证，返回20条时记录真实完整块read数、文档metadata读取次数/字节，首先断言页外块及大文档metadata未装载。初版必须因全量装载而RED；不以缺模块或mock成功代替。扩展回归比较原paginate+原DTO基线，覆盖过滤严格类型、父/媒体/disabled、排序tie、bigint、软删/错误namespace、空页和参数/权限错误；验证读前后SQLite无写入。相关核心检查与typecheck统一记录原日志，root负责最终GUI复测，不运行完整suite/build。

结果及源SHA将保存到[独立证据](../refactor-evidence/20261012-knowledge-chunk-pagination-evidence.json)。

真实RED已执行且保留[原始日志](../refactor-evidence/20261012-knowledge-chunk-pagination-red.tap)：SQLite夹具共有67条合法块，返回第2页20条且原DTO/总数比对通过后，完整块read断言失败，实际67次而非20次；块metadata读取2,752,819字节，完整文档metadata读取2次、2,097,320字节。没有缺模块或模拟返回值导致的失败。

最小修复后同一夹具[初次GREEN](../refactor-evidence/20261012-knowledge-chunk-pagination-initial-green.tap)返回内容一致，完整块read仅20次，块metadata821,740字节，完整文档metadata0次。候选查询返回67条且字段严格为id/chunk_type，SQL同时应用tenant/KB/doc/soft-delete范围，再保留原chunk_index,id排序。未增加is_enabled或searchable-type条件：父块、媒体容器和disabled块仍返回。无类型/假值类型筛选仍覆盖全部合法块，正文、指针、来源范围和准确64位seq DTO原样保留，原非分页chunks方法也保留完整行语义。

[六项新回归](../refactor-evidence/20261012-knowledge-chunk-pagination-green.tap)全部通过，覆盖默认值/offset/limit/page优先级、clamp/fallback/小数、严格类型比较、空文档和空页、完整DTO、错误namespace/软删、无效payload与权限错误优先级、membership撤销前的复核，以及真实两连接WAL中写连接在候选与页内hydrate之间原子提交时的一致性。[相关七个测试文件](../refactor-evidence/20261012-knowledge-chunk-pagination-related.tap)共51项通过，无失败/跳过/取消。

`packages/core` 的 `npm run typecheck` 实际退出0，[原日志](../refactor-evidence/20261012-knowledge-chunk-pagination-typecheck.tap)保留；未运行完整suite/build。两产品源的差异还原后SHA与上一轮纯知识查询抽取的冻结SHA一致，独立证据包含本轮最小diff与最终源码SHA。

这些结果证明真实读取操作和装载字段减少，测试命令/subtest耗时包含SQLite建库、真实密码散列和夹具生成，不能当分页接口绝对耗时或P95证明。窄候选数量仍等于该文档合法块数，筛选/排序/准确总数仍有O(候选数)成本；页内正文/metadata保持完整，单块大字段仍可能昂贵。没有进行本任务live/GUI或11429块生产夹具延迟测量，root负责冻结后真实复测；同步publish_local响应阻塞和阶段3取消没有由本修复解决或验收。
