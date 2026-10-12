# 中文关键词修复独立审查

针对源码冻结 `39feca8035ebdb2c00d0dba9d603ff51a435f9bc766c525fe5fe9f8f92da1c3f` 的本次最小查询修复，未发现需要阻止集成的具体缺陷。只读审查完整相关实现与测试；没有修改产品、运行测试/模型/GUI、访问实时数据库或操作进程。审查证据与源码摘要见[独立冻结](../refactor-evidence/20261012-retrieval-chinese-query-review/freeze.json)。

- [keyword-query.ts](../../packages/core/src/retrieval/keyword-query.ts) 第3–7行沿用字母/数字/下划线取词规则，`Array.from` 按Unicode码点拆含汉字词的重叠三字窗口并在该词内去重；非汉字长词保持完整，短词不生成FTS项。没有新依赖、配置写入或模型调用。
- [SearchIndex.keyword](../../packages/core/src/retrieval/search-index.ts) 第129–146行只将原取词换成共享函数。引号转义、MATCH/bm25、无长项时整条原查询的转义LIKE、两种稳定排序均保留。tenant/KB、关联一致性、启停/软删除/有效块类型条件仍在SQL LIMIT之前；当前页候选水合仍复核同一scope，精确seq仍经原bigint整数路径。
- [RetrievalService](../../packages/core/src/retrieval/service.ts) 第39行依据共享函数标记实际FTS或LIKE，修正含英文短助词时的旧元信息误报。[确定性基线](../../packages/core/src/evaluation/deterministic.ts) 第114–119行使用相同terms及相同quoted OR构造，只对实际授权lexical候选的seq读BM25，没有扩展范围或新候选LIMIT。原融合、BM25转换和阈值规则未改。
- [六项SQLite回归](../../packages/core/test/retrieval-chinese-query.test.ts)覆盖自然中文问句、中英实体、astral汉字、短文字/符号LIKE、LIMIT前外部空间及失效源过滤、编辑重索引和英文元信息。keyword且rerankTopK=0的用例没有绑定模型；测试返回usage空，修复本身是纯本地解析。
- [聊天扩展测试](../../packages/core/test/chat-retrieval.test.ts) 第81–93行将来源改为有空格的双字词，并先断言原查询确实无候选、存在正确扩展variant。原真实本地HTTP ReRank的原始query、实际候选正文、单次请求、usage与阈值断言均保留，生产扩展逻辑未改。Git工作区还含先前发布fence/state抽取等改动，本审查不把那些变化归属本次中文修复。

已核对原始日志及对应JSON/hash：[业务RED](../refactor-evidence/20261012-retrieval-chinese-query/red-final.log) 0PASS/6FAIL，其中5项为零召回，另一项为FTS结果被元信息误标LIKE；[专项GREEN](../refactor-evidence/20261012-retrieval-chinese-query/green.log) 6/6；[相关组原记录](../refactor-evidence/20261012-retrieval-chinese-query/related.log)保留102/103，唯一失败为旧测试强制keyword_expansion；[独立聊天复验](../refactor-evidence/20261012-retrieval-chinese-query/chat-green.log)9/9。相关组余94项与复验9项来自同未变产品摘要，不改写原组为一次103/103。已有[typecheck](../refactor-evidence/20261012-retrieval-chinese-query/typecheck.json)与[build](../refactor-evidence/20261012-retrieval-chinese-query/build.json)均退出0，本审查未重复执行。

边界：重叠三字OR放宽字面召回，也可能命中含常用片段或混合词内部ASCII三字的其他资料；没有语义等价/排序质量保证。没有三字项时仍整条literal LIKE，双字词被标点拆开或改写不会因此获得语义匹配。该修复不保证任何配置下零付费：recursive/keyword/关闭ReRank的指定免费链路仍本地；semantic或向量/ReRank设置继续走原模型链路。新实际页面报告、唯一正式Ragas和最终Windows安装版验收仍由根代理独立执行，不从六项回归推断整体质量或P95。
