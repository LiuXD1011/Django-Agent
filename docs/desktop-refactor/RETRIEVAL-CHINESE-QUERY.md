# 中文问句关键词召回修复

## 问题与证据

真实评测的原单题和新发布五题均使用 `keyword`、关闭 ReRank。原单题仅分块和仅检索完成但 Hit/MRR/Recall 全为 0；只读真实 SQLite 诊断确认来源存在、范围有效，而六个问句均没有 FTS 候选。见 [只读诊断](../refactor-evidence/20261012-evaluation-real-recheck/088-keyword-query-readonly-diagnostic.json) 和 [实际下载报告](../refactor-evidence/20261012-evaluation-real-recheck/082-downloaded-chunking-report.json)。

当前 FTS5 使用 `trigram`。连续中文与夹杂字母/数字的词被正则整体提取后加引号，要求全文出现同一个问句，导致资料包含答案也无法匹配。来源证据、阈值与模型配置没有造成此次零召回；正式 Ragas 尚未启动。

## 设计与实施顺序

继续使用已有三字索引。含汉字且至少三个 Unicode 码点的词拆成重叠三字项，以 OR 查询；纯英文/数字长词保留原项。两个字及更短、纯符号查询继续使用现有转义 LIKE。优先于引入分词依赖或更换索引：本次根因可以在查询侧解决，不迁移或重建用户数据库。

关键词查询、检索元信息及确定性评测的 BM25 基线共用同一个解析函数，避免实际候选与报告使用不同查询。SQL 的授权范围、启停/删除检查、排序、LIMIT、精确序号和来源水合保持现有实现。

先用临时真实 SQLite 编写并运行失败回归：中文自然问句、中英混合实体、Unicode、外部空间与失效块过滤、内容修改后的召回、英文及短符号行为。然后实现最小修复，执行相关检索/评测测试、类型检查与构建。最后接入测试核心，在原页面免费重验并下载报告；确认五题来源召回后再运行已经授权的一次小规模 Ragas。

此前 Windows `85b54e…` 冻结仍保留为历史，该构建不含此修复。最终安装包须使用新的源码冻结重新验证。

## 验证结果

- [最终失败回归](../refactor-evidence/20261012-retrieval-chinese-query/red-final.json)：6/6 失败，2931.464 ms；5 项确实零召回，另 1 项发现英文问句实际走 FTS 却被元信息标为 LIKE。
- [专项通过](../refactor-evidence/20261012-retrieval-chinese-query/green.json)：6/6，2502.931 ms。真实临时 SQLite/FTS，没有厂商调用。
- [相关组首次结果](../refactor-evidence/20261012-retrieval-chinese-query/related.json)：102/103，199324.523 ms。唯一失败是旧聊天测试强制所有中文命中标为 `keyword_expansion`，新查询已直接命中。没有修改生产扩展逻辑或删除断言；将该测试资料改为含空格的双字词，另加“原始查询无命中”和“存在扩展词”前置断言，保留真实本地 HTTP ReRank、原始问题、候选正文、用量与阈值检查。[聊天组重验](../refactor-evidence/20261012-retrieval-chinese-query/chat-green.json) 9/9，5868.506 ms。其余 94 项没有变化，不把首次 102/103 记录改写成整组通过。
- [类型检查](../refactor-evidence/20261012-retrieval-chinese-query/typecheck.json)退出 0，19529.479 ms；[核心构建](../refactor-evidence/20261012-retrieval-chinese-query/build.json)退出 0，22936.536 ms。核对期间源码摘要一致。
- [真实核心接入](../refactor-evidence/20261012-retrieval-chinese-query-live/live-after.json)：旧进程正常退出后启动 PID 1464221；16 张表跨重启的记录摘要相同，四模型和凭据材料摘要保持。页面原题/新五题的免费重验及正式 Ragas 尚未完成，旧零分报告仍保留。
- [新集成冻结](../refactor-evidence/20261012-integrated-chinese-query-source-freeze.json)：454 个构建输入、5 个额外桌面测试、523 个本地编译文件，SHA-256 `39feca8035ebdb2c00d0dba9d603ff51a435f9bc766c525fe5fe9f8f92da1c3f`。

旧 `85b54e…` Windows refresh 在源码门处拒绝，[原始收据](../refactor-evidence/20261012-integrated-image-readiness-windows-build/prepare-execution.json)退出 1，658.335 s；未执行打包或安装。由于中途覆盖了部分 payload，后续没有重写清单或冒充可复用依赖，而使用全新 `Marlin TS Chinese Query Final Build 20261012` 目录完整构建。[新构建目录](../refactor-evidence/20261012-integrated-chinese-query-windows-build/)尚未有成功终态。

关键词搜索按共同字面片段召回，不提供语义等价保证；双字短词行为和混合检索继续依现有链路。小规模验收不代表整体检索质量或可靠 P95。
